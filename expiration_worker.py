import time

from datetime import datetime
from functools import partial

from bot_config import TOKEN, ADMIN_ID
from db import conn
from guardian_service import send_guardian_event_log_sync
from invite_link_service import revoke_telegram_invite_link
from notification_service import send_telegram_message
from payment_access_service import get_user_group_access_state
from rbac_helpers import is_super_admin
from telegram_group_actions import kick_chat_member


revoke_link = partial(revoke_telegram_invite_link, TOKEN)


def is_protected_group_admin(user_id, group_id):

    if is_super_admin(user_id):

        return True


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT 1
                FROM admins
                WHERE user_id=%s
                AND group_id=%s
                AND COALESCE(is_active, TRUE)=TRUE
                LIMIT 1

            """, (
                user_id,
                group_id
            ))

            return cur.fetchone() is not None

    except Exception as e:

        print("Error comprobando admin protegido en expiración:", e)
        return True


def has_active_subscription_record(cur, user_id, group_id):

    cur.execute("""

        SELECT 1
        FROM subscriptions
        WHERE user_id=%s
        AND group_id=%s
        AND LOWER(COALESCE(status, '')) IN ('active', 'paid', 'completed', 'trialing')
        AND (
            end_date IS NULL
            OR end_date > NOW()
        )
        LIMIT 1

    """, (
        user_id,
        group_id
    ))

    return cur.fetchone() is not None


def check_expirations():

    while True:

        with conn.cursor() as cur:

            cur.execute("""

            SELECT user_id, group_id, expiration
            FROM users
            WHERE expiration IS NOT NULL

            """)

            rows = cur.fetchall()

            now = datetime.now()

            for user_id, group_id, expiration in rows:

                if expiration and now > expiration:

                    try:

                        print(
                            "Expulsando expirado:",
                            user_id,
                            "grupo:",
                            group_id
                        )

                        # =========================
                        # OBTENER TELEGRAM_GROUP_ID
                        # =========================

                        cur.execute("""

                        SELECT telegram_group_id,
                               COALESCE(is_free_group, FALSE)
                        FROM groups
                        WHERE id=%s

                        """, (group_id,))

                        group_row = cur.fetchone()

                        if not group_row:
                            continue

                        telegram_group_id = group_row[0]
                        is_free_group = group_row[1] is True


                        if is_free_group:

                            print("Expiración omitida por grupo gratis:", user_id, group_id)
                            continue


                        if is_protected_group_admin(user_id, group_id):

                            print("Expiración omitida por admin/owner protegido:", user_id, group_id)
                            continue


                        try:

                            access_state = get_user_group_access_state(user_id, group_id)

                        except Exception as e:

                            print("Error resolviendo estado antes de expulsar:", e)
                            conn.rollback()
                            continue


                        if (
                            access_state.get("has_active_access")
                            or access_state.get("subscription_status") == "paid_without_access_record"
                        ):

                            print("Expiración omitida por acceso activo:", user_id, group_id, access_state.get("reason"))
                            continue


                        try:

                            active_subscription = has_active_subscription_record(cur, user_id, group_id)

                        except Exception as e:

                            print("Error comprobando suscripción activa antes de expulsar:", e)
                            conn.rollback()
                            continue


                        if active_subscription:

                            print("Expiración omitida por suscripción activa:", user_id, group_id)
                            continue


                        # =========================
                        # OBTENER LINK DEL GRUPO
                        # =========================

                        cur.execute("""

                        SELECT invite_link
                        FROM invite_links
                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))

                        links = cur.fetchall()


                        # =========================
                        # REVOCAR LINKS
                        # =========================

                        for (link,) in links:

                            try:

                                revoke_link(
                                    telegram_group_id,
                                    link
                                )

                                # =========================
                                # MARCAR LINK COMO INACTIVO
                                # =========================

                                cur.execute("""

                                UPDATE invite_links

                                SET is_active=FALSE,

                                    revoked_at=NOW()

                                WHERE invite_link=%s

                                """, (link,))


                            except Exception as e:

                                print(

                                    "Error revocando link expirado:",

                                    e

                                )


                        # =========================
                        # EXPULSAR USUARIO
                        # =========================

                        try:

                            kick_chat_member(
                                TOKEN,
                                telegram_group_id,
                                user_id
                            )

                        except Exception as e:

                            print(
                                "Error expulsando usuario:",
                                e
                            )


                        # =========================
                        # DESACTIVAR LINK EXPIRADO
                        # =========================

                        cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        # =========================
                        # BORRAR LINK DESACTIVADO
                        # =========================

                        cur.execute("""

                        DELETE FROM invite_links

                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        # =========================
                        # MARCAR SUSCRIPCIÓN EXPIRADA SIN BORRAR HISTORIAL
                        # =========================

                        cur.execute("""

                        UPDATE users
                        SET subscription_active=FALSE
                        WHERE user_id=%s
                        AND group_id=%s

                        """, (

                            user_id,
                            group_id

                        ))


                        conn.commit()


                        # =========================
                        # AVISAR ADMIN
                        # =========================

                        send_telegram_message(
                            TOKEN,
                            ADMIN_ID,
                            f"⛔ Usuario expirado eliminado\n\n"
                            f"User ID: {user_id}\n"
                            f"Grupo ID: {group_id}"
                        )

                        send_guardian_event_log_sync(
                            group_id,
                            "guardian_access_expired",
                            "Usuario expirado procesado por el worker.",
                            telegram_group_id=telegram_group_id,
                            severity="warning",
                            actor_user_id=user_id,
                            target_user_id=user_id,
                            metadata={
                                "user_id": user_id,
                                "expiration": expiration,
                                "subscription_active": False
                            }
                        )


                    except Exception as e:

                        print(

                            "Error procesando expiración:",

                            e

                        )

        time.sleep(60)
