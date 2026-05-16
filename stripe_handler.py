import time
import stripe

from flask import request

from datetime import datetime, timedelta

from bot_config import TOKEN, ADMIN_ID, STRIPE_WEBHOOK_SECRET
from db import conn
from invite_link_service import create_telegram_invite_link
from notification_service import send_telegram_message


# =========================
# WEBHOOK STRIPE
# =========================

def stripe_webhook():

    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:

        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET
        )

    except Exception as e:

        print("Webhook error:", e)
        return "Error", 400


    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]

        user_id = int(
            session["metadata"]["telegram_id"]
        )


        # =========================
        # COMPROBAR SI ESTÁ BANEADO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM banned_users
                WHERE user_id=%s

            """, (user_id,))

            banned = cur.fetchone()

            if banned:

                print("Usuario baneado intentó pagar:", user_id)

                return "OK"


        # =========================
        # OBTENER PLAN PAGADO
        # =========================

        line_items = stripe.checkout.Session.list_line_items(
            session["id"]
        )

        price_id = line_items["data"][0]["price"]["id"]

        metadata_group_id = int(
            session["metadata"]["group_id"]
        )

        # =========================
        # CALCULAR DURACIÓN
        # =========================

        try:

            metadata_group_id = int(
                session["metadata"]["group_id"]
            )

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT duration_days, name

                    FROM plans

                    WHERE price_id=%s
                    AND group_id=%s

                """, (

                    price_id,
                    metadata_group_id

                ))

                row = cur.fetchone()


            if not row:

                print(
                    "ERROR: plan no encontrado:",
                    price_id,
                    metadata_group_id
                )

                expiration = None
                plan_name = "Desconocido"

            else:

                duration_days, plan_name = row

                # Protección contra valores inválidos

                if duration_days is None or duration_days == 0:

                    expiration = None

                else:

                    duration_value = int(duration_days)

                    # =========================
                    # MODO INTELIGENTE DURACIÓN
                    # < 1440 → minutos
                    # >= 1440 → días
                    # =========================

                    if duration_value < 1440:

                        expiration = datetime.now() + timedelta(
                            minutes=duration_value
                        )

                    else:

                        expiration = datetime.now() + timedelta(
                            days=duration_value // 1440
                        )

        except Exception as e:

            print(
                "Error calculando duración:",
                e
            )

            expiration = None
            plan_name = "Error"


        # =========================
        # GUARDAR USUARIO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

            INSERT INTO users
            (user_id, group_id, expiration)

            VALUES (%s, %s, %s)

            ON CONFLICT (user_id, group_id)

            DO UPDATE SET expiration=%s

            """, (

                user_id,
                metadata_group_id,
                expiration,
                expiration

            ))


            # =========================
            # REGISTRAR PAGO
            # =========================

            cur.execute("""

            INSERT INTO payments
            (user_id, plan)

            VALUES (%s, %s)

            """, (

                user_id,
                plan_name

            ))


            conn.commit()


        print("Usuario guardado:", user_id)


        # =========================
        # CREAR LINK VIP (1 uso)
        # =========================

        group_id = int(
            session["metadata"]["group_id"]
        )

        # Obtener telegram_group_id real

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id

                FROM groups

                WHERE id=%s

            """, (group_id,))

            row = cur.fetchone()

            if not row:

                print("ERROR: grupo no encontrado en DB:", group_id)

                return "OK"

            telegram_group_id = row[0]


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        max_expire = int(time.time()) + 180

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


        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1
        )


        print("Respuesta createChatInviteLink:", link)


        if not link:

            print("ERROR creando invite link")

            return "OK"


        # =========================
        # GUARDAR LINK EN DATABASE
        # =========================

        try:

            with conn.cursor() as cur:

                # borrar links antiguos

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    telegram_group_id

                ))


                # guardar nuevo

                cur.execute("""

                    INSERT INTO invite_links
                    (user_id, group_id, invite_link)

                    VALUES (%s, %s, %s)

                """, (

                    user_id,
                    telegram_group_id,
                    link

                ))


                conn.commit()

        except Exception as e:

            print("Error guardando invite link:", e)


        # =========================
        # ENVIAR LINK AL USUARIO
        # =========================

        send_telegram_message(
            TOKEN,
            user_id,
            f"🔗 Tu acceso VIP:\n{link}"
        )


        # =========================
        # AVISAR AL ADMIN
        # =========================

        send_telegram_message(
            TOKEN,
            ADMIN_ID,
            f"💳 Nuevo pago recibido\n\n"
            f"Usuario: {user_id}\n"
            f"Plan: {plan_name}"
        )


        print("Pago confirmado:", user_id)


    return "OK"


