"""
Cambiar de plan sin perder el acceso ni pagar dos veces.

El bot bloquea comprar otra vez cuando ya tienes acceso — y hace bien: ese
bloqueo evita el doble cobro accidental del que se impacienta con el
webhook. Pero convertía en callejón el caso legítimo: el suscriptor mensual
al que se le ofrece el plan anual pulsaba el botón y aterrizaba en «ya
tienes acceso a esta comunidad».

Aquí está el camino explícito. Lo que lo hace seguro no es un permiso
nuevo, es la salvaguarda que ya existe en attach_subscription_to_member: al
anclar la suscripción nueva, la anterior se apaga con cancel_at_period_end.
El comprador nunca acaba con dos cobros vivos.

Las reglas:

  MISMA COMUNIDAD   Solo se ofrecen planes activos de la comunidad a la que
                    ya tiene acceso, y nunca el que ya tiene. Un "cambio"
                    hacia otro sitio es una compra normal, con su bloqueo.

  STRIPE O NADA     Si su renovación viva es de PayPal, no se ofrece el
                    cambio: la salvaguarda que apaga la anterior es de
                    Stripe, y en PayPal quedarían dos suscripciones
                    cobrando. Se le dice qué hacer, en ese orden: primero
                    apagar la de PayPal, después elegir el plan nuevo.

  SIN PERDER LO PAGADO   El periodo ya pagado sigue siendo suyo: el acceso
                    se lo gobierna users.expiration, y el plan nuevo lo
                    extiende desde su alta.
"""

from db import conn


def fetch_current_plan_name(user_id, group_id):
    """El nombre del plan de su último pago cobrado, si lo hay."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT plan
                FROM payments
                WHERE user_id=%s AND group_id=%s
                  AND LOWER(COALESCE(status, '')) IN ('paid', 'completed')
                ORDER BY payment_date DESC NULLS LAST, id DESC
                LIMIT 1

            """, (user_id, group_id))

            fila = cur.fetchone()

            return fila[0] if fila else None

    except Exception as e:

        print("Cambio de plan: error leyendo el plan actual:", e)

        return None


def has_paypal_anchor(user_id, group_id):
    """True si su renovación viva es de PayPal (no se puede cambiar en caliente)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM payment_transactions
                WHERE provider='paypal'
                  AND user_id=%s
                  AND group_id=%s
                  AND external_checkout_id IS NOT NULL
                  AND LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'active')
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone() is not None

    except Exception as e:

        print("Cambio de plan: error comprobando PayPal:", e)

        # Ante la duda, NO ofrecer el cambio: dos suscripciones de PayPal
        # cobrando a la vez es el peor resultado posible.
        return True


def member_has_active_access(user_id, group_id):
    """True si tiene acceso activo a ESA comunidad (permanente incluido)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM users
                WHERE user_id=%s AND group_id=%s
                  AND (expiration IS NULL OR expiration > NOW())
                LIMIT 1

            """, (user_id, group_id))

            return cur.fetchone() is not None

    except Exception as e:

        print("Cambio de plan: error comprobando el acceso:", e)

        return False


def fetch_switch_options(user_id, group_id):
    """Planes activos de la comunidad a los que puede cambiarse.

    [(plan_id, nombre, amount, currency, duration_days, price_id, provider)]
    sin el que ya tiene. Lista vacía = no hay a dónde cambiar.
    """

    actual = fetch_current_plan_name(user_id, group_id)

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       amount,
                       COALESCE(NULLIF(currency, ''), 'EUR'),
                       duration_days,
                       price_id,
                       COALESCE(NULLIF(payment_provider, ''), 'stripe')
                FROM plans
                WHERE group_id=%s
                  AND COALESCE(is_active, TRUE)=TRUE
                  AND amount IS NOT NULL
                  AND amount > 0
                  AND (%s IS NULL OR name <> %s)
                ORDER BY duration_days DESC NULLS LAST, amount ASC

            """, (group_id, actual, actual))

            return cur.fetchall() or []

    except Exception as e:

        print("Cambio de plan: error leyendo los planes:", e)

        return []


def plan_is_switchable_target(group_id, plan_id):
    """El plan existe, está activo y es de ESA comunidad. Devuelve su price_id.

    Es la comprobación que se repite en el servidor antes de aceptar el
    dinero: un callback se puede escribir a mano, esta consulta no.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT price_id,
                       COALESCE(NULLIF(payment_provider, ''), 'stripe')
                FROM plans
                WHERE id=%s AND group_id=%s
                  AND COALESCE(is_active, TRUE)=TRUE

            """, (plan_id, group_id))

            return cur.fetchone()

    except Exception as e:

        print("Cambio de plan: error validando el plan destino:", e)

        return None


def switch_is_allowed(user_id, group_id, plan_id=None):
    """(permitido, motivo). El motivo es para explicárselo, no para el log.

    Motivos: 'no_access' (no es socio de esa comunidad), 'paypal' (su
    renovación es de PayPal), 'bad_plan' (el plan no es de esa comunidad o
    no está activo).
    """

    if not member_has_active_access(user_id, group_id):
        return (False, "no_access")

    if has_paypal_anchor(user_id, group_id):
        return (False, "paypal")

    if plan_id is not None and not plan_is_switchable_target(group_id, plan_id):
        return (False, "bad_plan")

    return (True, None)


def formato_duracion(duration_days):

    dias = int(duration_days or 0)

    if dias >= 365:
        return "1 año"

    if dias >= 30:
        meses = dias // 30
        return "1 mes" if meses == 1 else f"{meses} meses"

    return f"{dias} días"


def build_switch_text(group_name, opciones, current_plan=None):
    """La pantalla del cambio de plan, con lo que pasa dicho antes de pulsar."""

    lineas = [f"🔀 Cambiar de plan en {group_name}", ""]

    if current_plan:

        lineas.append(f"Tu plan ahora: {current_plan}")
        lineas.append("")

    lineas.extend([
        "Al activarse el plan nuevo, tu suscripción actual se apaga sola "
        "al final del periodo que ya tienes pagado: no se te cobra dos "
        "veces y no pierdes ni un día de acceso.",
        "",
        "Planes disponibles:",
    ])

    for _plan_id, nombre, amount, currency, duration_days, _price, _prov in opciones:

        lineas.append(
            f"• {nombre} — {amount} {currency} / {formato_duracion(duration_days)}"
        )

    return "\n".join(lineas)
