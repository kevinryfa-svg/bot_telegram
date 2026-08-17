"""
Referidos: el socio contento trae a otro, y los dos ganan días.

El canal de venta más barato que existe es un miembro que recomienda la
comunidad. Aquí se le da la herramienta: un enlace personal por comunidad,
y cuando el invitado PAGA, los dos se llevan días gratis (7 por defecto,
REFERRAL_DAYS).

Las reglas, que son las que evitan que esto se convierta en un agujero:

  SOLO GENTE NUEVA      No cuenta invitar a quien ya tiene acceso a esa
                        comunidad, ni invitarse a uno mismo. Un referido
                        que no trae a nadie nuevo no es un referido.

  PAGA, LUEGO COBRA     El crédito se genera cuando el invitado paga, no
                        cuando entra al bot. Un clic no es una venta.

  UNA ATRIBUCIÓN        El primer enlace que trajo a la persona a esa
                        comunidad es el que cuenta, para siempre (clave
                        única invitado+comunidad). Sin peleas por el
                        último clic ni doble pago del mismo alta.

  DÍAS DE VERDAD        Los días se suman a users.expiration desde HOY (no
                        desde una fecha ya pasada). Y si el miembro tiene
                        suscripción Stripe, se EMPUJA su próximo cobro con
                        trial_end: sin eso, Stripe cobraría en la fecha de
                        siempre y la semana regalada no sería gratis, solo
                        una línea bonita en la pantalla.
"""

import os
import time

import stripe

from audit_log_service import log_event
from db import conn


REFERRAL_DAYS = int(os.environ.get("REFERRAL_DAYS", "7"))

REFERRALS_ENABLED = os.environ.get(
    "REFERRALS_ENABLED", "true"
).strip().lower() not in ("0", "false", "no", "off")

BOT_USERNAME = os.environ.get("BOT_USERNAME", "TheStarVipBOT")


def build_referral_link(user_id, group_id):
    """El enlace personal. La carga la lee start() y atribuye el alta."""

    return (
        f"https://t.me/{BOT_USERNAME}?start=ref_{int(group_id)}_{int(user_id)}"
    )


def parse_referral_payload(carga):
    """'ref_83_701' -> (83, 701). None si la carga no es un referido válido."""

    if not carga or not carga.startswith("ref_"):
        return None

    partes = carga.split("_")

    if len(partes) != 3:
        return None

    try:

        return (int(partes[1]), int(partes[2]))

    except (TypeError, ValueError):

        return None


def member_has_access(user_id, group_id):
    """True si esta persona ya está dentro de esa comunidad (o lo estuvo)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM users
                WHERE user_id=%s AND group_id=%s
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone() is not None

    except Exception as e:

        print("Referidos: error comprobando acceso previo:", e)

        # Ante la duda, NO atribuir: un referido de más paga días de más.
        return True


def record_referral_click(referrer_user_id, invited_user_id, group_id):
    """Atribuye el alta al que compartió el enlace. True si quedó registrada.

    Devuelve False cuando no hay nada que atribuir: autorreferido, invitado
    que ya tiene acceso a esa comunidad, o una atribución previa (la
    primera manda).
    """

    if not REFERRALS_ENABLED:
        return False

    if int(referrer_user_id) == int(invited_user_id):
        return False

    if member_has_access(invited_user_id, group_id):
        return False

    if not member_has_access(referrer_user_id, group_id):
        # Quien recomienda tiene que ser de la casa: si no está dentro, el
        # enlace es de alguien que solo quiere días gratis.
        return False

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO referrals
                    (referrer_user_id, invited_user_id, group_id, status)
                VALUES (%s, %s, %s, 'pending')
                ON CONFLICT (invited_user_id, group_id) DO NOTHING

            """, (referrer_user_id, invited_user_id, group_id))

            hecho = cur.rowcount > 0
            conn.commit()

        if hecho:

            log_event(
                "referral_click_recorded",
                category="marketing",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=referrer_user_id,
                target_user_id=invited_user_id,
                message="Invitado atribuido a un miembro por enlace de referido.",
                metadata={"referrer_user_id": referrer_user_id}
            )

        return hecho

    except Exception as e:

        conn.rollback()

        print("Referidos: error registrando la atribución:", e)

        return False


def _empujar_ciclo_stripe(user_id, group_id, nueva_expiracion):
    """Mueve el próximo cobro de Stripe a la nueva fecha de acceso.

    Sin esto, los días regalados no son gratis: el acceso local diría una
    fecha y Stripe cobraría en la de siempre. trial_end no toca items ni
    precio — el precio heredado del socio sigue intacto — solo retrasa el
    cargo, que es exactamente lo que es un regalo de días.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT stripe_subscription_id
                FROM users
                WHERE user_id=%s AND group_id=%s
                  AND stripe_subscription_id IS NOT NULL

            """, (user_id, group_id))

            row = cur.fetchone()

        if not row or not row[0]:
            return None

        subscription_id = row[0]

        stripe.Subscription.modify(
            subscription_id,
            trial_end=int(nueva_expiracion.timestamp()),
            proration_behavior="none",
        )

        return subscription_id

    except Exception as e:

        # El regalo local ya está dado: que Stripe no acepte el empujón no
        # puede tumbar la operación, pero sí tiene que quedar por escrito.
        log_event(
            "referral_stripe_cycle_push_failed",
            category="payment",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="No se pudo empujar el próximo cobro tras un referido.",
            metadata={"error": str(e)[:200]}
        )

        return None


def credit_referral_days(user_id, group_id, days=None, reason="referral"):
    """Suma días de acceso a un miembro. Devuelve la nueva fecha, o None.

    Los días se cuentan desde HOY cuando el acceso ya venció: sumarlos a
    una fecha pasada sería regalar nada.
    """

    dias = int(days if days is not None else REFERRAL_DAYS)

    if dias <= 0:
        return None

    try:

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE users
                SET expiration = GREATEST(
                        COALESCE(expiration, NOW()), NOW()
                    ) + (%s || ' days')::interval,
                    subscription_active = TRUE
                WHERE user_id=%s AND group_id=%s
                RETURNING expiration

            """, (dias, user_id, group_id))

            row = cur.fetchone()
            conn.commit()

        if not row:
            return None

        nueva_expiracion = row[0]

        subscription_id = _empujar_ciclo_stripe(
            user_id, group_id, nueva_expiracion
        )

        log_event(
            "referral_days_credited",
            category="marketing",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message=f"{dias} días de acceso acreditados ({reason}).",
            metadata={
                "days": dias,
                "reason": reason,
                "new_expiration": str(nueva_expiracion),
                "stripe_cycle_pushed": bool(subscription_id),
            }
        )

        return nueva_expiracion

    except Exception as e:

        conn.rollback()

        print("Referidos: error acreditando días:", e)

        return None


def convert_referral(invited_user_id, group_id):
    """El invitado ha pagado: los dos cobran sus días. Idempotente.

    Devuelve {"referrer_user_id", "days", ...} si esta llamada fue la que
    convirtió el referido; None si no había nada pendiente (segundo pago,
    reintento de webhook, o alta sin referido).
    """

    if not REFERRALS_ENABLED:
        return None

    try:

        with conn.cursor() as cur:

            # El UPDATE condicionado al estado 'pending' es la puerta: dos
            # webhooks del mismo pago solo pueden pasar por ella una vez.
            cur.execute("""

                UPDATE referrals
                SET status='converted', converted_at=NOW(), days_awarded=%s
                WHERE invited_user_id=%s AND group_id=%s AND status='pending'
                RETURNING referrer_user_id

            """, (REFERRAL_DAYS, invited_user_id, group_id))

            row = cur.fetchone()
            conn.commit()

        if not row:
            return None

        referrer_user_id = row[0]

    except Exception as e:

        conn.rollback()

        print("Referidos: error convirtiendo el referido:", e)

        return None


    expiracion_invitado = credit_referral_days(
        invited_user_id, group_id, reason="referral_invited"
    )
    expiracion_referidor = credit_referral_days(
        referrer_user_id, group_id, reason="referral_referrer"
    )

    log_event(
        "referral_converted",
        category="marketing",
        severity="info",
        scope="group",
        group_id=group_id,
        actor_user_id=referrer_user_id,
        target_user_id=invited_user_id,
        message="Referido convertido: días acreditados a los dos.",
        metadata={
            "referrer_user_id": referrer_user_id,
            "invited_user_id": invited_user_id,
            "days": REFERRAL_DAYS,
        }
    )

    return {
        "referrer_user_id": referrer_user_id,
        "invited_user_id": invited_user_id,
        "days": REFERRAL_DAYS,
        "invited_expiration": expiracion_invitado,
        "referrer_expiration": expiracion_referidor,
    }


def fetch_referral_stats(user_id, group_id):
    """{'invitados', 'convertidos', 'dias'} para la pantalla del miembro."""

    vacio = {"invitados": 0, "convertidos": 0, "dias": 0}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status='converted'),
                       COALESCE(SUM(days_awarded) FILTER (
                           WHERE status='converted'
                       ), 0)
                FROM referrals
                WHERE referrer_user_id=%s AND group_id=%s

            """, (user_id, group_id))

            row = cur.fetchone() or (0, 0, 0)

        return {
            "invitados": int(row[0] or 0),
            "convertidos": int(row[1] or 0),
            "dias": int(row[2] or 0),
        }

    except Exception as e:

        print("Referidos: error leyendo estadísticas:", e)

        return vacio


def notify_referral_conversion(token_bot, resultado, group_name):
    """Avisa a los dos. El referidor se entera de que su recomendación pagó.

    Envío directo por HTTP: esto se llama desde el webhook de pago, que no
    tiene el bucle de asyncio del bot a mano.
    """

    if not resultado:
        return False

    import requests

    from i18n_service import load_user_language, t

    enviados = 0

    for user_id, clave in (
        (resultado["referrer_user_id"], "referral.referrer_rewarded"),
        (resultado["invited_user_id"], "referral.invited_rewarded"),
    ):

        try:

            language = load_user_language(user_id)

            requests.post(
                f"https://api.telegram.org/bot{token_bot}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": t(
                        clave, language,
                        group=group_name or "",
                        days=resultado["days"],
                    ),
                },
                timeout=10,
            )

            enviados += 1

        except Exception as e:

            print("Referidos: no se pudo avisar de la conversión:",
                  str(e)[:200])

    return enviados > 0
