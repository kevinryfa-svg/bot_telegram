"""
mysub_callbacks: tramo extraído de callback_router.py.

Prefijos: mysub_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import time

from audit_log_service import log_event
from commercial_catalog import CALLBACK_SUBSCRIPTIONS_HELP
from db import conn
from formatters import format_tiempo_restante
from group_delivery_health_service import recheck_group_delivery_live
from group_service import (
    format_community_kind,
    normalize_community_type,
)
from i18n_service import (
    load_user_language,
    t,
)
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    format_access_link_validity,
)
from owner_publicity_callbacks import TOKEN
from rbac_helpers import get_group_owner_user_id
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


# revoke_link NO es una constante: es un marcador que main.py rellena en
# caliente con `callback_router_module.revoke_link = ...`. Si el None viviera
# aquí, este módulo se quedaría con él para siempre y el botón reventaría con
# "NoneType is not callable". Se lee del router EN EL MOMENTO de la llamada.
def revoke_link(*args, **kwargs):
    from callback_router import revoke_link as impl
    return impl(*args, **kwargs)



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_recovery_keyboard(*args, **kwargs):
    from callback_router import build_group_recovery_keyboard as impl
    return impl(*args, **kwargs)


def reply_with_recover_navigation(*args, **kwargs):
    from callback_router import reply_with_recover_navigation as impl
    return impl(*args, **kwargs)


def resolve_group_access_state_for_user(*args, **kwargs):
    from callback_router import resolve_group_access_state_for_user as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

async def report_access_link_unavailable(context, query, user_id, group_id,
                                        group_name, telegram_group_id,
                                        community_kind):
    """
    Tiene el acceso pagado y activo, y el enlace no se puede crear.

    Es el mismo fallo que vigila el repaso periódico de entrega, pero aquí hay una
    persona esperando delante, así que hace falta algo más que apuntarlo:

      - al cliente se le dice lo que le sirve —que no es cosa suya, que no ha
        perdido nada y que hay alguien mirándolo—, con botones. Antes se le daba
        una instrucción interna sobre un grupo que no es el suyo;
      - a quien puede arreglarlo se le avisa de que un cliente que ha pagado está
        fuera, que es lo único que mueve a alguien a mirarlo hoy;
      - y se vuelve a preguntar a Telegram para dejar el estado de entrega al día:
        acabamos de tener la prueba de que algo no va.
    """

    language = load_user_language(user_id)

    await query.message.reply_text(
        t("access.link_unavailable", language, group=group_name or community_kind),
        reply_markup=build_group_recovery_keyboard(group_id)
    )


    log_event(
        "access_link_unavailable_for_paid_user",
        category="access",
        severity="critical",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Un usuario con acceso activo no ha podido recibir su enlace.",
        metadata={
            "telegram_group_id": telegram_group_id,
            "group_name": str(group_name or "")[:80]
        }
    )


    aviso = (
        "🚨 Un cliente con acceso pagado no puede entrar\n\n"
        f"Comunidad: {group_name or group_id}\n"
        f"Usuario: {user_id}\n\n"
        "El bot no ha podido crear su enlace de invitación. Lo más habitual es "
        "que haya perdido el permiso «Invitar usuarios mediante enlace» en el "
        "grupo.\n\n"
        "Mientras siga así, nadie puede entrar en esta comunidad."
    )

    try:

        owner_user_id = get_group_owner_user_id(group_id)

        if owner_user_id:

            await context.bot.send_message(chat_id=owner_user_id, text=aviso)

    except Exception as e:

        print("Enlace no disponible: no se pudo avisar al propietario:", str(e)[:200])


    try:

        await recheck_group_delivery_live(
            context,
            group_id,
            group_name or f"Comunidad {group_id}",
            telegram_group_id
        )

    except Exception as e:

        print("Enlace no disponible: fallo la reconsulta de entrega:", str(e)[:200])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_mysub_callbacks(update, context, query, user_id, data):

    if data.startswith("mysub_"):

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id
        mysub_parts = data.split("_")


        if len(mysub_parts) < 2 or not mysub_parts[1].lstrip("-").isdigit():

            await reply_with_recover_navigation(
                query,
                "⚠️ Esta opción ya no está disponible o no está configurada."
            )

            return

        requested_group_ref = int(
            mysub_parts[1]
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER COMUNIDAD
                # =========================

                cur.execute("""

                    SELECT id,
                           name,
                           telegram_group_id,
                           COALESCE(community_type, 'group')

                    FROM groups

                    WHERE telegram_group_id=%s
                    OR id=%s
                    LIMIT 1

                """, (
                    requested_group_ref,
                    requested_group_ref
                ))

                group_row = cur.fetchone()


                if not group_row:

                    # Sin botones, esta pantalla era un callejón sin salida: y es
                    # justo la que se le ofrece a quien acaba de pagar.
                    await reply_with_recover_navigation(
                        query,
                        "❌ No encuentro esa comunidad."
                    )

                    return


                real_group_id = group_row[0]
                group_name = group_row[1]
                telegram_group_id = group_row[2]
                community_type = normalize_community_type(group_row[3])
                community_kind = format_community_kind(community_type)


                # =========================
                # OBTENER EXPIRATION
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id

                ))

                user_row = cur.fetchone()


                access_state = await resolve_group_access_state_for_user(
                    context,
                    user_id,
                    real_group_id
                )


                if not user_row and not access_state.get("has_active_access"):

                    log_event(
                        "access_recovery_denied_no_active_access",
                        category="access",
                        severity="info",
                        scope="group",
                        group_id=real_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Recuperación de acceso denegada por no tener acceso activo.",
                        metadata={
                            "user_id": user_id,
                            "group_id": real_group_id,
                            "telegram_group_id": telegram_group_id,
                            "access_source": access_state.get("access_source"),
                            "reason": access_state.get("reason")
                        }
                    )

                    await reply_with_recover_navigation(
                        query,
                        f"No tienes una suscripción activa para este {community_kind}."
                    )

                    return


                expiration = user_row[0] if user_row else access_state.get("expires_at")


                if access_state.get("has_active_access") and expiration is None:

                    log_event(
                        "access_recovery_permanent_access_allowed",
                        category="access",
                        severity="info",
                        scope="group",
                        group_id=real_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Recuperación permitida por acceso permanente/free activo.",
                        metadata={
                            "user_id": user_id,
                            "group_id": real_group_id,
                            "telegram_group_id": telegram_group_id,
                            "access_source": access_state.get("access_source"),
                            "reason": access_state.get("reason")
                        }
                    )


                # =========================
                # OBTENER LINK ACTUAL
                # =========================

                cur.execute("""

                    SELECT invite_link

                    FROM invite_links

                    WHERE user_id=%s
                    AND (
                        group_id=%s
                        OR telegram_group_id=%s
                        OR group_id=%s
                    )
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id,
                    telegram_group_id,
                    telegram_group_id

                ))

                link_row = cur.fetchone()


        except Exception as e:

            print("Error cargando detalle suscripción:", e)

            await reply_with_recover_navigation(
                query,
                "❌ No he podido cargar tu acceso ahora mismo.\n\n"
                "Inténtalo otra vez en un momento. Si sigue igual, escríbenos."
            )

            return


        # =========================
        # FORMATEAR TIEMPO
        # =========================

        tiempo_texto = format_tiempo_restante(
            expiration
        )


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link

                FROM invite_links

                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_link(
                        telegram_group_id,
                        old_link
                    )

                    cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE invite_link=%s

                    """, (old_link,))

                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


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
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        # 24 h por defecto (ACCESS_LINK_EXPIRE_SECONDS) en vez de 180 s: el
        # enlace es de un solo uso y al entrar se comprueba el acceso, así que
        # los tres minutos solo dejaban fuera a clientes que ya habían pagado.
        max_expire = int(time.time()) + max(ACCESS_LINK_EXPIRE_SECONDS, 60)

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1,
            community_type=community_type
        )


        if not link:

            # Antes esto le decía al CLIENTE que se asegurase de que el bot es
            # administrador del grupo: una instrucción interna, sobre un grupo que
            # no es suyo. Ahora se le dice lo que le sirve y se avisa a quien
            # puede arreglarlo de verdad.
            await report_access_link_unavailable(
                context,
                query,
                user_id,
                real_group_id,
                group_name,
                telegram_group_id,
                community_kind
            )

            return


        # =========================
        # GUARDAR LINK NUEVO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link)

                VALUES (%s, %s, %s, %s)

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                link

            ))

            conn.commit()


        keyboard = [

            [

                # Si el enlace caduca, antes había que volver atrás y entrar de
                # nuevo en la comunidad para conseguir otro. Desde aquí es un
                # solo toque, que es lo que hace falta cuando alguien que ha
                # pagado se ha quedado fuera.
                InlineKeyboardButton(

                    "🔄 Enviarme otro enlace",

                    callback_data=f"mysub_{telegram_group_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    "💬 Ayuda sobre este menú",

                    callback_data=CALLBACK_SUBSCRIPTIONS_HELP

                )

            ],

            [

                InlineKeyboardButton(

                    "⬅️ Volver",

                    callback_data="mis_subs"

                )

            ]

        ]


        access_intro = (
            f"✅ Tienes acceso permanente activo a este {community_kind}.\n\n"
            if expiration is None
            else ""
        )


        mensaje = (

            f"📦 {group_name}\n\n"

            f"{access_intro}"

            f"⏳ Tiempo restante:\n"
            f"{tiempo_texto}\n\n"

            f"⏱ El enlace vale {format_access_link_validity(expire_seconds, load_user_language(user_id))} "
            "y solo lo puedes usar tú, una vez.\n"
            "Si caduca, pide otro con el botón de abajo.\n\n"

            f"🔗 Tu nuevo acceso:\n"
            f"{link}"

        )


        await query.message.reply_text(

            mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    return NOT_HANDLED
