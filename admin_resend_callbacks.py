"""
admin_resend_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_resend_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import requests

from db import conn
from group_service import normalize_community_type
from i18n_service import DEFAULT_LANGUAGE
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    format_access_link_validity,
)
from owner_publicity_callbacks import TOKEN
from rbac_helpers import is_super_admin
from ui_menu_helpers import send_clean_message


# get_group_id NO es una constante: es un marcador que main.py rellena en
# caliente con `callback_router_module.get_group_id = ...`. Se lee del router
# EN EL MOMENTO de la llamada; si el None viviera aquí, este módulo se quedaría
# con él para siempre.
def get_group_id(*args, **kwargs):
    from callback_router import get_group_id as impl
    return impl(*args, **kwargs)



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


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def user_can_recover_community_access_links(*args, **kwargs):
    from callback_router import user_can_recover_community_access_links as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_link_validity_line(language=None):
    """
    Cuánto vale un enlace de acceso, dicho al usuario.

    El reenvío masivo mandaba el enlace a secas, así que quien lo recibía no
    sabía si tenía que correr. Ahora que duran un día entero, decirlo evita que
    lo deje para luego pensando que caduca en minutos.
    """

    return (
        f"⏱ Válido {format_access_link_validity(ACCESS_LINK_EXPIRE_SECONDS, language or DEFAULT_LANGUAGE)}. "
        "Es personal y de un solo uso."
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_resend_callbacks(update, context, query, user_id, data):

    if data == "admin_resend_access":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_resend_links", "can_recover_access", "can_manage_users"]
        )


        if not group_id or not user_can_recover_community_access_links(user_id, group_id):

            await query.message.reply_text(
                "⛔ No tienes permiso para reenviar o recuperar links de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_community_links_recover_menu_text(group_id),
            reply_markup=build_community_links_recover_menu_keyboard(group_id)
        )

        return

    if data == "admin_resend_links":

        if not is_super_admin(query.from_user.id):
            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT user_id
                    FROM users

                    WHERE
                    (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    AND user_id NOT IN (

                        SELECT user_id
                        FROM banned_users

                    )

                """)

                users = cur.fetchall()


            enviados = 0

            for (user_id,) in users:

                try:

                    # =========================
                    # OBTENER TELEGRAM_GROUP_ID REAL
                    # =========================

                    with conn.cursor() as cur2:

                        cur2.execute("""

                            SELECT telegram_group_id,
                                   COALESCE(community_type, 'group')

                            FROM groups

                            WHERE id=(

                                SELECT group_id
                                FROM users
                                WHERE user_id=%s
                                LIMIT 1

                            )

                        """, (user_id,))

                        group_row = cur2.fetchone()


                    if not group_row:
                        continue


                    telegram_group_id = group_row[0]
                    community_type = normalize_community_type(group_row[1])


                    link = create_telegram_invite_link(
                        TOKEN,
                        telegram_group_id,
                        expire_seconds=ACCESS_LINK_EXPIRE_SECONDS,
                        member_limit=1,
                        community_type=community_type
                    )


                    if not link:

                        print(
                            "Error creando link para usuario:",
                            user_id
                        )

                        continue


                    with conn.cursor() as cur:

                        cur.execute("""

                            DELETE FROM invite_links
                            WHERE user_id=%s

                        """, (user_id,))


                        cur.execute("""

                            INSERT INTO invite_links
                            (user_id, group_id, telegram_group_id, invite_link)

                            VALUES (%s, %s, %s, %s)

                        """, (

                            user_id,
                            get_group_id(),
                            telegram_group_id,
                            link

                        ))

                        conn.commit()


                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={
                            "chat_id": user_id,
                            "text": (
                                "🔗 Nuevo acceso VIP\n\n"
                                f"{link}\n\n"
                                f"{build_link_validity_line()}"
                            )
                        }

                    )

                    enviados += 1

                except Exception as e:

                    print("Error enviando link:", e)


            await query.message.reply_text(

                f"📩 {enviados} nuevos links enviados."

            )

        except Exception as e:

            print("Error reenviando:", e)

            await query.message.reply_text(
                "❌ Error reenviando links"
            )

        return

    return NOT_HANDLED
