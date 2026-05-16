from datetime import datetime

from db import conn


# =========================
# ACCOUNT SERVICE — SUBSCRIPTION STATUS
# =========================

def get_user_subscriptions(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT u.group_id,
                   u.expiration,
                   g.name,
                   g.telegram_group_id

            FROM users u
            LEFT JOIN groups g
            ON g.id = u.group_id

            WHERE u.user_id=%s

            ORDER BY u.expiration DESC NULLS FIRST

        """, (user_id,))

        return cur.fetchall()



def get_user_subscription_for_group(user_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT u.group_id,
                   u.expiration,
                   g.name,
                   g.telegram_group_id

            FROM users u
            LEFT JOIN groups g
            ON g.id = u.group_id

            WHERE u.user_id=%s
            AND u.group_id=%s

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone()



def is_subscription_active(expiration):

    if expiration is None:

        return True


    return datetime.now() <= expiration



def format_subscription_status(expiration):

    if expiration is None:

        return "♾️ Permanente"


    if is_subscription_active(expiration):

        return "✅ Activa"


    return "⛔ Caducada"



def format_expiration_text(expiration):

    if expiration is None:

        return "♾️ Permanente"


    return str(expiration)


# =========================
# ACCOUNT SERVICE — INVITE LINKS
# =========================

def get_user_invite_links(user_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT invite_link,
                   group_id,
                   created_at,
                   is_active

            FROM invite_links

            WHERE user_id=%s

            ORDER BY created_at DESC

        """, (user_id,))

        return cur.fetchall()



def get_latest_user_invite_link(user_id, group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT invite_link,
                   created_at,
                   is_active

            FROM invite_links

            WHERE user_id=%s
            AND group_id=%s

            ORDER BY created_at DESC
            LIMIT 1

        """, (
            user_id,
            group_id
        ))

        return cur.fetchone()


# =========================
# ACCOUNT SERVICE — TEXT FORMATTERS
# =========================

def build_account_summary_text(user_id):

    subscriptions = get_user_subscriptions(
        user_id
    )

    if not subscriptions:

        return (
            "👤 Mi cuenta\n\n"
            "No tienes suscripciones activas todavía.\n\n"
            "Puedes comprar acceso desde el menú principal."
        )


    text = "👤 Mi cuenta\n\n"

    for group_id, expiration, group_name, telegram_group_id in subscriptions:

        group_label = group_name or f"Grupo {group_id}"
        status = format_subscription_status(expiration)
        expiration_text = format_expiration_text(expiration)

        text += (
            f"📌 {group_label}\n"
            f"Estado: {status}\n"
            f"Caducidad: {expiration_text}\n\n"
        )


    return text.strip()



def build_subscription_detail_text(user_id, group_id):

    subscription = get_user_subscription_for_group(
        user_id,
        group_id
    )

    if not subscription:

        return (
            "⚠️ No se encontró una suscripción para este grupo."
        )


    group_id, expiration, group_name, telegram_group_id = subscription

    group_label = group_name or f"Grupo {group_id}"
    status = format_subscription_status(expiration)
    expiration_text = format_expiration_text(expiration)

    latest_link = get_latest_user_invite_link(
        user_id,
        telegram_group_id
    )

    if latest_link:

        invite_link, created_at, is_active = latest_link
        link_status = "✅ Activo" if is_active else "⛔ Inactivo"

    else:

        invite_link = "No disponible"
        created_at = "No disponible"
        link_status = "No disponible"


    return (
        f"📌 {group_label}\n\n"
        f"Estado: {status}\n"
        f"Caducidad: {expiration_text}\n\n"
        f"🔗 Último link: {invite_link}\n"
        f"Estado link: {link_status}\n"
        f"Creado: {created_at}"
    )
