"""
«¿Está lista mi comunidad para vender?»: la respuesta, con lo que falta.

Una comunidad puede estar publicada, con su descripción y su preview, y no
vender absolutamente nada por un detalle invisible: el bot sin permiso para
invitar, ningún plan activo, o ningún método de cobro disponible. Cada una de
esas cosas ya se vigila por separado y avisa por su lado, pero el propietario
nuevo no sabe que existen: monta su comunidad, no le compra nadie, y se va.

Esta pantalla junta las cuatro condiciones de vender y dice, en cada una, si
está y qué hacer si no. Sin porcentajes de progreso ni medallas: lo que hace
falta es una lista de lo que falta.

Las cuatro:

  ENTREGA     El bot tiene que ser administrador con permiso de invitar. Sin
              eso se puede cobrar y no se puede entregar — y el bot se niega
              a cobrar, así que es lo primero.

  PLANES      Al menos un plan activo con precio y duración válidos. Un plan
              con duración vacía es peor que ninguno: aparece y no se puede
              conceder.

  COBRO       Al menos un método de pago disponible para esa comunidad
              (plataforma o propio).

  VISIBLE     Que alguien pueda encontrarla: mercado o menú principal.

El diagnóstico no adivina: cada línea sale de la misma fuente que gobierna
esa condición en el momento de comprar, para que no pueda decir "listo" donde
el checkout dirá "no".
"""

from db import conn


def check_delivery(group_id):
    """(ok, texto). El permiso de invitar del bot, según la salud de entrega."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT can_deliver, bot_status, detail
                FROM group_delivery_health
                WHERE group_id = %s

            """, (group_id,))

            fila = cur.fetchone()

    except Exception as e:

        print("Listo para vender: error leyendo la entrega:", e)

        return (False, "No se pudo comprobar la entrega de accesos.")


    if not fila:

        return (
            False,
            "Sin comprobar todavía. Se comprueba solo al poco de añadir el "
            "bot; si acabas de crearla, dale unos minutos."
        )

    can_deliver, bot_status, detail = fila

    if can_deliver:

        return (True, "El bot puede crear enlaces de entrada.")

    return (
        False,
        f"El bot no puede invitar ({bot_status or 'sin estado'}). "
        "Hazlo administrador del grupo con permiso para invitar usuarios: "
        "sin eso no se puede entregar lo que se cobre."
        + (f" Detalle: {str(detail)[:120]}" if detail else "")
    )


def check_plans(group_id):
    """(ok, texto). Planes activos con precio y duración utilizables."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT
                    COUNT(*) FILTER (
                        WHERE COALESCE(is_active, TRUE) = TRUE
                          AND amount IS NOT NULL AND amount > 0
                          AND duration_days IS NOT NULL AND duration_days > 0
                    ),
                    COUNT(*) FILTER (
                        WHERE COALESCE(is_active, TRUE) = TRUE
                          AND (
                              amount IS NULL OR amount <= 0
                              OR duration_days IS NULL OR duration_days <= 0
                          )
                    )
                FROM plans
                WHERE group_id = %s

            """, (group_id,))

            buenos, rotos = cur.fetchone() or (0, 0)

    except Exception as e:

        print("Listo para vender: error leyendo los planes:", e)

        return (False, "No se pudieron comprobar los planes.")


    buenos, rotos = int(buenos or 0), int(rotos or 0)

    if not buenos:

        return (
            False,
            "No hay ningún plan activo con precio y duración. Crea uno en "
            "«Planes»: es lo que se le enseña a quien quiere comprar."
        )

    etiqueta = "plan activo" if buenos == 1 else "planes activos"
    texto = f"{buenos} {etiqueta}."

    if rotos:

        # No tumba la condición, pero avisa: un plan roto aparece en la lista
        # y luego no se puede conceder.
        texto += (
            f" Ojo: {rotos} sin precio o sin duración; se enseñan y no se "
            "pueden entregar."
        )

    return (True, texto)


def check_payment_methods(group_id):
    """(ok, texto). Métodos de cobro realmente disponibles para esa comunidad.

    Se pregunta a las mismas funciones que decide el checkout: si aquí dijera
    "listo" y allí no hubiera método, la pantalla sería una mentira.
    """

    disponibles = []

    try:

        from payment_service import (
            is_changenow_group_checkout_available,
            is_guardarian_group_checkout_available,
            is_paypal_group_checkout_available,
            is_revolut_group_checkout_available,
            is_stripe_payments_enabled,
        )

        if is_stripe_payments_enabled():
            disponibles.append("Stripe")

        for nombre, comprobar in (
            ("PayPal", is_paypal_group_checkout_available),
            ("Revolut", is_revolut_group_checkout_available),
            ("ChangeNOW", is_changenow_group_checkout_available),
            ("Guardarian", is_guardarian_group_checkout_available),
        ):

            try:

                if comprobar(group_id):
                    disponibles.append(nombre)

            except Exception:

                continue

    except Exception as e:

        print("Listo para vender: error comprobando los cobros:", e)

        return (False, "No se pudieron comprobar los métodos de cobro.")


    if not disponibles:

        return (
            False,
            "Ningún método de cobro disponible. Sin esto el botón de comprar "
            "no puede llevar a ninguna parte."
        )

    return (True, "Cobro por " + ", ".join(disponibles) + ".")


def check_visibility(group_id):
    """(ok, texto). Que alguien pueda llegar a la comunidad."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(is_marketplace_visible, FALSE),
                       COALESCE(is_main_menu_visible, FALSE),
                       COALESCE(is_active, TRUE)
                FROM groups
                WHERE id = %s

            """, (group_id,))

            fila = cur.fetchone()

    except Exception as e:

        print("Listo para vender: error leyendo la visibilidad:", e)

        return (False, "No se pudo comprobar la visibilidad.")


    if not fila:

        return (False, "La comunidad no aparece en la base de datos.")

    mercado, menu, activa = fila

    if not activa:

        return (
            False,
            "La comunidad está desactivada: no se le enseña a nadie."
        )

    if not (mercado or menu):

        return (
            False,
            "No está visible en el mercado ni en el menú principal. Quien no "
            "tenga tu enlace directo no puede encontrarla."
        )

    sitios = []

    if mercado:
        sitios.append("mercado")

    if menu:
        sitios.append("menú principal")

    return (True, "Visible en " + " y ".join(sitios) + ".")


def collect_readiness(group_id):
    """[(ok, titulo, detalle)] — la lista completa, en orden de arreglo."""

    comprobaciones = (
        ("Entrega de accesos", check_delivery),
        ("Planes de venta", check_plans),
        ("Métodos de cobro", check_payment_methods),
        ("Visibilidad", check_visibility),
    )

    resultado = []

    for titulo, comprobar in comprobaciones:

        ok, detalle = comprobar(group_id)

        resultado.append((ok, titulo, detalle))

    return resultado


def build_readiness_text(group_id, group_name):
    """La pantalla. Sin medallas: una lista de lo que falta."""

    filas = collect_readiness(group_id)
    pendientes = [f for f in filas if not f[0]]

    lineas = [f"🚦 ¿Puede vender {group_name}?", ""]

    if not pendientes:

        lineas.append(
            "✅ Todo listo: se puede cobrar y entregar. Si no entra nadie, el "
            "problema ya no es de configuración — mira el panel de ingresos y "
            "quién visita sin comprar."
        )

    else:

        cuantas = len(pendientes)
        lineas.append(
            f"Falta {cuantas} cosa para poder vender:"
            if cuantas == 1 else
            f"Faltan {cuantas} cosas para poder vender:"
        )

    lineas.append("")

    for ok, titulo, detalle in filas:

        lineas.append(f"{'✅' if ok else '❌'} {titulo}")
        lineas.append(f"   {detalle}")
        lineas.append("")

    return "\n".join(lineas).rstrip()
