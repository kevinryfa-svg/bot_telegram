import time

from datetime import datetime
from functools import partial

from bot_config import TOKEN, ADMIN_ID
from db import conn
from invite_link_service import revoke_telegram_invite_link
from notification_service import send_telegram_message
from telegram_group_actions import kick_chat_member


revoke_link = partial(revoke_telegram_invite_link, TOKEN)


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

                        SELECT telegram_group_id
                        FROM groups
                        WHERE id=%s

                        """, (group_id,))

                        group_row = cur.fetchone()

                        if not group_row:
                            continue

                        telegram_group_id = group_row[0]


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
                        # BORRAR SOLO SUSCRIPCIÓN EXPIRADA
                        # =========================

                        cur.execute("""

                        DELETE FROM users
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


                    except Exception as e:

                        print(

                            "Error procesando expiración:",

                            e

                        )

        time.sleep(60)
