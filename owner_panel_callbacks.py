"""
owner_panel_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_panel_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from admin_button_audit import (
    callback_has_handler,
    flatten_keyboard_buttons,
    load_callback_router_source,
)
from admin_payment_provider_callbacks import (
    OWNER_PAYMENT_PROVIDER_CHANGENOW,
    OWNER_PAYMENT_PROVIDER_GUARDARIAN,
)
from admin_permission_map import get_required_permissions_for_callback
from db import conn
from group_service import (
    format_community_kind_capitalized,
    normalize_community_type,
)
from guardian_callbacks import (
    build_owner_guardian_addon_required_keyboard,
    build_owner_guardian_addon_required_text,
    build_owner_guardian_panel_keyboard,
    log_owner_guardian_addon_gate,
    owner_can_use_guardian,
)
from guardian_service import (
    ensure_guardian_settings,
    fetch_guardian_settings,
)
from owner_backup_service import fetch_owner_backup_job
from owner_group_callbacks import (
    OWNER_PAYMENT_PROVIDER_PAYPAL,
    OWNER_PAYMENT_PROVIDER_REVOLUT,
)
from owner_revenue_service import build_owner_revenue_text, build_payments_csv
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

OWNER_PANEL_SECTIONS = {
    "owner_panel_users": (
        "👥 Usuarios y accesos",
        "Gestiona entradas, expulsiones, bans, warnings y recuperación de acceso.",
        ["can_view_users", "can_manage_users", "can_kick_users", "can_ban_users", "can_unban_users", "can_warn_users", "can_reset_warnings", "can_resend_links", "can_recover_access"],
        "users"
    ),
    "owner_panel_codes": (
        "🎟 Códigos y promociones",
        "Crea y revisa códigos de acceso exclusivos para esta comunidad.",
        ["can_manage_codes"],
        "codes"
    ),
    "owner_panel_payments": (
        "💳 Planes y pagos del grupo",
        "Gestiona planes y métodos de pago: Stripe, PayPal, Revolut, ChangeNOW, Guardarian y promociones.",
        ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"],
        "payments"
    ),
    "owner_panel_security": (
        "🛡 Seguridad del grupo",
        "Revisa protección de acceso, anti-intrusos, anti-links y ubicación permitida.",
        ["can_manage_groups", "can_view_logs"],
        "security"
    ),
    "owner_panel_marketplace": (
        "🖼 Marketplace y preview",
        "Configura visibilidad pública, ficha, previews, categoría y tags.",
        ["can_manage_groups", "can_edit_group_texts", "can_edit_marketplace_preview"],
        "marketplace"
    ),
    "owner_panel_admins": (
        "👑 Administradores del grupo",
        "Añade admins de grupo y ajusta sus permisos por comunidad.",
        ["can_manage_admins"],
        "admins"
    ),
    "owner_panel_logs": (
        "📜 Logs y actividad del grupo",
        "Consulta accesos, pagos, códigos, backups y errores de esta comunidad.",
        ["can_view_logs"],
        "logs"
    ),
    "owner_panel_support": (
        "🛟 Solicitudes de soporte",
        "Revisa el acceso al soporte de esta comunidad sin mezclar tickets globales.",
        ["can_respond_group_support"],
        "support"
    ),
    "owner_panel_satisfaction": (
        "😊 Encuestas de comunidad",
        "Envía encuestas solo a usuarios de esta comunidad sin duplicar completados.",
        ["can_manage_groups", "can_view_logs"],
        "satisfaction"
    ),
    "owner_panel_backup": (
        "💾 Backups automáticos",
        "Crea backups JSON manuales o automáticos de la configuración operativa de esta comunidad.",
        ["can_manage_groups"],
        "backup"
    ),
    "owner_panel_general": (
        "⚙️ Configuración de la comunidad",
        "Edita datos básicos, tipo de acceso y ajustes seguros de la comunidad.",
        ["can_manage_groups", "can_edit_group_texts"],
        "general"
    )
}



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_settings_keyboard(*args, **kwargs):
    from callback_router import build_group_settings_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_backup_addon_required_keyboard(*args, **kwargs):
    from callback_router import build_owner_backup_addon_required_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_backup_addon_required_text(*args, **kwargs):
    from callback_router import build_owner_backup_addon_required_text as impl
    return impl(*args, **kwargs)


def build_owner_backup_panel_keyboard(*args, **kwargs):
    from callback_router import build_owner_backup_panel_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_location_management_keyboard(*args, **kwargs):
    from callback_router import build_owner_location_management_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_location_management_text(*args, **kwargs):
    from callback_router import build_owner_location_management_text as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_satisfaction_panel_keyboard(*args, **kwargs):
    from callback_router import build_owner_satisfaction_panel_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_section_keyboard(*args, **kwargs):
    from callback_router import build_owner_section_keyboard as impl
    return impl(*args, **kwargs)


def button(*args, **kwargs):
    from callback_router import button as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_owner_backup_frequency(*args, **kwargs):
    from callback_router import format_owner_backup_frequency as impl
    return impl(*args, **kwargs)


def get_group_location_gate_display(*args, **kwargs):
    from callback_router import get_group_location_gate_display as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def log_owner_backup_addon_gate(*args, **kwargs):
    from callback_router import log_owner_backup_addon_gate as impl
    return impl(*args, **kwargs)


def owner_can_use_backups(*args, **kwargs):
    from callback_router import owner_can_use_backups as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_owner_guardian_panel_text(group_id, settings=None):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    telegram_group_id = group[2] if group else None
    settings = settings or fetch_guardian_settings(group_id)

    if not settings:

        settings = ensure_guardian_settings(
            group_id,
            owner_user_id=get_group_owner_user_id(group_id),
            telegram_group_id=telegram_group_id
        )


    log_channel = (
        f"{settings.get('log_channel_title') or settings.get('log_channel_id')}"
        if settings and settings.get("log_channel_id")
        else "No conectado"
    )
    enabled_text = "Configurado" if settings and settings.get("is_enabled") else "Pendiente"
    action_mode = settings.get("action_mode") if settings else "log_only"

    return (
        "🛡 Guardian\n\n"
        f"Comunidad: {group_name}\n"
        f"Telegram group id: {telegram_group_id or '-'}\n"
        f"Estado: {enabled_text}\n"
        f"Canal de logs: {log_channel}\n"
        f"Modo: {action_mode or 'log_only'}\n\n"
        "Base técnica activa:\n"
        "- Canal de logs Guardian.\n"
        "- Ajustes iniciales anti-links, palabras bloqueadas, warnings y modo noche.\n"
        "- Registro interno de eventos.\n\n"
        "Seguridad: en esta fase Guardian está en modo solo registro. No expulsa, no banea, no borra mensajes y no modifica accesos."
    )


OWNER_PANEL_ALLOWED_REPEATED_CALLBACKS = {
    "public_back_start",
    "admin_edit_group",
    "edit_group_back",
    "back_admin",
    "back_owner",
    "owner_panel_users",
    "owner_panel_codes",
    "owner_panel_payments",
    "owner_panel_security",
    "owner_panel_marketplace",
    "owner_panel_admins",
    "owner_panel_logs",
    "owner_panel_support",
    "owner_panel_satisfaction",
    "owner_panel_backup",
    "owner_panel_guardian",
    "owner_panel_general",
    "owner_addons_menu",
    "owner_addons_active",
    "owner_panel_commercial_config",
    "edit_group_name",
    "edit_group_preview",
    "owner_panel_location_info",
    "owner_panel_security_info",
    "owner_panel_audit"
}


OWNER_PANEL_ALLOWED_REPEATED_PREFIXES = (
    "owner_panel_help_",
    "owner_group_logs_",
    "owner_group_users_",
    "community_users_sync_known_",
    "owner_location_",
    "owner_backup_",
    "owner_guardian_"
)


def classify_owner_panel_repeated_callback(callback_data, placeholder_callbacks=None):

    placeholder_callbacks = placeholder_callbacks or {}

    if callback_data in OWNER_PANEL_ALLOWED_REPEATED_CALLBACKS:
        return "allowed_navigation"

    if any(callback_data.startswith(prefix) for prefix in OWNER_PANEL_ALLOWED_REPEATED_PREFIXES):
        return "allowed_navigation"

    if callback_data in placeholder_callbacks:
        return "allowed_informational"

    return "suspicious"


def build_owner_security_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    location_enabled, region_label = get_group_location_gate_display(group_id)
    location_status = "Activada" if location_enabled else "Desactivada"

    return (
        "🛡 Seguridad del grupo\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        "Estado actual:\n"
        "- Anti-intrusos: activo con validación de users e invite_links.\n"
        "- Links no registrados: se bloquean desde el control de entrada.\n"
        f"- Restricción por ubicación: {location_status}.\n"
        f"- Región permitida: {region_label}.\n\n"
        "Acciones disponibles ahora:\n"
        "- Gestionar ubicación permitida.\n"
        "- Revisar logs de accesos y bloqueos.\n"
        "- Gestionar usuarios/warnings desde Usuarios y accesos.\n\n"
        "Próximamente: interruptores separados para anti-links y políticas avanzadas. "
        "No aparecen como botones porque todavía no existen como configuración independiente segura."
    )


def build_owner_security_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Guardian", callback_data="owner_panel_guardian")],
        [InlineKeyboardButton("📍 Gestionar ubicación", callback_data="owner_panel_location_info")],
        [InlineKeyboardButton("📢 Grupos de publicidad", callback_data=f"owner_publicity_group_{group_id}")],
        [InlineKeyboardButton("📜 Logs de accesos", callback_data=f"owner_group_logs_access_{group_id}")],
        [InlineKeyboardButton("👥 Usuarios y accesos", callback_data="owner_panel_users")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_security")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_users_panel_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    return (
        "👥 Usuarios y accesos\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        "Desde aquí puedes revisar usuarios de esta comunidad y abrir acciones de acceso. "
        "Las acciones usan el grupo seleccionado para evitar mezclar usuarios de otras comunidades.\n\n"
        "Acciones disponibles según permisos:\n"
        "- Ver usuarios de esta comunidad.\n"
        "- Expulsar, banear o desbanear usuarios.\n"
        "- Gestionar warnings si tu rol lo permite.\n"
        "- Reenviar o recuperar enlaces de acceso."
    )


def build_owner_backup_panel_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    owner_user_id = get_group_owner_user_id(group_id)
    job = fetch_owner_backup_job(owner_user_id, group_id) if owner_user_id else None
    frequency = job.get("frequency") if job else "manual"
    automatic_status = "Activo" if job and job.get("is_active") else "Manual"
    next_run_at = format_commercial_datetime(job.get("next_run_at")) if job else "-"

    return (
        "💾 Backups automáticos\n\n"
        f"Comunidad actual: {group_name or f'Grupo {group_id}'}\n\n"
        "Puedes crear un backup JSON manual o configurar backups automáticos de la configuración operativa de esta comunidad.\n\n"
        "Incluye configuración básica, planes, permisos, resúmenes de códigos, links, campañas, servicios extra, encuestas, soporte y métricas.\n"
        "No incluye secretos, tokens, datos de tarjetas, variables de entorno, conversaciones completas ni enlaces privados completos.\n\n"
        f"Modo actual: {automatic_status}\n"
        f"Frecuencia: {format_owner_backup_frequency(frequency)}\n"
        f"Próximo backup: {next_run_at}"
    )


def build_owner_general_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    telegram_group_id = group[2] if group else None
    community_type = normalize_community_type(group[3] if group and len(group) > 3 else None)
    access_type = "No configurado"
    public_visibility = "-"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT (
                           COALESCE(is_free_group, FALSE)
                           OR COALESCE(is_free, FALSE)
                       ),
                       public_visibility
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()


        if row:

            access_type = "Gratis" if row[0] else "Pago"
            public_visibility = row[1] or "-"

    except Exception as e:

        print("Error cargando configuración general owner:", e)


    return (
        "⚙️ Configuración de la comunidad\n\n"
        f"Nombre: {group_name or f'Grupo {group_id}'}\n"
        f"ID interno: {group_id}\n"
        f"Telegram ID: {telegram_group_id or '-'}\n"
        f"Tipo: {format_community_kind_capitalized(community_type)}\n"
        f"Tipo de acceso: {access_type}\n"
        f"Visibilidad marketplace: {public_visibility}\n\n"
        "Esta pantalla agrupa rutas seguras de configuración. Los cambios sensibles, como pagos o visibilidad, "
        "se abren en pantallas específicas para evitar tocar checkout o accesos por accidente."
    )


def build_owner_general_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Nombre / descripción", callback_data="edit_group_name")],
        [InlineKeyboardButton("🔓 Configuración comercial", callback_data="owner_panel_commercial_config")],
        [InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")],
        [InlineKeyboardButton("📍 Ubicación permitida", callback_data="owner_panel_location_info")],
        [InlineKeyboardButton("🛡 Seguridad del grupo", callback_data="owner_panel_security")],
        [InlineKeyboardButton("💳 Métodos de pago del grupo", callback_data=f"owner_group_payment_methods_{group_id}")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_general")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_commercial_config_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    is_free_group = None
    active_plans = 0
    active_payment_methods = 0


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT (
                    COALESCE(is_free_group, FALSE)
                    OR COALESCE(is_free, FALSE)
                )
                FROM groups
                WHERE id=%s
                LIMIT 1

            """, (group_id,))

            row = cur.fetchone()

            is_free_group = row[0] if row else None

            cur.execute("""

                SELECT COUNT(*)
                FROM plans
                WHERE group_id=%s
                AND is_active=TRUE

            """, (group_id,))
            active_plans = cur.fetchone()[0]

            cur.execute("""

                SELECT COUNT(*)
                FROM group_payment_provider_configs
                WHERE group_id=%s
                AND is_enabled=TRUE
                AND status='active'

            """, (group_id,))
            active_payment_methods = cur.fetchone()[0]

    except Exception as e:

        print("Error cargando configuración comercial owner:", e)


    access_type = "Gratis" if is_free_group is True else "Pago" if is_free_group is False else "No configurado"

    return (
        "💳 Configuración de pagos del grupo\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n"
        f"Tipo de acceso actual: {access_type}\n"
        f"Planes activos: {active_plans}\n"
        f"Métodos de pago del grupo activos: {active_payment_methods}\n\n"
        "Marcar el grupo como de pago no obliga a usar Stripe. Puedes activar uno o varios métodos de pago para cobrar tus suscripciones.\n\n"
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
        "ChangeNOW sirve para pagos cripto y puede requerir revisión manual según configuración."
    )


def build_owner_commercial_config_keyboard(group_id, user_id=None):

    keyboard = []
    owner_can_manage_payment_methods = (
        user_id is not None
        and (
            is_super_admin(user_id)
            or get_group_owner_user_id(group_id) == user_id
        )
    )


    if owner_can_manage_payment_methods:

        keyboard.extend([
            [InlineKeyboardButton("💳 Stripe", callback_data="edit_group_stripe")],
            [InlineKeyboardButton("🅿️ PayPal", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_PAYPAL}")],
            [InlineKeyboardButton("🏦 Revolut", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_REVOLUT}")],
            [InlineKeyboardButton("💱 ChangeNOW.io / Cripto", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_CHANGENOW}")],
            [InlineKeyboardButton("💳 Tarjeta EUR → USDT / Guardarian", callback_data=f"owner_group_payment_provider_{group_id}_{OWNER_PAYMENT_PROVIDER_GUARDARIAN}")],
            [InlineKeyboardButton("💳 Ver todos los métodos", callback_data=f"owner_group_payment_methods_{group_id}")]
        ])


    keyboard.extend([
        [InlineKeyboardButton("🎟 Códigos y promociones", callback_data="owner_panel_codes")],
        [InlineKeyboardButton("📋 Ver planes", callback_data="view_group_plans")],
        [InlineKeyboardButton("➕ Crear/editar planes", callback_data="edit_group_plans")],
        [InlineKeyboardButton("🖼 Marketplace y preview", callback_data="owner_panel_marketplace")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="owner_panel_help_payments")],
        [InlineKeyboardButton("⬅️ Volver a configuración", callback_data="owner_panel_general")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_owner_panel_help_text(section):

    help_texts = {
        "users": "👥 Usuarios y accesos\n\nSirve para revisar usuarios, recuperar enlaces, expulsar, banear y gestionar warnings. Úsalo cuando un usuario tenga problemas de entrada o incumpla normas.",
        "codes": "🎟 Códigos y promociones\n\nCrea códigos de acceso para esta comunidad. Solo afectan a este grupo y no se mezclan con códigos comerciales globales.",
        "payments": "💳 Planes y pagos\n\nGestiona planes, pagos recibidos, suscripciones activas y métodos de pago del grupo. De pago no significa solo Stripe: puedes activar Stripe, PayPal, Revolut, ChangeNOW, Guardarian o códigos/promociones según tu configuración.",
        "security": "🛡 Seguridad\n\nGuardian es el control principal: antispam, palabras prohibidas, bloqueo de enlaces y modo noche. Aquí también tienes el resumen de seguridad, la ubicación permitida, los grupos de publicidad y los logs de accesos. Las acciones que afectan a usuarios reales quedan registradas.",
        "marketplace": "🖼 Marketplace y preview\n\nEdita la ficha pública, previews, categoría y tags de la comunidad.",
        "admins": "👑 Administradores\n\nAñade o retira admins de grupo y define permisos concretos por comunidad.",
        "logs": "📜 Logs y actividad\n\nRevisa actividad importante de esta comunidad: accesos, pagos, códigos, soporte, backups y errores. Owner/admin solo ve su grupo.",
        "support": "🛟 Soporte\n\nMuestra tickets vinculados a esta comunidad. El owner solo ve tickets de sus grupos; el soporte global queda para super admin.",
        "satisfaction": "😊 Encuestas de comunidad\n\nEnvía encuestas solo a usuarios de esta comunidad. Por justicia, quienes ya respondieron no vuelven a recibirla por defecto.",
        "backup": "🛡 Backup premium\n\nConfigura copia de mensajes nuevos que el bot recibe. No descarga archivos ni usa cuentas usuario.",
        "general": "⚙️ Configuración general\n\nAgrupa datos básicos y opciones seguras de comunidad. Los cambios sensibles usan confirmación o pantallas específicas."
    }

    return help_texts.get(
        section,
        "🏪 Panel de comunidad\n\nGestiona esta comunidad por apartados. Usa Volver para regresar al panel y Inicio para salir."
    )


def build_owner_panel_audit_report(user_id, group_id):

    router_source = load_callback_router_source()
    handler_source = router_source.split("async def button", 1)[-1]
    menu_specs = [{
        "name": "Panel de comunidad",
        "keyboard": InlineKeyboardMarkup(build_group_settings_keyboard(user_id, group_id))
    }]


    for callback_data, (_title, _description, required_permissions, section) in OWNER_PANEL_SECTIONS.items():

        if user_has_group_permission_any(user_id, group_id, required_permissions):

            menu_specs.append({
                "name": f"Sección {section}",
                "keyboard": build_owner_section_keyboard(user_id, group_id, section)
            })


    all_buttons = []


    for menu in menu_specs:

        all_buttons.extend(
            flatten_keyboard_buttons(
                menu.get("name"),
                menu.get("keyboard")
            )
        )


    placeholder_callbacks = {
        "owner_panel_general_info": "solo informativo: configuración general avanzada pendiente",
        "edit_group_stripe": "solo informativo: Stripe propio por grupo pendiente"
    }
    editable_callbacks = {
        "owner_panel_users",
        "owner_panel_security",
        "owner_panel_backup",
        "owner_panel_general",
        "owner_panel_commercial_config",
        "owner_panel_access_type_info",
        "owner_panel_location_info",
        "owner_panel_security_info",
        "owner_support_tickets",
        "owner_panel_satisfaction",
        "owner_satisfaction_send_pending",
        "owner_satisfaction_resend_incomplete",
        "owner_satisfaction_send_never_sent",
        "owner_satisfaction_delivery_status",
        "owner_satisfaction_force_new_cycle",
        "owner_panel_logs",
        "owner_panel_codes",
        "owner_panel_payments",
        "owner_panel_admins",
        "owner_panel_marketplace"
    }
    occurrences = {}


    for button in all_buttons:

        occurrences.setdefault(button.get("callback_data"), []).append(button)


    details = []
    missing_handlers = 0
    repeated_allowed = 0
    repeated_suspicious = 0
    placeholders = 0
    editable = 0


    for button in all_buttons:

        callback_data = button.get("callback_data")
        observations = []
        state = "✅ OK"


        if not callback_has_handler(callback_data, handler_source):

            state = "❌ Problema"
            missing_handlers += 1
            observations.append("callback sin handler")


        if callback_data in placeholder_callbacks:

            if state == "✅ OK":

                state = "ℹ️ Informativo"


            placeholders += 1
            observations.append(placeholder_callbacks[callback_data])


        if callback_data in editable_callbacks or callback_data.startswith("owner_location_") or callback_data.startswith("owner_group_logs_") or callback_data.startswith("owner_group_users_"):

            editable += 1
            observations.append("funcional para esta comunidad")


        if len(occurrences.get(callback_data, [])) > 1:

            duplicate_kind = classify_owner_panel_repeated_callback(
                callback_data,
                placeholder_callbacks
            )


            if duplicate_kind == "suspicious":

                if state == "✅ OK":

                    state = "⚠️ Revisar"


                repeated_suspicious += 1
                observations.append("callback repetido sospechoso en el panel")

            elif duplicate_kind == "allowed_informational":

                repeated_allowed += 1
                observations.append("Repetido permitido: acción informativa compartida")

            else:

                repeated_allowed += 1
                observations.append("Repetido permitido: navegación común")


        required_permissions = get_required_permissions_for_callback(callback_data)

        details.append({
            "menu": button.get("menu"),
            "text": button.get("text"),
            "callback_data": callback_data,
            "state": state,
            "permissions": ", ".join(required_permissions) if required_permissions else "público/validación interna",
            "observation": "; ".join(observations) or "sin observaciones"
        })


    return {
        "group_id": group_id,
        "total_buttons": len(all_buttons),
        "missing_handlers": missing_handlers,
        "repeated_allowed": repeated_allowed,
        "repeated_suspicious": repeated_suspicious,
        "placeholders": placeholders,
        "editable": editable,
        "details": details
    }


def format_owner_panel_audit_summary(report):

    state = "✅ OK"


    if report.get("missing_handlers"):

        state = "❌ Problema"

    elif report.get("repeated_suspicious"):

        state = "⚠️ Revisar"


    return (
        "🧪 Auditoría del panel de comunidad\n\n"
        f"Estado: {state}\n"
        f"Comunidad: {report.get('group_id')}\n"
        f"Botones visibles revisados: {report.get('total_buttons')}\n"
        f"Acciones funcionales/editables detectadas: {report.get('editable')}\n"
        f"Callbacks sin handler: {report.get('missing_handlers')}\n"
        f"Callbacks repetidos permitidos/navegación: {report.get('repeated_allowed')}\n"
        f"Callbacks repetidos sospechosos: {report.get('repeated_suspicious')}\n"
        f"Acciones informativas/próximamente: {report.get('placeholders')}\n\n"
        "Usa Ver detalle para revisar botón por botón."
    )


def format_owner_panel_audit_detail(report, limit=60):

    lines = [
        "📋 Detalle auditoría comunidad",
        ""
    ]


    for index, detail in enumerate((report.get("details") or [])[:limit], start=1):

        lines.extend([
            f"{index}. {detail.get('state')} {detail.get('menu')}",
            f"Botón: {detail.get('text')}",
            f"Callback: {detail.get('callback_data')}",
            f"Permisos: {detail.get('permissions')}",
            f"Observación: {detail.get('observation')}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_owner_panel_audit_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver detalle", callback_data="owner_panel_audit_detail")],
        [InlineKeyboardButton("🔁 Repetir auditoría", callback_data="owner_panel_audit")],
        [InlineKeyboardButton("⬅️ Volver al panel comunidad", callback_data="edit_group_back")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


def _teclado_cupones(group_id):
    """La pantalla de cupones: crear, apagar los vivos, y volver."""

    from stripe_coupon_service import list_group_coupons

    teclado = [[InlineKeyboardButton("➕ Crear cupón",
                                     callback_data="owner_stripe_coupon_new")]]

    for fila_id, code, percent, _creado in list_group_coupons(group_id):

        teclado.append([InlineKeyboardButton(
            f"🚫 Desactivar {code} ({percent}%)",
            callback_data=f"owner_stripe_coupon_off_{fila_id}"
        )])

    teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

    return teclado


async def handle_owner_panel_callbacks(update, context, query, user_id, data):

    if data == "owner_panel_satisfaction":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "😊 Encuestas de comunidad\n\n"
            "Envía encuestas solo a usuarios de esta comunidad.\n\n"
            "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron.",
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return

    if data in ("owner_panel_audit", "owner_panel_audit_detail"):

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para auditar este panel de comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        report = context.user_data.get("owner_panel_audit_report")


        if data == "owner_panel_audit" or not report or report.get("group_id") != group_id:

            report = build_owner_panel_audit_report(user_id, group_id)
            context.user_data["owner_panel_audit_report"] = report


        text = (
            format_owner_panel_audit_detail(report)
            if data == "owner_panel_audit_detail"
            else format_owner_panel_audit_summary(report)
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=build_owner_panel_audit_keyboard()
        )

        return

    if data.startswith("owner_panel_help_"):

        section = data.replace("owner_panel_help_", "", 1)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_panel_help_text(section),
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return

    if data == "owner_panel_guardian":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir Guardian en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        allowed, owner_user_id = owner_can_use_guardian(user_id, group_id)

        if not allowed:

            log_owner_guardian_addon_gate(
                "owner_guardian_addon_required",
                user_id,
                owner_user_id,
                group_id,
                data
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_guardian_addon_required_text(group_id),
                reply_markup=build_owner_guardian_addon_required_keyboard()
            )

            return


        group = fetch_group_basic_info(group_id)
        settings = ensure_guardian_settings(
            group_id,
            owner_user_id=owner_user_id,
            telegram_group_id=group[2] if group else None
        )

        log_owner_guardian_addon_gate(
            "owner_guardian_addon_allowed",
            user_id,
            owner_user_id,
            group_id,
            data
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_panel_text(group_id, settings=settings),
            reply_markup=build_owner_guardian_panel_keyboard(group_id)
        )

        return

    if data in (
        "owner_panel_users",
        "owner_panel_security",
        "owner_panel_backup",
        "owner_panel_general"
    ):

        title, description, required_permissions, section = OWNER_PANEL_SECTIONS[data]

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            required_permissions
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir esta sección de la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id


        if data == "owner_panel_users":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_users_panel_text(group_id),
                reply_markup=build_owner_section_keyboard(
                    user_id,
                    group_id,
                    section
                )
            )

            return


        if data == "owner_panel_security":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_security_text(group_id),
                reply_markup=build_owner_security_keyboard(group_id)
            )

            return


        if data == "owner_panel_backup":

            allowed, owner_user_id = owner_can_use_backups(user_id, group_id)

            if not allowed:

                log_owner_backup_addon_gate(
                    "owner_backup_addon_required",
                    user_id,
                    owner_user_id,
                    group_id,
                    data
                )

                await send_clean_message(
                    context,
                    query.message.chat_id,
                    build_owner_backup_addon_required_text(group_id),
                    reply_markup=build_owner_backup_addon_required_keyboard()
                )

                return


            log_owner_backup_addon_gate(
                "owner_backup_addon_allowed",
                user_id,
                owner_user_id,
                group_id,
                data
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_backup_panel_text(group_id),
                reply_markup=build_owner_backup_panel_keyboard(group_id)
            )

            return


        if data == "owner_panel_general":

            await send_clean_message(
                context,
                query.message.chat_id,
                build_owner_general_text(group_id),
                reply_markup=build_owner_general_keyboard(group_id)
            )

            return

    if data == "owner_panel_commercial_config" or data == "owner_panel_access_type_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_manage_plans", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para abrir la configuración comercial de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_commercial_config_text(group_id),
            reply_markup=build_owner_commercial_config_keyboard(group_id, user_id)
        )

        return

    # =========================
    # STRIPE CONNECT (cobrar en la cuenta del creador)
    # =========================
    # Solo el propietario: es SU cuenta bancaria la que se conecta.

    if data in ("owner_stripe_connect", "owner_stripe_connect_start",
                "owner_stripe_connect_check"):

        from stripe_connect_service import (
            describe_connect_status,
            fetch_connect_account,
            refresh_connect_status,
            start_connect_onboarding,
        )

        group_id = get_selected_group_for_permissions(
            context, user_id, ["can_manage_payments", "can_manage_plans"]
        )

        if not group_id or not (
            is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id
        ):

            await query.message.reply_text(
                "⛔ Solo el propietario puede conectar su cuenta de Stripe.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        if data == "owner_stripe_connect_start":

            resultado = start_connect_onboarding(group_id, user_id)

            if resultado.get("ok"):

                await query.message.reply_text(
                    "🚀 Alta de tu cuenta de Stripe\n\n"
                    "Completa el formulario de Stripe con el botón de abajo. "
                    "Al terminar, vuelve aquí y pulsa «Comprobar estado».",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "📝 Abrir el formulario de Stripe",
                            url=resultado["url"]
                        )],
                        [InlineKeyboardButton(
                            "🔄 Comprobar estado",
                            callback_data="owner_stripe_connect_check"
                        )],
                    ])
                )

            else:

                await query.message.reply_text(
                    "❌ Ahora mismo no se puede empezar el alta.\n\n"
                    "Lo más probable es que Stripe Connect no esté activado "
                    "aún en la cuenta de Stripe de la plataforma (se activa "
                    "una vez, en el panel de Stripe → Connect). Avisa al "
                    "administrador de la plataforma.",
                    reply_markup=build_owner_panel_nav_keyboard()
                )

            return


        if data == "owner_stripe_connect_check":

            refresh_connect_status(group_id)


        # La pantalla de estado (también tras comprobar).
        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        cuenta = fetch_connect_account(group_id)

        teclado = []

        if not cuenta:

            teclado.append([InlineKeyboardButton(
                "🚀 Conectar mi cuenta de Stripe",
                callback_data="owner_stripe_connect_start"
            )])

        elif not cuenta["charges_enabled"]:

            teclado.append([InlineKeyboardButton(
                "📝 Continuar el alta",
                callback_data="owner_stripe_connect_start"
            )])
            teclado.append([InlineKeyboardButton(
                "🔄 Comprobar estado",
                callback_data="owner_stripe_connect_check"
            )])

        else:

            teclado.append([InlineKeyboardButton(
                "🔄 Comprobar estado",
                callback_data="owner_stripe_connect_check"
            )])

        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        # El IVA automático se cuenta aquí, junto al cobro: es la otra mitad
        # de "cómo entra el dinero" y el propietario tiene que saber si está
        # cobrando con impuesto calculado o sin él.
        from stripe_tax_service import tax_status_line

        await send_clean_message(
            context,
            query.message.chat_id,
            f"🏦 Stripe Connect — {group_name}\n\n"
            f"{describe_connect_status(group_id)}\n\n"
            f"{tax_status_line()}",
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    # =========================
    # CUPONES DE DESCUENTO (Stripe)
    # =========================
    # Solo el propietario (o super admin): los cupones tocan el cobro real.
    # El "off" va antes que la pantalla por la trampa de prefijos de siempre.

    if data.startswith("owner_stripe_coupon_off_"):

        from stripe_coupon_service import build_coupons_text, deactivate_group_coupon

        group_id = get_selected_group_for_permissions(
            context, user_id, ["can_manage_plans", "can_manage_payments"]
        )

        if not group_id or not (
            is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id
        ):

            await query.message.reply_text(
                "⛔ Solo el propietario puede gestionar los cupones.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        fila = data[len("owner_stripe_coupon_off_"):]

        if fila.isdigit() and deactivate_group_coupon(group_id, int(fila),
                                                      actor_user_id=user_id):

            await query.answer("Cupón desactivado ✅", show_alert=False)

        else:

            await query.answer("No se pudo desactivar", show_alert=True)

        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        await send_clean_message(
            context,
            query.message.chat_id,
            build_coupons_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(
                _teclado_cupones(group_id)
            )
        )

        return


    if data == "owner_stripe_coupon_new":

        group_id = get_selected_group_for_permissions(
            context, user_id, ["can_manage_plans", "can_manage_payments"]
        )

        if not group_id or not (
            is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id
        ):

            await query.message.reply_text(
                "⛔ Solo el propietario puede crear cupones.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        context.user_data["creating_stripe_coupon"] = {
            "group_id": group_id,
            "step": 1,
        }

        await query.message.reply_text(
            "🏷 Nuevo cupón de descuento\n\n"
            "Paso 1️⃣ — Escribe el CÓDIGO que tecleará el comprador "
            "(3-30 caracteres, letras/números/guiones; p. ej. VERANO20)."
        )

        return


    if data == "owner_stripe_coupons":

        from stripe_coupon_service import build_coupons_text

        group_id = get_selected_group_for_permissions(
            context, user_id, ["can_manage_plans", "can_manage_payments"]
        )

        if not group_id or not (
            is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id
        ):

            await query.message.reply_text(
                "⛔ Solo el propietario puede gestionar los cupones.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        await send_clean_message(
            context,
            query.message.chat_id,
            build_coupons_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(
                _teclado_cupones(group_id)
            )
        )

        return


    if data == "owner_panel_revenue":

        # Misma resolución de comunidad y mismos permisos que la sección de
        # pagos: quien puede ver los pagos puede ver los ingresos.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        teclado = [
            [InlineKeyboardButton("🔄 Actualizar", callback_data="owner_panel_revenue")],
            [InlineKeyboardButton("👥 Suscriptores",
                                  callback_data="owner_panel_subscribers")],
            # Los ingresos dicen lo que entra; la retención, lo que se queda.
            [InlineKeyboardButton("🔄 Retención",
                                  callback_data="owner_panel_retention")],
            # Y cuando no entra nada, lo primero es saber si se PUEDE vender.
            [InlineKeyboardButton("🚦 ¿Puedo vender?",
                                  callback_data="owner_panel_ready")],
            # Y si se puede vender y aun así no entra: ¿falta gente, espanta
            # el precio, o se rompe el pago?
            [InlineKeyboardButton("🔻 Embudo",
                                  callback_data="owner_panel_funnel")],
            [InlineKeyboardButton("📥 Exportar pagos (CSV)",
                                  callback_data="owner_panel_revenue_csv")],
            # Los pagos son las transacciones; esto es la gente, que es lo
            # que hace falta para decidir a quién escribir.
            [InlineKeyboardButton("📥 Exportar socios (CSV)",
                                  callback_data="owner_panel_members_csv")],
        ]
        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_revenue_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data == "owner_panel_funnel":

        from owner_funnel_service import build_owner_funnel_text

        # Mismos permisos que el resto del panel de negocio.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        teclado = [
            [InlineKeyboardButton("🔄 Actualizar",
                                  callback_data="owner_panel_funnel")],
            [InlineKeyboardButton("🚦 ¿Puedo vender?",
                                  callback_data="owner_panel_ready")],
            [InlineKeyboardButton("💰 Panel de ingresos",
                                  callback_data="owner_panel_revenue")],
        ]
        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_funnel_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data == "owner_panel_ready":

        from owner_readiness_service import build_readiness_text

        # Mismos permisos que el resto del panel de negocio: quien puede ver
        # los ingresos puede ver por qué no los hay.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        teclado = [
            [InlineKeyboardButton("🔄 Comprobar otra vez",
                                  callback_data="owner_panel_ready")],
            [InlineKeyboardButton("💰 Panel de ingresos",
                                  callback_data="owner_panel_revenue")],
        ]
        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_readiness_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data == "owner_panel_retention":

        from owner_retention_service import build_owner_retention_text

        # Mismos permisos que los ingresos: la retención se calcula con los
        # mismos pagos.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        teclado = [
            [InlineKeyboardButton("🔄 Actualizar",
                                  callback_data="owner_panel_retention")],
            [InlineKeyboardButton("💰 Panel de ingresos",
                                  callback_data="owner_panel_revenue")],
        ]
        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_retention_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data == "owner_panel_subscribers":

        from owner_revenue_service import build_owner_subscribers_text

        # Mismos permisos que los ingresos: la lista de quién paga ES la
        # información de pagos.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        teclado = [
            [InlineKeyboardButton("🔄 Actualizar",
                                  callback_data="owner_panel_subscribers")],
            [InlineKeyboardButton("💰 Panel de ingresos",
                                  callback_data="owner_panel_revenue")],
        ]
        teclado.extend(build_owner_panel_nav_keyboard().inline_keyboard)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_subscribers_text(group_id, group_name),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data == "owner_panel_members_csv":

        from owner_revenue_service import build_members_csv

        # Mismos permisos que los pagos: son los mismos datos de negocio,
        # vistos por persona en vez de por transacción.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        import io

        # BOM (utf-8-sig) para que Excel en español lo abra sin pelearse.
        archivo = io.BytesIO(build_members_csv(group_id).encode("utf-8-sig"))
        archivo.name = f"socios_{group_id}.csv"

        try:

            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=archivo,
                filename=archivo.name,
                caption=f"📥 Socios de {group_name} — activos, caducados y "
                        "permanentes, con lo que ha pagado cada uno."
            )

        except Exception as e:

            print("Socios: error enviando el CSV:", str(e)[:200])

            await query.message.reply_text(
                "❌ No he podido generar el CSV ahora mismo. "
                "Inténtalo de nuevo en un momento.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

        return


    if data == "owner_panel_revenue_csv":

        # Mismos permisos que la pantalla de ingresos: el CSV es la misma
        # información, en un formato que se lleva a una hoja de cálculo.
        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_plans", "can_manage_groups", "can_view_payments", "can_manage_payments"]
        )


        if not group_id:

            await query.message.reply_text(
                "⚠️ No he podido saber sobre qué comunidad quieres actuar.\n\n"
                "Ábrela primero en «🏪 Mis comunidades» y repite la acción.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        info = fetch_group_basic_info(group_id)
        group_name = (info[1] if info else None) or f"Comunidad {group_id}"

        import io

        # BOM (utf-8-sig) para que Excel en español lo abra sin pelearse.
        archivo = io.BytesIO(build_payments_csv(group_id).encode("utf-8-sig"))
        archivo.name = f"pagos_{group_id}.csv"

        try:

            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=archivo,
                filename=archivo.name,
                caption=f"📥 Pagos de {group_name} — importes en unidades "
                        "mayores (15.00), separados por ';'."
            )

        except Exception as e:

            print("Ingresos: error enviando el CSV:", str(e)[:200])

            await query.message.reply_text(
                "❌ No he podido generar el CSV ahora mismo. "
                "Inténtalo de nuevo en un momento.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

        return

    if data == "owner_panel_location_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar ubicación en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_location_management_text(group_id),
            reply_markup=build_owner_location_management_keyboard(group_id)
        )

        return

    if data == "owner_panel_security_info":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para revisar seguridad en esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_security_text(group_id),
            reply_markup=build_owner_security_keyboard(group_id)
        )

        return

    if data in (
        "owner_panel_access_type_info",
        "owner_panel_general_info"
    ):

        info_texts = {
            "owner_panel_access_type_info": (
                "🔓 Tipo gratis/pago\n\n"
                "El tipo de acceso se revisa desde Configuración de pagos del grupo. "
                "De pago no significa solo Stripe: puedes activar Stripe, PayPal, Revolut, ChangeNOW, Guardarian o códigos."
            ),
            "owner_panel_general_info": (
                "⚙️ Configuración general\n\n"
                "Estos ajustes se gestionan con flujos seguros existentes. "
                "No se reinicia ni borra configuración sin confirmación específica."
            )
        }

        await query.message.reply_text(
            info_texts.get(data, "Información no disponible."),
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return

    return NOT_HANDLED
