"""
La puesta a punto, vista desde el panel.

`bootstrap_tasks` arregla DATOS de producción —una comunidad sin descripción, un
plan sin precio, un plan que no cobra por Stripe— y solo se activa poniendo
`BOOTSTRAP_TASKS` en el servidor y volviendo a desplegar. Su resultado iba a un
`print` del arranque, así que había dos cosas que un operador no podía saber de
ninguna manera:

  1. Si la variable está puesta AHORA. Una tarea que alguien dejó armada se
     vuelve a ejecutar en CADA despliegue y en cada reinicio, para siempre, y no
     había una sola pantalla que lo dijera. Ese es el riesgo de verdad de este
     mecanismo, y era invisible.

  2. Qué contestó la última vez. Si una tarea dijo «el grupo 4 no existe», eso
     se lo llevó el log del contenedor anterior.

Esta pantalla contesta las dos, y deja ejecutar a mano la ÚNICA tarea que no
escribe nada: listar los planes de una comunidad, que es justo el diagnóstico
que hace falta cuando un plan está roto y no se puede mirar la base de datos.
"""

# La única de las ocho que no toca un dato. Las demás siguen necesitando la
# variable y un despliegue a propósito: un botón que reescribe precios de
# producción a un toque es exactamente lo que no debe existir.
TAREAS_SOLO_DE_LECTURA = ("listar_planes",)


def _cuando(momento):

    if not momento:
        return "todavía no ha corrido en este proceso"

    try:
        return momento.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(momento)[:19]


def build_bootstrap_panel_text():
    """La pantalla entera. Nunca lanza."""

    try:

        from bootstrap_tasks import (
            nombres_de_tareas,
            tareas_pedidas,
            ultima_ejecucion_de_puesta_a_punto
        )

        pedidas = tareas_pedidas()
        ultima = ultima_ejecucion_de_puesta_a_punto()
        disponibles = nombres_de_tareas()

    except Exception as e:

        return (
            "🧰 Puesta a punto\n\n"
            f"No se pudo leer el estado: {str(e)[:200]}"
        )


    lineas = ["🧰 Puesta a punto (arreglos de datos de producción)", ""]

    if pedidas:

        # Esto es lo importante de la pantalla. Armado significa «se repite en
        # cada despliegue», y eso hay que decirlo con el susto que merece.
        lineas += [
            f"⚠️ ARMADA AHORA MISMO: {', '.join(pedidas)}",
            "",
            "Estas tareas se vuelven a ejecutar en CADA despliegue y en cada "
            "reinicio mientras BOOTSTRAP_TASKS siga puesta en el servidor. "
            "Son idempotentes —no estropean nada repitiéndose— pero si ya "
            "hicieron su trabajo, lo suyo es quitar la variable.",
            "",
        ]

    else:

        lineas += ["✅ No hay ninguna armada. Es el estado normal.", ""]


    lineas.append(f"Último arranque: {_cuando(ultima.get('cuando'))}")

    if ultima.get("lineas"):

        lineas.append("")

        for linea in ultima["lineas"]:
            lineas.append(f"  · {linea}")

    elif not ultima.get("cuando"):

        pass

    else:

        lineas.append("  Sin nada que hacer, no hizo nada.")


    lineas += [
        "",
        "Tareas que existen: " + ", ".join(disponibles),
        "",
        "Solo «listar_planes» se puede lanzar desde aquí: es la única que no "
        "escribe nada. Las demás cambian datos de producción y siguen "
        "necesitando la variable y un despliegue a propósito.",
    ]

    return "\n".join(lineas)


def build_bootstrap_panel_keyboard():

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from admin_menu_catalog import build_admin_screen_keyboard

    return build_admin_screen_keyboard(
        "admin_bootstrap",
        extra=[[InlineKeyboardButton(
            "📋 Listar planes de una comunidad",
            callback_data="admin_bootstrap_list_plans"
        )]]
    )


def ejecutar_listado_de_planes():
    """
    Lanza `listar_planes` y devuelve su texto. Nunca lanza.

    La tarea lee BOOTSTRAP_PLAN_LIST para saber de qué comunidad, así que si la
    variable no está puesta lo dirá ella misma — y esa es la respuesta correcta,
    no un error.
    """

    try:

        from bootstrap_tasks import ejecutar_una_tarea

        return ejecutar_una_tarea("listar_planes")

    except Exception as e:

        return f"listar_planes: no se pudo ejecutar ({str(e)[:200]})"
