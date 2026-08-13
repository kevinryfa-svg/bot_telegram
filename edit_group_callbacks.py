"""
edit_group_callbacks: tramo extraído de callback_router.py.

Prefijos: edit_group_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from creator_preview_callbacks import PREVIEW_MODE_LABELS
from db import conn
from group_delivery_health_service import describe_group_delivery
from group_service import format_community_kind_capitalized
from rbac_helpers import is_super_admin
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

ADMIN_PERMISSION_COLUMNS = [
    "can_manage_users",
    "can_kick_users",
    "can_ban_users",
    "can_unban_users",
    "can_warn_users",
    "can_reset_warnings",
    "can_manage_plans",
    "can_manage_codes",
    "can_manage_groups",
    "can_manage_payments",
    "can_manage_admins",
    "can_view_users",
    "can_view_payments",
    "can_view_stats",
    "can_view_logs",
    "can_edit_group_texts",
    "can_edit_marketplace_preview",
    "can_respond_group_support",
    "can_resend_links"
]



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_admin_error_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_error_keyboard as impl
    return impl(*args, **kwargs)


def build_group_admin_panel_keyboard(*args, **kwargs):
    from callback_router import build_group_admin_panel_keyboard as impl
    return impl(*args, **kwargs)


def build_group_settings_keyboard(*args, **kwargs):
    from callback_router import build_group_settings_keyboard as impl
    return impl(*args, **kwargs)


def build_group_user_codes_keyboard(*args, **kwargs):
    from callback_router import build_group_user_codes_keyboard as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def fetch_owner_group_quick_status(*args, **kwargs):
    from callback_router import fetch_owner_group_quick_status as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def set_group_user_promo_context(*args, **kwargs):
    from callback_router import set_group_user_promo_context as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

OWNER_QUICK_STATUS_PERMISSIONS = {
    "can_view_users": "ver usuarios",
    "can_manage_users": "gestionar usuarios",
    "can_kick_users": "expulsar usuarios",
    "can_ban_users": "banear usuarios",
    "can_unban_users": "desbanear usuarios",
    "can_warn_users": "gestionar warnings",
    "can_reset_warnings": "reiniciar warnings",
    "can_resend_links": "reenviar enlaces",
    "can_recover_access": "recuperar accesos",
    "can_manage_codes": "gestionar códigos",
    "can_manage_plans": "gestionar planes",
    "can_manage_payments": "gestionar pagos",
    "can_view_payments": "ver pagos",
    "can_manage_groups": "configurar comunidad",
    "can_manage_admins": "gestionar admins",
    "can_view_logs": "ver logs",
    "can_edit_group_texts": "editar textos",
    "can_edit_marketplace_preview": "editar marketplace",
}


def get_group_permission_summary(user_id, group_id):

    if is_super_admin(user_id):

        return "Puedes gestionar: todo el panel de esta comunidad."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT role, """ + ", ".join(ADMIN_PERMISSION_COLUMNS) + """
                FROM admins
                WHERE user_id=%s
                AND group_id=%s
                AND is_active=TRUE
                LIMIT 1

            """, (user_id, group_id))

            row = cur.fetchone()

    except Exception as e:

        print("Error cargando permisos del grupo:", e)

        return "Puedes gestionar: permisos no disponibles ahora."


    if not row:

        return "Puedes gestionar: ninguna sección de esta comunidad."


    role = row[0]

    if role == "GROUP_OWNER":

        return "Puedes gestionar: todo el panel owner de esta comunidad."


    granted = [
        OWNER_QUICK_STATUS_PERMISSIONS[column]
        for index, column in enumerate(ADMIN_PERMISSION_COLUMNS, start=1)
        if row[index] and column in OWNER_QUICK_STATUS_PERMISSIONS
    ]


    if not granted:

        return "Puedes gestionar: permisos limitados sin accesos rápidos activos."


    return "Puedes gestionar: " + ", ".join(granted[:8]) + ("..." if len(granted) > 8 else "") + "."


def build_owner_quick_status_text(user_id, group_id):

    status = fetch_owner_group_quick_status(group_id)
    access_type = "Gratis" if status["is_free_group"] else "Pago"
    marketplace_text = "ON" if status["is_marketplace_visible"] else "OFF"
    main_menu_text = "ON" if status["is_main_menu_visible"] else "OFF"
    free_link_text = "Configurado" if status["free_invite_link"] else "Pendiente"
    community_kind_cap = format_community_kind_capitalized(status.get("community_type"))
    backup_text = "Activo" if status["backup_active"] else "No activo"
    errors_text = "Sin errores críticos recientes"


    if status["critical_errors"]:

        errors_text = "\n".join(
            f"- {event_type or 'error'}: {message or 'sin detalle'}"
            for event_type, message in status["critical_errors"]
        )


    return (
        "✅ Estado rápido de esta comunidad\n\n"
        f"Comunidad: {status['name']}\n"
        f"Tipo: {community_kind_cap}\n"
        f"Tipo de acceso: {access_type}\n"
        f"Marketplace: {marketplace_text}\n"
        f"Menú principal: {main_menu_text}\n"
        f"Link gratuito: {free_link_text}\n"
        f"Usuarios activos: {status['active_users']}\n"
        f"Planes activos: {status['active_plans']}\n"
        f"Códigos activos: {status['active_codes']}\n"
        f"Admins activos: {status['active_admins']}\n"
        f"Backup: {backup_text}\n"
        # Sin esta línea, el propietario no tenía forma de ver desde el panel que
        # su comunidad no puede dar acceso: se enteraba por el aviso, y si lo
        # había borrado, por nada.
        f"Entrega de accesos: {describe_group_delivery(group_id)}\n"
        f"Errores críticos recientes: {errors_text}\n\n"
        f"{get_group_permission_summary(user_id, group_id)}\n\n"
        "🏪 Panel de comunidad\n"
        "Elige el apartado que quieres gestionar."
    )


def build_group_preview_mode_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 Preview manual",
            callback_data="edit_group_preview_mode_manual"
        )],
        [InlineKeyboardButton(
            "⚡ Preview dinámico",
            callback_data="edit_group_preview_mode_dynamic"
        )],
        [InlineKeyboardButton(
            "💎 Preview mixto",
            callback_data="edit_group_preview_mode_hybrid"
        )],
        [InlineKeyboardButton(
            "🔒 Sin preview público",
            callback_data="edit_group_preview_mode_private"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="edit_group_back"
        )]
    ])


def preview_mode_selection_text():

    return (
        "¿Qué tipo de preview quieres para este grupo?\n\n"
        "📝 Manual:\n"
        "Subes una imagen o vídeo fijo que verán los usuarios antes de entrar.\n\n"
        "⚡ Dinámico:\n"
        "El bot mostrará los últimos 3 vídeos publicados en el grupo desde que actives este modo.\n\n"
        "💎 Mixto:\n"
        "Muestra primero el preview manual y además permite ver los últimos vídeos dinámicos.\n\n"
        "🔒 Sin preview:\n"
        "No se mostrará contenido previo, solo la ficha del grupo."
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_edit_group_callbacks(update, context, query, user_id, data):

    edit_group_parts = data.split("_")

    if (
        data.startswith("edit_group_")
        and len(edit_group_parts) >= 3
        and edit_group_parts[2].isdigit()
    ):

        try:
            await query.message.delete()
        except:
            pass


        group_id = int(edit_group_parts[2])


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        # Guardar grupo seleccionado

        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        keyboard = build_group_settings_keyboard(user_id, group_id)


        await query.message.reply_text(

            build_owner_quick_status_text(user_id, group_id)
            + "\nSolo verás secciones compatibles con tus permisos en esta comunidad.",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    if data == "edit_group_back":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans"]
            + ["can_manage_codes", "can_manage_admins"]
            + ["can_edit_group_texts", "can_edit_marketplace_preview"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar este grupo."
            )

            return


        await query.message.reply_text(
            build_owner_quick_status_text(user_id, group_id),
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return

    if data in (
        "edit_group_name",
        "edit_group_stripe",
        "edit_group_admins",
        "edit_group_user_codes"
    ):

        required_permissions = ["can_manage_groups"]


        if data == "edit_group_name":

            required_permissions = ["can_edit_group_texts", "can_manage_groups"]


        if data == "edit_group_admins":

            required_permissions = ["can_manage_admins"]

        if data == "edit_group_user_codes":

            required_permissions = ["can_manage_codes"]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)",
                reply_markup=build_group_admin_error_keyboard()
            )

            return


        if data == "edit_group_admins":

            context.user_data["selected_owner_group"] = group_id

            await send_clean_message(
                context,
                query.message.chat_id,
                "👥 Admins de mi grupo\n\nGestiona admins y permisos por comunidad.",
                reply_markup=build_group_admin_panel_keyboard()
            )

            return


        if data == "edit_group_user_codes":

            set_group_user_promo_context(
                context,
                group_id,
                step="panel"
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                "🎟 Códigos de mi grupo\n\n"
                "Crea códigos para usuarios finales de esta comunidad. "
                "Estos códigos solo funcionan en este grupo y no se mezclan con los códigos promocionales comerciales.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        if data == "edit_group_stripe":

            group = fetch_group_basic_info(group_id)
            group_name = group[1] if group else f"Grupo {group_id}"

            await send_clean_message(
                context,
                query.message.chat_id,
                "🔗 Stripe/configuración pagos\n\n"
                f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
                "Stripe global sigue funcionando para los pagos actuales del bot.\n\n"
                "La configuración de Stripe propio por grupo todavía no está disponible. "
                "Se activará en una fase posterior, con almacenamiento seguro y validación de webhooks por comunidad.\n\n"
                "Por seguridad, todavía no se piden ni se guardan credenciales Stripe del owner desde este panel.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Ver métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
                    [InlineKeyboardButton("⬅️ Volver a planes y pagos", callback_data="owner_panel_payments")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        log_event(
            "owner_panel_placeholder_callback",
            category="ui",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Callback placeholder del panel owner pulsado.",
            metadata={"callback_data": data}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "⚠️ Esta acción todavía no tiene un flujo seguro disponible.\n\n"
                "No se ha modificado ningún dato. Usa las opciones disponibles del panel de comunidad."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data == "edit_group_preview":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)"
            )

            return


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        ):

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)"
            )

            return


        await query.message.reply_text(
            preview_mode_selection_text(),
            reply_markup=build_group_preview_mode_keyboard()

        )

        return

    if data.startswith("edit_group_preview_mode_"):

        preview_mode = data.replace("edit_group_preview_mode_", "", 1)

        if preview_mode not in PREVIEW_MODE_LABELS:

            await query.message.reply_text("❌ Nivel de preview no válido.")

            return


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_edit_marketplace_preview", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\nÁbrela primero en «🏪 Mis comunidades» y repite la acción. Si administras varias, elige la correcta.\n\n(Si crees que deberías tener acceso y no lo tienes, avisa al propietario principal.)"
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE groups
                SET preview_mode=%s
                WHERE id=%s

            """, (
                preview_mode,
                group_id
            ))

            conn.commit()


        if preview_mode in ("manual", "hybrid"):

            context.user_data["editing_preview"] = True
            context.user_data["editing_preview_mode"] = preview_mode

            await query.message.reply_text(
                "✅ Tipo de preview actualizado.\n\n"
                "Envía ahora una imagen o vídeo para guardarlo como preview manual.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver",
                        callback_data="edit_group_back"
                    )]
                ])
            )

            return


        message = "✅ Preview dinámico activado."

        if preview_mode == "dynamic":

            message = (
                "✅ Preview dinámico activado.\n\n"
                "Solo capturará vídeos nuevos publicados en el grupo después de activar este modo."
            )

        elif preview_mode == "private":

            message = "✅ Sin preview público activado."


        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(
                build_group_settings_keyboard(user_id, group_id)
            )
        )

        return

    if data == "edit_group_plans":

        try:
            await query.message.delete()
        except:
            pass


        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "📋 Ver planes",
                callback_data="view_group_plans"
            )],

            [InlineKeyboardButton(
                "➕ Añadir plan",
                callback_data="add_group_plan"
            )],

            [InlineKeyboardButton(
                "✏️ Editar plan",
                callback_data="edit_group_plan_select"
            )],

            [InlineKeyboardButton(
                "🗑 Eliminar plan",
                callback_data="delete_group_plan_select"
            )],

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data=f"edit_group_{group_id}"
            )]

        ]


        await query.message.reply_text(

            "💳 GESTIÓN DE PLANES\n\n"
            "Selecciona una opción:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    if data == "edit_group_plan_select":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permisos para gestionar planes de este grupo."
            )

            return

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE
                ORDER BY id ASC

            """, (group_id,))

            plans = cur.fetchall()


        if not plans:

            await query.message.reply_text(
                "⚠️ No hay planes disponibles."
            )

            return


        keyboard = []


        for plan_id, name in plans:

            keyboard.append([

                InlineKeyboardButton(
                    name,
                    callback_data=f"edit_plan_{plan_id}"
                )

            ])


        keyboard.append([

            InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="edit_group_plans"
            )

        ])


        await query.message.reply_text(

            "✏️ Selecciona el plan a editar:",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    return NOT_HANDLED
