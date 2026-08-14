"""
Stripe Connect: cada creador cobra en SU cuenta, la plataforma su comisión.

Hasta ahora todos los cobros de Stripe entraban en la cuenta de la
plataforma y el reparto era un problema humano. Con Connect, el dinero del
creador aterriza en su propia cuenta de Stripe en el momento del cobro, y la
comisión de la plataforma se queda sola.

Las tres decisiones, tomadas con el estándar del sector:

  EXPRESS      El alta más simple que existe para el creador: un enlace, un
               formulario de Stripe, y su cuenta queda operativa. La
               plataforma no custodia datos bancarios de nadie.

  10%          STRIPE_CONNECT_FEE_PERCENT (10 por defecto). En suscripciones
               va como application_fee_percent (se aplica solo a cada cobro);
               en pagos únicos como application_fee_amount calculado del
               precio del plan.

  CARGOS CON   transfer_data.destination: el cargo nace en la cuenta de la
  DESTINO      plataforma y el neto viaja solo al creador. Es la variante
               donde TODOS los webhooks siguen llegando a la plataforma — el
               camino del dinero ya construido (concesiones, renovaciones,
               reembolsos, incidencias) se reutiliza intacto — y donde las
               devoluciones las gobierna la plataforma, que es quien da la
               cara ante el comprador.

INACTIVO-SEGURO: sin cuenta conectada y verificada, el checkout es
exactamente el de siempre, byte a byte. Y si Connect no está activado aún en
la cuenta de Stripe de la plataforma (se activa una vez en el panel), el alta
se degrada con un mensaje claro al propietario en vez de romperse.
"""

import os

import stripe

from audit_log_service import log_event
from db import conn
from group_subscription_service import BOT_RETURN_URL, recurso_plano
from payment_gateway_config import amount_to_minor_units


def get_platform_fee_percent():
    try:
        valor = float(os.environ.get("STRIPE_CONNECT_FEE_PERCENT", "10"))
    except Exception:
        valor = 10.0

    return min(max(valor, 0.0), 100.0)


def fetch_connect_account(group_id):
    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_account_id, COALESCE(charges_enabled, FALSE),
                       owner_user_id
                FROM creator_connect_accounts
                WHERE group_id = %s

            """, (group_id,))

            row = cur.fetchone()

        if not row:
            return None

        return {
            "stripe_account_id": row[0],
            "charges_enabled": bool(row[1]),
            "owner_user_id": row[2],
        }

    except Exception as e:

        print("Connect: error leyendo la cuenta:", e)

        return None


def start_connect_onboarding(group_id, owner_user_id):
    """
    Crea (o reutiliza) la cuenta Express del creador y devuelve el enlace de
    alta de Stripe. {'ok': True, 'url': ...} o {'ok': False, 'error': ...}.
    """

    try:

        existente = fetch_connect_account(group_id)

        if existente:

            account_id = existente["stripe_account_id"]

        else:

            cuenta = recurso_plano(stripe.Account.create(
                type="express",
                metadata={
                    "group_id": str(group_id),
                    "owner_user_id": str(owner_user_id),
                },
            ))

            account_id = cuenta["id"]

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO creator_connect_accounts
                        (group_id, owner_user_id, stripe_account_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (group_id) DO NOTHING

                """, (group_id, owner_user_id, account_id))

                conn.commit()

            log_event(
                "stripe_connect_account_created",
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=owner_user_id,
                message="Cuenta Express de Stripe Connect creada.",
                metadata={"stripe_account_id": account_id},
            )


        enlace = recurso_plano(stripe.AccountLink.create(
            account=account_id,
            refresh_url=BOT_RETURN_URL,
            return_url=BOT_RETURN_URL,
            type="account_onboarding",
        ))

        return {"ok": True, "url": enlace["url"], "account_id": account_id}

    except Exception as e:

        detalle = str(e)[:300]

        print("Connect: error en el alta:", detalle)

        # El caso más probable: Connect sin activar en la cuenta de la
        # plataforma. Se degrada con instrucción, nunca con silencio.
        return {"ok": False, "error": "connect_no_disponible",
                "detalle": detalle}


def refresh_connect_status(group_id):
    """
    Pregunta a Stripe si la cuenta ya puede cobrar y lo guarda. La fuente de
    verdad es charges_enabled: hasta que Stripe no lo pone a True, el checkout
    sigue siendo el de la plataforma.
    """

    cuenta = fetch_connect_account(group_id)

    if not cuenta:
        return None

    try:

        datos = recurso_plano(
            stripe.Account.retrieve(cuenta["stripe_account_id"])
        ) or {}

        habilitada = bool(datos.get("charges_enabled"))

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE creator_connect_accounts
                SET charges_enabled = %s, updated_at = NOW()
                WHERE group_id = %s

            """, (habilitada, group_id))

            conn.commit()

        cuenta["charges_enabled"] = habilitada

        return cuenta

    except Exception as e:

        print("Connect: error comprobando el estado:", str(e)[:200])

        return cuenta


def connect_checkout_kwargs(group_id, plan_es_recurrente, amount_major,
                            currency):
    """
    Lo que hay que añadir al checkout para que el dinero viaje al creador.

    {} si el grupo no tiene cuenta conectada Y VERIFICADA: el checkout de
    siempre, byte a byte. La verificación (charges_enabled) es la guardada en
    la base — el checkout no puede permitirse una llamada a Stripe por visita.
    """

    cuenta = fetch_connect_account(group_id)

    if not cuenta or not cuenta["charges_enabled"]:

        return {}


    destino = cuenta["stripe_account_id"]
    fee = get_platform_fee_percent()

    if plan_es_recurrente:

        # En suscripciones la comisión es porcentual y se aplica sola a CADA
        # cobro, renovaciones incluidas.
        return {
            "subscription_data": {
                "application_fee_percent": fee,
                "transfer_data": {"destination": destino},
            }
        }


    # Pago único: la comisión se calcula del precio del plan, en céntimos.
    total_minor = amount_to_minor_units(amount_major or 0, currency)
    fee_minor = int(round(total_minor * fee / 100.0))

    return {
        "payment_intent_data": {
            "application_fee_amount": fee_minor,
            "transfer_data": {"destination": destino},
        }
    }


def describe_connect_status(group_id):
    """Para la pantalla del propietario."""

    cuenta = fetch_connect_account(group_id)

    if not cuenta:

        return (
            "Sin cuenta conectada: los cobros de Stripe entran en la cuenta "
            "de la plataforma, como siempre."
        )

    if cuenta["charges_enabled"]:

        return (
            "✅ Cuenta ACTIVA: los cobros de Stripe de esta comunidad "
            f"aterrizan en tu cuenta, y la plataforma retiene su "
            f"{get_platform_fee_percent():g}% en el momento del cobro."
        )

    return (
        "⏳ Alta empezada pero sin terminar: completa el formulario de "
        "Stripe (botón de abajo) y pulsa «Comprobar estado» al acabar."
    )
