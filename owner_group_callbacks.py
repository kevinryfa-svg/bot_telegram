"""
owner_group_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_group_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from admin_payment_provider_callbacks import (
    OWNER_PAYMENT_PROVIDER_CHANGENOW,
    OWNER_PAYMENT_PROVIDER_GUARDARIAN,
)
from audit_log_service import (
    list_recent_events,
    log_event,
)
from db import conn
from group_service import (
    format_community_kind,
    normalize_community_type,
)
from payment_secret_store import has_payment_encryption_key
from payment_service import (
    PAYMENT_UX_GROUP_LABELS,
    PAYMENT_UX_GROUP_ORDER,
    build_group_payment_methods_text,
    build_group_payment_provider_detail_text,
    clear_group_payment_provider_config,
    disable_group_payment_provider_config,
    ensure_group_payment_provider_config,
    group_payment_provider_statuses_by_ux,
    list_group_payment_provider_statuses,
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_PAYPAL,
    PLAN_PAYMENT_PROVIDER_REVOLUT,
)
from rbac_helpers import (
    get_group_owner_user_id,
    is_super_admin,
)
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

OWNER_PAYMENT_PROVIDER_PAYPAL = PLAN_PAYMENT_PROVIDER_PAYPAL


OWNER_PAYMENT_PROVIDER_REVOLUT = PLAN_PAYMENT_PROVIDER_REVOLUT



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_changenow_tutorial_text(*args, **kwargs):
    from callback_router import build_changenow_tutorial_text as impl
    return impl(*args, **kwargs)


def build_community_users_page(*args, **kwargs):
    from callback_router import build_community_users_page as impl
    return impl(*args, **kwargs)


def build_guardarian_tutorial_text(*args, **kwargs):
    from callback_router import build_guardarian_tutorial_text as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def clear_owner_payment_provider_wizard(*args, **kwargs):
    from callback_router import clear_owner_payment_provider_wizard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def fetch_owner_group_quick_status(*args, **kwargs):
    from callback_router import fetch_owner_group_quick_status as impl
    return impl(*args, **kwargs)


def format_free_invite_link_error(*args, **kwargs):
    from callback_router import format_free_invite_link_error as impl
    return impl(*args, **kwargs)


def get_or_create_free_group_invite_link(*args, **kwargs):
    from callback_router import get_or_create_free_group_invite_link as impl
    return impl(*args, **kwargs)


def user_can_view_community_users(*args, **kwargs):
    from callback_router import user_can_view_community_users as impl
    return impl(*args, **kwargs)


def user_can_view_group_panel(*args, **kwargs):
    from callback_router import user_can_view_group_panel as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_owner_paypal_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_paypal_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_paypal_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_paypal_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")]
    ])


def build_owner_revolut_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_revolut_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_revolut_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_revolut_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")]
    ])


def build_owner_changenow_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Fixed", callback_data=f"owner_payment_changenow_mode_fixed_{group_id}")],
        [InlineKeyboardButton("🌊 Floating", callback_data=f"owner_payment_changenow_mode_float_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_changenow_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")]
    ])


def build_owner_guardarian_mode_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Sandbox", callback_data=f"owner_payment_guardarian_mode_sandbox_{group_id}")],
        [InlineKeyboardButton("🚀 Live", callback_data=f"owner_payment_guardarian_mode_live_{group_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_payment_guardarian_cancel_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")]
    ])


def resolve_group_public_visibility(is_marketplace_visible, is_main_menu_visible):

    if is_marketplace_visible and is_main_menu_visible:

        return "both"


    if is_marketplace_visible:

        return "explore_only"


    if is_main_menu_visible:

        return "start_home"


    return "hidden"


def format_owner_group_publication_state(group_id):

    status = fetch_owner_group_quick_status(group_id)

    return (
        "🌐 Publicación de comunidad\n\n"
        f"Comunidad: {status['name']}\n"
        f"Marketplace: {'ON' if status['is_marketplace_visible'] else 'OFF'}\n"
        f"Menú principal: {'ON' if status['is_main_menu_visible'] else 'OFF'}\n"
        f"Grupo gratuito: {'ON' if status['is_free_group'] else 'OFF'}\n"
        f"Link gratuito: {'configurado' if status['free_invite_link'] else 'pendiente'}"
    )


def build_group_publication_controls_keyboard(user_id, group_id):

    status = fetch_owner_group_quick_status(group_id)
    keyboard = []


    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_edit_marketplace_preview"]):

        keyboard.append([InlineKeyboardButton(
            f"🛒 Marketplace {'OFF' if status['is_marketplace_visible'] else 'ON'}",
            callback_data=f"owner_group_toggle_marketplace_{group_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            f"🏠 Menú principal {'OFF' if status['is_main_menu_visible'] else 'ON'}",
            callback_data=f"owner_group_toggle_main_menu_{group_id}"
        )])
        keyboard.append([InlineKeyboardButton(
            "🙈 Ocultar grupo",
            callback_data=f"owner_group_hide_{group_id}"
        )])


    if user_has_group_permission_any(user_id, group_id, ["can_manage_groups"]):

        keyboard.append([InlineKeyboardButton(
            f"🎁 Grupo gratuito {'OFF' if status['is_free_group'] else 'ON'}",
            callback_data=f"owner_group_toggle_free_{group_id}"
        )])

        if status["free_invite_link"]:

            keyboard.append([InlineKeyboardButton(
                "🔄 Regenerar link gratuito",
                callback_data=f"owner_group_regenerate_free_link_{group_id}"
            )])

        else:

            keyboard.append([InlineKeyboardButton(
                "🔗 Generar link gratuito",
                callback_data=f"owner_group_generate_free_link_{group_id}"
            )])


        keyboard.append([InlineKeyboardButton(
            "🧪 Probar entrada",
            callback_data=f"owner_group_test_entry_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_marketplace")])
    keyboard.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return InlineKeyboardMarkup(keyboard)


def fetch_owner_group_logs(group_id, category_filter=None, event_types=None, limit=30):

    rows = list_recent_events(
        limit=80,
        group_ids=[group_id]
    )


    if category_filter:

        rows = [row for row in rows if row[2] == category_filter]


    if event_types:

        rows = [row for row in rows if row[1] in event_types]


    return rows[:limit]


def build_owner_group_logs_text(group_id, rows, title):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"


    if not rows:

        return (
            f"{title}\n\n"
            f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
            "Todavía no hay actividad registrada para este filtro."
        )


    text = f"{title}\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


    for created_at, event_type, category, severity, log_group_id, log_telegram_group_id, actor_user_id, target_user_id, message in rows:

        text += (
            f"Evento: {event_type or '-'}\n"
            f"Categoría: {category or '-'} / {severity or '-'}\n"
            f"Actor: {actor_user_id or '-'}\n"
            f"Usuario: {target_user_id or '-'}\n"
            f"Detalle: {message or '-'}\n"
            f"Fecha: {created_at or '-'}\n\n"
        )


    return text[:3900]


def build_owner_group_logs_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver a logs", callback_data="owner_panel_logs")],
        [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_group_callbacks(update, context, query, user_id, data):

    if data.startswith("owner_group_users_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_users_"
        )


        if not user_can_view_community_users(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver usuarios de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        try:

            text, keyboard = build_community_users_page(group_id, "active", 0)

        except Exception as e:

            print("community_users_panel_load_error:", str(e)[:500])

            await query.message.reply_text(
                "❌ No he podido cargar usuarios de esta comunidad ahora mismo.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=keyboard
        )

        log_event(
            "community_users_panel_opened",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Panel de usuarios de comunidad abierto.",
            metadata={"segment": "active", "page": 0}
        )

        return

    if data.startswith("owner_group_logs_"):

        payload = data.replace("owner_group_logs_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar los logs de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        log_filter = parts[0]
        group_id = int(parts[1])


        if not user_can_view_group_panel(user_id, group_id, ["can_view_logs"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para ver logs de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        context.user_data["selected_group_admin"] = group_id

        title = "📜 Actividad reciente del grupo"
        category_filter = None
        event_types = None


        if log_filter == "access":

            title = "👥 Logs de accesos"
            category_filter = "access"

        elif log_filter == "payment":

            title = "💳 Logs de pagos"
            category_filter = "payment"

        elif log_filter == "support":

            title = "🛟 Logs de soporte"
            event_types = ["support_ticket_created"]

        elif log_filter == "security":

            title = "🛡 Seguridad / errores"
            event_types = [
                "access_unauthorized",
                "location_check_failed",
                "location_region_mismatch",
                "location_geocode_failed",
                "owner_location_gate_updated",
                "telegram_handler_error"
            ]


        rows = fetch_owner_group_logs(
            group_id,
            category_filter=category_filter,
            event_types=event_types
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_group_logs_text(group_id, rows, title),
            reply_markup=build_owner_group_logs_keyboard()
        )

        return

    if data.startswith("owner_group_payment_methods_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_payment_methods_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver métodos de pago de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        group_id, group_name, telegram_group_id, *_ = group

        keyboard_rows = []
        provider_statuses = list_group_payment_provider_statuses(group_id)
        grouped_provider_statuses = group_payment_provider_statuses_by_ux(
            provider_statuses
        )


        for group_key in PAYMENT_UX_GROUP_ORDER:

            for provider_status in grouped_provider_statuses.get(group_key) or []:

                provider = provider_status.get("provider")
                label = provider_status.get("label") or provider
                group_label = PAYMENT_UX_GROUP_LABELS.get(group_key, "Métodos")

                keyboard_rows.append([
                    InlineKeyboardButton(
                        f"⚙️ {group_label} · {label}",
                        callback_data=f"owner_group_payment_provider_{group_id}_{provider}"
                    )
                ])


        keyboard_rows.extend([
            [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")],
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        keyboard = InlineKeyboardMarkup(keyboard_rows)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_payment_methods_text(
                group_id,
                group_name,
                telegram_group_id,
                owner_user_id
            ),
            reply_markup=keyboard
        )

        return

    if data.startswith("owner_group_payment_provider_"):

        payload = data.replace("owner_group_payment_provider_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        provider_statuses = {
            item.get("provider"): item
            for item in list_group_payment_provider_statuses(group_id)
        }
        provider_status = provider_statuses.get(provider)


        if not provider_status:

            await query.message.reply_text(
                "⚠️ Proveedor no disponible.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id, *_ = group

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔌 Configurar / conectar", callback_data=f"owner_group_payment_connect_{group_id}_{provider}")],
            [InlineKeyboardButton("🚫 Desactivar", callback_data=f"owner_group_payment_disable_{group_id}_{provider}")],
            [InlineKeyboardButton("🗑 Borrar configuración", callback_data=f"owner_group_payment_delete_{group_id}_{provider}")],
            [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            build_group_payment_provider_detail_text(
                group_id,
                group_name,
                provider_status
            ),
            reply_markup=keyboard
        )

        return

    if data.startswith("owner_group_payment_connect_"):

        payload = data.replace("owner_group_payment_connect_", "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para configurar este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        ensure_group_payment_provider_config(
            owner_user_id or user_id,
            group_id,
            provider,
            status="pending"
        )
        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        provider_name = provider.upper()


        if provider == OWNER_PAYMENT_PROVIDER_PAYPAL:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ PayPal no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context, user_id=user_id, action="start_owner_payment_provider_config")
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_PAYPAL
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔌 Conectar PayPal al grupo\n\n"
                "Necesitarás estos datos de tu cuenta PayPal Developer:\n"
                "- PAYPAL_CLIENT_ID\n"
                "- PAYPAL_CLIENT_SECRET\n"
                "- PAYPAL_WEBHOOK_ID\n"
                "- modo sandbox o live\n\n"
                "Las claves se cifran antes de guardarse, no se muestran completas y no deben enviarse por soporte.\n\n"
                "Importante: los cobros PayPal reales para compradores solo estarán disponibles si ENABLE_PAYPAL_PAYMENTS está activo y el plan usa PayPal.",
                reply_markup=build_owner_paypal_mode_keyboard(group_id)
            )

            return

        if provider == OWNER_PAYMENT_PROVIDER_REVOLUT:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Revolut no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context, user_id=user_id, action="start_owner_payment_provider_config")
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_REVOLUT
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔌 Conectar Revolut al grupo\n\n"
                "Necesitarás estos datos de tu cuenta Revolut Merchant:\n"
                "- REVOLUT_API_KEY\n"
                "- REVOLUT_WEBHOOK_SECRET\n"
                "- modo sandbox o live\n"
                "- REVOLUT_BASE_URL opcional\n\n"
                "Las claves se cifran antes de guardarse, no se muestran completas y no deben enviarse por soporte.\n\n"
                "Importante: estas credenciales son del owner/grupo y no usan las variables Railway de la plataforma.",
                reply_markup=build_owner_revolut_mode_keyboard(group_id)
            )

            return

        if provider == OWNER_PAYMENT_PROVIDER_CHANGENOW:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ ChangeNOW no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a ChangeNOW", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context, user_id=user_id, action="start_owner_payment_provider_config")
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_CHANGENOW
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                build_changenow_tutorial_text("esta comunidad")
                + "\n\nPulsa el modo de tasa que quieres preparar para esta comunidad.",
                reply_markup=build_owner_changenow_mode_keyboard(group_id)
            )

            return


        if provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

            if not has_payment_encryption_key():

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    "⚠️ Guardarian no puede configurarse todavía\n\n"
                    "Falta PAYMENT_CONFIG_ENCRYPTION_KEY en la configuración segura del bot.\n\n"
                    "Por seguridad no se piden ni se guardan credenciales reales sin cifrado.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Volver a Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                    ])
                )

                return


            clear_owner_payment_provider_wizard(context, user_id=user_id, action="start_owner_payment_provider_config")
            context.user_data["configuring_owner_payment_provider"] = True
            context.user_data["owner_payment_provider"] = OWNER_PAYMENT_PROVIDER_GUARDARIAN
            context.user_data["owner_payment_group_id"] = group_id
            context.user_data["owner_payment_step"] = "mode"
            context.user_data["owner_payment_payload"] = {}

            await send_clean_message(
                context,
                query.message.chat_id,
                build_guardarian_tutorial_text("esta comunidad")
                + "\n\nPulsa el entorno que quieres preparar para esta comunidad.",
                reply_markup=build_owner_guardarian_mode_keyboard(group_id)
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "🔌 Configurar método de pago del grupo\n\n"
            f"Proveedor: {provider_name}\n\n"
            "Las credenciales propias del owner se introducirán desde el bot, no en Railway.\n\n"
            "Por seguridad, todavía no se piden secretos en esta fase. Antes de guardar credenciales reales debe existir PAYMENT_CONFIG_ENCRYPTION_KEY y el wizard debe borrar/ocultar mensajes sensibles.\n\n"
            "Para PayPal se necesitará client_id, client_secret, webhook_id y modo sandbox/live. No se mostrarán secretos completos en Telegram.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver al proveedor", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("owner_group_payment_disable_") or data.startswith("owner_group_payment_delete_"):

        deleting = data.startswith("owner_group_payment_delete_")
        prefix = "owner_group_payment_delete_" if deleting else "owner_group_payment_disable_"
        payload = data.replace(prefix, "", 1)
        parts = payload.split("_", 1)


        if len(parts) != 2 or not parts[0].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar el método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        provider = parts[1]
        owner_user_id = get_group_owner_user_id(group_id)


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para modificar este método de pago.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_CHANGENOW:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración ChangeNOW\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Stripe, PayPal ni Revolut.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_changenow_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_PAYPAL:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración PayPal\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a PayPal plataforma ni a Stripe global.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_paypal_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_REVOLUT:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración Revolut\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Revolut plataforma, PayPal ni Stripe.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_revolut_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting and provider == OWNER_PAYMENT_PROVIDER_GUARDARIAN:

            await send_clean_message(
                context,
                query.message.chat_id,
                "🗑 Borrar configuración Guardarian\n\n"
                "Esto eliminará las credenciales cifradas guardadas para esta comunidad. "
                "No afecta a Stripe, PayPal, Revolut ni ChangeNOW.\n\n"
                "¿Confirmas el borrado?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirmar borrado", callback_data=f"owner_payment_guardarian_confirm_delete_{group_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_group_payment_provider_{group_id}_{provider}")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if deleting:

            updated = clear_group_payment_provider_config(group_id, provider)
            event_type = "group_payment_provider_config_deleted"
            message = "Configuración de método de pago del grupo borrada."

        else:

            updated = disable_group_payment_provider_config(group_id, provider)
            event_type = "group_payment_provider_config_disabled"
            message = "Método de pago del grupo desactivado."


        if updated:

            log_event(
                event_type,
                category="payment",
                severity="info",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message=message,
                metadata={"provider": provider}
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            ("✅ " if updated else "⚠️ ") + (
                "Configuración borrada." if deleting else "Método desactivado."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a métodos de pago", callback_data=f"owner_group_payment_methods_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("owner_group_payments_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_payments_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver pagos de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id, *_ = group

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id,
                           plan,
                           amount,
                           currency,
                           status,
                           payment_date
                    FROM payments
                    WHERE group_id=%s
                    ORDER BY payment_date DESC
                    LIMIT 30

                """, (group_id,))

                rows = cur.fetchall()

                cur.execute("""

                    SELECT user_id,
                           plan_id,
                           amount,
                           currency,
                           status,
                           created_at,
                           provider,
                           id
                    FROM payment_transactions
                    WHERE group_id=%s
                    AND provider='changenow'
                    ORDER BY created_at DESC
                    LIMIT 20

                """, (group_id,))

                changenow_rows = cur.fetchall()

        except Exception as e:

            print("Error cargando pagos de grupo:", e)

            await query.message.reply_text(
                "❌ No he podido cargar los pagos de esta comunidad ahora mismo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if not rows and not changenow_rows:

            await send_clean_message(
                context,
                query.message.chat_id,
                f"💳 Pagos recibidos\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\nTodavía no hay pagos recibidos para esta comunidad.",
                reply_markup=keyboard
            )

            return


        text = f"💳 Pagos recibidos\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


        for payment_user_id, plan_name, amount, currency, status, payment_date in rows:

            text += (
                f"Usuario: {payment_user_id}\n"
                f"Plan: {plan_name or '-'}\n"
                f"Importe: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n\n"
            )


        if changenow_rows:

            text += "💱 ChangeNOW en revisión/manual\n\n"


        for payment_user_id, plan_id, amount, currency, status, payment_date, provider, transaction_id in changenow_rows:

            text += (
                f"Referencia: #{transaction_id}\n"
                f"Usuario: {payment_user_id}\n"
                f"Plan ID: {plan_id or '-'}\n"
                f"Importe plan: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n"
                "Acceso: pendiente de revisión manual\n\n"
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            text[:3900],
            reply_markup=keyboard
        )

        return

    if data.startswith("owner_group_subscriptions_"):

        group_id = extract_commercial_request_id(
            data,
            "owner_group_subscriptions_"
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        owner_user_id = get_group_owner_user_id(group_id)


        if not group:

            await query.message.reply_text(
                "⚠️ Comunidad no encontrada.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if not is_super_admin(user_id) and owner_user_id != user_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver suscripciones de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id
        _group_id, group_name, _telegram_group_id, *_ = group

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id,
                           username,
                           first_name,
                           expiration,
                           subscription_active,
                           created_at
                    FROM users
                    WHERE group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )
                    ORDER BY expiration ASC NULLS LAST,
                             created_at DESC
                    LIMIT 30

                """, (group_id,))

                rows = cur.fetchall()

        except Exception as e:

            print("Error cargando suscripciones de grupo:", e)

            await query.message.reply_text(
                "❌ No he podido cargar las suscripciones de esta comunidad ahora mismo.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
            [InlineKeyboardButton("🏪 Mis comunidades", callback_data="admin_edit_group")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])


        if not rows:

            await send_clean_message(
                context,
                query.message.chat_id,
                f"📌 Suscripciones activas\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\nTodavía no hay suscripciones activas para esta comunidad.",
                reply_markup=keyboard
            )

            return


        text = f"📌 Suscripciones activas\n\nComunidad: {group_name or f'Grupo {group_id}'}\n\n"


        for subscriber_user_id, username, first_name, expiration, _subscription_active, created_at in rows:

            name = first_name or "Sin nombre"

            if username:

                name += f" (@{username})"


            expiration_text = "permanente" if expiration is None else str(expiration)

            text += (
                f"Usuario: {subscriber_user_id}\n"
                f"Nombre: {name}\n"
                f"Acceso: {expiration_text}\n"
                f"Alta: {created_at or '-'}\n\n"
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            text[:3900],
            reply_markup=keyboard
        )

        return

    if data.startswith("owner_group_publication_"):

        group_id = extract_commercial_request_id(data, "owner_group_publication_")


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups", "can_edit_marketplace_preview"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar la publicación de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_owner_group"] = group_id
        context.user_data["selected_group_admin"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            format_owner_group_publication_state(group_id),
            reply_markup=build_group_publication_controls_keyboard(user_id, group_id)
        )

        return

    if (
        data.startswith("owner_group_toggle_marketplace_")
        or data.startswith("owner_group_toggle_main_menu_")
        or data.startswith("owner_group_hide_")
    ):

        if data.startswith("owner_group_toggle_marketplace_"):

            group_id = extract_commercial_request_id(data, "owner_group_toggle_marketplace_")
            action = "marketplace"

        elif data.startswith("owner_group_toggle_main_menu_"):

            group_id = extract_commercial_request_id(data, "owner_group_toggle_main_menu_")
            action = "main_menu"

        else:

            group_id = extract_commercial_request_id(data, "owner_group_hide_")
            action = "hide"


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups", "can_edit_marketplace_preview"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar la visibilidad de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        status = fetch_owner_group_quick_status(group_id)
        marketplace_visible = bool(status["is_marketplace_visible"])
        main_menu_visible = bool(status["is_main_menu_visible"])


        if action == "marketplace":

            marketplace_visible = not marketplace_visible

        elif action == "main_menu":

            main_menu_visible = not main_menu_visible

        else:

            marketplace_visible = False
            main_menu_visible = False


        public_visibility = resolve_group_public_visibility(
            marketplace_visible,
            main_menu_visible
        )

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET is_marketplace_visible=%s,
                    is_main_menu_visible=%s,
                    public_visibility=%s
                WHERE id=%s

            """, (
                marketplace_visible,
                main_menu_visible,
                public_visibility,
                group_id
            ))

            conn.commit()


        log_event(
            "owner_group_publication_updated",
            category="marketplace",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó visibilidad pública de comunidad.",
            metadata={
                "is_marketplace_visible": marketplace_visible,
                "is_main_menu_visible": main_menu_visible,
                "public_visibility": public_visibility
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Visibilidad actualizada.\n\n" + format_owner_group_publication_state(group_id),
            reply_markup=build_group_publication_controls_keyboard(user_id, group_id)
        )

        return

    if data.startswith("owner_group_toggle_free_"):

        group_id = extract_commercial_request_id(data, "owner_group_toggle_free_")


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para cambiar el tipo de acceso de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        status = fetch_owner_group_quick_status(group_id)
        new_value = not bool(status["is_free_group"])

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET is_free_group=%s,
                    is_free=%s
                WHERE id=%s

            """, (
                new_value,
                new_value,
                group_id
            ))

            conn.commit()


        log_event(
            "owner_group_free_access_updated",
            category="marketplace",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Owner actualizó acceso gratuito de comunidad.",
            metadata={
                "is_free": new_value
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Tipo de acceso actualizado.\n\n" + format_owner_group_publication_state(group_id),
            reply_markup=build_group_publication_controls_keyboard(user_id, group_id)
        )

        return

    if (
        data.startswith("owner_group_generate_free_link_")
        or data.startswith("owner_group_regenerate_free_link_")
        or data.startswith("owner_group_test_entry_")
    ):

        if data.startswith("owner_group_generate_free_link_"):

            group_id = extract_commercial_request_id(data, "owner_group_generate_free_link_")
            regenerate = False

        elif data.startswith("owner_group_regenerate_free_link_"):

            group_id = extract_commercial_request_id(data, "owner_group_regenerate_free_link_")
            regenerate = True

        else:

            group_id = extract_commercial_request_id(data, "owner_group_test_entry_")
            regenerate = False


        if not user_can_view_group_panel(user_id, group_id, ["can_manage_groups"]):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar el link gratuito de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        result = get_or_create_free_group_invite_link(
            group_id,
            regenerate=regenerate
        )

        if not result.get("ok"):

            reason = result.get("reason")
            community_type = normalize_community_type(result.get("community_type"))
            community_kind = format_community_kind(community_type)

            if reason == "not_free_group":

                message = "Este grupo aún no está configurado como gratuito ni tiene planes activos."

            elif reason == "telegram_error":

                message = format_free_invite_link_error(
                    result.get("telegram_result"),
                    community_kind=community_kind
                )

            else:

                message = "No he podido generar el link gratuito de esta comunidad."


            await send_clean_message(
                context,
                query.message.chat_id,
                f"⚠️ {message}",
                reply_markup=build_group_publication_controls_keyboard(user_id, group_id)
            )

            return


        action_text = "regenerado" if regenerate else ("creado" if result.get("created") else "ya estaba configurado")

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                f"✅ Link gratuito {action_text}.\n\n"
                f"{result.get('invite_link')}"
            ),
            reply_markup=build_group_publication_controls_keyboard(user_id, group_id)
        )

        return

    return NOT_HANDLED
