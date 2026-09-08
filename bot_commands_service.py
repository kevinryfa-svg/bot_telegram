"""
El menú de comandos de Telegram, que este bot no tenía.

Telegram enseña la lista de comandos de un bot en el botón «/» de la barra de
escribir —y en el menú de tres puntos— si el bot la ha registrado con
`setMyCommands`. Este bot nunca la registró: `set_my_commands` no aparece en
ninguna línea del proyecto.

Consecuencia para el comprador: el «/» está vacío. Los comandos existen, pero
la única forma de saber que existen era que alguien te los dijera. Y uno de
ellos es el único sitio del bot donde se puede cambiar el idioma.

Solo se anuncian los comandos del PÚBLICO. Los de administración (/admin,
/codigos, /usuarios, /debug*) se dejan fuera a propósito: anunciarlos a todo el
mundo es enseñar dónde está la puerta, y el que la usa ya se la sabe.
"""

COMANDOS_PUBLICOS = [
    ("start", "Ver las comunidades y comprar acceso"),
    ("idioma", "Cambiar idioma / Change language"),
    ("ia", "Preguntar una duda al asistente"),
    ("salir", "Salir del modo de preguntas"),
]


def comandos_publicos():
    """[(comando, descripción)] de lo que se le anuncia a cualquiera."""

    return list(COMANDOS_PUBLICOS)


async def registrar_menu_de_comandos(application):
    """
    Deja el menú «/» puesto. Devuelve True si se registró.

    Nunca lanza: un bot sin menú de comandos funciona igual, y tumbar el
    arranque por un adorno sería cambiar un problema pequeño por uno enorme.
    """

    try:

        from telegram import BotCommand

        await application.bot.set_my_commands([
            BotCommand(comando, descripcion)
            for comando, descripcion in comandos_publicos()
        ])

        print(
            "Menú de comandos registrado:",
            ", ".join("/" + c for c, _ in comandos_publicos())
        )

        return True

    except Exception as e:

        print("Menú de comandos: no se pudo registrar:", str(e)[:200])

        return False
