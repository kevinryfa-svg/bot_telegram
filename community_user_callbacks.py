"""
community_user_callbacks: tramo extraído de callback_router.py.

Prefijos: community_user_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from datetime import (
    datetime,
    timedelta,
)
from db import conn
from payment_access_service import get_user_group_access_state
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
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_community_user_manage_keyboard(*args, **kwargs):
    from callback_router import build_community_user_manage_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def fetch_community_user_profile(*args, **kwargs):
    from callback_router import fetch_community_user_profile as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_community_user_access_type(*args, **kwargs):
    from callback_router import format_community_user_access_type as impl
    return impl(*args, **kwargs)


def format_community_user_display_name(*args, **kwargs):
    from callback_router import format_community_user_display_name as impl
    return impl(*args, **kwargs)


def parse_community_user_callback(*args, **kwargs):
    from callback_router import parse_community_user_callback as impl
    return impl(*args, **kwargs)


def resolve_group_access_state_for_user(*args, **kwargs):
    from callback_router import resolve_group_access_state_for_user as impl
    return impl(*args, **kwargs)


def user_can_view_community_users(*args, **kwargs):
    from callback_router import user_can_view_community_users as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def user_can_manage_community_user_access(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return user_has_group_permission_any(user_id, group_id, ["can_manage_users"])


async def build_community_user_detail_text(context, group_id, target_user_id):

    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"
    profile = fetch_community_user_profile(group_id, target_user_id)
    access_state = await resolve_group_access_state_for_user(context, target_user_id, group_id)
    expires_at = access_state.get("expires_at") or profile.get("expiration")
    expires_text = "permanente" if access_state.get("has_active_access") and not expires_at else format_commercial_datetime(expires_at)

    return (
        "👤 Gestión de usuario\n\n"
        f"Usuario: {format_community_user_display_name(profile)}\n"
        f"ID: {target_user_id}\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n\n"
        f"Estado actual: {'activo' if access_state.get('has_active_access') else access_state.get('subscription_status') or 'inactivo'}\n"
        f"Expiración: {expires_text}\n"
        f"Tipo/fuente: {format_community_user_access_type(access_state)}\n"
        f"Acceso permanente: {'sí' if access_state.get('has_active_access') and not expires_at else 'no'}"
    )


def upsert_community_user_access(group_id, target_user_id, expiration, active=True):

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO users (user_id, group_id, expiration, subscription_active, created_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, group_id) DO UPDATE
            SET expiration=EXCLUDED.expiration,
                subscription_active=EXCLUDED.subscription_active

        """, (target_user_id, group_id, expiration, active))

        cur.execute("""

            UPDATE subscriptions
            SET end_date=%s,
                status=%s
            WHERE id=(
                SELECT id
                FROM subscriptions
                WHERE user_id=%s
                AND group_id=%s
                ORDER BY created_at DESC
                LIMIT 1
            )

        """, (expiration, "active" if active else "revoked", target_user_id, group_id))


        if cur.rowcount == 0 and active:

            cur.execute("""

                INSERT INTO subscriptions (user_id, group_id, status, start_date, end_date)
                VALUES (%s, %s, 'active', CURRENT_TIMESTAMP, %s)

            """, (target_user_id, group_id, expiration))

    conn.commit()


def adjust_community_user_access_days(group_id, target_user_id, days, operation):

    access_state = get_user_group_access_state(target_user_id, group_id)
    expires_at = access_state.get("expires_at")


    if access_state.get("has_active_access") and not expires_at:

        return {"ok": False, "reason": "permanent_access"}


    now = datetime.now()


    if operation == "add":

        base = expires_at if expires_at and expires_at > now else now
        new_expiration = base + timedelta(days=days)
        upsert_community_user_access(group_id, target_user_id, new_expiration, active=True)

        return {"ok": True, "expiration": new_expiration}


    if not expires_at:

        return {"ok": False, "reason": "permanent_access"}


    new_expiration = expires_at - timedelta(days=days)
    active = new_expiration > now


    if not active:

        new_expiration = now


    upsert_community_user_access(group_id, target_user_id, new_expiration, active=active)

    return {"ok": True, "expiration": new_expiration}


def revoke_community_user_access(group_id, target_user_id):

    now = datetime.now()


    with conn.cursor() as cur:

        cur.execute("UPDATE users SET subscription_active=FALSE, expiration=%s WHERE user_id=%s AND group_id=%s", (now, target_user_id, group_id))
        users_count = cur.rowcount
        cur.execute("UPDATE subscriptions SET status='revoked', end_date=%s WHERE user_id=%s AND group_id=%s", (now, target_user_id, group_id))
        subscriptions_count = cur.rowcount
        cur.execute("UPDATE invite_links SET is_active=FALSE, revoked_at=CURRENT_TIMESTAMP WHERE user_id=%s AND group_id=%s", (target_user_id, group_id))
        invite_links_count = cur.rowcount

    conn.commit()

    return {"users": users_count, "subscriptions": subscriptions_count, "invite_links": invite_links_count}


def delete_community_user_records(group_id, target_user_id):

    deleted_counts = {}


    with conn.cursor() as cur:

        for table_name in ("group_user_promo_redemptions", "invite_links", "subscriptions", "users"):

            cur.execute(f"DELETE FROM {table_name} WHERE user_id=%s AND group_id=%s", (target_user_id, group_id))
            deleted_counts[table_name] = cur.rowcount

    conn.commit()

    return deleted_counts


async def notify_community_user_access_change(context, target_user_id, text, group_id, actor_user_id):

    try:

        await context.bot.send_message(chat_id=target_user_id, text=text)

    except Exception as e:

        log_event(
            "community_user_access_notification_failed",
            category="access",
            severity="warning",
            scope="group",
            group_id=group_id,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            message="No se pudo notificar al usuario sobre un cambio de acceso.",
            metadata={"error": str(e)[:300]}
        )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_community_user_callbacks(update, context, query, user_id, data):

    if data.startswith("community_user_manage_"):

        parsed = parse_community_user_callback(data, "community_user_manage_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_view_community_users(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para ver este usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        text = await build_community_user_detail_text(context, group_id, target_user_id)
        await send_clean_message(context, query.message.chat_id, text, reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id))
        return

    if data.startswith("community_user_add_days_") or data.startswith("community_user_subtract_days_"):

        is_add = data.startswith("community_user_add_days_")
        prefix = "community_user_add_days_" if is_add else "community_user_subtract_days_"
        parsed = parse_community_user_callback(data, prefix, include_days=True)


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar la acción.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id, days = parsed


        if days not in (1, 15, 30) or not user_can_manage_community_user_access(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para modificar este acceso.", reply_markup=build_owner_panel_nav_keyboard())
            return


        result = adjust_community_user_access_days(group_id, target_user_id, days, "add" if is_add else "subtract")


        if not result.get("ok"):

            message = "Este usuario tiene acceso permanente. No se pueden añadir días sin convertir el acceso." if is_add else "Este usuario tiene acceso permanente. No se pueden restar días."
            await query.message.reply_text(message, reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id))
            return


        group = fetch_group_basic_info(group_id)
        group_name = group[1] if group else f"Grupo {group_id}"
        expiration_text = format_commercial_datetime(result.get("expiration"))
        log_event(
            "community_user_access_days_added" if is_add else "community_user_access_days_subtracted",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            target_user_id=target_user_id,
            message="Acceso de usuario modificado desde panel owner.",
            metadata={"days": days, "operation": "add" if is_add else "subtract", "new_expiration": expiration_text}
        )
        await notify_community_user_access_change(
            context,
            target_user_id,
            f"{'✅' if is_add else '⚠️'} Se te han {'añadido' if is_add else 'restado'} {days} días de suscripción/acceso a la comunidad \"{group_name}\".\nNueva fecha de expiración: {expiration_text}",
            group_id,
            user_id
        )
        text = await build_community_user_detail_text(context, group_id, target_user_id)
        await send_clean_message(context, query.message.chat_id, f"{text}\n\n✅ Cambio aplicado. Nueva expiración: {expiration_text}", reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id))
        return

    if data.startswith("community_user_revoke_access_") and not data.startswith("community_user_revoke_access_yes_"):

        parsed = parse_community_user_callback(data, "community_user_revoke_access_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_manage_community_user_access(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para revocar este acceso.", reply_markup=build_owner_panel_nav_keyboard())
            return


        await send_clean_message(
            context,
            query.message.chat_id,
            "⚠️ ¿Seguro que quieres revocar el acceso de este usuario?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, revocar acceso", callback_data=f"community_user_revoke_access_yes_{group_id}_{target_user_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"community_user_manage_{group_id}_{target_user_id}")]
            ])
        )
        return

    if data.startswith("community_user_revoke_access_yes_"):

        parsed = parse_community_user_callback(data, "community_user_revoke_access_yes_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_manage_community_user_access(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para revocar este acceso.", reply_markup=build_owner_panel_nav_keyboard())
            return


        counts = revoke_community_user_access(group_id, target_user_id)
        group = fetch_group_basic_info(group_id)
        group_name = group[1] if group else f"Grupo {group_id}"
        log_event("community_user_access_revoked", category="access", severity="warning", scope="group", group_id=group_id, actor_user_id=user_id, target_user_id=target_user_id, message="Acceso de usuario revocado desde panel owner.", metadata={"updated_counts": counts})
        await notify_community_user_access_change(context, target_user_id, f"🚫 Tu acceso a la comunidad \"{group_name}\" ha sido revocado.", group_id, user_id)
        text = await build_community_user_detail_text(context, group_id, target_user_id)
        await send_clean_message(context, query.message.chat_id, f"{text}\n\n✅ Acceso revocado.", reply_markup=build_community_user_manage_keyboard(group_id, target_user_id, user_id))
        return

    if data.startswith("community_user_delete_") and not data.startswith("community_user_delete_yes_"):

        parsed = parse_community_user_callback(data, "community_user_delete_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_manage_community_user_access(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para eliminar registros de este usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        log_event("community_user_delete_confirmation_opened", category="access", severity="warning", scope="group", group_id=group_id, actor_user_id=user_id, target_user_id=target_user_id, message="Confirmación de eliminación de usuario abierta.", metadata={})
        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "⚠️ ¿Seguro que quieres eliminar este usuario de la base de datos?\n\n"
                "Se eliminarán registros locales relacionados con esta comunidad donde sea posible.\n"
                "No necesariamente banea al usuario en Telegram.\n"
                "No emite reembolsos.\n"
                "No cancela suscripciones Stripe/PayPal.\n"
                "Esta acción es más difícil de recuperar."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, eliminar de la base de datos", callback_data=f"community_user_delete_yes_{group_id}_{target_user_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"community_user_manage_{group_id}_{target_user_id}")]
            ])
        )
        return

    if data.startswith("community_user_delete_yes_"):

        parsed = parse_community_user_callback(data, "community_user_delete_yes_")


        if not parsed:

            await query.message.reply_text("⚠️ No he podido identificar al usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        group_id, target_user_id = parsed


        if not user_can_manage_community_user_access(user_id, group_id):

            await query.message.reply_text("⛔ No tienes permiso para eliminar registros de este usuario.", reply_markup=build_owner_panel_nav_keyboard())
            return


        deleted_counts = delete_community_user_records(group_id, target_user_id)
        log_event("community_user_deleted_from_db", category="access", severity="warning", scope="group", group_id=group_id, actor_user_id=user_id, target_user_id=target_user_id, message="Registros locales de usuario eliminados para una comunidad.", metadata={"deleted_counts": deleted_counts})
        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Usuario eliminado de los registros locales de esta comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Volver a usuarios activos", callback_data=f"community_users_{group_id}_active_0")],
                [InlineKeyboardButton("⚠️ Ver inactivos/expirados", callback_data=f"community_users_{group_id}_inactive_0")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )
        return

    return NOT_HANDLED
