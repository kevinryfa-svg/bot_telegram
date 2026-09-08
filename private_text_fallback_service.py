"""
Lo que contesta el bot cuando un comprador le escribe: nada.

`handle_text` va probando estados de asistentes —guardián, promociones,
ubicación, soporte, IA— y si no hay ninguno llama a `receive_code`, que a pesar
del nombre solo atiende asistentes de ADMINISTRACIÓN: borrar código, buscar
usuario, expulsar, banear, desbanear, crear grupo. Si tampoco hay ninguno de
esos, la función se acaba y devuelve None.

O sea: un comprador que escribe al bot en privado —«hola», «no puedo pagar»,
«quiero comprar», o su código de invitación pegado— recibía SILENCIO ABSOLUTO.
Sin acuse, sin error, sin un botón. El silencio de un bot se lee como «está
roto», y quien lo lee así ya no vuelve.

Aquí está la contestación. Dos casos, porque son dos problemas distintos:

  - Si lo que ha escrito ES un código de los que existen, se le dice de qué
    comunidad es y se le lleva a canjearlo ahí (que es donde el canje funciona
    de verdad, con su validación y su registro).
  - Si no, una respuesta corta con las salidas que sirven: comunidades, sus
    accesos, soporte y la IA.

Lo que NO se hace aquí es canjear nada ni adivinar intenciones: contestar es
una cosa y decidir por el usuario es otra.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n_service import load_user_language, t


# Un código pegado suele venir solo, en una línea. Una frase, no. Se usa para
# no ir a la base de datos por cada «hola».
MAXIMO_PALABRAS_DE_UN_CODIGO = 1
LARGO_MINIMO_DE_UN_CODIGO = 4
LARGO_MAXIMO_DE_UN_CODIGO = 32


def parece_un_codigo(texto):
    """Si merece la pena mirar en la base de datos si es un código."""

    if not texto:
        return False

    limpio = str(texto).strip()

    if len(limpio.split()) > MAXIMO_PALABRAS_DE_UN_CODIGO:
        return False

    if not LARGO_MINIMO_DE_UN_CODIGO <= len(limpio) <= LARGO_MAXIMO_DE_UN_CODIGO:
        return False

    return all(
        c.isalnum() or c in "-_"
        for c in limpio
    )


def buscar_comunidad_del_codigo(texto):
    """
    (group_id, nombre_de_la_comunidad) si ese código existe. None si no.

    Se pregunta a la MISMA fuente que usa el canje de verdad, para no decirle
    «ese código no me consta» a alguien que tiene uno bueno.
    """

    if not parece_un_codigo(texto):
        return None

    try:

        from callback_router import fetch_group_user_promo_by_code

        fila = fetch_group_user_promo_by_code(texto)

    except Exception as e:

        print("Texto suelto: no se pudo mirar el código:", str(e)[:200])
        return None

    if not fila:
        return None

    try:
        return int(fila[1]), fila[11]
    except (IndexError, TypeError, ValueError):
        return None


def build_code_hint_text(nombre_comunidad, language=None):

    return t(
        "fallback.looks_like_code",
        language,
        comunidad=nombre_comunidad or "una comunidad"
    )


def build_code_hint_keyboard(group_id, language=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("fallback.btn_redeem", language),
            callback_data=f"group_user_promo_redeem_start_{int(group_id)}"
        )],
        [InlineKeyboardButton(
            t("fallback.btn_home", language),
            callback_data="public_back_start"
        )]
    ])


def build_fallback_text(language=None):

    return t("fallback.not_understood", language)


def build_fallback_keyboard(language=None, con_accesos=False):

    filas = [[InlineKeyboardButton(
        t("fallback.btn_explore", language),
        callback_data="start_explore_groups"
    )]]

    # «Mis accesos» solo si tiene alguno: el botón que promete y contesta «no
    # tienes ninguno» es un toque perdido, y esta pantalla ya es la de alguien
    # que no ha encontrado lo que buscaba.
    if con_accesos:

        filas.append([InlineKeyboardButton(
            t("fallback.btn_my_access", language),
            callback_data="mis_subs"
        )])

    filas.append([
        InlineKeyboardButton(
            t("fallback.btn_ai", language),
            callback_data="ai_buyer_panel"
        ),
        InlineKeyboardButton(
            t("fallback.btn_support", language),
            callback_data="public_support"
        )
    ])

    filas.append([InlineKeyboardButton(
        t("fallback.btn_home", language),
        callback_data="public_back_start"
    )])

    return InlineKeyboardMarkup(filas)


def tiene_algun_acceso(user_id):
    """Nunca lanza: es para decidir si pintar un botón."""

    try:

        from db import conn

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM users
                WHERE user_id = %s
                  AND COALESCE(subscription_active, FALSE) = TRUE
                  AND (expiration IS NULL OR expiration > NOW())
                LIMIT 1

            """, (int(user_id),))

            return cur.fetchone() is not None

    except Exception as e:

        print("Texto suelto: no se pudo mirar los accesos:", str(e)[:200])
        return False


async def responder_al_texto_suelto(update, context):
    """
    Contesta a un mensaje privado que no encajaba en ningún asistente.

    Devuelve True si contestó. Nunca lanza: es el último recurso del bot y si
    revienta el usuario se queda otra vez sin respuesta, que es justo lo que se
    venía a arreglar.
    """

    try:

        mensaje = getattr(update, "message", None)

        if not mensaje or not (mensaje.text or "").strip():
            return False

        # SOLO EN PRIVADO. En un grupo, contestar a cada mensaje que el bot no
        # entiende es convertirlo en el bot que hay que echar. El registro de
        # handlers ya manda el texto de grupo a otro sitio, pero esto no puede
        # depender del orden de una lista de 40 handlers.
        if getattr(getattr(mensaje, "chat", None), "type", None) != "private":
            return False

        user_id = update.effective_user.id

        idioma = load_user_language(
            user_id,
            telegram_language_code=getattr(
                update.effective_user, "language_code", None
            )
        )

        encontrado = buscar_comunidad_del_codigo(mensaje.text)

        if encontrado:

            group_id, nombre = encontrado

            await mensaje.reply_text(
                build_code_hint_text(nombre, idioma),
                reply_markup=build_code_hint_keyboard(group_id, idioma)
            )

            return True


        await mensaje.reply_text(
            build_fallback_text(idioma),
            reply_markup=build_fallback_keyboard(
                idioma,
                con_accesos=tiene_algun_acceso(user_id)
            )
        )

        return True

    except Exception as e:

        print("Texto suelto: no se pudo contestar:", str(e)[:300])

        return False
