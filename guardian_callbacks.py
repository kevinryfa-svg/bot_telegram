"""
Guardian: panel del propietario y sus botones.

Primera fase de partir callback_router.py. Ese archivo tiene 51.861 líneas y su
función button() 24.275, con 1.272 ramas if seguidas; el peligro real de esa
forma no es el tamaño, es que una rama de arriba puede tapar a otra de abajo sin
dar ningún error — es lo que dejó este mismo panel de Guardian invisible.

Aquí vive Guardian entero: los textos y teclados del panel y el despacho de sus
botones. Se ha movido tal cual, sin reescribir nada, para que se pueda comprobar
que el comportamiento es idéntico botón por botón.

Por qué el despacho no devuelve si ha atendido o no: en el original, todos los
caminos del bloque terminaban en return, así que quien llama puede retornar
justo después de la llamada y el resultado es exactamente el mismo. Se comprobó
antes de mover: 34 return, ninguno con valor, ninguna función anidada, y el
cuerpo siempre acaba en return.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from audit_log_service import log_event
from guardian_service import (
    GUARDIAN_LOG_EVENT_CATEGORIES,
    count_guardian_forbidden_words,
    count_guardian_link_whitelist_domains,
    deactivate_guardian_forbidden_word,
    ensure_guardian_settings,
    fetch_guardian_settings,
    get_guardian_anti_links_settings,
    get_guardian_forbidden_words_settings,
    get_guardian_log_event_settings,
    get_guardian_night_mode_settings,
    list_guardian_forbidden_words,
    list_guardian_link_whitelist_domains,
    list_guardian_warning_summary,
    record_guardian_log_event,
    send_guardian_event_log,
    send_guardian_test_log,
    set_guardian_log_event_enabled,
    update_guardian_anti_links_settings,
    update_guardian_forbidden_words_settings,
    update_guardian_night_mode_settings
)
from owner_addon_service import fetch_owner_addon_product, owner_has_feature
from rbac_helpers import get_group_owner_user_id, is_super_admin
from ui_menu_helpers import send_clean_message


# =========================
# AYUDANTES QUE SE QUEDAN EN callback_router
# =========================
# Estas cuatro las usa medio bot, no solo Guardian, así que se quedan donde
# estaban. Se llaman de forma diferida porque callback_router importa este
# módulo: importarlo de vuelta arriba sería una importación circular.
#
# Los envoltorios existen para que el código movido quede idéntico al original,
# carácter por carácter, y así se pueda comparar de verdad.

def build_owner_panel_nav_keyboard(*args, **kwargs):

    from callback_router import build_owner_panel_nav_keyboard as impl

    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):

    from callback_router import fetch_group_basic_info as impl

    return impl(*args, **kwargs)


def format_owner_addon_price(*args, **kwargs):

    from callback_router import format_owner_addon_price as impl

    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):

    from callback_router import user_has_group_permission_any as impl

    return impl(*args, **kwargs)


def build_owner_guardian_addon_required_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Ver servicios extra", callback_data="owner_addons_menu")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="owner_panel_security")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_addon_required_text(group_id=None):

    lines = [
        "🛡 Guardian",
        "",
        "Este servicio es un extra mensual para dueños de comunidades.",
        "Permite preparar protección avanzada: canal de logs, anti-links, palabras bloqueadas, warnings y modo noche.",
        "",
        "En esta fase solo se configura la base técnica y los logs. No se ejecutan expulsiones, bans ni acciones automáticas.",
        "",
        "Para usarlo necesitas activar Guardian."
    ]

    product = fetch_owner_addon_product("guardian")


    if product and product.get("is_active"):

        lines.append("")
        lines.append("Servicio disponible:")
        lines.append(f"- {product.get('name')}: {format_owner_addon_price(product)}")


    return "\n".join(lines)


def build_owner_guardian_anti_links_keyboard(group_id):

    settings = get_guardian_anti_links_settings(group_id)
    enabled = bool(settings.get("enabled"))
    action = settings.get("action") or "log_only"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Desactivar anti-links" if enabled else "🔴 Activar anti-links", callback_data=f"owner_guardian_toggle_anti_links_{group_id}")],
        [
            InlineKeyboardButton(("✅ " if action == "log_only" else "") + "Acción: log_only", callback_data=f"owner_guardian_anti_links_action_{group_id}_log_only"),
            InlineKeyboardButton(("✅ " if action == "warn" else "") + "Acción: warn", callback_data=f"owner_guardian_anti_links_action_{group_id}_warn")
        ],
        [InlineKeyboardButton("📋 Ver whitelist", callback_data=f"owner_guardian_link_whitelist_{group_id}")],
        [InlineKeyboardButton("➕ Añadir dominio whitelist: pendiente", callback_data=f"owner_guardian_link_whitelist_add_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver Guardian", callback_data="owner_panel_guardian")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_anti_links_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    settings = get_guardian_anti_links_settings(group_id)
    whitelist_count = count_guardian_link_whitelist_domains(group_id)
    status_text = "activo" if settings.get("enabled") else "inactivo"

    return (
        "🔗 Guardian · Anti-links\n\n"
        f"Comunidad: {group_name}\n"
        f"Estado: {status_text}\n"
        f"Acción actual: {settings.get('action') or 'log_only'}\n"
        f"Whitelist: {whitelist_count} dominios\n\n"
        "Modo seguro actual: solo registra y, si eliges warn, añade warning automático.\n"
        "No borra mensajes, no expulsa, no banea y no restringe usuarios."
    )


def build_owner_guardian_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_guardian_log_channel_cancel_{group_id}")]
    ])


def build_owner_guardian_design_placeholder_text(feature_name):

    return (
        f"🛡 Guardian · {feature_name}\n\n"
        "Esta parte queda preparada en base de datos, pero todavía no ejecuta acciones reales.\n\n"
        "Modo actual: solo diseño y registro.\n"
        "No se expulsan usuarios, no se banean cuentas y no se borran mensajes."
    )


def build_owner_guardian_forbidden_words_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_guardian_forbidden_words_cancel_add_{group_id}")]
    ])


def build_owner_guardian_forbidden_words_keyboard(group_id):

    settings = get_guardian_forbidden_words_settings(group_id)
    enabled = bool(settings.get("enabled"))
    action = settings.get("action") or "log_only"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Desactivar palabras" if enabled else "🔴 Activar palabras", callback_data=f"owner_guardian_toggle_forbidden_words_{group_id}")],
        [
            InlineKeyboardButton(("✅ " if action == "log_only" else "") + "Acción: log_only", callback_data=f"owner_guardian_forbidden_words_action_{group_id}_log_only"),
            InlineKeyboardButton(("✅ " if action == "warn" else "") + "Acción: warn", callback_data=f"owner_guardian_forbidden_words_action_{group_id}_warn")
        ],
        [InlineKeyboardButton("📋 Ver palabras", callback_data=f"owner_guardian_forbidden_words_list_{group_id}")],
        [InlineKeyboardButton("➕ Añadir palabra/frase", callback_data=f"owner_guardian_forbidden_words_add_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver Guardian", callback_data="owner_panel_guardian")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_forbidden_words_list_keyboard(group_id):

    words = list_guardian_forbidden_words(group_id, limit=20)
    keyboard = []

    for item in words:

        keyboard.append([
            InlineKeyboardButton(
                f"🚫 Desactivar #{item.get('id')}",
                callback_data=f"owner_guardian_forbidden_words_remove_{group_id}_{item.get('id')}"
            )
        ])


    keyboard.append([InlineKeyboardButton("➕ Añadir palabra/frase", callback_data=f"owner_guardian_forbidden_words_add_{group_id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Volver a palabras", callback_data=f"owner_guardian_forbidden_words_{group_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def build_owner_guardian_forbidden_words_list_text(group_id):

    words = list_guardian_forbidden_words(group_id)

    lines = [
        "📋 Guardian · Palabras prohibidas",
        "",
        "Palabras/frases activas:"
    ]

    if not words:

        lines.append("- No hay palabras prohibidas activas.")

    else:

        for item in words:

            lines.append(
                f"- #{item.get('id')} · {item.get('word')} · acción {item.get('action') or 'log_only'}"
            )


    return "\n".join(lines)


def build_owner_guardian_forbidden_words_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    settings = get_guardian_forbidden_words_settings(group_id)
    words_count = count_guardian_forbidden_words(group_id)
    status_text = "activo" if settings.get("enabled") else "inactivo"

    return (
        "🚫 Guardian · Palabras prohibidas\n\n"
        f"Comunidad: {group_name}\n"
        f"Estado: {status_text}\n"
        f"Acción actual: {settings.get('action') or 'log_only'}\n"
        f"Palabras activas: {words_count}\n\n"
        "Modo seguro actual: solo registra y, si eliges warn, añade warning automático.\n"
        "No borra mensajes, no expulsa, no banea y no restringe usuarios."
    )


def build_owner_guardian_link_whitelist_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver a anti-links", callback_data=f"owner_guardian_anti_links_{group_id}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_link_whitelist_text(group_id):

    domains = list_guardian_link_whitelist_domains(group_id)

    lines = [
        "📋 Guardian · Whitelist anti-links",
        "",
        "Dominios permitidos:"
    ]

    if not domains:

        lines.append("- No hay dominios en whitelist.")

    else:

        for domain in domains:

            lines.append(f"- {domain}")


    return "\n".join(lines)


def build_owner_guardian_log_channel_request_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    return (
        "📡 Conectar canal de logs Guardian\n\n"
        f"Comunidad: {group_name}\n\n"
        "1. Añade el bot como administrador del canal donde quieres recibir logs.\n"
        "2. Reenvía aquí un mensaje de ese canal.\n\n"
        "Guardaré solo el chat_id y el título del canal. No se guardan tokens ni enlaces privados."
    )


def build_owner_guardian_log_events_keyboard(group_id):

    event_settings = get_guardian_log_event_settings(group_id)
    keyboard = []

    for category in GUARDIAN_LOG_EVENT_CATEGORIES:

        current = event_settings.get(category["key"], category)
        marker = "✅" if current.get("is_enabled") else "⬜"
        keyboard.append([
            InlineKeyboardButton(
                f"{marker} {category['label']}",
                callback_data=f"owner_guardian_toggle_log_{group_id}_{category['key']}"
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver Guardian", callback_data="owner_panel_guardian")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return InlineKeyboardMarkup(keyboard)


def build_owner_guardian_log_events_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    settings = fetch_guardian_settings(group_id)
    event_settings = get_guardian_log_event_settings(group_id)
    log_channel = (
        settings.get("log_channel_title") or settings.get("log_channel_id")
        if settings and settings.get("log_channel_id")
        else "No conectado"
    )

    lines = [
        "📡 Guardian · Eventos del canal",
        "",
        f"Comunidad: {group_name}",
        f"Canal de logs: {log_channel}",
        "",
        "Elige qué eventos se envían al canal Guardian.",
        "La auditoría interna se sigue guardando aunque desactives una categoría.",
        ""
    ]

    for category in GUARDIAN_LOG_EVENT_CATEGORIES:

        current = event_settings.get(category["key"], category)
        marker = "✅" if current.get("is_enabled") else "⬜"
        lines.append(f"{marker} {category['label']}")


    return "\n".join(lines)


def build_owner_guardian_night_mode_cancel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data=f"owner_guardian_night_mode_cancel_time_{group_id}")]
    ])


def build_owner_guardian_night_mode_keyboard(group_id):

    settings = get_guardian_night_mode_settings(group_id)
    enabled = bool(settings.get("enabled"))
    action = settings.get("action") or "log_only"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Desactivar modo noche" if enabled else "🔴 Activar modo noche", callback_data=f"owner_guardian_toggle_night_mode_{group_id}")],
        [
            InlineKeyboardButton(("✅ " if action == "log_only" else "") + "Acción: log_only", callback_data=f"owner_guardian_night_mode_action_{group_id}_log_only"),
            InlineKeyboardButton(("✅ " if action == "warn" else "") + "Acción: warn", callback_data=f"owner_guardian_night_mode_action_{group_id}_warn")
        ],
        [
            InlineKeyboardButton("🕚 Hora inicio", callback_data=f"owner_guardian_night_mode_start_{group_id}"),
            InlineKeyboardButton("🕖 Hora fin", callback_data=f"owner_guardian_night_mode_end_{group_id}")
        ],
        [InlineKeyboardButton("🌍 Zona horaria: Europe/Madrid", callback_data=f"owner_guardian_night_mode_timezone_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver Guardian", callback_data="owner_panel_guardian")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_night_mode_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    settings = get_guardian_night_mode_settings(group_id)
    status_text = "activo" if settings.get("enabled") else "inactivo"

    return (
        "🌙 Guardian · Modo noche\n\n"
        f"Comunidad: {group_name}\n"
        f"Estado: {status_text}\n"
        f"Horario: {settings.get('start_time') or '23:00'} → {settings.get('end_time') or '07:00'}\n"
        f"Zona horaria: {settings.get('timezone') or 'Europe/Madrid'}\n"
        f"Acción actual: {settings.get('action') or 'log_only'}\n\n"
        "Modo seguro actual: solo registra mensajes durante la franja y, si eliges warn, añade warning automático.\n"
        "No borra mensajes, no expulsa, no banea, no restringe y no silencia usuarios."
    )


def build_owner_guardian_panel_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Conectar canal de logs", callback_data=f"owner_guardian_log_channel_{group_id}")],
        [InlineKeyboardButton("🧪 Enviar log de prueba", callback_data=f"owner_guardian_test_log_{group_id}")],
        [InlineKeyboardButton("⚙️ Eventos del canal", callback_data=f"owner_guardian_log_events_{group_id}")],
        [InlineKeyboardButton("🔗 Anti-links: solo diseño", callback_data=f"owner_guardian_anti_links_{group_id}")],
        [InlineKeyboardButton("🚫 Palabras prohibidas", callback_data=f"owner_guardian_forbidden_words_{group_id}")],
        [InlineKeyboardButton("🌙 Modo noche", callback_data=f"owner_guardian_night_mode_{group_id}")],
        [InlineKeyboardButton("⚠️ Warnings manuales", callback_data=f"owner_guardian_warns_{group_id}")],
        [InlineKeyboardButton("⬅️ Seguridad", callback_data="owner_panel_security")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_warning_ranking_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    summary = list_guardian_warning_summary(group_id, limit=20)

    lines = [
        "📊 Guardian · Ranking warnings",
        "",
        f"Comunidad: {group_name}",
        ""
    ]


    if not summary:

        lines.append("Todavía no hay usuarios con warnings activos.")

    else:

        for index, row in enumerate(summary, start=1):

            lines.append(
                f"{index}. Usuario {row.get('user_id')} · {row.get('active_warnings')} warnings"
            )


    return "\n".join(lines)


def build_owner_guardian_warnings_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Ver ranking warnings", callback_data=f"owner_guardian_warning_rank_{group_id}")],
        [InlineKeyboardButton("⬅️ Volver Guardian", callback_data="owner_panel_guardian")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_owner_guardian_warnings_text(group_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    all_summary = list_guardian_warning_summary(group_id, limit=1000)
    summary = all_summary[:5]
    total_active = sum(row.get("active_warnings") or 0 for row in all_summary)

    lines = [
        "⚠️ Guardian · Warnings",
        "",
        f"Comunidad: {group_name}",
        f"Warnings activos: {total_active}",
        f"Usuarios con warnings: {len(all_summary)}",
        "",
        "Ranking rápido:"
    ]


    if not summary:

        lines.append("- Todavía no hay warnings activos.")

    else:

        for index, row in enumerate(summary, start=1):

            lines.append(
                f"{index}. Usuario {row.get('user_id')} · {row.get('active_warnings')} warnings"
            )


    lines.extend([
        "",
        "Guardian todavía no ejecuta acciones automáticas por warnings.",
        "No hay bans, expulsiones, restricciones ni borrado de mensajes."
    ])

    return "\n".join(lines)


def log_owner_guardian_addon_gate(event_name, user_id, owner_user_id, group_id, action):

    log_event(
        event_name,
        category="guardian",
        severity="info" if event_name.endswith("_allowed") else "warning",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Puerta de addon Guardian evaluada.",
        metadata={
            "user_id": user_id,
            "owner_user_id": owner_user_id,
            "group_id": group_id,
            "callback": action,
            "required_feature": "guardian"
        }
    )


def owner_can_use_guardian(user_id, group_id):

    if not group_id:

        return False, None


    owner_user_id = get_group_owner_user_id(group_id)

    if not owner_user_id:

        return False, None


    if (
        not is_super_admin(user_id)
        and int(owner_user_id) != int(user_id)
        and not user_has_group_permission_any(user_id, group_id, ["can_manage_groups"])
    ):

        return False, owner_user_id


    return (
        owner_has_feature(
            owner_user_id,
            "guardian",
            group_id=group_id
        ),
        owner_user_id
    )


def user_can_view_guardian_warnings(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(
        user_id,
        group_id,
        ["can_warn_users", "can_reset_warnings", "can_manage_users"]
    )


# =========================
# DESPACHO DE LOS BOTONES DE GUARDIAN
# =========================

async def handle_guardian_callbacks(update, context, query, user_id, data):
    """
    Atiende los botones "owner_guardian_*".

    Quien llama comprueba el prefijo y retorna justo después de esta llamada:
    en el original, cada camino de este bloque acababa en return, así que el
    comportamiento es el mismo.
    """


    guardian_prefixes = (
        "owner_guardian_log_channel_cancel_",
        "owner_guardian_log_channel_",
        "owner_guardian_log_events_",
        "owner_guardian_toggle_log_",
        "owner_guardian_test_log_",
        "owner_guardian_anti_links_action_",
        "owner_guardian_toggle_anti_links_",
        "owner_guardian_link_whitelist_add_",
        "owner_guardian_link_whitelist_",
        "owner_guardian_anti_links_",
        "owner_guardian_forbidden_words_action_",
        "owner_guardian_toggle_forbidden_words_",
        "owner_guardian_forbidden_words_cancel_add_",
        "owner_guardian_forbidden_words_add_",
        "owner_guardian_forbidden_words_remove_",
        "owner_guardian_forbidden_words_list_",
        "owner_guardian_forbidden_words_",
        "owner_guardian_night_mode_action_",
        "owner_guardian_toggle_night_mode_",
        "owner_guardian_night_mode_cancel_time_",
        "owner_guardian_night_mode_start_",
        "owner_guardian_night_mode_end_",
        "owner_guardian_night_mode_timezone_",
        "owner_guardian_night_mode_",
        "owner_guardian_warns_",
        "owner_guardian_warning_rank_"
    )
    matched_prefix = next(
        (prefix for prefix in guardian_prefixes if data.startswith(prefix)),
        None
    )

    if not matched_prefix:

        await query.message.reply_text(
            "⚠️ Callback Guardian no reconocido.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    try:

        anti_links_action = None
        forbidden_words_action = None
        night_mode_action = None
        forbidden_word_id = None

        if matched_prefix == "owner_guardian_toggle_log_":

            toggle_payload = data.replace(matched_prefix, "", 1)
            toggle_group_id_text, toggle_category = toggle_payload.split("_", 1)
            group_id = int(toggle_group_id_text)

        elif matched_prefix == "owner_guardian_anti_links_action_":

            action_payload = data.replace(matched_prefix, "", 1)
            if action_payload.endswith("_log_only"):

                anti_links_action = "log_only"
                action_group_id_text = action_payload[:-len("_log_only")]

            elif action_payload.endswith("_warn"):

                anti_links_action = "warn"
                action_group_id_text = action_payload[:-len("_warn")]

            else:

                raise ValueError("invalid anti-links action")

            group_id = int(action_group_id_text)
            toggle_category = None

        elif matched_prefix == "owner_guardian_forbidden_words_action_":

            action_payload = data.replace(matched_prefix, "", 1)
            if action_payload.endswith("_log_only"):

                forbidden_words_action = "log_only"
                action_group_id_text = action_payload[:-len("_log_only")]

            elif action_payload.endswith("_warn"):

                forbidden_words_action = "warn"
                action_group_id_text = action_payload[:-len("_warn")]

            else:

                raise ValueError("invalid forbidden words action")

            group_id = int(action_group_id_text)
            toggle_category = None

        elif matched_prefix == "owner_guardian_forbidden_words_remove_":

            remove_payload = data.replace(matched_prefix, "", 1)
            remove_group_id_text, forbidden_word_id_text = remove_payload.rsplit("_", 1)
            group_id = int(remove_group_id_text)
            forbidden_word_id = int(forbidden_word_id_text)
            toggle_category = None

        elif matched_prefix == "owner_guardian_night_mode_action_":

            action_payload = data.replace(matched_prefix, "", 1)
            if action_payload.endswith("_log_only"):

                night_mode_action = "log_only"
                action_group_id_text = action_payload[:-len("_log_only")]

            elif action_payload.endswith("_warn"):

                night_mode_action = "warn"
                action_group_id_text = action_payload[:-len("_warn")]

            else:

                raise ValueError("invalid night mode action")

            group_id = int(action_group_id_text)
            toggle_category = None

        else:

            toggle_category = None
            anti_links_action = None
            group_id = int(data.replace(matched_prefix, "", 1))

    except Exception:

        await query.message.reply_text(
            "⚠️ Comunidad Guardian no válida.",
            reply_markup=build_owner_panel_nav_keyboard()
        )

        return


    if data.startswith(("owner_guardian_warns_", "owner_guardian_warning_rank_")):

        has_guardian_permission = user_can_view_guardian_warnings(user_id, group_id)

    elif data.startswith((
        "owner_guardian_log_events_",
        "owner_guardian_toggle_log_",
        "owner_guardian_anti_links_",
        "owner_guardian_toggle_anti_links_",
        "owner_guardian_anti_links_action_",
        "owner_guardian_link_whitelist_",
        "owner_guardian_link_whitelist_add_",
        "owner_guardian_forbidden_words_",
        "owner_guardian_toggle_forbidden_words_",
        "owner_guardian_forbidden_words_action_",
        "owner_guardian_forbidden_words_list_",
        "owner_guardian_forbidden_words_add_",
        "owner_guardian_forbidden_words_cancel_add_",
        "owner_guardian_forbidden_words_remove_",
        "owner_guardian_night_mode_",
        "owner_guardian_toggle_night_mode_",
        "owner_guardian_night_mode_action_",
        "owner_guardian_night_mode_start_",
        "owner_guardian_night_mode_end_",
        "owner_guardian_night_mode_timezone_",
        "owner_guardian_night_mode_cancel_time_"
    )):

        group_owner_user_id = get_group_owner_user_id(group_id)
        has_guardian_permission = (
            is_super_admin(user_id)
            or (
                group_owner_user_id
                and int(group_owner_user_id) == int(user_id)
            )
            or user_has_group_permission_any(user_id, group_id, ["can_manage_groups"])
        )

    else:

        has_guardian_permission = user_has_group_permission_any(user_id, group_id, ["can_manage_groups", "can_view_logs"])


    if not has_guardian_permission:

        await query.message.reply_text(
            "⛔ No tienes permiso para gestionar Guardian en esta comunidad.",
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

    if data.startswith("owner_guardian_log_channel_cancel_"):

        context.user_data.pop("guardian_log_channel_group_id", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de canal Guardian cancelada.",
            reply_markup=build_owner_guardian_panel_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_log_channel_"):

        context.user_data["guardian_log_channel_group_id"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_log_channel_request_text(group_id),
            reply_markup=build_owner_guardian_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_log_events_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_log_events_text(group_id),
            reply_markup=build_owner_guardian_log_events_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_toggle_log_"):

        event_settings = get_guardian_log_event_settings(group_id)
        current = event_settings.get(toggle_category)

        if not current:

            await query.message.reply_text(
                "⚠️ Categoría Guardian no válida.",
                reply_markup=build_owner_guardian_panel_keyboard(group_id)
            )

            return


        new_enabled = not bool(current.get("is_enabled"))
        set_guardian_log_event_enabled(group_id, toggle_category, new_enabled)

        if get_guardian_log_event_settings(group_id).get("guardian_config", {}).get("is_enabled", True):

            await send_guardian_event_log(
                context,
                group_id,
                "guardian_log_event_settings_updated",
                "Configuración de eventos del canal Guardian actualizada.",
                telegram_group_id=group[2] if group else None,
                severity="info",
                actor_user_id=user_id,
                metadata={
                    "category": toggle_category,
                    "is_enabled": new_enabled
                }
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_log_events_text(group_id),
            reply_markup=build_owner_guardian_log_events_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_test_log_"):

        ok, error = await send_guardian_test_log(
            context,
            settings,
            group[1] if group else f"Grupo {group_id}",
            actor_user_id=user_id
        )

        text = (
            "✅ Log de prueba enviado al canal Guardian."
            if ok
            else f"⚠️ No he podido enviar el log de prueba: {error or 'canal no configurado'}"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=build_owner_guardian_panel_keyboard(group_id)
        )

        return


    if (
        data.startswith("owner_guardian_anti_links_")
        and not data.startswith("owner_guardian_anti_links_action_")
    ):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_anti_links_text(group_id),
            reply_markup=build_owner_guardian_anti_links_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_toggle_anti_links_"):

        current = get_guardian_anti_links_settings(group_id)
        new_enabled = not bool(current.get("enabled"))
        update_guardian_anti_links_settings(
            group_id,
            enabled=new_enabled,
            action=current.get("action") if current.get("action") != "disabled" else "log_only"
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_anti_links_settings_updated",
            "Configuración anti-links actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "anti_links_enabled": new_enabled,
                "action": current.get("action") if current.get("action") != "disabled" else "log_only"
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_anti_links_text(group_id),
            reply_markup=build_owner_guardian_anti_links_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_anti_links_action_"):

        if anti_links_action not in ("log_only", "warn"):

            await query.message.reply_text(
                "⚠️ Acción anti-links no válida.",
                reply_markup=build_owner_guardian_anti_links_keyboard(group_id)
            )

            return


        update_guardian_anti_links_settings(
            group_id,
            enabled=True,
            action=anti_links_action
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_anti_links_settings_updated",
            "Acción anti-links actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "anti_links_enabled": True,
                "action": anti_links_action
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_anti_links_text(group_id),
            reply_markup=build_owner_guardian_anti_links_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_link_whitelist_add_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Añadir dominios a la whitelist todavía no tiene flujo seguro en esta fase.\n\n"
            "El anti-links ya respeta los dominios activos que existan en la tabla Guardian.",
            reply_markup=build_owner_guardian_link_whitelist_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_link_whitelist_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_link_whitelist_text(group_id),
            reply_markup=build_owner_guardian_link_whitelist_keyboard(group_id)
        )

        return


    if (
        data.startswith("owner_guardian_forbidden_words_")
        and not data.startswith((
            "owner_guardian_forbidden_words_action_",
            "owner_guardian_forbidden_words_list_",
            "owner_guardian_forbidden_words_add_",
            "owner_guardian_forbidden_words_cancel_add_",
            "owner_guardian_forbidden_words_remove_"
        ))
    ):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_forbidden_words_text(group_id),
            reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_toggle_forbidden_words_"):

        current = get_guardian_forbidden_words_settings(group_id)
        new_enabled = not bool(current.get("enabled"))
        action = current.get("action") if current.get("action") != "disabled" else "log_only"
        update_guardian_forbidden_words_settings(
            group_id,
            enabled=new_enabled,
            action=action
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_forbidden_words_settings_updated",
            "Configuración de palabras prohibidas actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "forbidden_words_enabled": new_enabled,
                "action": action
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_forbidden_words_text(group_id),
            reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_forbidden_words_action_"):

        if forbidden_words_action not in ("log_only", "warn"):

            await query.message.reply_text(
                "⚠️ Acción de palabras prohibidas no válida.",
                reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
            )

            return


        update_guardian_forbidden_words_settings(
            group_id,
            enabled=True,
            action=forbidden_words_action
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_forbidden_words_settings_updated",
            "Acción de palabras prohibidas actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "forbidden_words_enabled": True,
                "action": forbidden_words_action
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_forbidden_words_text(group_id),
            reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_forbidden_words_list_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_forbidden_words_list_text(group_id),
            reply_markup=build_owner_guardian_forbidden_words_list_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_forbidden_words_add_"):

        context.user_data["guardian_forbidden_word_add_group_id"] = group_id

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Añadir palabra/frase prohibida\n\n"
            "Envía por aquí la palabra o frase que quieres registrar.\n\n"
            "Guardian solo registrará el evento y, si eliges warn, añadirá un warning. "
            "No borra mensajes, no expulsa, no banea y no restringe usuarios.",
            reply_markup=build_owner_guardian_forbidden_words_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_forbidden_words_cancel_add_"):

        context.user_data.pop("guardian_forbidden_word_add_group_id", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Añadir palabra prohibida cancelado.",
            reply_markup=build_owner_guardian_forbidden_words_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_forbidden_words_remove_"):

        updated_count = deactivate_guardian_forbidden_word(group_id, forbidden_word_id)

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_forbidden_word_deactivated",
            "Palabra prohibida desactivada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "word_id": forbidden_word_id,
                "updated_count": updated_count
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_forbidden_words_list_text(group_id),
            reply_markup=build_owner_guardian_forbidden_words_list_keyboard(group_id)
        )

        return


    if (
        data.startswith("owner_guardian_night_mode_")
        and not data.startswith((
            "owner_guardian_night_mode_action_",
            "owner_guardian_night_mode_start_",
            "owner_guardian_night_mode_end_",
            "owner_guardian_night_mode_timezone_",
            "owner_guardian_night_mode_cancel_time_"
        ))
    ):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_night_mode_text(group_id),
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_toggle_night_mode_"):

        current = get_guardian_night_mode_settings(group_id)
        new_enabled = not bool(current.get("enabled"))
        action = current.get("action") if current.get("action") != "disabled" else "log_only"
        update_guardian_night_mode_settings(
            group_id,
            enabled=new_enabled,
            action=action
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_night_mode_settings_updated",
            "Configuración de modo noche actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "night_mode_enabled": new_enabled,
                "action": action
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_night_mode_text(group_id),
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_night_mode_action_"):

        if night_mode_action not in ("log_only", "warn"):

            await query.message.reply_text(
                "⚠️ Acción de modo noche no válida.",
                reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
            )

            return


        update_guardian_night_mode_settings(
            group_id,
            enabled=True,
            action=night_mode_action
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_night_mode_settings_updated",
            "Acción de modo noche actualizada.",
            telegram_group_id=group[2] if group else None,
            severity="info",
            actor_user_id=user_id,
            metadata={
                "night_mode_enabled": True,
                "action": night_mode_action
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_night_mode_text(group_id),
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    if data.startswith(("owner_guardian_night_mode_start_", "owner_guardian_night_mode_end_")):

        field = "start" if data.startswith("owner_guardian_night_mode_start_") else "end"
        context.user_data["guardian_night_mode_time_group_id"] = group_id
        context.user_data["guardian_night_mode_time_field"] = field
        field_label = "inicio" if field == "start" else "fin"

        await send_clean_message(
            context,
            query.message.chat_id,
            f"🕒 Envía la hora de {field_label} del modo noche en formato HH:MM.\n\n"
            "Ejemplo: 23:00",
            reply_markup=build_owner_guardian_night_mode_cancel_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_night_mode_cancel_time_"):

        context.user_data.pop("guardian_night_mode_time_group_id", None)
        context.user_data.pop("guardian_night_mode_time_field", None)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Configuración de horario de modo noche cancelada.",
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_night_mode_timezone_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            "🌍 La zona horaria de modo noche queda fija en Europe/Madrid en esta fase segura.",
            reply_markup=build_owner_guardian_night_mode_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_warns_"):

        record_guardian_log_event(
            group_id,
            "guardian_warnings_panel_opened",
            telegram_group_id=group[2] if group else None,
            actor_user_id=user_id,
            message="Panel Guardian de warnings abierto.",
            metadata={
                "callback": data
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_warnings_text(group_id),
            reply_markup=build_owner_guardian_warnings_keyboard(group_id)
        )

        return


    if data.startswith("owner_guardian_warning_rank_"):

        await send_clean_message(
            context,
            query.message.chat_id,
            build_owner_guardian_warning_ranking_text(group_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a warnings", callback_data=f"owner_guardian_warns_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return


    feature_names = {
        "owner_guardian_anti_links_": "Anti-links"
    }
    feature_name = feature_names.get(matched_prefix, "Configuración")

    record_guardian_log_event(
        group_id,
        "guardian_design_placeholder_opened",
        telegram_group_id=group[2] if group else None,
        actor_user_id=user_id,
        message="Pantalla de diseño Guardian abierta.",
        metadata={
            "feature": feature_name,
            "callback": data
        }
    )

    await send_clean_message(
        context,
        query.message.chat_id,
        build_owner_guardian_design_placeholder_text(feature_name),
        reply_markup=build_owner_guardian_panel_keyboard(group_id)
    )

    return
