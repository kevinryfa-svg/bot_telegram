"""
admin_guardarian_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_guardarian_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import json

from admin_payment_provider_callbacks import OWNER_PAYMENT_PROVIDER_GUARDARIAN
from db import conn
from payment_access_service import grant_group_access_after_payment
from payment_providers.guardarian_provider import process_guardarian_webhook
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

def build_admin_payment_providers_keyboard(*args, **kwargs):
    from callback_router import build_admin_payment_providers_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_guardarian_callbacks(update, context, query, user_id, data):

    if data == "admin_guardarian_manual_review":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       status,
                       external_payment_id,
                       external_checkout_id,
                       created_at
                FROM payment_transactions
                WHERE provider=%s
                AND status=%s
                ORDER BY created_at DESC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                "manual_review"
            ))

            rows = cur.fetchall()

        lines = [
            "🧪 Pagos Guardarian en revisión",
            "",
            "Estos pagos no se pudieron verificar automáticamente como finished. Reconsulta o decide manualmente con cuidado."
        ]
        keyboard = []

        if not rows:

            lines.append("\nNo hay pagos Guardarian pendientes de revisión.")

        for row in rows:

            transaction_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, status, external_payment_id, external_checkout_id, created_at = row
            lines.extend([
                "",
                f"#{transaction_id} Usuario: {tx_user_id}",
                f"Grupo: {tx_group_id or '-'} Plan: {tx_plan_id or '-'}",
                f"Importe: {amount or '-'} {currency or ''}",
                f"Estado: {status}",
                f"Provider id: {external_payment_id or external_checkout_id or '-'}",
                f"Fecha: {created_at}"
            ])
            keyboard.append([
                InlineKeyboardButton(f"✅ Confirmar #{transaction_id}", callback_data=f"admin_guardarian_mark_paid_{transaction_id}"),
                InlineKeyboardButton(f"❌ Rechazar #{transaction_id}", callback_data=f"admin_guardarian_reject_{transaction_id}")
            ])

        keyboard.extend([
            [InlineKeyboardButton("🔁 Reconsultar pagos pendientes", callback_data="admin_guardarian_recheck_pending")],
            [InlineKeyboardButton("⬅️ Guardarian", callback_data="admin_payment_guardarian")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data == "admin_guardarian_recheck_pending":

        with conn.cursor() as cur:

            cur.execute("""

                SELECT external_checkout_id
                FROM payment_transactions
                WHERE provider=%s
                AND status IN (%s, %s)
                AND external_checkout_id IS NOT NULL
                ORDER BY created_at ASC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                "pending",
                "manual_review"
            ))
            rows = cur.fetchall()

        checked = 0

        for row in rows:

            provider_order_id = row[0]

            if not provider_order_id:

                continue

            process_guardarian_webhook({"id": provider_order_id})
            checked += 1

        await send_clean_message(
            context,
            query.message.chat_id,
            f"🔁 Reconsulta Guardarian terminada. Pagos revisados: {checked}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Ver revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("⬅️ Guardarian", callback_data="admin_payment_guardarian")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("admin_guardarian_reject_"):

        transaction_id = extract_commercial_request_id(data, "admin_guardarian_reject_")

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status='failed',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                AND provider=%s
                RETURNING id

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_GUARDARIAN
            ))
            updated = cur.fetchone()

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago Guardarian rechazado." if updated else "⚠️ No encontré ese pago Guardarian.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("admin_guardarian_mark_paid_"):

        transaction_id = extract_commercial_request_id(data, "admin_guardarian_mark_paid_")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       user_id,
                       group_id,
                       plan_id,
                       amount,
                       currency,
                       external_payment_id,
                       external_checkout_id,
                       status
                FROM payment_transactions
                WHERE id=%s
                AND provider=%s
                LIMIT 1

            """, (
                transaction_id,
                OWNER_PAYMENT_PROVIDER_GUARDARIAN
            ))
            row = cur.fetchone()

        if not row:

            await query.message.reply_text(
                "⚠️ No encontré ese pago Guardarian.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        _tx_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, external_payment_id, external_checkout_id, tx_status = row

        if tx_status == "paid":

            result = {"ok": True, "reason": "already_paid"}
            new_status = "paid"

        elif tx_group_id and tx_plan_id:

            result = grant_group_access_after_payment(
                OWNER_PAYMENT_PROVIDER_GUARDARIAN,
                tx_user_id,
                tx_group_id,
                tx_plan_id,
                external_payment_id=external_payment_id,
                external_checkout_id=external_checkout_id,
                amount=amount,
                currency=currency,
                transaction_id=transaction_id
            )
            new_status = "paid" if result.get("ok") else "manual_review"

        else:

            result = {"ok": True, "reason": "platform_manual_mark_paid"}
            new_status = "paid"

        with conn.cursor() as cur:

            cur.execute("""

                UPDATE payment_transactions
                SET status=%s,
                    metadata_json=COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                    metadata=COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s

            """, (
                new_status,
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                json.dumps({"manual_confirmed_by": user_id, "manual_result": result}),
                transaction_id
            ))

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago Guardarian confirmado manualmente." if result.get("ok") else "⚠️ No pude conceder el acceso. El pago sigue en revisión.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_guardarian_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    return NOT_HANDLED
