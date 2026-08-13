"""
admin_commercial_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_commercial_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import requests
import secrets
import string

from creator_setup_callbacks import COMMERCIAL_REQUEST_FIELDS
from db import conn
from rbac_helpers import (
    get_creator_group_quota_source,
    set_creator_group_quota,
    sync_commercial_creator_profile_from_request,
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

COMMERCIAL_REQUEST_MESSAGE_FIELDS = [

    "id",
    "commercial_request_id",
    "sender_type",
    "sender_id",
    "message_text",
    "created_at"

]



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_admin_commercial_request_chat_keyboard(*args, **kwargs):
    from callback_router import build_admin_commercial_request_chat_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_commercial_request(*args, **kwargs):
    from callback_router import fetch_commercial_request as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_public_visibility(*args, **kwargs):
    from callback_router import format_public_visibility as impl
    return impl(*args, **kwargs)


def is_commercial_request_advanced(*args, **kwargs):
    from callback_router import is_commercial_request_advanced as impl
    return impl(*args, **kwargs)


def is_commercial_request_archived(*args, **kwargs):
    from callback_router import is_commercial_request_archived as impl
    return impl(*args, **kwargs)


def notify_commercial_request_user(*args, **kwargs):
    from callback_router import notify_commercial_request_user as impl
    return impl(*args, **kwargs)


def reply_duplicate_commercial_approval(*args, **kwargs):
    from callback_router import reply_duplicate_commercial_approval as impl
    return impl(*args, **kwargs)


def row_to_commercial_request(*args, **kwargs):
    from callback_router import row_to_commercial_request as impl
    return impl(*args, **kwargs)


def row_to_commercial_request_message(*args, **kwargs):
    from callback_router import row_to_commercial_request_message as impl
    return impl(*args, **kwargs)


def start_commercial_request_chat_reply(*args, **kwargs):
    from callback_router import start_commercial_request_chat_reply as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def format_commercial_request_type(request_type):

    labels = {
        "shared_trial": "prueba comunidad compartida",
        "custom_bot": "bot personalizado",
        "support_contact": "contacto comercial"
    }

    return labels.get(request_type, request_type or "-")


def format_commercial_request_status(status):

    labels = {
        "pending": "pendiente",
        "approved": "aprobada",
        "rejected": "rechazada",
        "trial_active": "trial activo",
        "trial_expired": "trial caducado",
        "awaiting_creator_setup": "pendiente de configuración",
        "setup_in_progress": "configuración en curso",
        "setup_ready": "configuración lista",
        "awaiting_payment_setup": "pendiente de cobro",
        "awaiting_payment": "pendiente de pago",
        "active": "activa",
        "disabled": "desactivada",
        "expired_pending_reactivation": "pendiente de reactivación",
        "archived": "archivada",
        "closed": "cerrada"
    }

    return labels.get(status, status or "-")


def get_commercial_request_title(request_row):

    return (
        request_row.get("community_name")
        or request_row.get("bot_name")
        or request_row.get("project_description")
        or "-"
    )


def get_owner_groups_summary(user_id):

    if not user_id:

        return 0, "Sin grupos"


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.name
                FROM admins a
                JOIN groups g
                ON g.id=a.group_id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            names = [
                row[0] or "Sin nombre"
                for row in cur.fetchall()
            ]

    except Exception as e:

        print("Error cargando grupos del propietario:", e)

        names = []


    if not names:

        return 0, "Sin grupos"


    shown = ", ".join(names[:3])

    if len(names) > 3:

        shown += f" +{len(names) - 3} más"


    return len(names), shown


def build_owner_groups_detail_text(request_row):

    user_id = request_row.get("user_id") if request_row else None

    if not user_id:

        return "🏪 Grupos del propietario\n\nNo hay usuario asociado a esta solicitud."


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT DISTINCT g.id, g.name, g.telegram_group_id, COALESCE(g.is_active, TRUE)
                FROM groups g
                JOIN admins a
                ON a.group_id = g.id
                WHERE a.user_id=%s
                AND a.role='GROUP_OWNER'
                AND a.is_active=TRUE
                ORDER BY g.name ASC

            """, (user_id,))

            rows = cur.fetchall()

    except Exception as e:

        print("Error cargando detalle de grupos del propietario:", e)

        rows = []


    if not rows:

        return "🏪 Grupos del propietario\n\nEste propietario todavía no tiene grupos vinculados."


    lines = [
        "🏪 Grupos del propietario",
        "",
        format_owner_request_card(request_row)
    ]


    for group_id, name, telegram_group_id, is_active in rows:

        lines.append(
            "\n"
            f"Grupo: {name or 'Sin nombre'}\n"
            f"ID interno: {group_id}\n"
            f"Telegram ID: {telegram_group_id or '-'}\n"
            f"Estado: {'activo' if is_active else 'inactivo'}"
        )


    return "\n".join(lines)


def format_owner_request_card(request_row):

    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    first_name = request_row.get("first_name") or "Sin nombre disponible"
    user_id = request_row.get("user_id")
    status = request_row.get("status") or "-"
    max_groups, _quota_source = get_creator_group_quota_source(user_id, request_row)
    used_groups, group_names = get_owner_groups_summary(user_id)
    trial_until = request_row.get("trial_ends_at")
    subscription_until = request_row.get("commercial_subscription_until")
    last_activity = (
        request_row.get("last_interaction_at")
        or request_row.get("updated_at")
        or request_row.get("created_at")
    )

    trial_text = "inactivo"
    if status == "trial_active":
        trial_text = f"activo hasta {format_commercial_datetime(trial_until)}"

    commercial_text = "activo" if status == "active" else "inactivo"
    if subscription_until:
        commercial_text = f"{commercial_text} hasta {format_commercial_datetime(subscription_until)}"

    return (
        f"👤 Nombre: {first_name} {username}\n"
        f"🆔 Usuario: {user_id or '-'}\n"
        f"📌 Estado: {format_commercial_request_status(status)}\n"
        f"📦 Cupo: {used_groups}/{max_groups}\n"
        f"🧪 Trial: {trial_text}\n"
        f"💳 Comercial: {commercial_text}\n"
        f"🏪 Grupos: {used_groups} · {group_names}\n"
        f"🕒 Última actividad: {format_commercial_datetime(last_activity)}"
    )


def format_owner_request_button_label(request_row, prefix="👁 Ver"):

    first_name = request_row.get("first_name") or "Sin nombre"
    username = request_row.get("username") or "Sin username"

    if username != "Sin username" and not username.startswith("@"):

        username = f"@{username}"


    return (
        f"{prefix} · {first_name} {username} "
        f"#{request_row.get('id')}"
    )[:64]


def fetch_pending_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status='pending'
            ORDER BY created_at ASC
            LIMIT 10

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_archived_commercial_requests():

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status IN ('archived', 'closed')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 20

        """)

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def fetch_commercial_requests_by_statuses(statuses, limit=20):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_FIELDS)}
            FROM commercial_requests
            WHERE status = ANY(%s)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s

        """, (statuses, limit))

        rows = cur.fetchall()


    return [
        row_to_commercial_request(row)
        for row in rows
    ]


def build_commercial_status_list_text(title, requests):

    if not requests:

        return f"{title}\n\nNo hay solicitudes en esta vista."


    lines = [title]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_commercial_status_list_keyboard(requests, back_callback="admin_owners_panel"):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton("🧑‍💼 Propietarios", callback_data=back_callback)
    ])

    keyboard.append([
        InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")
    ])

    return keyboard


def archive_commercial_request(request_id, archived_by):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='archived',
                reviewed_by=COALESCE(reviewed_by, %s),
                reviewed_at=COALESCE(reviewed_at, NOW()),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            archived_by,
            request_id
        ))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def reopen_archived_commercial_request(request_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='setup_ready',
                updated_at=NOW()
            WHERE id=%s
            AND status IN ('archived', 'closed')
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (request_id,))

        row = cur.fetchone()


    return row_to_commercial_request(row)


def fetch_commercial_request_messages(request_id, limit=10):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(COMMERCIAL_REQUEST_MESSAGE_FIELDS)}
            FROM commercial_request_messages
            WHERE commercial_request_id=%s
            ORDER BY created_at DESC, id DESC
            LIMIT %s

        """, (
            request_id,
            limit
        ))

        rows = cur.fetchall()


    messages = [
        row_to_commercial_request_message(row)
        for row in rows
    ]

    return list(reversed(messages))


def build_admin_trial_visibility_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "🏠 Publicar en inicio",
            callback_data=f"admin_trial_visibility_start_home_{request_id}"
        )],

        [InlineKeyboardButton(
            "🔎 Publicar en explorar",
            callback_data=f"admin_trial_visibility_explore_only_{request_id}"
        )],

        [InlineKeyboardButton(
            "🙈 Dejar oculta/borrador",
            callback_data=f"admin_trial_visibility_hidden_{request_id}"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


def build_commercial_requests_text(requests):

    if not requests:

        return (
            "📩 Solicitudes comerciales\n\n"
            "No hay solicitudes pendientes."
        )


    lines = [
        "🕓 Solicitudes pendientes\n\n"
        "Gestiona aquí a los dueños de comunidades: solicitudes, pruebas, cupos, grupos y estado comercial."
    ]


    for request_row in requests:

        lines.append(
            "\n"
            f"{format_owner_request_card(request_row)}\n"
            f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
            f"Solicitud: {get_commercial_request_title(request_row)}\n"
            f"Contacto: {request_row.get('contact_text') or '-'}"
        )


    return "\n".join(lines)


def build_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "📄 Ver detalle"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "📁 Solicitudes archivadas",
            callback_data="admin_commercial_archived_requests"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_archived_commercial_requests_text(requests):

    if not requests:

        return (
            "📁 Solicitudes archivadas\n\n"
            "No hay solicitudes archivadas."
        )


    lines = [
        "📁 Archivados\n\n"
        "Solicitudes finalizadas o cerradas sin borrar sus datos."
    ]


    for request_row in requests:

        lines.append("\n" + format_owner_request_card(request_row))


    return "\n".join(lines)


def build_archived_commercial_requests_keyboard(requests):

    keyboard = []


    for request_row in requests:

        request_id = request_row.get("id")

        keyboard.append([
            InlineKeyboardButton(
                format_owner_request_button_label(request_row, "👁 Ver estado"),
                callback_data=f"admin_commercial_review_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_request_detail_text(request_row):

    username = request_row.get("username") or "-"
    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    if username != "-" and not username.startswith("@"):

        username = f"@{username}"


    return (
        "📩 Solicitud comercial\n\n"
        f"{format_owner_request_card(request_row)}\n\n"
        f"ID: {request_row.get('id')}\n"
        f"Estado: {request_row.get('status') or '-'}\n"
        f"Tipo: {format_commercial_request_type(request_row.get('request_type'))}\n"
        f"Usuario: {request_row.get('user_id') or '-'}\n"
        f"Username: {username}\n"
        f"Nombre Telegram: {request_row.get('first_name') or '-'}\n\n"
        f"Comunidad/proyecto: {request_row.get('community_name') or '-'}\n"
        f"Descripción comunidad: {request_row.get('community_description') or '-'}\n"
        f"Link grupo/canal: {request_row.get('telegram_group_link') or '-'}\n"
        f"Nombre bot: {request_row.get('bot_name') or '-'}\n"
        f"Username bot: {request_row.get('bot_username') or '-'}\n"
        f"Descripción proyecto: {request_row.get('project_description') or '-'}\n"
        f"Contacto: {request_row.get('contact_text') or '-'}\n\n"
        f"Creada: {format_commercial_datetime(request_row.get('created_at'))}\n"
        f"Revisada por: {request_row.get('reviewed_by') or '-'}\n"
        f"Revisada: {format_commercial_datetime(request_row.get('reviewed_at'))}\n"
        f"Inicio prueba: {format_commercial_datetime(request_row.get('trial_starts_at'))}\n"
        f"Fin prueba: {format_commercial_datetime(request_row.get('trial_ends_at'))}\n"
        f"Modo pago: {request_row.get('payment_mode') or '-'}\n"
        f"Modo Stripe: {request_row.get('stripe_mode') or '-'}\n"
        f"Grupo vinculado: {request_row.get('approved_group_id') or '-'}\n"
        f"Telegram group ID: {request_row.get('approved_telegram_group_id') or '-'}\n"
        f"Ubicación pública solicitada: {format_public_visibility(request_row.get('requested_public_visibility'))}\n"
        f"Estado configuración creador: {request_row.get('creator_setup_status') or '-'}\n"
        f"Preview creador: {request_row.get('creator_preview_text') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente de cupo: {quota_source}\n"
        f"Último user_id interacción: {request_row.get('last_interaction_user_id') or '-'}\n"
        f"Último username interacción: {request_row.get('last_interaction_username') or '-'}\n"
        f"Último nombre interacción: {request_row.get('last_interaction_first_name') or '-'}\n"
        f"Última interacción: {format_commercial_datetime(request_row.get('last_interaction_at'))}\n"
        f"Plan comercial: {request_row.get('selected_commercial_plan_id') or '-'}\n"
        f"Estado suscripción comercial: {request_row.get('commercial_subscription_status') or '-'}\n"
        f"Suscripción comercial hasta: {format_commercial_datetime(request_row.get('commercial_subscription_until'))}"
    )


def build_commercial_contact_button(request_row):

    return InlineKeyboardButton(
        "💬 Hablar con solicitante",
        callback_data=f"admin_commercial_chat_{request_row.get('id')}"
    )


def build_commercial_advanced_review_keyboard(request_row):

    request_id = request_row.get("id")
    keyboard = []
    contact_button = build_commercial_contact_button(request_row)


    keyboard.append([contact_button])


    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])

    if not is_commercial_request_archived(request_row):

        keyboard.append([
            InlineKeyboardButton(
                "🔢 Cambiar cupo",
                callback_data=f"admin_commercial_group_limit_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "🗄 Finalizar solicitud",
                callback_data=f"admin_commercial_archive_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "📝 Añadir nota interna",
                callback_data=f"admin_commercial_internal_note_{request_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "📁 Archivada",
                callback_data=f"admin_commercial_status_{request_id}"
            )
        ])

        keyboard.append([
            InlineKeyboardButton(
                "♻️ Reabrir solicitud",
                callback_data=f"admin_commercial_reopen_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_archive_confirm_keyboard(request_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Confirmar archivo",
            callback_data=f"admin_commercial_archive_confirm_{request_id}"
        )],
        [InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"admin_commercial_archive_cancel_{request_id}"
        )]
    ])


def build_commercial_pending_review_keyboard(request_row):

    request_id = request_row.get("id")
    request_type = request_row.get("request_type")
    keyboard = [
        [build_commercial_contact_button(request_row)]
    ]

    keyboard.append([
        InlineKeyboardButton(
            "📄 Ver detalle completo",
            callback_data=f"admin_commercial_status_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🏪 Ver sus grupos",
            callback_data=f"admin_commercial_owner_groups_{request_id}"
        )
    ])


    if request_type == "shared_trial":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar prueba",
                callback_data=f"admin_commercial_approve_trial_{request_id}"
            )
        ])

    elif request_type == "custom_bot":

        keyboard.append([
            InlineKeyboardButton(
                "✅ Aprobar personalizada",
                callback_data=f"admin_commercial_approve_custom_{request_id}"
            )
        ])


    keyboard.append([
        InlineKeyboardButton(
            "❌ Rechazar",
            callback_data=f"admin_commercial_reject_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📦 Cambiar cupo",
            callback_data=f"admin_commercial_group_limit_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "📝 Añadir nota interna",
            callback_data=f"admin_commercial_internal_note_{request_id}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Volver al panel de propietarios",
            callback_data="admin_owners_panel"
        )
    ])

    return keyboard


def build_commercial_review_keyboard(request_row):

    if is_commercial_request_advanced(request_row):

        return build_commercial_advanced_review_keyboard(request_row)


    return build_commercial_pending_review_keyboard(request_row)


def build_commercial_request_chat_text(request_row, messages):

    request_id = request_row.get("id")
    title = get_commercial_request_title(request_row)


    lines = [
        "💬 Chat de solicitud comercial",
        "",
        f"Solicitud: #{request_id}",
        f"Solicitante: {request_row.get('user_id') or '-'}",
        f"Proyecto: {title}",
        ""
    ]


    if not messages:

        lines.append("Todavía no hay mensajes en esta conversación.")

    else:

        lines.append("Historial reciente:")


        for message in messages:

            sender_label = (
                "Admin"
                if message.get("sender_type") == "admin"
                else "Solicitante"
            )
            created_at = format_commercial_datetime(message.get("created_at"))
            text = (message.get("message_text") or "").strip()

            lines.append(
                "\n"
                f"{sender_label} · {created_at}\n"
                f"{text}"
            )


    return "\n".join(lines)


def build_commercial_group_limit_text(request_row):

    profile_quota, quota_source = get_creator_group_quota_source(
        request_row.get("user_id"),
        request_row
    )

    return (
        "🔢 Cupo de grupos\n\n"
        f"Solicitud: #{request_row.get('id')}\n"
        f"Creador: {request_row.get('user_id') or '-'}\n"
        f"Cupo actual del creator: {profile_quota}\n"
        f"Cupo de esta solicitud: {request_row.get('max_groups_allowed') or 1}\n"
        f"Fuente: {quota_source}\n\n"
        "Elige el máximo de comunidades que este creador puede añadir."
    )


def build_commercial_group_limit_keyboard(request_id):

    return [

        [InlineKeyboardButton(
            "1 grupo",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_1"
        )],

        [InlineKeyboardButton(
            "2 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_2"
        )],

        [InlineKeyboardButton(
            "5 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_5"
        )],

        [InlineKeyboardButton(
            "10 grupos",
            callback_data=f"admin_commercial_set_group_limit_{request_id}_10"
        )],

        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data=f"admin_commercial_review_{request_id}"
        )]

    ]


COMMERCIAL_PROMO_DURATIONS = {
    "15d": (15, "15 días"),
    "1m": (30, "1 mes"),
    "3m": (90, "3 meses"),
    "1y": (365, "1 año")
}


def generate_commercial_promo_code():

    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(
        secrets.choice(alphabet)
        for _ in range(8)
    )

    return f"OWNER-{suffix}"


def create_commercial_promo_code(duration_days, created_by):

    for _ in range(5):

        code = generate_commercial_promo_code()

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    INSERT INTO commercial_promo_codes
                    (
                        code,
                        duration_days,
                        max_uses,
                        uses_count,
                        is_active,
                        created_by,
                        updated_at
                    )
                    VALUES (%s, %s, 1, 0, TRUE, %s, NOW())
                    RETURNING id, code, duration_days

                """, (
                    code,
                    duration_days,
                    created_by
                ))

                return cur.fetchone()

        except Exception as e:

            print("Error creando código promocional comercial:", e)


    return None


def fetch_active_commercial_promo_codes():

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   code,
                   duration_days,
                   max_uses,
                   uses_count,
                   created_by,
                   created_at
            FROM commercial_promo_codes
            WHERE is_active=TRUE
            AND uses_count < max_uses
            ORDER BY created_at DESC
            LIMIT 20

        """)

        return cur.fetchall()


def deactivate_commercial_promo_code(code_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE commercial_promo_codes
            SET is_active=FALSE,
                updated_at=NOW()
            WHERE id=%s
            RETURNING code

        """, (code_id,))

        row = cur.fetchone()

    return row[0] if row else None


def format_commercial_promo_duration(days):

    if days == 15:

        return "15 días"

    if days == 30:

        return "1 mes"

    if days == 90:

        return "3 meses"

    if days == 365:

        return "1 año"

    return f"{days} días"


def build_commercial_promo_codes_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Crear código 15 días",
            callback_data="admin_commercial_promo_create_15d"
        )],
        [InlineKeyboardButton(
            "Crear código 1 mes",
            callback_data="admin_commercial_promo_create_1m"
        )],
        [InlineKeyboardButton(
            "Crear código 3 meses",
            callback_data="admin_commercial_promo_create_3m"
        )],
        [InlineKeyboardButton(
            "Crear código 1 año",
            callback_data="admin_commercial_promo_create_1y"
        )],
        [InlineKeyboardButton(
            "Ver códigos activos",
            callback_data="admin_commercial_promo_active"
        )],
        [InlineKeyboardButton(
            "Desactivar código",
            callback_data="admin_commercial_promo_deactivate_menu"
        )],
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="admin_back_main"
        )]
    ])


def build_commercial_promo_active_text(rows):

    if not rows:

        return "🎟 Códigos promocionales\n\nNo hay códigos activos."


    lines = ["🎟 Códigos promocionales activos"]


    for row in rows:

        code_id, code, duration_days, max_uses, uses_count, created_by, created_at = row
        lines.append(
            "\n"
            f"ID: {code_id}\n"
            f"Código: {code}\n"
            f"Duración: {format_commercial_promo_duration(duration_days)}\n"
            f"Usos: {uses_count}/{max_uses}\n"
            f"Creado por: {created_by or '-'}\n"
            f"Fecha: {format_commercial_datetime(created_at)}"
        )


    return "\n".join(lines)


def build_commercial_promo_deactivate_keyboard(rows):

    keyboard = []


    for row in rows:

        code_id, code, *_rest = row
        keyboard.append([InlineKeyboardButton(
            f"Desactivar {code}",
            callback_data=f"admin_commercial_promo_deactivate_{code_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="admin_commercial_promo_codes"
    )])

    return InlineKeyboardMarkup(keyboard)


def extract_commercial_group_limit_selection(data):

    prefix = "admin_commercial_set_group_limit_"


    try:

        raw_value = data.replace(prefix, "", 1)
        request_id_text, limit_text = raw_value.rsplit("_", 1)
        request_id = int(request_id_text)
        limit = int(limit_text)

    except Exception:

        return None, None


    if limit not in (1, 2, 5, 10):

        return None, None


    return request_id, limit


def update_commercial_request_group_limit(request_id, max_groups_allowed):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET max_groups_allowed=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (
            max_groups_allowed,
            request_id
        ))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        set_creator_group_quota(
            request_row.get("user_id"),
            max_groups_allowed,
            request_row.get("status")
        )

        with conn.cursor() as cur:

            cur.execute(f"""

                UPDATE commercial_requests
                SET max_groups_allowed=%s,
                    updated_at=NOW()
                WHERE user_id=%s
                RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

            """, (
                max_groups_allowed,
                request_row.get("user_id")
            ))


    return request_row


def update_commercial_request_custom_approved(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='awaiting_payment',
                reviewed_by=%s,
                reviewed_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    request_row = row_to_commercial_request(row)


    if request_row:

        sync_commercial_creator_profile_from_request(
            request_row.get("user_id")
        )


    return request_row


def update_commercial_request_rejected(request_id, reviewer_id):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE commercial_requests
            SET status='rejected',
                reviewed_by=%s,
                reviewed_at=NOW(),
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(COMMERCIAL_REQUEST_FIELDS)}

        """, (reviewer_id, request_id))

        row = cur.fetchone()


    return row_to_commercial_request(row)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_commercial_callbacks(update, context, query, user_id, data):

    if data in (
        "admin_commercial_active_requests",
        "admin_commercial_trials_active",
        "admin_commercial_subscriptions",
        "admin_commercial_group_limits",
        "admin_commercial_owner_tools",
        "admin_commercial_reassign_owner_group"
    ):

        if data == "admin_commercial_active_requests":

            solicitudes = fetch_commercial_requests_by_statuses([
                "approved",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = "✅ Solicitudes activas"

        elif data == "admin_commercial_trials_active":

            solicitudes = fetch_commercial_requests_by_statuses([
                "trial_active"
            ])

            title = "⏳ Trials activos"

        elif data == "admin_commercial_subscriptions":

            solicitudes = fetch_commercial_requests_by_statuses([
                "active",
                "trial_expired",
                "expired_pending_reactivation"
            ])

            title = "💳 Suscripciones comerciales"

        else:

            solicitudes = fetch_commercial_requests_by_statuses([
                "approved",
                "trial_active",
                "awaiting_creator_setup",
                "setup_in_progress",
                "setup_ready",
                "active"
            ])

            title = (
                "🔢 Cupos de grupos"
                if data == "admin_commercial_group_limits"
                else (
                    "🔁 Reasignar owner/grupo"
                    if data == "admin_commercial_reassign_owner_group"
                    else "🔎 Buscar propietario"
                )
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_status_list_text(title, solicitudes),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_status_list_keyboard(solicitudes)
            )
        )

        return

    if data == "admin_commercial_owner_summary":

        pending_requests = fetch_pending_commercial_requests()
        active_requests = fetch_commercial_requests_by_statuses([
            "approved",
            "awaiting_creator_setup",
            "setup_in_progress",
            "setup_ready",
            "active"
        ])
        trial_requests = fetch_commercial_requests_by_statuses([
            "trial_active"
        ])
        subscription_requests = fetch_commercial_requests_by_statuses([
            "active",
            "trial_expired",
            "expired_pending_reactivation"
        ])
        archived_requests = fetch_archived_commercial_requests()

        await send_clean_message(
            context,
            query.message.chat_id,
            "📊 Resumen propietarios\n\n"
            f"🕓 Solicitudes pendientes: {len(pending_requests)}\n"
            f"✅ Propietarios activos/configurando: {len(active_requests)}\n"
            f"🧪 Trials activos: {len(trial_requests)}\n"
            f"💳 Suscripciones/recoveries: {len(subscription_requests)}\n"
            f"📁 Archivados: {len(archived_requests)}\n\n"
            "Usa los botones del panel de propietarios para abrir cada vista y revisar casos concretos.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🕓 Solicitudes pendientes", callback_data="admin_commercial_requests")],
                [InlineKeyboardButton("✅ Propietarios activos", callback_data="admin_commercial_active_requests")],
                [InlineKeyboardButton("🧑‍💼 Propietarios", callback_data="admin_owners_panel")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data == "admin_commercial_promo_codes":

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos promocionales\n\nCrea códigos para que dueños de grupos publiquen su comunidad sin pasar por checkout durante el periodo elegido.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return

    if data.startswith("admin_commercial_promo_create_"):

        slug = data.replace("admin_commercial_promo_create_", "", 1)
        duration = COMMERCIAL_PROMO_DURATIONS.get(slug)


        if not duration:

            await query.message.reply_text(
                "❌ Duración no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_commercial_promo_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        duration_days, duration_label = duration
        row = create_commercial_promo_code(duration_days, user_id)


        if not row:

            await query.message.reply_text("❌ Error creando código promocional.")

            return


        _code_id, code, _duration_days = row

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código promocional creado\n\n"
            f"Código: {code}\n"
            f"Duración: {duration_label}\n"
            "Uso: 1 vez\n\n"
            "El dueño debe usarlo desde 📦 Configurar comunidad > 🎟 Tengo un código promocional.",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return

    if data == "admin_commercial_promo_active":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            build_commercial_promo_active_text(rows),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Desactivar código",
                    callback_data="admin_commercial_promo_deactivate_menu"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_promo_codes"
                )]
            ])
        )

        return

    if data == "admin_commercial_promo_deactivate_menu":

        rows = fetch_active_commercial_promo_codes()

        await send_clean_message(
            context,
            query.message.chat_id,
            "❌ Desactivar código\n\nElige el código promocional que quieres desactivar.",
            reply_markup=build_commercial_promo_deactivate_keyboard(rows)
        )

        return

    if data.startswith("admin_commercial_promo_deactivate_"):

        code_id = extract_commercial_request_id(
            data,
            "admin_commercial_promo_deactivate_"
        )
        code = deactivate_commercial_promo_code(code_id)


        if not code:

            await query.message.reply_text("❌ Código promocional no encontrado.")

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            f"✅ Código desactivado: {code}",
            reply_markup=build_commercial_promo_codes_keyboard()
        )

        return

    if data == "admin_commercial_requests":

        solicitudes = fetch_pending_commercial_requests()

        await query.message.reply_text(
            build_commercial_requests_text(solicitudes),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_requests_keyboard(solicitudes)
            )
        )

        return

    if data == "admin_commercial_archived_requests":

        solicitudes = fetch_archived_commercial_requests()

        await query.message.reply_text(
            build_archived_commercial_requests_text(solicitudes),
            reply_markup=InlineKeyboardMarkup(
                build_archived_commercial_requests_keyboard(solicitudes)
            )
        )

        return

    if data.startswith("admin_commercial_status_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_status_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return

    if data.startswith("admin_commercial_owner_groups_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_owner_groups_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_owner_groups_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return

    if data.startswith("admin_commercial_internal_note_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_internal_note_"
        )

        await query.message.reply_text(
            "📝 Añadir nota interna\n\n"
            "Este acceso deja claro dónde irá la nota interna. "
            "La edición de notas se conectará al flujo de texto seguro en una fase posterior.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📄 Ver detalle completo",
                    callback_data=f"admin_commercial_status_{request_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Volver al panel de propietarios",
                    callback_data="admin_owners_panel"
                )]
            ])
        )

        return

    if data.startswith("admin_commercial_archive_confirm_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_confirm_"
        )

        request_row = archive_commercial_request(request_id, user_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            "🗄 Solicitud archivada.\n\n"
            "No se han borrado datos, grupo, owner ni conversación comercial.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return

    if data.startswith("admin_commercial_archive_cancel_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_cancel_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return

    if data.startswith("admin_commercial_archive_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_archive_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_archived(request_row):

            await query.message.reply_text(
                "📁 Esta solicitud ya está archivada.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(request_row)
                )
            )

            return


        await query.message.reply_text(
            "🗄 Finalizar solicitud\n\n"
            "Se archivará la solicitud comercial sin borrar datos, grupo, owner ni conversación comercial.",
            reply_markup=build_commercial_archive_confirm_keyboard(request_id)
        )

        return

    if data.startswith("admin_commercial_reopen_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reopen_"
        )

        request_row = reopen_archived_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud archivada no encontrada."
            )

            return


        await query.message.reply_text(
            "♻️ Solicitud reabierta.",
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return

    if data.startswith("admin_commercial_chat_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_chat_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        messages = fetch_commercial_request_messages(request_id)

        await query.message.reply_text(
            build_commercial_request_chat_text(request_row, messages),
            reply_markup=build_admin_commercial_request_chat_keyboard(request_id)
        )

        return

    if data.startswith("admin_commercial_reply_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reply_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        start_commercial_request_chat_reply(
            context,
            request_id,
            "admin"
        )

        await query.message.reply_text(
            f"✍️ Responder solicitud comercial #{request_id}\n\n"
            "Escribe ahora el mensaje para el solicitante."
        )

        return

    if data.startswith("admin_commercial_group_limit_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_group_limit_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_group_limit_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_group_limit_keyboard(request_id)
            )
        )

        return

    if data.startswith("admin_commercial_set_group_limit_"):

        request_id, max_groups_allowed = extract_commercial_group_limit_selection(
            data
        )


        if not request_id or not max_groups_allowed:

            await query.message.reply_text(
                "❌ Cupo de grupos no válido."
            )

            return


        request_row = update_commercial_request_group_limit(
            request_id,
            max_groups_allowed
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            f"✅ Cupo actualizado a {max_groups_allowed} grupo(s).",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔎 Volver a solicitud",
                    callback_data=f"admin_commercial_review_{request_id}"
                )],
                [InlineKeyboardButton(
                    "🔢 Cambiar cupo",
                    callback_data=f"admin_commercial_group_limit_{request_id}"
                )]
            ])
        )

        return

    if data.startswith("admin_commercial_review_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_review_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await query.message.reply_text(
            build_commercial_request_detail_text(request_row),
            reply_markup=InlineKeyboardMarkup(
                build_commercial_review_keyboard(request_row)
            )
        )

        return

    if data.startswith("admin_commercial_approve_trial_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_trial_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

            return


        await query.message.reply_text(
            "✅ Aprobar prueba de comunidad\n\n"
            "Elige dónde quieres colocar esta comunidad inicialmente:\n\n"
            "🏠 Inicio: aparecerá directamente en /start.\n"
            "🔎 Explorar: aparecerá dentro de Explorar comunidades privadas.\n"
            "🙈 Oculta/Borrador: no aparecerá públicamente todavía.",
            reply_markup=InlineKeyboardMarkup(
                build_admin_trial_visibility_keyboard(request_id)
            )
        )

        return

    if data.startswith("admin_commercial_approve_custom_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_approve_custom_"
        )

        request_row = fetch_commercial_request(request_id)


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        if is_commercial_request_advanced(request_row):

            await reply_duplicate_commercial_approval(query, request_id)

            return


        request_row = update_commercial_request_custom_approved(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "✅ Tu solicitud de bot personalizado ha sido aprobada. "
            "El siguiente paso será completar configuración y pago para activar el servicio."
        )

        await query.message.reply_text(
            "✅ Configuración aprobada.\n\n"
            "La solicitud queda en espera de configuración y pago.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return

    if data.startswith("admin_commercial_reject_"):

        request_id = extract_commercial_request_id(
            data,
            "admin_commercial_reject_"
        )

        existing_request = fetch_commercial_request(request_id)


        if is_commercial_request_advanced(existing_request):

            await query.message.reply_text(
                "Esta solicitud ya está aprobada, configurada o archivada. No se ha rechazado.",
                reply_markup=InlineKeyboardMarkup(
                    build_commercial_review_keyboard(existing_request)
                )
            )

            return


        request_row = update_commercial_request_rejected(
            request_id,
            user_id
        )


        if not request_row:

            await query.message.reply_text(
                "❌ Solicitud comercial no encontrada."
            )

            return


        await notify_commercial_request_user(
            context,
            request_row,
            "❌ Tu solicitud no ha sido aprobada por ahora.\n\n"
            "Puedes volver a intentarlo más adelante o contactar con soporte si necesitas revisar la propuesta."
        )

        await query.message.reply_text(
            "❌ Solicitud comercial rechazada.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Volver",
                    callback_data="admin_commercial_requests"
                )]
            ])
        )

        return

    return NOT_HANDLED
