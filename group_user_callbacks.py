"""
group_user_callbacks: tramo extraído de callback_router.py.

Prefijos: group_user_

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
from group_service import (
    format_community_kind,
    normalize_community_type,
)
from guardian_service import send_guardian_event_log
from i18n_service import (
    load_user_language,
    t,
)
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    revoke_telegram_invite_link,
)
from owner_publicity_callbacks import TOKEN
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from ui_menu_helpers import send_clean_message
from user_activity_logger import log_user_event_by_ids


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_recovery_keyboard(*args, **kwargs):
    from callback_router import build_group_recovery_keyboard as impl
    return impl(*args, **kwargs)


def build_group_user_code_callback(*args, **kwargs):
    from callback_router import build_group_user_code_callback as impl
    return impl(*args, **kwargs)


def build_group_user_code_uses_keyboard(*args, **kwargs):
    from callback_router import build_group_user_code_uses_keyboard as impl
    return impl(*args, **kwargs)


def build_group_user_codes_error_keyboard(*args, **kwargs):
    from callback_router import build_group_user_codes_error_keyboard as impl
    return impl(*args, **kwargs)


def build_group_user_codes_keyboard(*args, **kwargs):
    from callback_router import build_group_user_codes_keyboard as impl
    return impl(*args, **kwargs)


def clear_group_user_promo_wizard(*args, **kwargs):
    from callback_router import clear_group_user_promo_wizard as impl
    return impl(*args, **kwargs)


def clear_location_flow_navigation(*args, **kwargs):
    from callback_router import clear_location_flow_navigation as impl
    return impl(*args, **kwargs)


def create_group_user_promo_code(*args, **kwargs):
    from callback_router import create_group_user_promo_code as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def format_group_user_promo_duration(*args, **kwargs):
    from callback_router import format_group_user_promo_duration as impl
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


def validate_group_user_promo_row(*args, **kwargs):
    from callback_router import validate_group_user_promo_row as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def fetch_group_user_promo_codes(group_id, active_only=False):

    with conn.cursor() as cur:

        active_filter = ""


        if active_only:

            active_filter = """
                AND is_active=TRUE
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
                AND (
                    max_uses=0
                    OR used_count < max_uses
                )
            """


        cur.execute(f"""

            SELECT id,
                   code,
                   duration_days,
                   is_permanent,
                   max_uses,
                   used_count,
                   is_active,
                   expires_at,
                   created_at
            FROM group_user_promo_codes
            WHERE group_id=%s
            {active_filter}
            ORDER BY created_at DESC
            LIMIT 50

        """, (group_id,))

        return cur.fetchall()


def fetch_group_user_promo_usage(group_id, limit=30):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT r.redeemed_at,
                   r.user_id,
                   c.code,
                   r.expiration
            FROM group_user_promo_redemptions r
            JOIN group_user_promo_codes c
            ON c.id = r.code_id
            WHERE r.group_id=%s
            ORDER BY r.redeemed_at DESC
            LIMIT %s

        """, (
            group_id,
            limit
        ))

        return cur.fetchall()


def format_group_user_promo_uses(max_uses, used_count):

    if max_uses == 0:

        return f"{used_count}/ilimitado"


    return f"{used_count}/{max_uses}"


def build_group_user_code_duration_keyboard(group_id=None):

    suffix = f"_{group_id}" if group_id else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 día", callback_data=f"group_user_code_duration{suffix}_1")],
        [InlineKeyboardButton("7 días", callback_data=f"group_user_code_duration{suffix}_7")],
        [InlineKeyboardButton("30 días", callback_data=f"group_user_code_duration{suffix}_30")],
        [InlineKeyboardButton("Permanente", callback_data=f"group_user_code_duration{suffix}_permanent")],
        [InlineKeyboardButton("Personalizado", callback_data=f"group_user_code_duration{suffix}_custom")],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
    ])


def build_group_user_code_kind_keyboard(group_id=None):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Código automático", callback_data=build_group_user_code_callback("group_user_code_auto", group_id))],
        [InlineKeyboardButton("Código manual", callback_data=build_group_user_code_callback("group_user_code_manual", group_id))],
        [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_code_create", group_id))]
    ])


def build_group_user_code_deactivate_keyboard(rows, group_id=None):

    keyboard = []


    for code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, _expires_at, _created_at in rows:

        keyboard.append([
            InlineKeyboardButton(
                f"{code} · {format_group_user_promo_duration(duration_days, is_permanent)} · {format_group_user_promo_uses(max_uses, used_count)}",
                callback_data=(
                    f"group_user_code_deactivate_{group_id}_{code_id}"
                    if group_id
                    else f"group_user_code_deactivate_{code_id}"
                )
            )
        ])


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))])

    return InlineKeyboardMarkup(keyboard)


async def grant_group_user_promo_access(context, chat_id, telegram_user, promo_row):

    (
        code_id,
        group_id,
        telegram_group_id,
        owner_user_id,
        code,
        duration_days,
        is_permanent,
        _max_uses,
        _used_count,
        _is_active,
        _expires_at,
        group_name,
        community_type,
        _group_is_active
    ) = promo_row

    community_type = normalize_community_type(community_type)
    community_kind = format_community_kind(community_type)

    user_id = telegram_user.id


    if not is_permanent and not duration_days:

        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Este código no tiene una duración válida."
        )

        return


    expiration = None


    if not is_permanent:

        expiration = datetime.now() + timedelta(days=int(duration_days))


    link = create_telegram_invite_link(
        TOKEN,
        telegram_group_id,
        expire_seconds=ACCESS_LINK_EXPIRE_SECONDS,
        member_limit=1,
        community_type=community_type
    )


    if not link:

        # Quien canjea un código es un cliente, no el administrador del grupo:
        # pedirle que revise permisos ajenos no le sirve de nada.
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(
                "access.link_unavailable",
                load_user_language(user_id),
                group=group_name or community_kind
            ),
            reply_markup=build_group_recovery_keyboard(group_id)
        )

        return


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE group_user_promo_codes
            SET used_count=used_count + 1
            WHERE id=%s
            AND is_active=TRUE
            AND (
                expires_at IS NULL
                OR expires_at > NOW()
            )
            AND (
                max_uses=0
                OR used_count < max_uses
            )
            RETURNING used_count

        """, (code_id,))

        code_update = cur.fetchone()


        if not code_update:

            conn.rollback()

            try:

                revoke_telegram_invite_link(
                    TOKEN,
                    telegram_group_id,
                    link
                )

            except Exception as e:

                print("Error revocando link de código no disponible:", e)


            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Este código ya no está disponible."
            )

            return


        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND (
                group_id=%s
                OR telegram_group_id=%s
                OR group_id=%s
            )

        """, (
            user_id,
            group_id,
            telegram_group_id,
            telegram_group_id
        ))

        cur.execute("""

            INSERT INTO invite_links
            (user_id, group_id, telegram_group_id, invite_link, is_active)
            VALUES (%s, %s, %s, %s, TRUE)

        """, (
            user_id,
            group_id,
            telegram_group_id,
            link
        ))

        cur.execute("""

            INSERT INTO users
            (
                user_id,
                group_id,
                username,
                first_name,
                expiration,
                subscription_active,
                last_invite_link
            )
            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                expiration=EXCLUDED.expiration,
                subscription_active=TRUE,
                last_invite_link=EXCLUDED.last_invite_link

        """, (
            user_id,
            group_id,
            telegram_user.username,
            telegram_user.first_name,
            expiration,
            link
        ))

        cur.execute("""

            INSERT INTO group_user_promo_redemptions
            (
                code_id,
                group_id,
                user_id,
                invite_link,
                expiration
            )
            VALUES (%s, %s, %s, %s, %s)

        """, (
            code_id,
            group_id,
            user_id,
            link,
            expiration
        ))

        conn.commit()


    log_event(
        "group_user_promo_redeemed",
        category="access",
        severity="info",
        scope="group",
        group_id=group_id,
        telegram_group_id=telegram_group_id,
        actor_user_id=user_id,
        target_user_id=owner_user_id,
        message="Código promocional de grupo canjeado.",
        metadata={
            "code_id": code_id,
            "code": code,
            "is_permanent": is_permanent,
            "duration_days": duration_days
        }
    )

    await send_guardian_event_log(
        context,
        group_id,
        "guardian_group_code_redeemed",
        "Código promocional de grupo canjeado.",
        telegram_group_id=telegram_group_id,
        severity="info",
        actor_user_id=user_id,
        target_user_id=user_id,
        metadata={
            "user_id": user_id,
            "code_id": code_id,
            "is_permanent": is_permanent,
            "duration_days": duration_days,
            "expiration": expiration
        }
    )

    log_user_event_by_ids(
        user_id,
        "code_redeemed",
        event_key="group_user_promo_code",
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        group_id=group_id,
        metadata={
            "code_id": code_id,
            "duration_days": duration_days,
            "is_permanent": is_permanent
        }
    )


    try:

        await context.bot.send_message(
            chat_id=owner_user_id,
            text=(
                "🎟 Código de tu grupo canjeado\n\n"
                f"Grupo: {group_name or group_id}\n"
                f"Usuario: {user_id}\n"
                f"Código: {code}"
            )
        )

    except Exception as e:

        print("Error avisando al owner del canje de código:", e)


    expiration_text = "permanente" if expiration is None else expiration.strftime("%Y-%m-%d %H:%M")

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Código canjeado correctamente.\n\n"
            f"Comunidad: {group_name or group_id}\n"
            f"Acceso: {expiration_text}\n\n"
            "Este enlace es personal y de un solo uso.\n"
            "No lo compartas.\n\n"
            f"{link}"
        ),
        reply_markup=ReplyKeyboardRemove()
    )


def resolve_group_user_codes_group(context, user_id, permissions, group_id=None):

    if group_id:

        try:

            group_id = int(group_id)

        except Exception:

            return None


        if not user_has_group_permission_any(user_id, group_id, permissions):

            return None


        if not set_group_user_promo_context(context, group_id):

            return None


        return group_id


    return get_selected_group_for_permissions(
        context,
        user_id,
        permissions
    )


def parse_group_user_code_group_callback(data, prefix):

    if data == prefix:

        return None


    if not data.startswith(f"{prefix}_"):

        return None


    payload = data.replace(f"{prefix}_", "", 1)


    if not payload.isdigit():

        return None


    return int(payload)


def parse_group_user_code_step_callback(data, prefix):

    payload = data.replace(prefix, "", 1).strip("_")


    if not payload:

        return None, None


    parts = payload.split("_", 1)


    if len(parts) == 2 and parts[0].isdigit():

        return int(parts[0]), parts[1]


    return None, payload



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_group_user_callbacks(update, context, query, user_id, data):

    if data.startswith("group_user_code_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "group_user_code_select_group_"
        )


        if not user_has_group_permission_any(
            user_id,
            group_id,
            ["can_manage_codes"]
        ):

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        group = set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )


        if not group:

            await query.message.reply_text(
                "❌ Grupo no encontrado.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Volver", callback_data="admin_group_user_codes")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        _group_id, group_name, _telegram_group_id, *_ = group

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            f"Grupo: {group_name or group_id}\n\n"
            "Crea códigos para usuarios finales de esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_codes_panel" or data.startswith("group_user_codes_panel_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_panel"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para gestionar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="panel"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "🎟 Códigos de mi grupo\n\n"
            "Estos códigos dan acceso a usuarios finales solo para esta comunidad.",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_code_create" or data.startswith("group_user_code_create_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_create"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="duration"
        )
        clear_group_user_promo_wizard(context, keep_group=True)
        context.user_data["group_user_promo_step"] = "duration"

        await send_clean_message(
            context,
            query.message.chat_id,
            "➕ Crear código\n\nElige la duración del acceso para el usuario final.",
            reply_markup=build_group_user_code_duration_keyboard(group_id)
        )

        return

    if data.startswith("group_user_code_duration_"):

        callback_group_id, slug = parse_group_user_code_step_callback(
            data,
            "group_user_code_duration"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="uses"
        )


        if slug == "custom":

            context.user_data["group_user_promo_waiting"] = "custom_duration"

            await query.message.reply_text(
                "Envía la duración en días, entre 1 y 3650.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if slug == "permanent":

            context.user_data["group_user_promo_duration_days"] = None
            context.user_data["group_user_promo_is_permanent"] = True

        else:

            try:

                duration_days = int(slug)

            except Exception:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            if not 1 <= duration_days <= 3650:

                await query.message.reply_text(
                    "❌ Duración no válida.",
                    reply_markup=build_group_user_codes_error_keyboard()
                )

                return


            context.user_data["group_user_promo_duration_days"] = duration_days
            context.user_data["group_user_promo_is_permanent"] = False


        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cuántos usos tendrá el código.",
            reply_markup=build_group_user_code_uses_keyboard(group_id)
        )

        return

    if data.startswith("group_user_code_uses_"):

        callback_group_id, uses_text = parse_group_user_code_step_callback(
            data,
            "group_user_code_uses"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            max_uses = int(uses_text)

        except Exception:

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        if max_uses not in (0, 1, 5, 10):

            await query.message.reply_text(
                "❌ Número de usos no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="code_kind"
        )
        context.user_data["group_user_promo_max_uses"] = max_uses

        await send_clean_message(
            context,
            query.message.chat_id,
            "Elige cómo quieres generar el código.",
            reply_markup=build_group_user_code_kind_keyboard(group_id)
        )

        return

    if data == "group_user_code_manual" or data.startswith("group_user_code_manual_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_manual"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        set_group_user_promo_context(
            context,
            group_id,
            step="manual_code"
        )
        context.user_data["group_user_promo_waiting"] = "manual_code"

        await query.message.reply_text(
            "Envía el código manual.\n\n"
            "Usa entre 4 y 32 caracteres: letras, números, guion o guion bajo.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver", callback_data=build_group_user_code_callback("group_user_codes_panel", group_id))]
            ])
        )

        return

    if data == "group_user_code_auto" or data.startswith("group_user_code_auto_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_auto"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para crear códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        duration_days = context.user_data.get("group_user_promo_duration_days")
        is_permanent = context.user_data.get("group_user_promo_is_permanent") is True
        max_uses = context.user_data.get("group_user_promo_max_uses")


        if max_uses is None:

            await query.message.reply_text(
                "❌ Falta completar la configuración del código.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            row = create_group_user_promo_code(
                group_id,
                user_id,
                duration_days,
                is_permanent,
                max_uses
            )

        except Exception as e:

            print("Error creando código de grupo:", e)

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        if not row:

            await query.message.reply_text(
                "❌ Error creando el código.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        clear_group_user_promo_wizard(context, keep_group=True)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Código creado\n\n"
            f"Código: {row[1]}\n"
            f"Duración: {format_group_user_promo_duration(row[2], row[3])}\n"
            f"Usos máximos: {'ilimitado' if row[4] == 0 else row[4]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_codes_active" or data.startswith("group_user_codes_active_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_codes_active"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        if not rows:

            await query.message.reply_text(
                "📋 No hay códigos activos para este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📋 Códigos activos de mi grupo\n\n"


        for _code_id, code, duration_days, is_permanent, max_uses, used_count, _is_active, expires_at, _created_at in rows:

            text += (
                f"Código: {code}\n"
                f"Duración: {format_group_user_promo_duration(duration_days, is_permanent)}\n"
                f"Usos: {format_group_user_promo_uses(max_uses, used_count)}\n"
                f"Caduca: {expires_at or '-'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_code_deactivate_menu" or data.startswith("group_user_code_deactivate_menu_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_deactivate_menu"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_codes(group_id, active_only=True)


        await query.message.reply_text(
            "🚫 Desactivar código\n\nElige el código que quieres desactivar.",
            reply_markup=build_group_user_code_deactivate_keyboard(rows, group_id)
        )

        return

    if data.startswith("group_user_code_deactivate_"):

        payload = data.replace("group_user_code_deactivate_", "", 1)
        callback_group_id = None
        code_id_text = payload


        if "_" in payload:

            maybe_group_id, maybe_code_id = payload.split("_", 1)


            if maybe_group_id.isdigit() and maybe_code_id.isdigit():

                callback_group_id = int(maybe_group_id)
                code_id_text = maybe_code_id


        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para desactivar códigos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        try:

            code_id = int(code_id_text)

        except Exception:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                UPDATE group_user_promo_codes
                SET is_active=FALSE
                WHERE id=%s
                AND group_id=%s
                RETURNING code

            """, (
                code_id,
                group_id
            ))

            row = cur.fetchone()
            conn.commit()


        if not row:

            await query.message.reply_text(
                "❌ Código no encontrado.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        await query.message.reply_text(
            f"🚫 Código desactivado:\n{row[0]}",
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_code_usage" or data.startswith("group_user_code_usage_"):

        callback_group_id = parse_group_user_code_group_callback(
            data,
            "group_user_code_usage"
        )
        group_id = resolve_group_user_codes_group(
            context,
            user_id,
            ["can_manage_codes"],
            callback_group_id
        )


        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver usos en esta comunidad.",
                reply_markup=build_group_user_codes_error_keyboard()
            )

            return


        rows = fetch_group_user_promo_usage(group_id)


        if not rows:

            await query.message.reply_text(
                "📊 Todavía no hay usos de códigos en este grupo.",
                reply_markup=build_group_user_codes_keyboard(group_id)
            )

            return


        text = "📊 Usos de códigos\n\n"


        for redeemed_at, redeemed_user_id, code, expiration in rows:

            text += (
                f"Código: {code}\n"
                f"Usuario: {redeemed_user_id}\n"
                f"Canjeado: {redeemed_at}\n"
                f"Expira: {expiration or 'permanente'}\n\n"
            )


        await query.message.reply_text(
            text,
            reply_markup=build_group_user_codes_keyboard(group_id)
        )

        return

    if data == "group_user_promo_redeem_start":

        await clear_location_flow_navigation(context, query.message.chat_id)

        await query.message.reply_text(
            "🎟 Código de comunidad\n\n"
            "El canje de códigos se hace desde la ficha de una comunidad concreta.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("group_user_promo_redeem_start_"):

        await clear_location_flow_navigation(context, query.message.chat_id)

        redeem_group_id = extract_commercial_request_id(
            data,
            "group_user_promo_redeem_start_"
        )

        if redeem_group_id is None:

            await query.message.reply_text(
                "❌ Comunidad no válida.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return

        context.user_data["group_user_promo_waiting"] = "redeem_code"
        context.user_data["group_user_promo_redeem_group_id"] = redeem_group_id

        await query.message.reply_text(
            "🎟 Canjear código de esta comunidad\n\n"
            "Envía ahora el código de acceso. Solo será válido si pertenece a esta comunidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a comunidad", callback_data=f"marketplace_group_{redeem_group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("group_user_promo_confirm_"):

        code_id = extract_commercial_request_id(
            data,
            "group_user_promo_confirm_"
        )

        if code_id is None:

            await query.message.reply_text(
                "❌ Código no válido.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        pending_code_id = context.user_data.get("group_user_promo_pending_code_id")


        if int(pending_code_id or 0) != code_id:

            await query.message.reply_text(
                "❌ No hay un código pendiente para confirmar.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        with conn.cursor() as cur:

            cur.execute("""

                SELECT c.id,
                       c.group_id,
                       c.telegram_group_id,
                       c.owner_user_id,
                       c.code,
                       c.duration_days,
                       c.is_permanent,
                       c.max_uses,
                       c.used_count,
                       c.is_active,
                       c.expires_at,
                       g.name,
                       COALESCE(g.community_type, 'group'),
                       COALESCE(g.is_active, TRUE)
                FROM group_user_promo_codes c
                JOIN groups g
                ON g.id = c.group_id
                WHERE c.id=%s
                LIMIT 1

            """, (code_id,))

            promo_row = cur.fetchone()


        valid, error_message = validate_group_user_promo_row(promo_row)
        selected_group_id = context.user_data.get("group_user_promo_redeem_group_id")


        if valid and selected_group_id and int(promo_row[1]) != int(selected_group_id):

            valid = False
            error_message = "❌ Este código no pertenece a esta comunidad."


        if not valid:

            await query.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver a comunidad",
                        callback_data=f"marketplace_group_{selected_group_id}"
                        if selected_group_id
                        else "start_explore_groups"
                    )],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        if len(promo_row) != 14:

            log_event(
                "group_user_promo_confirm_error",
                category="access",
                severity="error",
                scope="group",
                group_id=promo_row[1] if promo_row and len(promo_row) > 1 else None,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Formato inesperado de código de acceso de grupo.",
                metadata={
                    "callback_data": data,
                    "promo_id": code_id,
                    "row_length": len(promo_row) if promo_row else 0,
                    "error": "unexpected_promo_row_length"
                }
            )

            await query.message.reply_text(
                "❌ No he podido confirmar este código ahora mismo. Inténtalo de nuevo o contacta con el administrador.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

            return


        try:

            await grant_group_user_promo_access(
                context,
                query.message.chat_id,
                query.from_user,
                promo_row
            )

            context.user_data.pop("group_user_promo_pending_code_id", None)
            context.user_data.pop("group_user_promo_waiting", None)
            context.user_data.pop("group_user_promo_redeem_group_id", None)

        except Exception as e:

            print("Error canjeando código de grupo:", e)
            log_event(
                "group_user_promo_confirm_error",
                category="access",
                severity="error",
                scope="group",
                group_id=promo_row[1] if promo_row and len(promo_row) > 1 else None,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error confirmando código de acceso de grupo.",
                metadata={
                    "callback_data": data,
                    "promo_id": code_id,
                    "error": str(e)[:500]
                }
            )

            await query.message.reply_text(
                "❌ Error canjeando el código.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Explorar comunidades", callback_data="start_explore_groups")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
                ])
            )

        return

    return NOT_HANDLED
