import json

from db import conn
from rbac_helpers import (
    get_admin_group_ids,
    is_super_admin,
    user_owns_group
)
from payment_service import list_group_payment_provider_statuses
from user_activity_logger import fetch_tracking_overview, fetch_recent_user_events
from ai_policy import (
    AI_CONTEXT_OWNER_DASHBOARD,
    AI_CONTEXT_PUBLIC_MARKETPLACE,
    AI_CONTEXT_SUPERADMIN_DASHBOARD,
    AI_ROLE_BUYER,
    AI_ROLE_GROUP_ADMIN,
    AI_ROLE_OWNER,
    AI_ROLE_SUPERADMIN,
    sanitize_ai_text
)


def fetch_one(sql, params=None):

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    except Exception as exc:
        print("ai_context_fetch_one_error:", str(exc)[:200])
        return None


def fetch_all(sql, params=None):

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    except Exception as exc:
        print("ai_context_fetch_all_error:", str(exc)[:200])
        return []


def get_ai_role_for_user(user_id, group_id=None):

    if is_super_admin(user_id):
        return AI_ROLE_SUPERADMIN

    if group_id and user_owns_group(user_id, group_id):
        return AI_ROLE_OWNER

    group_ids = get_admin_group_ids(user_id)

    if group_ids:
        if group_id:
            return AI_ROLE_GROUP_ADMIN if int(group_id) in [int(item) for item in group_ids] else AI_ROLE_BUYER
        return AI_ROLE_OWNER

    return AI_ROLE_BUYER


def get_accessible_ai_group_ids(user_id, role):

    if role == AI_ROLE_SUPERADMIN:
        return None

    group_ids = get_admin_group_ids(user_id)

    return group_ids or []


def user_can_use_group_ai_context(user_id, role, group_id):

    if not group_id:
        return True

    if role == AI_ROLE_SUPERADMIN:
        return True

    return int(group_id) in [int(item) for item in get_accessible_ai_group_ids(user_id, role)]


def build_public_marketplace_context(user_id):

    groups = fetch_all("""
        SELECT g.id,
               COALESCE(g.name, 'Comunidad'),
               COUNT(p.id) FILTER (WHERE p.is_active=TRUE),
               MIN(p.amount) FILTER (WHERE p.is_active=TRUE),
               MIN(p.currency) FILTER (WHERE p.is_active=TRUE)
        FROM groups g
        LEFT JOIN plans p ON p.group_id=g.id
        WHERE g.is_active=TRUE
        AND g.telegram_group_id != 0
        GROUP BY g.id, g.name
        ORDER BY g.id DESC
        LIMIT 8
    """)
    subscriptions = fetch_all("""
        SELECT u.group_id,
               COALESCE(g.name, 'Comunidad'),
               u.expiration
        FROM users u
        LEFT JOIN groups g ON g.id=u.group_id
        WHERE u.user_id=%s
        AND COALESCE(u.subscription_active, FALSE)=TRUE
        ORDER BY u.expiration DESC NULLS LAST
        LIMIT 8
    """, (user_id,))
    support = fetch_all("""
        SELECT id, status, group_id, last_message_at
        FROM support_tickets
        WHERE user_id=%s
        ORDER BY last_message_at DESC
        LIMIT 5
    """, (user_id,))

    lines = [
        "Contexto comprador seguro:",
        "Comunidades visibles recientes:"
    ]

    for group_id, name, plan_count, min_amount, min_currency in groups:
        price = f"desde {min_amount} {min_currency}" if min_amount and min_currency else "sin precio mínimo visible"
        lines.append(f"- {name} (id {group_id}): {plan_count or 0} planes activos, {price}.")

    lines.append("Accesos activos del usuario:")

    for group_id, name, expiration in subscriptions:
        lines.append(f"- {name} (id {group_id}), caduca: {expiration or 'sin caducidad'}.")

    if not subscriptions:
        lines.append("- No hay accesos activos registrados para este usuario.")

    lines.append("Tickets recientes del usuario:")

    for ticket_id, status, group_id, last_message_at in support:
        lines.append(f"- Ticket #{ticket_id}, estado {status}, comunidad {group_id or 'global'}, última actividad {last_message_at}.")

    if not support:
        lines.append("- No hay tickets recientes registrados.")

    return "\n".join(lines)


def build_group_context(user_id, role, group_id):

    if not group_id or not user_can_use_group_ai_context(user_id, role, group_id):
        return "No hay una comunidad autorizada seleccionada para este usuario."

    group = fetch_one("""
        SELECT id,
               COALESCE(name, 'Comunidad'),
               telegram_group_id,
               COALESCE(is_free_group, FALSE),
               COALESCE(public_visibility, '-')
        FROM groups
        WHERE id=%s
        LIMIT 1
    """, (group_id,))

    if not group:
        return "La comunidad seleccionada no existe o no está disponible."

    plans = fetch_all("""
        SELECT name, amount, currency, is_active
        FROM plans
        WHERE group_id=%s
        ORDER BY id ASC
        LIMIT 8
    """, (group_id,))
    support_count = fetch_one("""
        SELECT COUNT(*)
        FROM support_tickets
        WHERE group_id=%s
        AND status IN ('open', 'answered')
    """, (group_id,))
    survey_count = fetch_one("""
        SELECT COUNT(*)
        FROM customer_satisfaction_responses r
        JOIN customer_satisfaction_surveys s ON s.id=r.survey_id
        WHERE s.group_id=%s
        AND r.completed_at IS NOT NULL
    """, (group_id,))
    recent_events = fetch_recent_user_events(limit=8, group_id=group_id)

    lines = [
        "Contexto de comunidad autorizado:",
        f"- Nombre: {group[1]}",
        f"- ID interno: {group[0]}",
        f"- Tipo: {'gratis' if group[3] else 'pago'}",
        f"- Visibilidad: {group[4]}",
        f"- Tickets abiertos/respondidos: {(support_count or [0])[0]}",
        f"- Encuestas completadas: {(survey_count or [0])[0]}",
        "Planes:",
    ]

    for name, amount, currency, is_active in plans:
        lines.append(f"- {name}: {amount or '-'} {currency or ''}, {'activo' if is_active else 'inactivo'}.")

    if not plans:
        lines.append("- No hay planes registrados.")

    lines.append("Métodos de pago del grupo:")

    for status in list_group_payment_provider_statuses(group_id):
        lines.append(
            f"- {status.get('label')}: global {'activo' if status.get('global_enabled') else 'deshabilitado'}, "
            f"grupo {status.get('status_label')}, credenciales {status.get('secret_status')}."
        )

    lines.append("Actividad reciente del grupo:")

    for row in recent_events:
        lines.append(f"- {row[8]} · {row[3]} · {row[4]} · usuario {row[0]}.")

    return "\n".join(lines)


def build_superadmin_context():

    overview = fetch_tracking_overview()
    payments = fetch_all("""
        SELECT provider,
               payment_scope,
               status,
               COUNT(*)
        FROM payment_transactions
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY provider, payment_scope, status
        ORDER BY COUNT(*) DESC
        LIMIT 12
    """)
    errors = fetch_all("""
        SELECT event_type, severity, message, created_at
        FROM audit_logs
        WHERE severity IN ('error', 'critical', 'warning')
        ORDER BY created_at DESC
        LIMIT 8
    """)

    lines = [
        "Contexto superadmin seguro:",
        f"- Usuarios iniciados: {overview.get('started_users', 0)}",
        f"- Activos 24h: {overview.get('active_24h', 0)}",
        f"- Activos 7d: {overview.get('active_7d', 0)}",
        f"- Eventos 24h: {overview.get('events_24h', 0)}",
        f"- Pagos iniciados 7d: {overview.get('payments_started', 0)}",
        f"- Pagos completados 7d: {overview.get('payments_completed', 0)}",
        f"- Soportes abiertos 7d: {overview.get('support_opened', 0)}",
        f"- Encuestas completadas 7d: {overview.get('surveys_completed', 0)}",
        "Transacciones por proveedor/estado:"
    ]

    for provider, scope, status, count in payments:
        lines.append(f"- {provider or '-'} / {scope or '-'} / {status or '-'}: {count}.")

    lines.append("Errores/warnings recientes:")

    for event_type, severity, message, created_at in errors:
        lines.append(f"- {created_at} · {severity} · {event_type}: {sanitize_ai_text(message)[:180]}.")

    return "\n".join(lines)


def build_support_ticket_context(ticket_id, user_id, role):

    row = fetch_one("""
        SELECT id, user_id, username, first_name, status, group_id, last_message_at
        FROM support_tickets
        WHERE id=%s
        LIMIT 1
    """, (ticket_id,))

    if not row:
        return "Ticket no encontrado."

    ticket_group_id = row[5]

    if role != AI_ROLE_SUPERADMIN and ticket_group_id and not user_can_use_group_ai_context(user_id, role, ticket_group_id):
        return "No autorizado para ver el contexto de este ticket."

    messages = fetch_all("""
        SELECT sender_type, sender_id, message_text, created_at
        FROM support_messages
        WHERE ticket_id=%s
        ORDER BY created_at DESC
        LIMIT 8
    """, (ticket_id,))

    lines = [
        "Contexto de soporte autorizado:",
        f"- Ticket: #{row[0]}",
        f"- Estado: {row[4]}",
        f"- Usuario: {row[1]}",
        f"- Username: @{row[2]}" if row[2] else "- Username: sin username",
        f"- Nombre: {row[3] or '-'}",
        f"- Comunidad: {ticket_group_id or 'global'}",
        "Mensajes recientes:"
    ]

    for sender_type, sender_id, message_text, created_at in reversed(messages):
        lines.append(f"- {created_at} · {sender_type} {sender_id}: {sanitize_ai_text(message_text)[:500]}")

    return "\n".join(lines)


def build_ai_context(user_id, role=None, context_key=None, group_id=None, support_ticket_id=None):

    role = role or get_ai_role_for_user(user_id, group_id=group_id)
    context_key = context_key or (
        AI_CONTEXT_SUPERADMIN_DASHBOARD
        if role == AI_ROLE_SUPERADMIN
        else AI_CONTEXT_OWNER_DASHBOARD
        if role in (AI_ROLE_OWNER, AI_ROLE_GROUP_ADMIN)
        else AI_CONTEXT_PUBLIC_MARKETPLACE
    )

    context_parts = []

    if role == AI_ROLE_SUPERADMIN:
        context_parts.append(build_superadmin_context())
    elif group_id:
        context_parts.append(build_group_context(user_id, role, group_id))
    else:
        context_parts.append(build_public_marketplace_context(user_id))

    if support_ticket_id:
        context_parts.append(build_support_ticket_context(support_ticket_id, user_id, role))

    context_text = sanitize_ai_text("\n\n".join(context_parts))
    context_summary = {
        "role": role,
        "context_key": context_key,
        "group_id": group_id,
        "support_ticket_id": support_ticket_id
    }

    return {
        "role": role,
        "context_key": context_key,
        "group_id": group_id,
        "context_text": context_text,
        "context_summary": json.dumps(context_summary, ensure_ascii=False)
    }
