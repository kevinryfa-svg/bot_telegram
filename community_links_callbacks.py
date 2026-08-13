"""
community_links_callbacks: tramo extraído de callback_router.py.

Prefijos: community_links_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import asyncio

from audit_log_service import log_event
from guardian_service import send_guardian_event_log
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

def build_community_links_recover_menu_keyboard(*args, **kwargs):
    from callback_router import build_community_links_recover_menu_keyboard as impl
    return impl(*args, **kwargs)


def build_community_links_recover_menu_text(*args, **kwargs):
    from callback_router import build_community_links_recover_menu_text as impl
    return impl(*args, **kwargs)


def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_community_user_rows(*args, **kwargs):
    from callback_router import fetch_community_user_rows as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def format_community_user_display_name(*args, **kwargs):
    from callback_router import format_community_user_display_name as impl
    return impl(*args, **kwargs)


def send_recovered_community_access_link(*args, **kwargs):
    from callback_router import send_recovered_community_access_link as impl
    return impl(*args, **kwargs)


def user_can_recover_community_access_links(*args, **kwargs):
    from callback_router import user_can_recover_community_access_links as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_community_links_recover_user_page(group_id, page=0):

    rows = [
        row
        for row in fetch_community_user_rows(group_id)
        if row.get("is_active")
    ]
    per_page = 8
    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    inicio = page * per_page
    page_rows = rows[inicio:inicio + per_page]
    group = fetch_group_basic_info(group_id)
    group_name = group[1] if group else f"Grupo {group_id}"

    text = (
        "👤 Reenviar link a usuario específico\n\n"
        f"Comunidad: {group_name or f'Grupo {group_id}'}\n"
        f"Usuarios activos: {total}\n"
        f"Página {page + 1}/{total_pages}\n\n"
    )


    if not page_rows:

        text += "No hay usuarios activos a los que reenviar link."

    else:

        text += "Selecciona un usuario activo:"


    keyboard = []


    for row in page_rows:

        keyboard.append([
            InlineKeyboardButton(
                f"🔗 Reenviar link · {format_community_user_display_name(row)}",
                callback_data=f"community_link_recover_user_{group_id}_{row.get('user_id')}"
            )
        ])


    nav_row = []


    if page > 0:

        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"community_links_recover_one_{group_id}_{page - 1}"))


    if page + 1 < total_pages:

        nav_row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"community_links_recover_one_{group_id}_{page + 1}"))


    if nav_row:

        keyboard.append(nav_row)


    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data=f"community_links_recover_menu_{group_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")])

    return text, InlineKeyboardMarkup(keyboard)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_community_links_callbacks(update, context, query, user_id, data):

    if data.startswith("community_links_recover_menu_"):

        group_id = extract_commercial_request_id(
            data,
            "community_links_recover_menu_"
        )


        if not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar o recuperar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        context.user_data["selected_group_admin"] = group_id
        context.user_data["selected_owner_group"] = group_id

        log_event(
            "community_link_recover_menu_opened",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Menú de reenvío/recuperación de links abierto.",
            metadata={}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_community_links_recover_menu_text(group_id),
            reply_markup=build_community_links_recover_menu_keyboard(group_id)
        )

        return

    if data.startswith("community_links_recover_one_"):

        payload = data.replace("community_links_recover_one_", "", 1)
        parts = payload.split("_")


        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():

            await query.message.reply_text(
                "⚠️ No he podido identificar la comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        group_id = int(parts[0])
        page = int(parts[1])


        if not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar o recuperar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        text, keyboard = build_community_links_recover_user_page(group_id, page)
        await send_clean_message(
            context,
            query.message.chat_id,
            text,
            reply_markup=keyboard
        )

        return

    if data.startswith("community_links_recover_all_yes_"):

        group_id = extract_commercial_request_id(
            data,
            "community_links_recover_all_yes_"
        )


        if not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        active_rows = [
            row
            for row in fetch_community_user_rows(group_id)
            if row.get("is_active")
        ]
        limit = 50
        rows_to_send = active_rows[:limit]
        sent_count = 0
        link_reused_count = 0
        link_created_count = 0
        failed_dm_count = 0
        no_access_count = 0
        link_generation_failed_count = 0
        failed_no_telegram_group_id = 0
        failed_bot_permission = 0
        failed_telegram_api = 0
        failed_db_save = 0
        failed_other = 0
        failed_paid_without_access_record = 0
        failed_rate_limited = 0
        stopped_by_rate_limit = False
        retry_after = None

        log_event(
            "community_link_recover_all_started",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Reenvío masivo de links de acceso iniciado.",
            metadata={
                "total": len(active_rows),
                "limit": limit
            }
        )


        for row in rows_to_send:

            target_user_id = row.get("user_id")

            if not target_user_id:

                continue


            result = await send_recovered_community_access_link(
                context,
                group_id,
                target_user_id,
                user_id
            )


            if result.get("source") == "existing":

                link_reused_count += 1

            elif result.get("source") == "new":

                link_created_count += 1


            if result.get("ok"):

                sent_count += 1

            elif result.get("reason") == "dm_failed":

                failed_dm_count += 1

            elif result.get("reason") in ("no_active_access", "expired_access"):

                no_access_count += 1

            elif result.get("reason") == "paid_without_access_record":

                failed_paid_without_access_record += 1

            else:

                link_generation_failed_count += 1

                if result.get("reason") == "telegram_rate_limited":

                    failed_rate_limited += 1
                    retry_after = result.get("retry_after")
                    stopped_by_rate_limit = True
                    break

                elif result.get("reason") == "missing_telegram_group_id":

                    failed_no_telegram_group_id += 1

                elif result.get("reason") == "bot_permission_failed":

                    failed_bot_permission += 1

                elif result.get("reason") == "db_save_failed":

                    failed_db_save += 1

                elif result.get("reason") == "telegram_api_failed":

                    failed_telegram_api += 1

                else:

                    failed_other += 1


            await asyncio.sleep(0.15)


        skipped_by_limit = max(0, len(active_rows) - len(rows_to_send))

        log_event(
            "community_link_recover_all_completed",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=user_id,
            message="Reenvío masivo de links de acceso terminado.",
            metadata={
                "total": len(active_rows),
                "link_reused_count": link_reused_count,
                "link_created_count": link_created_count,
                "sent_count": sent_count,
                "dm_failed_count": failed_dm_count,
                "no_access_count": no_access_count,
                "link_generation_failed_count": link_generation_failed_count,
                "failed_no_telegram_group_id": failed_no_telegram_group_id,
                "failed_bot_permission": failed_bot_permission,
                "failed_telegram_api": failed_telegram_api,
                "failed_db_save": failed_db_save,
                "failed_other": failed_other,
                "failed_paid_without_access_record": failed_paid_without_access_record,
                "failed_rate_limited": failed_rate_limited,
                "stopped_by_rate_limit": stopped_by_rate_limit,
                "retry_after": retry_after,
                "skipped_by_limit": skipped_by_limit
            }
        )

        await send_guardian_event_log(
            context,
            group_id,
            "guardian_access_links_bulk_completed",
            "Reenvío masivo de links de acceso terminado.",
            severity="info" if not link_generation_failed_count else "warning",
            actor_user_id=user_id,
            metadata={
                "total": len(active_rows),
                "limit": limit,
                "link_reused_count": link_reused_count,
                "link_created_count": link_created_count,
                "sent_count": sent_count,
                "dm_failed_count": failed_dm_count,
                "link_generation_failed_count": link_generation_failed_count,
                "failed_rate_limited": failed_rate_limited,
                "stopped_by_rate_limit": stopped_by_rate_limit,
                "skipped_by_limit": skipped_by_limit
            }
        )

        error_hint = ""

        if link_generation_failed_count:

            error_hint = "\n\nRevisa logs: community_link_recover_generation_failed"


        rate_limit_hint = ""

        if stopped_by_rate_limit:

            retry_text = f"{retry_after} segundos" if retry_after else "unos minutos"
            rate_limit_hint = (
                "\n\nTelegram ha limitado temporalmente la creación de enlaces.\n"
                f"Espera aproximadamente {retry_text} y vuelve a intentarlo.\n"
                "No se han seguido generando enlaces para evitar más errores."
            )


        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "✅ Reenvío terminado\n\n"
                f"Usuarios activos encontrados: {len(active_rows)}\n"
                f"Límite aplicado: {limit}\n"
                f"Links reutilizados: {link_reused_count}\n"
                f"Links nuevos creados: {link_created_count}\n"
                f"Links enviados por privado: {sent_count}\n"
                f"Privado bloqueado/fallido: {failed_dm_count}\n"
                f"Errores generando link: {link_generation_failed_count}\n"
                f"- Sin telegram_group_id: {failed_no_telegram_group_id}\n"
                f"- Permisos del bot: {failed_bot_permission}\n"
                f"- Telegram API: {failed_telegram_api}\n"
                f"- Guardado DB: {failed_db_save}\n"
                f"- Otros errores: {failed_other}\n"
                f"- Pagos confirmados sin registro local: {failed_paid_without_access_record}\n"
                f"- Rate limit Telegram: {failed_rate_limited}\n"
                f"Omitidos sin acceso activo: {no_access_count}\n"
                f"Omitidos por límite de seguridad: {skipped_by_limit}"
                f"{error_hint}"
                f"{rate_limit_hint}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Ver usuarios de esta comunidad", callback_data=f"owner_group_users_{group_id}")],
                [InlineKeyboardButton("⬅️ Menú de links", callback_data=f"community_links_recover_menu_{group_id}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("community_links_recover_all_") or data.startswith("community_links_recover_all"):

        group_id = extract_commercial_request_id(
            data,
            "community_links_recover_all_"
        ) or extract_commercial_request_id(
            data,
            "community_links_recover_all"
        )


        if not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        active_count = sum(
            1
            for row in fetch_community_user_rows(group_id)
            if row.get("is_active")
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            (
                "⚠️ Vas a reenviar o regenerar links de acceso a los usuarios activos de esta comunidad.\n\n"
                "Esto puede enviar muchos mensajes privados. No toca pagos ni suscripciones.\n\n"
                f"Usuarios activos detectados: {active_count}\n"
                "Por seguridad, se procesarán como máximo 50 usuarios por ejecución.\n\n"
                "¿Continuar?"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, enviar a todos los activos", callback_data=f"community_links_recover_all_yes_{group_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"community_links_recover_menu_{group_id}")]
            ])
        )

        return

    return NOT_HANDLED
