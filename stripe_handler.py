import time
import stripe

from flask import request

from datetime import datetime, timedelta

from bot_config import TOKEN, ADMIN_ID, STRIPE_WEBHOOK_SECRET
from audit_log_service import log_event
from db import conn
from invite_link_service import create_telegram_invite_link
from notification_service import notify_super_admins, send_telegram_message
from payment_gateway_config import (
    PAYMENT_PROVIDER_STRIPE,
    PAYMENT_SCOPE_PLATFORM,
    PAYMENT_STATUS_PAID,
    PURCHASE_TYPE_GROUP_ACCESS
)
from payment_service import create_payment_transaction
from rbac_helpers import get_group_owner_user_id


def get_payment_owner_user_id(group_id, telegram_group_id):

    owner_user_id = get_group_owner_user_id(group_id)


    if owner_user_id:

        return owner_user_id


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT user_id
                FROM commercial_requests
                WHERE (
                    approved_group_id=%s
                    OR approved_telegram_group_id=%s
                )
                AND user_id IS NOT NULL
                ORDER BY updated_at DESC NULLS LAST,
                         created_at DESC
                LIMIT 1

            """, (
                group_id,
                telegram_group_id
            ))

            row = cur.fetchone()


        if row:

            return row[0]

    except Exception as e:

        print("Error buscando owner de pago:", e)


    return None


def format_payment_amount(amount, currency):

    if amount is None:

        return "-"


    try:

        return f"{int(amount) / 100:.2f} {(currency or '').upper()}".strip()

    except Exception:

        return f"{amount} {(currency or '').upper()}".strip()


def mask_invite_link(invite_link):

    if not invite_link:

        return None


    return f"{str(invite_link)[:12]}***"


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
        stripe_session_id = session.get("id")
        stripe_payment_id = session.get("payment_intent") or stripe_session_id
        amount_total = session.get("amount_total")
        currency = (session.get("currency") or "").upper() or None


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

                log_event(
                    "payment_blocked_banned_user",
                    category="payment",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Usuario baneado intentó completar un pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

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

        create_payment_transaction(
            PAYMENT_PROVIDER_STRIPE,
            status=PAYMENT_STATUS_PAID,
            payment_scope=PAYMENT_SCOPE_PLATFORM,
            purchase_type=PURCHASE_TYPE_GROUP_ACCESS,
            user_id=user_id,
            group_id=metadata_group_id,
            amount=amount_total,
            currency=currency,
            external_payment_id=stripe_payment_id,
            external_checkout_id=stripe_session_id,
            idempotency_key=stripe_session_id,
            metadata={
                "price_id": price_id,
                "source": "stripe_webhook"
            }
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

                # plans.duration_days siempre está expresado en DÍAS.
                # El valor 0 se reserva para planes permanentes explícitos.

                if duration_days is None or duration_days == 0:

                    expiration = None

                else:

                    duration_value = int(duration_days)

                    if duration_value < 1 or duration_value > 3650:

                        print(
                            "ERROR: duración de plan fuera de rango:",
                            duration_value,
                            price_id,
                            metadata_group_id
                        )

                        log_event(
                            "payment_plan_duration_invalid",
                            category="payment",
                            severity="error",
                            scope="group",
                            group_id=metadata_group_id,
                            actor_user_id=user_id,
                            target_user_id=user_id,
                            message="Pago recibido con duración de plan fuera de rango.",
                            metadata={
                                "stripe_session_id": stripe_session_id,
                                "stripe_payment_id": stripe_payment_id,
                                "price_id": price_id,
                                "duration_days": duration_value
                            }
                        )

                        return "OK"


                    expiration = datetime.now() + timedelta(
                        days=duration_value
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

        # =========================
        # CREAR LINK VIP (1 uso)
        # =========================

        group_id = int(
            session["metadata"]["group_id"]
        )

        # Obtener telegram_group_id real

        with conn.cursor() as cur:

            cur.execute("""

                SELECT telegram_group_id,
                       name

                FROM groups

                WHERE id=%s

            """, (group_id,))

            row = cur.fetchone()

            if not row:

                print("ERROR: grupo no encontrado en DB:", group_id)

                log_event(
                    "payment_group_not_found",
                    category="payment",
                    severity="error",
                    group_id=group_id,
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Pago recibido pero no se encontró el grupo interno.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id,
                        "plan": plan_name,
                        "amount": amount_total,
                        "currency": currency
                    }
                )

                return "OK"

            telegram_group_id = row[0]
            group_name = row[1] or f"Grupo {group_id}"


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


        print(
            "Invite link creado:",
            f"group_id={group_id}",
            f"telegram_group_id={telegram_group_id}",
            f"user_id={user_id}",
            "status=created" if link else "status=failed",
            f"link_masked={mask_invite_link(link)}"
        )


        if not link:

            print("ERROR creando invite link")

            log_event(
                "payment_invite_link_error",
                category="payment",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Pago confirmado pero no se pudo crear invite link.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero no se pudo crear el link de acceso.\n\n"
                f"Grupo: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )

            return "OK"


        # =========================
        # GUARDAR LINK EN DATABASE
        # =========================

        try:

            with conn.cursor() as cur:

                # guardar acceso activo del comprador

                cur.execute("""

                    INSERT INTO users
                    (
                        user_id,
                        group_id,
                        expiration,
                        subscription_active,
                        last_invite_link
                    )
                    VALUES (%s, %s, %s, TRUE, %s)
                    ON CONFLICT (user_id, group_id)
                    DO UPDATE SET
                        expiration=EXCLUDED.expiration,
                        subscription_active=TRUE,
                        last_invite_link=EXCLUDED.last_invite_link

                """, (

                    user_id,
                    group_id,
                    expiration,
                    link

                ))


                # registrar pago

                cur.execute("""

                    INSERT INTO payments
                    (
                        user_id,
                        group_id,
                        stripe_payment_id,
                        amount,
                        currency,
                        status,
                        plan
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)

                """, (

                    user_id,
                    group_id,
                    stripe_payment_id,
                    amount_total,
                    currency,
                    "paid",
                    plan_name

                ))


                # borrar links antiguos del mismo usuario y grupo

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


                # guardar nuevo

                cur.execute("""

                    INSERT INTO invite_links
                    (
                        user_id,
                        group_id,
                        telegram_group_id,
                        invite_link,
                        is_active
                    )

                    VALUES (%s, %s, %s, %s, TRUE)

                """, (

                    user_id,
                    group_id,
                    telegram_group_id,
                    link

                ))


                conn.commit()

        except Exception as e:

            print("Error guardando invite link:", e)

            log_event(
                "payment_storage_error",
                category="payment",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Pago confirmado pero falló el guardado del acceso/link.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency,
                    "error": str(e)
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero falló el guardado del acceso.\n\n"
                f"Grupo: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )

            return "OK"


        log_event(
            "payment_confirmed",
            category="payment",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Pago confirmado y acceso activado.",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_payment_id": stripe_payment_id,
                "plan": plan_name,
                "amount": amount_total,
                "currency": currency,
                "expiration": expiration
            }
        )

        log_event(
            "invite_link_created",
            category="access",
            severity="info",
            scope="group",
            group_id=group_id,
            telegram_group_id=telegram_group_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            message="Invite link creado tras pago confirmado.",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_payment_id": stripe_payment_id
            }
        )


        # =========================
        # ENVIAR LINK AL USUARIO
        # =========================

        user_response = send_telegram_message(
            TOKEN,
            user_id,
            f"🔗 Tu acceso VIP:\n{link}"
        )


        if not user_response or not user_response.get("ok"):

            log_event(
                "payment_buyer_notification_error",
                category="notification",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="No se pudo notificar el link de acceso al comprador.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id
                }
            )


        # =========================
        # AVISAR AL ADMIN
        # =========================

        amount_text = format_payment_amount(
            amount_total,
            currency
        )


        admin_text = (
            f"💳 Nuevo pago recibido\n\n"
            f"Grupo: {group_name}\n"
            f"Usuario: {user_id}\n"
            f"Plan: {plan_name}\n"
            f"Importe: {amount_text}\n"
            "Acceso: activo"
        )

        sent_admins = notify_super_admins(
            TOKEN,
            admin_text,
            fallback_admin_id=ADMIN_ID
        )


        if sent_admins:

            log_event(
                "payment_admin_notified",
                category="notification",
                severity="info",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=ADMIN_ID,
                message="Super admin notificado de pago confirmado.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "sent_admin_count": sent_admins
                }
            )

        else:

            log_event(
                "payment_admin_notification_error",
                category="notification",
                severity="error",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=ADMIN_ID,
                message="No se pudo notificar a ningún super admin del pago.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id
                }
            )

        owner_user_id = get_payment_owner_user_id(
            group_id,
            telegram_group_id
        )

        if owner_user_id and int(owner_user_id) != int(ADMIN_ID):

            owner_response = send_telegram_message(
                TOKEN,
                owner_user_id,
                f"💳 Nuevo pago en tu comunidad\n\n"
                f"Grupo: {group_name}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}\n"
                f"Importe: {amount_text}\n"
                "Acceso: activo"
            )


            if owner_response and owner_response.get("ok"):

                log_event(
                    "payment_owner_notified",
                    category="notification",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="Owner notificado de nuevo pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

            else:

                log_event(
                    "payment_owner_notification_error",
                    category="notification",
                    severity="warning",
                    scope="group",
                    group_id=group_id,
                    telegram_group_id=telegram_group_id,
                    actor_user_id=user_id,
                    target_user_id=owner_user_id,
                    message="No se pudo notificar al owner del pago.",
                    metadata={
                        "stripe_session_id": stripe_session_id,
                        "stripe_payment_id": stripe_payment_id
                    }
                )

        elif not owner_user_id:

            log_event(
                "payment_owner_not_found",
                category="payment",
                severity="warning",
                scope="group",
                group_id=group_id,
                telegram_group_id=telegram_group_id,
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Pago recibido pero no se encontró owner del grupo.",
                metadata={
                    "stripe_session_id": stripe_session_id,
                    "stripe_payment_id": stripe_payment_id,
                    "plan": plan_name,
                    "amount": amount_total,
                    "currency": currency
                }
            )

            notify_super_admins(
                TOKEN,
                "⚠️ Pago recibido pero no encontré owner del grupo\n\n"
                f"Grupo: {group_name}\n"
                f"ID interno: {group_id}\n"
                f"Telegram ID: {telegram_group_id}\n"
                f"Usuario: {user_id}\n"
                f"Plan: {plan_name}",
                fallback_admin_id=ADMIN_ID
            )


        print("Pago confirmado:", user_id)


    return "OK"
