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
from payment_access_service import MAX_PLAN_DURATION_DAYS


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
                          AND duration_days IS NOT NULL
                          AND duration_days > 0
                          AND duration_days <= %(max_dias)s
                    ),
                    COUNT(*) FILTER (
                        WHERE COALESCE(is_active, TRUE) = TRUE
                          AND (
                              amount IS NULL OR amount <= 0
                              OR duration_days IS NULL OR duration_days <= 0
                          )
                    ),
                    -- Aparte de los rotos «normales»: el plan cuya duración el
                    -- cobro se NIEGA a convertir en acceso. Este panel lo
                    -- contaba como bueno y le decía al propietario que podía
                    -- vender, cuando ese plan cobra y no entrega.
                    COUNT(*) FILTER (
                        WHERE COALESCE(is_active, TRUE) = TRUE
                          AND duration_days IS NOT NULL
                          AND duration_days > %(max_dias)s
                    ),
                    -- Y la moneda que no es un código de tres letras. En
                    -- producción había un plan con la moneda escrita «EURO».
                    -- Con Stripe no rompe el cobro (el price_id lleva su propia
                    -- moneda), pero PayPal y los demás mandan este código tal
                    -- cual y lo rechazan.
                    COUNT(*) FILTER (
                        WHERE COALESCE(is_active, TRUE) = TRUE
                          AND currency IS NOT NULL
                          AND currency !~ '^[A-Za-z]{3}$'
                    )
                FROM plans
                WHERE group_id = %(gid)s

            """, {"gid": group_id, "max_dias": MAX_PLAN_DURATION_DAYS})

            buenos, rotos, imposibles, monedas = cur.fetchone() or (0, 0, 0, 0)

    except Exception as e:

        print("Listo para vender: error leyendo los planes:", e)

        return (False, "No se pudieron comprobar los planes.")


    buenos = int(buenos or 0)
    rotos = int(rotos or 0)
    imposibles = int(imposibles or 0)
    monedas = int(monedas or 0)

    # Los avisos se ACUMULAN, y el orden es por gravedad: primero el que
    # impide vender, después el que solo se lee mal. Escritos con «=» en vez de
    # «+=», el segundo borraría al primero y el propietario arreglaría la
    # moneda sin enterarse de que su plan no se puede entregar.
    avisos = []

    if imposibles:

        # Se dice el número exacto y qué hacer: «duración inválida» manda a
        # adivinar. Y el 0 se nombra, porque es justo lo que querían poner los
        # que escriben un número enorme para decir «para siempre».
        avisos.append(
            f"🚨 {imposibles} con una duración de más de "
            f"{MAX_PLAN_DURATION_DAYS} días: el bot COBRA y no puede entregar "
            "el acceso. Ponle los días reales, o 0 si querías acceso "
            "permanente."
        )

    if monedas:

        # No tumba la condición: con Stripe se cobra igual, porque el precio de
        # Stripe lleva su propia moneda. Pero se dice, porque el comprador lee
        # ese texto en el botón y los demás proveedores lo rechazan.
        avisos.append(
            f"💱 {monedas} con la moneda escrita en un formato que no es un "
            "código de tres letras (EUR, USD...). Al comprador se le enseña "
            "corregida cuando se puede, pero PayPal y los demás la rechazan "
            "tal cual: arréglala en «Planes»."
        )

    aviso_imposibles = ("" if not avisos else " " + " ".join(avisos))


    if not buenos:

        return (
            False,
            "No hay ningún plan activo que se pueda entregar. Crea uno en "
            "«Planes»: es lo que se le enseña a quien quiere comprar."
            + aviso_imposibles
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

    return (True, texto + aviso_imposibles)


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


def check_pitch(group_id):
    """(ok, texto). Si le has contado a alguien QUÉ es esto.

    Lo encontré simulando el /start de un desconocido con los datos reales de
    producción. Esto es, literalmente, todo lo que veía:

        🔓 StarsVip
        Precio: 7 EUR/360 días

    Un nombre y un precio. Nadie paga por un nombre. El escaparate puede estar
    perfecto —precio en el botón, un toque hasta pagar— y no vender nada porque
    no hay ni una palabra sobre qué recibe el que paga.

    El texto sale de groups.preview_text, que es lo que el propietario escribe en
    «Vista previa». No bloquea la venta (quien llega del canal del propietario ya
    sabe qué es), pero es la primera cosa que hay que arreglar cuando no se
    vende.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COALESCE(NULLIF(TRIM(preview_text), ''), '')
                FROM groups
                WHERE id=%s

            """, (group_id,))

            fila = cur.fetchone()

    except Exception as e:

        print("Listo para vender: error leyendo la descripción:", e)

        return (False, "No se pudo comprobar la descripción.")

    texto = (fila[0] if fila else "") or ""

    if not texto:

        return (
            False,
            "Tu comunidad no tiene descripción: quien la ve solo lee el nombre "
            "y el precio, y nadie paga por un nombre. Escribe en «Vista previa» "
            "qué recibe quien entra, cada cuánto, y para quién es."
        )

    # 40 caracteres no es una descripción, es un titular. El umbral es bajo a
    # propósito: solo descarta lo que claramente no explica nada.
    if len(texto) < 40:

        return (
            True,
            f"Descripción muy corta ({len(texto)} caracteres). Di qué recibe "
            "quien paga y cada cuánto: es lo último que lee antes de decidir."
        )

    return (True, f"Descripción de {len(texto)} caracteres.")


def collect_readiness(group_id):
    """[(ok, titulo, detalle)] — la lista completa, en orden de arreglo."""

    comprobaciones = (
        ("Entrega de accesos", check_delivery),
        ("Planes de venta", check_plans),
        ("Métodos de cobro", check_payment_methods),
        ("Visibilidad", check_visibility),
        # La última porque es la única que no impide cobrar. Impide convencer,
        # que es lo que estaba pasando en producción.
        ("Qué es tu comunidad", check_pitch),
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
