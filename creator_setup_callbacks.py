"""
creator_setup_callbacks: tramo extraído de callback_router.py.

Prefijos: creator_setup_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from ai_handler import activate_ai_help_context
from creator_preview_callbacks import PREVIEW_MODE_LABELS
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

COMMERCIAL_REQUEST_FIELDS = [

    "id",
    "user_id",
    "username",
    "first_name",
    "request_type",
    "status",
    "community_name",
    "community_description",
    "telegram_group_link",
    "bot_name",
    "bot_username",
    "project_description",
    "contact_text",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "admin_notes",
    "trial_starts_at",
    "trial_ends_at",
    "payment_mode",
    "stripe_mode",
    "is_free_group",
    "approved_group_id",
    "approved_telegram_group_id",
    "approved_bot_username",
    "selected_commercial_plan_id",
    "commercial_subscription_status",
    "commercial_subscription_until",
    "requested_public_visibility",
    "creator_setup_status",
    "creator_preview_text",
    "max_groups_allowed",
    "expired_at",
    "delete_after",
    "last_expiry_reminder_at",
    "previous_public_visibility",
    "last_interaction_user_id",
    "last_interaction_username",
    "last_interaction_first_name",
    "last_interaction_at"

]



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def assign_owner_for_commercial_request(*args, **kwargs):
    from callback_router import assign_owner_for_commercial_request as impl
    return impl(*args, **kwargs)


def build_creator_marketplace_keyboard(*args, **kwargs):
    from callback_router import build_creator_marketplace_keyboard as impl
    return impl(*args, **kwargs)


def build_creator_setup_keyboard(*args, **kwargs):
    from callback_router import build_creator_setup_keyboard as impl
    return impl(*args, **kwargs)


def build_location_gate_owner_keyboard(*args, **kwargs):
    from callback_router import build_location_gate_owner_keyboard as impl
    return impl(*args, **kwargs)


def can_edit_marketplace_preview(*args, **kwargs):
    from callback_router import can_edit_marketplace_preview as impl
    return impl(*args, **kwargs)


def clear_creator_onboarding_context(*args, **kwargs):
    from callback_router import clear_creator_onboarding_context as impl
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


def fetch_marketplace_group(*args, **kwargs):
    from callback_router import fetch_marketplace_group as impl
    return impl(*args, **kwargs)


def format_marketplace_category(*args, **kwargs):
    from callback_router import format_marketplace_category as impl
    return impl(*args, **kwargs)


def format_public_visibility(*args, **kwargs):
    from callback_router import format_public_visibility as impl
    return impl(*args, **kwargs)


def get_commercial_request_group_id(*args, **kwargs):
    from callback_router import get_commercial_request_group_id as impl
    return impl(*args, **kwargs)


def get_group_location_gate_display(*args, **kwargs):
    from callback_router import get_group_location_gate_display as impl
    return impl(*args, **kwargs)


def get_marketplace_group_id_for_request(*args, **kwargs):
    from callback_router import get_marketplace_group_id_for_request as impl
    return impl(*args, **kwargs)


def row_to_commercial_request(*args, **kwargs):
    from callback_router import row_to_commercial_request as impl
    return impl(*args, **kwargs)


def start_creator_setup_state(*args, **kwargs):
    from callback_router import start_creator_setup_state as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_creator_marketplace_text(group_id):

    text = (
        "👁 Preview marketplace\n\n"
        "¿Qué tipo de preview quieres mostrar?\n\n"
        "📝 Preview fijo/manual: texto, imagen, vídeo teaser, categoría y tags.\n\n"
        "⚡ Preview dinámico: muestra los últimos 3 vídeos publicados después de activarlo. El bot no descarga vídeos; solo guarda el file_id de Telegram.\n\n"
        "💎 Preview mixto: combina tu teaser manual con los últimos vídeos dinámicos si existen.\n\n"
        "🔒 Sin preview público: muestra una ficha mínima sin enseñar contenido."
    )


    if not group_id:

        return (
            f"{text}\n\n"
            "Estado: pendiente de grupo/canal vinculado.\n"
            "Primero vincula un grupo real para guardar imagen, vídeo, categoría y tags."
        )


    group = fetch_marketplace_group(group_id)


    if not group:

        return f"{text}\n\nEstado: comunidad no disponible o pendiente de publicación."


    return (
        f"{text}\n\n"
        f"Nivel de preview: {PREVIEW_MODE_LABELS.get(group.get('preview_mode'), group.get('preview_mode') or 'manual')}\n"
        f"Texto preview: {'configurado' if group.get('preview_text') else 'pendiente'}\n"
        f"Imagen preview: {'configurada' if group.get('preview_image_file_id') else 'pendiente'}\n"
        f"Vídeo preview: {'configurado' if group.get('preview_video_file_id') else 'pendiente'}\n"
        f"Categoría: {format_marketplace_category(group)}\n"
        f"Tags: {group.get('tags') or 'pendiente'}"
    )


def get_group_payment_settings(request_id):

    with conn.cursor() as cur:

        # Solo se lee is_configured, que es lo único que se usaba: quien llama
        # muestra "configurado" o "pendiente". Antes se traían también las
        # claves de Stripe del creador para descartarlas acto seguido, así que
        # ya no se seleccionan.
        cur.execute("""

            SELECT is_configured
            FROM group_payment_settings
            WHERE commercial_request_id=%s
            LIMIT 1

        """, (request_id,))

        return cur.fetchone()


def get_creator_plan_count(group_id):

    if not group_id:

        return 0


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*)
            FROM plans
            WHERE group_id=%s
            AND is_active=TRUE

        """, (group_id,))

        return cur.fetchone()[0]


def build_creator_setup_summary(request_row):

    request_id = request_row.get("id")
    assigned, group_id = assign_owner_for_commercial_request(request_row)


    if group_id and not assigned:

        owner_status = "pendiente"

    elif group_id:

        owner_status = "asignado"

    else:

        owner_status = "pendiente"


    payment_settings = get_group_payment_settings(request_id)
    stripe_status = "configurado" if payment_settings and payment_settings[0] else "pendiente"
    plan_count = get_creator_plan_count(group_id)
    group_status = "configurado" if group_id else "pendiente"
    texts_status = (
        "configurado"
        if request_row.get("community_name")
        and request_row.get("community_description")
        else "pendiente"
    )
    visibility = format_public_visibility(
        request_row.get("requested_public_visibility")
    )
    location_enabled, region_label = get_group_location_gate_display(group_id)
    location_status = "Activada" if location_enabled else "Desactivada"
    setup_ready = (
        group_status == "configurado"
        and texts_status == "configurado"
        and (
            request_row.get("payment_mode") != "paid"
            or (
                stripe_status == "configurado"
                and plan_count > 0
            )
        )
    )
    setup_status = "setup_ready" if setup_ready else "setup_in_progress"


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_requests
            SET creator_setup_status=%s,
                updated_at=NOW()
            WHERE id=%s

        """, (
            setup_status,
            request_id
        ))


    return (
        "✅ Revisar configuración\n\n"
        f"Grupo/canal: {group_status}\n"
        f"Textos: {texts_status}\n"
        f"Stripe propio: {stripe_status}\n"
        f"Planes: {plan_count}\n"
        f"Visibilidad: {visibility}\n"
        f"📍 Ubicación: {location_status}\n"
        f"Región permitida: {region_label}\n"
        f"Estado owner: {owner_status}\n"
        f"Estado setup: {setup_status}\n\n"
        "El checkout real con Stripe del creador todavía está pendiente de conectar."
    )


def update_commercial_request_access_type(request_id, payment_mode):

    is_free = payment_mode == "free"


    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET payment_mode=%s,
                is_free_group=%s,
                creator_setup_status='setup_in_progress',
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            payment_mode,
            is_free,
            request_id
        ))

        row = cur.fetchone()
        request_row = row_to_commercial_request(row)


        if request_row and request_row.get("approved_group_id"):

            cur.execute("""

                UPDATE groups
                SET is_free_group=%s,
                    is_free=%s
                WHERE id=%s

            """, (
                is_free,
                is_free,
                request_row.get("approved_group_id")
            ))


    return request_row


def build_access_type_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔓 Comunidad gratuita",
            callback_data=f"creator_setup_access_free_{request_id}"
        )],
        [InlineKeyboardButton(
            "💎 Comunidad de pago",
            callback_data=f"creator_setup_access_paid_{request_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"configure_community_{request_id}"
        )]
    ])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_creator_setup_callbacks(update, context, query, user_id, data):

    if data.startswith("creator_setup_reset_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_confirm_"
        )
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        clear_creator_onboarding_context(context)

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE commercial_requests
                SET updated_at=NOW()
                WHERE id=%s

            """, (request_id,))


        await send_clean_message(
            context,
            query.message.chat_id,
            "🧹 Configuración reiniciada.\n\n"
            "La prueba y el cupo asignado se mantienen. Puedes continuar desde el panel.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 Recuperar configuración",
                    callback_data=f"configure_community_{request_id}"
                )],
                [InlineKeyboardButton(
                    "📡 Añadir grupo/canal",
                    callback_data=f"creator_setup_group_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🏠 Inicio",
                    callback_data="public_back_start"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_reset_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_reset_"
        )
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
            "🧹 Reiniciar configuración\n\n"
            "Esto limpiará los pasos temporales abiertos en este chat, pero no borrará tu prueba, cupo ni solicitud comercial.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Confirmar reinicio",
                    callback_data=f"creator_setup_reset_confirm_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver a configuración",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_marketplace_"):

        request_id = extract_commercial_request_id(data, "creator_setup_marketplace_")
        request_row = fetch_commercial_request(request_id)

        if not can_edit_marketplace_preview(request_row, user_id):

            await send_clean_message(
                context,
                query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_marketplace_group_id_for_request(request_row)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_creator_marketplace_text(group_id),
            reply_markup=InlineKeyboardMarkup(
                build_creator_marketplace_keyboard(request_id)
            )
        )

        return

    if data.startswith("creator_setup_group_"):

        request_id = extract_commercial_request_id(data, "creator_setup_group_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "group")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📡 Grupo o canal\n\n"
            "Flujo recomendado:\n\n"
            "1️⃣ Añade este bot a tu grupo o canal.\n"
            "2️⃣ Dale permisos de administrador para gestionar enlaces, usuarios y mensajes de acceso.\n"
            "3️⃣ Espera 30 segundos.\n"
            "4️⃣ El bot detectará automáticamente el ID del grupo.\n"
            "5️⃣ Recibirás un mensaje privado para confirmar la vinculación.\n\n"
            "No necesitas usar bots externos para obtener el ID.\n\n"
            "Si quieres, puedes enviar aquí el link del grupo como referencia. "
            "El link no se usará para sacar el ID real; el ID real se detecta cuando añades el bot al grupo."
        )

        return

    if data.startswith("creator_setup_texts_"):

        request_id = extract_commercial_request_id(data, "creator_setup_texts_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        start_creator_setup_state(context, request_id, "texts")

        await send_clean_message(
            context,
            query.message.chat_id,
            "📝 Textos y descripción\n\n"
            "Paso 1: escribe el nombre público de tu comunidad.\n\n"
            "Ejemplo: GrupoStarsVip"
        )

        return

    if data.startswith("creator_setup_stripe_"):

        request_id = extract_commercial_request_id(data, "creator_setup_stripe_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        group_id = get_commercial_request_group_id(request_row)


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💳 Métodos de pago\n\n"
                "Esta comunidad está marcada como gratuita. Puedes configurar grupo/canal y textos sin activar métodos de pago.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        keyboard = []


        if group_id:

            keyboard.extend([
                [InlineKeyboardButton("💳 Abrir métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")],
                [InlineKeyboardButton("➕ Crear/editar planes", callback_data="edit_group_plans")]
            ])


        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"configure_community_{request_id}")])
        keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

        await send_clean_message(
            context,
            query.message.chat_id,
            "💳 Configuración de pagos del grupo\n\n"
            "Marcar la comunidad como de pago no obliga a usar Stripe. Puedes activar uno o varios métodos de pago.\n\n"
            "💳 Pagos tradicionales\n"
            "- Stripe\n"
            "- PayPal\n"
            "- Revolut\n\n"
            "🪙 Cripto / USDT\n"
            "- ChangeNOW.io / Cripto\n"
            "- Tarjeta EUR → USDT / Guardarian\n\n"
            "🎟 Promociones\n"
            "- Códigos y promociones\n\n"
            "Guardarian permite que el comprador pague con tarjeta en euros y que tú recibas USDT en tu wallet.\n"
            "ChangeNOW sirve para pagos cripto y puede requerir revisión manual según configuración.\n\n"
            + (
                "Abre Métodos de pago del grupo para configurar cada proveedor."
                if group_id
                else
                "Primero vincula tu grupo/canal. Después podrás abrir Métodos de pago del grupo para configurar cada proveedor."
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data.startswith("creator_setup_plans_not_applicable_"):

        request_id = extract_commercial_request_id(
            data,
            "creator_setup_plans_not_applicable_"
        )
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
            "💰 Planes de acceso\n\n"
            "No aplica para comunidad gratuita.\n\n"
            "Puedes configurar grupo/canal y textos. No se pedirá Stripe ni price_id mientras el modo sea gratuito.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_plans_"):

        request_id = extract_commercial_request_id(data, "creator_setup_plans_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        if request_row.get("payment_mode") == "free":

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "No aplica para comunidad gratuita.\n\n"
                "No se pedirá Stripe ni price_id en este modo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "💰 Planes de acceso\n\n"
                "Pendiente de crear/publicar grupo.\n\n"
                "La tabla actual de planes necesita un groups.id real. "
                "No existe una estructura segura de planes pendientes por solicitud, así que primero hay que vincular el grupo/canal.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        plan_count = get_creator_plan_count(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Planes de acceso\n\n"
            f"Planes activos configurados: {plan_count}\n\n"
            "El price_id debe pertenecer al Stripe propio del creador. "
            "No se mezcla con el Stripe global del bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➕ Crear plan",
                    callback_data=f"creator_setup_add_plan_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_add_plan_"):

        request_id = extract_commercial_request_id(data, "creator_setup_add_plan_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        _assigned, group_id = assign_owner_for_commercial_request(request_row)


        if not group_id:

            await send_clean_message(
            context,
            query.message.chat_id,
                "⚠️ No se puede crear un plan todavía.\n\n"
                "Falta un groups.id real asociado a tu solicitud.",
                reply_markup=InlineKeyboardMarkup(
                    build_creator_setup_keyboard(
                        request_id,
                        request_row.get("payment_mode")
                    )
                )
            )

            return


        start_creator_setup_state(context, request_id, "plan")

        await send_clean_message(
            context,
            query.message.chat_id,
            "💰 Crear plan de acceso\n\n"
            "Paso 1: escribe el nombre del plan."
        )

        return

    if data.startswith("creator_setup_access_type_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_type_")
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
            "💳 Tipo de acceso\n\n"
            "Elige cómo entrarán los usuarios a tu comunidad. Puedes cambiarlo mientras configuras la comunidad.",
            reply_markup=build_access_type_keyboard(request_id)
        )

        return

    if data.startswith("creator_setup_access_free_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_free_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "free")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como gratuita. No se pedirá Stripe ni price_id y se mostrará Entrar gratis.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return

    if data.startswith("creator_setup_access_paid_"):

        request_id = extract_commercial_request_id(data, "creator_setup_access_paid_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await send_clean_message(
            context,
            query.message.chat_id,
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        request_row = update_commercial_request_access_type(request_id, "paid")

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n"
            "Tu comunidad queda como de pago.\n\n"
            "Ahora configura planes y elige uno o varios métodos de pago: Stripe, PayPal, Revolut, ChangeNOW o Guardarian EUR → USDT.\n\n"
            "Marcarla como de pago no obliga a usar Stripe.",
            reply_markup=InlineKeyboardMarkup(
                build_creator_setup_keyboard(
                    request_id,
                    request_row.get("payment_mode")
                )
            )
        )

        return

    if data.startswith("creator_setup_location_gate_"):

        request_id = extract_commercial_request_id(data, "creator_setup_location_gate_")
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
                "📍 Restricción por ubicación\n\n"
                "Primero debes vincular tu grupo o canal. Después podrás activar esta restricción.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 Grupo o canal",
                        callback_data=f"creator_setup_group_{request_id}"
                    )],
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data=f"configure_community_{request_id}"
                    )]
                ])
            )

            return


        enabled, region_label = get_group_location_gate_display(group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📍 Restricción por ubicación\n\n"
            f"Estado: {'Activada' if enabled else 'Desactivada'}\n"
            f"Región permitida: {region_label}\n\n"
            "Si está activada, antes de entrar el usuario deberá enviar ubicación desde el botón oficial de Telegram.",
            reply_markup=build_location_gate_owner_keyboard(request_id)
        )

        return

    if data.startswith("creator_setup_visibility_"):

        request_id = extract_commercial_request_id(data, "creator_setup_visibility_")
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
            "👁 Visibilidad pública\n\n"
            f"Ubicación elegida: {format_public_visibility(request_row.get('requested_public_visibility'))}\n\n"
            "La visibilidad la define el propietario principal al aprobar la prueba.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_review_"):

        request_id = extract_commercial_request_id(data, "creator_setup_review_")
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
            build_creator_setup_summary(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_tutorial_"):

        request_id = extract_commercial_request_id(data, "creator_setup_tutorial_")
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
            "🧭 Tutorial paso a paso\n\n"
            "1. Crea o entra en tu cuenta de Stripe.\n"
            "2. En Stripe, busca las claves de desarrollador para copiar STRIPE_SECRET_KEY.\n"
            "3. Configura un webhook en Stripe y guarda el STRIPE_WEBHOOK_SECRET.\n"
            "4. Crea tus productos y precios en Stripe.\n"
            "5. Copia el price_id de cada precio y úsalo al crear planes en el bot.\n"
            "6. Prepara tu grupo/canal de Telegram y añade el bot.\n"
            "7. Asegúrate de que el bot tenga permisos de administrador para gestionar accesos.\n"
            "8. Vuelve a este panel y revisa la configuración.\n\n"
            "No inventes precios ni claves. Copia siempre los datos desde Stripe.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data=f"configure_community_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("creator_setup_ai_"):

        request_id = extract_commercial_request_id(data, "creator_setup_ai_")
        request_row = fetch_commercial_request(request_id)

        if not commercial_request_belongs_to_user(request_row, user_id):

            await query.message.reply_text(
                "⛔ Esta solicitud no pertenece a tu usuario."
            )

            return


        await activate_ai_help_context(
            update,
            context,
            help_context="creator_setup"
        )

        return

    return NOT_HANDLED
