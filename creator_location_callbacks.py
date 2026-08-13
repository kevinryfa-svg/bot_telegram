"""
creator_location_callbacks: tramo extraído de callback_router.py.

Prefijos: creator_location_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from db import conn
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message


# =========================
# CONSTANTES DE ESTE TRAMO
# =========================
# Viven aquí y las importa callback_router, no al revés: un envoltorio
# diferido no sirve para una constante, devolvería una función.

LOCATION_REGION_TYPE_COUNTRY = "country"


LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY = (
    "spanish_autonomous_community"
)


COMUNIDAD_VALENCIANA_REGION = "comunidad_valenciana"


COMUNIDAD_VALENCIANA_LABEL = "Comunidad Valenciana"


HISPANIC_COUNTRIES = [
    ("ES", "España"),
    ("MX", "México"),
    ("AR", "Argentina"),
    ("CO", "Colombia"),
    ("CL", "Chile"),
    ("PE", "Perú"),
    ("VE", "Venezuela"),
    ("EC", "Ecuador"),
    ("BO", "Bolivia"),
    ("PY", "Paraguay"),
    ("UY", "Uruguay"),
    ("CR", "Costa Rica"),
    ("PA", "Panamá"),
    ("GT", "Guatemala"),
    ("HN", "Honduras"),
    ("SV", "El Salvador"),
    ("NI", "Nicaragua"),
    ("DO", "República Dominicana"),
    ("CU", "Cuba"),
    ("PR", "Puerto Rico"),
    ("GQ", "Guinea Ecuatorial")
]


HISPANIC_COUNTRY_LABELS = dict(HISPANIC_COUNTRIES)


SPANISH_AUTONOMOUS_COMMUNITIES = [
    ("all_spain", "Toda España"),
    ("andalucia", "Andalucía"),
    ("aragon", "Aragón"),
    ("asturias", "Asturias"),
    ("islas_baleares", "Islas Baleares"),
    ("canarias", "Canarias"),
    ("cantabria", "Cantabria"),
    ("castilla_la_mancha", "Castilla-La Mancha"),
    ("castilla_y_leon", "Castilla y León"),
    ("cataluna", "Cataluña"),
    (COMUNIDAD_VALENCIANA_REGION, COMUNIDAD_VALENCIANA_LABEL),
    ("extremadura", "Extremadura"),
    ("galicia", "Galicia"),
    ("comunidad_de_madrid", "Comunidad de Madrid"),
    ("region_de_murcia", "Región de Murcia"),
    ("navarra", "Comunidad Foral de Navarra"),
    ("pais_vasco", "País Vasco"),
    ("la_rioja", "La Rioja"),
    ("ceuta", "Ceuta"),
    ("melilla", "Melilla")
]


SPANISH_AUTONOMOUS_COMMUNITY_LABELS = dict(SPANISH_AUTONOMOUS_COMMUNITIES)



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_location_gate_owner_keyboard(*args, **kwargs):
    from callback_router import build_location_gate_owner_keyboard as impl
    return impl(*args, **kwargs)


def commercial_request_belongs_to_user(*args, **kwargs):
    from callback_router import commercial_request_belongs_to_user as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_commercial_request(*args, **kwargs):
    from callback_router import fetch_commercial_request as impl
    return impl(*args, **kwargs)


def get_commercial_request_group_id(*args, **kwargs):
    from callback_router import get_commercial_request_group_id as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_location_country_keyboard(request_id):

    keyboard = []


    for country_code, country_name in HISPANIC_COUNTRIES:

        callback_data = (
            f"creator_location_spain_region_menu_{request_id}"
            if country_code == "ES"
            else f"creator_location_country_set_{request_id}_{country_code}"
        )

        keyboard.append([InlineKeyboardButton(
            country_name,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_spanish_autonomous_community_keyboard(request_id):

    keyboard = []


    for slug, label in SPANISH_AUTONOMOUS_COMMUNITIES:

        callback_data = (
            f"creator_location_country_set_{request_id}_ES"
            if slug == "all_spain"
            else f"creator_location_spain_region_set_{request_id}_{slug}"
        )

        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=callback_data
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data=f"creator_setup_location_gate_{request_id}"
    )])

    return InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_creator_location_callbacks(update, context, query, user_id, data):

    if data.startswith("creator_location_gate_enable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_enable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=COALESCE(allowed_region, %s),
                    allowed_region_type=COALESCE(allowed_region_type, %s)
                WHERE id=%s

            """, (
                "ES",
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación activada.\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.\n\n"
            "Región permitida: España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_gate_disable_"):

        request_id = extract_commercial_request_id(data, "creator_location_gate_disable_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if group_id:

            with conn.cursor() as cur:

                cur.execute("""

                    UPDATE groups
                    SET location_gate_enabled=FALSE
                    WHERE id=%s

                """, (group_id,))

                conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Restricción por ubicación desactivada.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_country_menu_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🌎 Elegir país\n\n"
            "Puedes restringir por país. En España también puedes restringir por comunidad autónoma.",
            reply_markup=build_location_country_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_menu_"):

        request_id = extract_commercial_request_id(data, "creator_location_spain_region_menu_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🇪🇸 España\n\n"
            "Elige toda España o una comunidad autónoma concreta.",
            reply_markup=build_spanish_autonomous_community_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_country_set_"):

        payload = data.replace("creator_location_country_set_", "", 1)

        try:

            request_id_text, country_code = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ País no válido."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            country_code not in HISPANIC_COUNTRY_LABELS
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                country_code,
                LOCATION_REGION_TYPE_COUNTRY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {HISPANIC_COUNTRY_LABELS.get(country_code)}.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_spain_region_set_"):

        payload = data.replace("creator_location_spain_region_set_", "", 1)

        try:

            request_id_text, region_slug = payload.split("_", 1)
            request_id = int(request_id_text)

        except Exception:

            await send_clean_message(
                context,
                query.message.chat_id,
                "❌ Comunidad autónoma no válida."
            )

            return


        request_row = fetch_commercial_request(request_id)

        if (
            region_slug not in SPANISH_AUTONOMOUS_COMMUNITY_LABELS
            or region_slug == "all_spain"
            or not commercial_request_belongs_to_user(request_row, user_id)
        ):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                region_slug,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            f"Región permitida: {SPANISH_AUTONOMOUS_COMMUNITY_LABELS.get(region_slug)}, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return


    if data.startswith("creator_location_region_cv_"):

        request_id = extract_commercial_request_id(data, "creator_location_region_cv_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if not group_id:

            await send_clean_message(
                context,
                query.message.chat_id,
                "📍 Primero vincula tu grupo o canal.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET location_gate_enabled=TRUE,
                    allowed_region=%s,
                    allowed_region_type=%s
                WHERE id=%s

            """, (
                COMUNIDAD_VALENCIANA_REGION,
                LOCATION_REGION_TYPE_SPANISH_AUTONOMOUS_COMMUNITY,
                group_id
            ))

            conn.commit()


        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Región permitida actualizada.\n\n"
            "Región permitida: Comunidad Valenciana, España.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return

    return NOT_HANDLED
