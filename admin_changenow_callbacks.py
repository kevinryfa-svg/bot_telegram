"""
admin_changenow_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_changenow_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import json

from admin_payment_provider_callbacks import OWNER_PAYMENT_PROVIDER_CHANGENOW
from audit_log_service import log_event
from db import conn
from payment_access_service import grant_group_access_after_payment
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


async def handle_admin_changenow_callbacks(update, context, query, user_id, data):

    if data == "admin_changenow_manual_review":

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
                       created_at
                FROM payment_transactions
                WHERE provider=%s
                AND status=%s
                ORDER BY created_at DESC
                LIMIT 20

            """, (
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
                "manual_review"
            ))

            rows = cur.fetchall()

        lines = [
            "🧪 Pagos ChangeNOW en revisión",
            "",
            "Estos pagos NO conceden acceso automático. Revisa wallet, importe y estado antes de confirmar."
        ]
        keyboard = []

        if not rows:

            lines.append("\nNo hay pagos ChangeNOW pendientes de revisión.")

        for row in rows:

            transaction_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, status, external_payment_id, created_at = row
            lines.extend([
                "",
                f"#{transaction_id} Usuario: {tx_user_id}",
                f"Grupo: {tx_group_id or '-'} Plan: {tx_plan_id or '-'}",
                f"Importe: {amount or '-'} {currency or ''}",
                f"Estado: {status}",
                f"Provider id: {external_payment_id or '-'}",
                f"Fecha: {created_at}"
            ])
            keyboard.append([
                InlineKeyboardButton(f"✅ Confirmar #{transaction_id}", callback_data=f"admin_changenow_mark_paid_{transaction_id}"),
                InlineKeyboardButton(f"❌ Rechazar #{transaction_id}", callback_data=f"admin_changenow_reject_ask_{transaction_id}")
            ])

        keyboard.extend([
            [InlineKeyboardButton("⬅️ ChangeNOW", callback_data="admin_payment_changenow")],
            [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
        ])

        await send_clean_message(
            context,
            query.message.chat_id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    # PIDE CONFIRMACIÓN. Esto marca como fallido un pago de CRIPTO de una
    # persona real, con un toque, sin paso intermedio, sin forma de deshacerlo
    # y sin dejar rastro de quién lo hizo. Y estaba pegado al botón de
    # confirmar en la misma pantalla.
    if data.startswith("admin_changenow_reject_ask_"):

        transaction_id = extract_commercial_request_id(
            data, "admin_changenow_reject_ask_"
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            f"⚠️ Vas a marcar como FALLIDO el pago #{transaction_id}.\n\n"
            "Si esa persona ha enviado la cripto de verdad, se queda sin "
            "acceso y sin su dinero, y esto no se deshace desde aquí.\n\n"
            "¿Seguro?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔴 Sí, rechazarlo",
                    callback_data=f"admin_changenow_reject_{transaction_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ No, volver a revisión",
                    callback_data="admin_changenow_manual_review"
                )],
            ])
        )

        return


    if data.startswith("admin_changenow_reject_"):

        transaction_id = extract_commercial_request_id(data, "admin_changenow_reject_")

        log_event(
            "changenow_payment_rejected",
            category="payment",
            severity="warning",
            scope="global",
            actor_user_id=query.from_user.id if query.from_user else None,
            message="Pago ChangeNOW marcado como fallido a mano.",
            metadata={"transaction_id": str(transaction_id)},
        )

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
                OWNER_PAYMENT_PROVIDER_CHANGENOW
            ))
            updated = cur.fetchone()

        conn.commit()

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Pago ChangeNOW rechazado." if updated else "⚠️ No encontré ese pago ChangeNOW.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_changenow_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    if data.startswith("admin_changenow_mark_paid_"):

        transaction_id = extract_commercial_request_id(data, "admin_changenow_mark_paid_")

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
                OWNER_PAYMENT_PROVIDER_CHANGENOW
            ))
            row = cur.fetchone()

        if not row:

            await query.message.reply_text(
                "⚠️ No encontré ese pago ChangeNOW.",
                reply_markup=build_admin_payment_providers_keyboard()
            )

            return


        _tx_id, tx_user_id, tx_group_id, tx_plan_id, amount, currency, external_payment_id, external_checkout_id, tx_status = row

        if tx_group_id and tx_plan_id:

            result = grant_group_access_after_payment(
                OWNER_PAYMENT_PROVIDER_CHANGENOW,
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
            # CON EL MOTIVO. Decía «no pude conceder el acceso» y punto: la
            # razón se guardaba en metadata_json y solo se podía leer con SQL,
            # así que el operador se quedaba mirando un pago cobrado sin saber
            # qué arreglar.
            (
                "✅ Pago ChangeNOW confirmado manualmente."
                if result.get("ok") else
                "⚠️ No pude conceder el acceso. El pago sigue en revisión.\n\n"
                f"Motivo: {result.get('reason') or 'sin detalle'}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 Volver a revisión", callback_data="admin_changenow_manual_review")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
            ])
        )

        return

    return NOT_HANDLED
