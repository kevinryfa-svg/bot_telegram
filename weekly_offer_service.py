"""
Ofertas semanales que se encienden y se apagan solas.

Un catálogo con el mismo precio todo el año no da ninguna razón para comprar
HOY. Y «hoy» es la única venta que existe: quien lo deja para más adelante no
vuelve. Esto pone, cada semana, una oferta de verdad —del 40% al 60%— sobre los
planes cortos, con fecha de caducidad visible, y la retira sola cuando pasa.

CÓMO NO SE ROMPE EL DINERO CON ESTO

  LA OFERTA NO TOCA EL PLAN   Vive en su propia tabla, con su ventana de fechas
                              y su propio precio de Stripe con el importe
                              rebajado. Lo que se enseña y lo que se cobra
                              siguen siendo el mismo número, que es la regla que
                              gobierna todo el dinero de este bot. Y cuando
                              caduca no hay nada que deshacer: deja de estar
                              viva y el plan sigue con su precio de siempre.

  SOLO PLANES CORTOS          Semana (5 a 10 días) y mes (28 a 31). Un descuento
                              del 60% sobre un plan anual regala once meses; y
                              sobre uno de dos días no significa nada.

  NUNCA POR DEBAJO DEL        Stripe no cobra menos de 0,50 EUR. Una oferta que
  MÍNIMO QUE SE PUEDE COBRAR  deja el importe por debajo no se crea: sería
                              anunciar algo que el cobro rechaza.

  UNA POR PLAN Y SEMANA       La clave de semana es única en la tabla, así que
                              el mismo lunes puede ejecutarse cinco veces y solo
                              habrá una oferta. Sin eso, cada reinicio del bot
                              crearía otro precio en Stripe.

LO QUE PASA A LOS 7 DÍAS

Nada especial, y eso es lo bueno: el plan de una semana concede acceso con
caducidad a 7 días, y el worker de expiraciones que ya existe expulsa del grupo
a quien caduca. La oferta no inventa un camino nuevo para eso — se apoya en el
que ya funciona.
"""

import os

from datetime import datetime, timedelta

from audit_log_service import log_event
from db import conn


# Los dos huecos que se ofertan, en días. Fuera de aquí no se toca nada.
SEMANA = (5, 10)
MES = (28, 31)

# Descuentos por tramo. «Súper buenas» de verdad: el de la semana es el gancho
# de entrada y el que más baja.
DESCUENTO_SEMANA = int(os.environ.get("OFERTA_DESCUENTO_SEMANA", "60"))
DESCUENTO_MES = int(os.environ.get("OFERTA_DESCUENTO_MES", "40"))

# El descuento del upsell anual, que es otra cosa: se le ofrece a quien ya ha
# comprado algo corto.
DESCUENTO_ANUAL = int(os.environ.get("OFERTA_DESCUENTO_ANUAL", "50"))

# Cuánto dura una oferta semanal. Siete días exactos: la cuenta atrás es parte
# de la oferta, y una que no termina nunca no es una oferta.
DIAS_DE_OFERTA = int(os.environ.get("OFERTA_DIAS", "7"))

# Por debajo de esto Stripe no cobra. Ofrecer algo así sería anunciar lo que el
# cobro va a rechazar.
MINIMO_COBRABLE = 0.50


def clave_de_semana(momento=None):
    """«2026-W34». La misma para todo el lunes y para todo el domingo."""

    momento = momento or datetime.now()

    año, semana, _dia = momento.isocalendar()

    return f"{año}-W{semana:02d}"


def tramo_de_plan(duration_days):
    """«semana», «mes» o None si ese plan no entra en las ofertas."""

    try:

        dias = int(duration_days or 0)

    except (TypeError, ValueError):

        return None

    if SEMANA[0] <= dias <= SEMANA[1]:
        return "semana"

    if MES[0] <= dias <= MES[1]:
        return "mes"

    return None


def descuento_de_tramo(tramo):
    """El porcentaje que le toca a cada tramo, acotado a lo razonable."""

    bruto = DESCUENTO_SEMANA if tramo == "semana" else DESCUENTO_MES

    # Un descuento fuera de 10-70 no es una oferta: o no se nota o regala el
    # producto. Se acota aquí y no en cada sitio que lo use.
    return max(10, min(70, int(bruto)))


def importe_con_descuento(base, percent):
    """El importe rebajado, redondeado a céntimos. None si no se puede cobrar."""

    try:

        base = float(base)

    except (TypeError, ValueError):

        return None

    if base <= 0:
        return None

    rebajado = round(base * (100 - int(percent)) / 100.0, 2)

    if rebajado < MINIMO_COBRABLE:
        return None

    return rebajado


def oferta_viva(plan_id):
    """La oferta en vigor de un plan ahora mismo. None si no hay."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, plan_id, group_id, percent, amount, base_amount,
                       COALESCE(currency, 'EUR'), stripe_price_id, ends_at
                FROM plan_offers
                WHERE plan_id = %s
                  AND starts_at <= NOW()
                  AND ends_at > NOW()
                  AND COALESCE(NULLIF(stripe_price_id, ''), '') <> ''
                ORDER BY ends_at DESC
                LIMIT 1

            """, (int(plan_id),))

            fila = cur.fetchone()

    except Exception as e:

        print("Ofertas: error leyendo la oferta del plan:", str(e)[:160])

        return None

    if not fila:
        return None

    return {
        "id": fila[0], "plan_id": fila[1], "group_id": fila[2],
        "percent": fila[3], "amount": fila[4], "base_amount": fila[5],
        "currency": fila[6], "stripe_price_id": fila[7], "ends_at": fila[8],
    }


def dias_que_quedan(oferta):
    """Cuántos días enteros quedan. 0 significa «hoy es el último»."""

    if not oferta or not oferta.get("ends_at"):
        return None

    restante = oferta["ends_at"] - datetime.now()

    return max(0, restante.days)


def planes_ofertables(group_id=None):
    """Los planes cortos que se pueden ofertar de verdad.

    Se exige lo mismo que para venderlos —activos, con importe, cobrables por
    Stripe y con la comunidad viva—, porque una oferta sobre algo que no se
    puede comprar es una mentira con cuenta atrás.
    """

    condicion = "AND p.group_id = %s" if group_id else ""
    parametros = (SEMANA[0], SEMANA[1], MES[0], MES[1])

    if group_id:
        parametros = parametros + (int(group_id),)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT p.id, p.group_id,
                       COALESCE(NULLIF(g.name, ''), 'la comunidad'),
                       COALESCE(NULLIF(p.name, ''), 'Plan'),
                       p.amount,
                       COALESCE(NULLIF(p.currency, ''), 'EUR'),
                       p.duration_days,
                       COALESCE(p.is_recurring, FALSE)
                FROM plans p
                JOIN groups g ON g.id = p.group_id
                WHERE COALESCE(p.is_active, TRUE) = TRUE
                  AND COALESCE(g.is_active, TRUE) = TRUE
                  AND COALESCE(NULLIF(p.payment_provider, ''), 'stripe') = 'stripe'
                  AND p.amount IS NOT NULL AND p.amount > 0
                  AND p.duration_days IS NOT NULL
                  AND (
                      (p.duration_days BETWEEN %s AND %s)
                      OR (p.duration_days BETWEEN %s AND %s)
                  )
                  """ + condicion + """
                ORDER BY p.group_id, p.duration_days, p.id

            """, parametros)

            filas = cur.fetchall() or []

    except Exception as e:

        print("Ofertas: error listando planes ofertables:", str(e)[:160])

        return []

    return [
        {
            "id": f[0], "group_id": f[1], "group_name": f[2], "name": f[3],
            "amount": f[4], "currency": f[5], "duration_days": f[6],
            "is_recurring": bool(f[7]),
        }
        for f in filas
    ]


def crear_oferta(plan, percent=None, dias=None, week_key=None, momento=None):
    """(oferta, detalle). Crea la oferta de un plan con su precio real.

    El precio de Stripe se crea con el importe YA rebajado, así que la página de
    pago dice exactamente lo que decía el botón. Nada de cupones invisibles.
    """

    from plan_price_service import crear_precio_stripe_para_plan

    tramo = tramo_de_plan(plan.get("duration_days"))

    if not tramo:

        return (None, f"el plan #{plan.get('id')} no es de semana ni de mes")

    percent = int(percent or descuento_de_tramo(tramo))
    dias = int(dias or DIAS_DE_OFERTA)
    momento = momento or datetime.now()
    week_key = week_key or clave_de_semana(momento)

    base = plan.get("amount")
    rebajado = importe_con_descuento(base, percent)

    if rebajado is None:

        return (
            None,
            f"el plan #{plan.get('id')} con -{percent}% se quedaría por debajo "
            f"de {MINIMO_COBRABLE:.2f}, que es lo mínimo que se puede cobrar"
        )

    ya = oferta_viva(plan["id"])

    if ya:
        return (ya, f"el plan #{plan['id']} ya tiene una oferta viva")

    # El nombre viaja al producto de Stripe: es lo que se lee con la tarjeta ya
    # en la mano, y ahí el descuento tiene que seguir estando.
    plan_para_precio = dict(plan)
    plan_para_precio["name"] = f"{plan.get('name') or 'Plan'} · -{percent}%"

    try:

        price_id = crear_precio_stripe_para_plan(plan_para_precio, rebajado)

    except Exception as e:

        return (None, f"Stripe no aceptó el precio de oferta: {str(e)[:160]}")

    termina = momento + timedelta(days=dias)

    try:

        with conn.cursor() as cur:

            # ON CONFLICT sobre (plan_id, week_key): si dos arranques del mismo
            # lunes llegan a la vez, solo una oferta queda.
            cur.execute("""

                INSERT INTO plan_offers
                    (plan_id, group_id, percent, amount, base_amount, currency,
                     stripe_price_id, starts_at, ends_at, week_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plan_id, week_key) DO NOTHING
                RETURNING id

            """, (
                plan["id"], plan.get("group_id"), percent, rebajado,
                float(base), plan.get("currency") or "EUR", price_id,
                momento, termina, week_key,
            ))

            fila = cur.fetchone()
            conn.commit()

    except Exception as e:

        conn.rollback()

        return (None, f"error guardando la oferta: {str(e)[:160]}")

    if not fila:

        # Otro proceso ganó la carrera: la suya vale igual que la nuestra.
        return (oferta_viva(plan["id"]), f"el plan #{plan['id']} ya estaba ofertado")

    log_event(
        "plan_offer_created",
        category="billing",
        severity="info",
        scope="group",
        group_id=plan.get("group_id"),
        message="Oferta semanal creada.",
        metadata={
            "plan_id": plan["id"],
            "percent": percent,
            "antes": float(base),
            "ahora": rebajado,
            "termina": termina.isoformat(),
            "stripe_price_id": price_id,
        },
    )

    return (
        {
            "id": fila[0], "plan_id": plan["id"], "group_id": plan.get("group_id"),
            "percent": percent, "amount": rebajado, "base_amount": float(base),
            "currency": plan.get("currency") or "EUR",
            "stripe_price_id": price_id, "ends_at": termina,
        },
        f"{plan.get('group_name')}/{plan.get('name')}: "
        f"{float(base):.2f} → {rebajado:.2f} {plan.get('currency') or 'EUR'} "
        f"(-{percent}%)"
    )


def lanzar_ofertas_de_la_semana(momento=None):
    """Pone la oferta de esta semana en todos los planes que la admiten.

    Idempotente por la clave de semana: se puede llamar en cada arranque sin
    llenar Stripe de precios duplicados.
    """

    momento = momento or datetime.now()
    week_key = clave_de_semana(momento)

    creadas, motivos = [], []

    for plan in planes_ofertables():

        oferta, detalle = crear_oferta(plan, week_key=week_key, momento=momento)

        if oferta and detalle and "ya" not in detalle:
            creadas.append(detalle)

        elif not oferta:
            motivos.append(detalle)

    return creadas, motivos


def describe_weekly_offers(momento=None):
    """Una línea para el arranque. Calla cuando no hay nada que decir."""

    try:

        creadas, motivos = lanzar_ofertas_de_la_semana(momento)

    except Exception as e:

        return f"Ofertas: no se pudieron preparar ({str(e)[:160]})."

    if not creadas and not motivos:
        return None

    partes = []

    if creadas:
        partes.append(f"{len(creadas)} oferta(s) nueva(s): " + "; ".join(creadas))

    if motivos:
        partes.append("sin oferta: " + "; ".join(motivos[:3]))

    return "Ofertas de la semana: " + ". ".join(partes) + "."


# =========================
# EL PRECIO VIGENTE: PLAN U OFERTA, EN UN SOLO SITIO
# =========================
# Con una oferta viva hay DOS identificadores de precio para el mismo plan, y
# cada consulta podría elegir uno distinto. Ese es exactamente el fallo que
# costó las ventas de este bot antes —el escaparate resolvía el precio de una
# manera y el cobro de otra—, así que aquí la regla se escribe una vez:
#
#   Mientras la oferta esté viva, ESE es el precio del plan. Para el
#   escaparate, para el botón de un toque y para el cobro.
#
# Y se aceptan los dos identificadores al cobrar, pero se cobra siempre el de la
# oferta: así un botón viejo con el precio de tarifa nunca cobra de más, que es
# lo único que no se puede permitir.


def sql_precio_vigente(alias="p"):
    """El identificador con el que se cobra hoy este plan (oferta incluida)."""

    from plan_price_service import sql_precio_efectivo

    prefijo = f"{alias}." if alias else ""

    return (
        "COALESCE((SELECT po.stripe_price_id FROM plan_offers po"
        f" WHERE po.plan_id = {prefijo}id"
        "   AND po.starts_at <= NOW() AND po.ends_at > NOW()"
        "   AND COALESCE(NULLIF(po.stripe_price_id, ''), '') <> ''"
        " ORDER BY po.ends_at DESC LIMIT 1), "
        + sql_precio_efectivo(alias) + ")"
    )


def sql_importe_vigente(alias="p"):
    """El importe que se va a cobrar hoy (el de la oferta si la hay)."""

    prefijo = f"{alias}." if alias else ""

    return (
        "COALESCE((SELECT po.amount FROM plan_offers po"
        f" WHERE po.plan_id = {prefijo}id"
        "   AND po.starts_at <= NOW() AND po.ends_at > NOW()"
        "   AND COALESCE(NULLIF(po.stripe_price_id, ''), '') <> ''"
        " ORDER BY po.ends_at DESC LIMIT 1), "
        f"{prefijo}amount)"
    )
