"""
admin_view_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_view_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import log_event
from db import conn
from rbac_helpers import get_admin_group_ids
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def fetch_admin_groups_for_permissions(*args, **kwargs):
    from callback_router import fetch_admin_groups_for_permissions as impl
    return impl(*args, **kwargs)



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_view_callbacks(update, context, query, user_id, data):

    if data == "admin_view_groups":

        try:
            await query.message.delete()
        except:
            pass

        try:

            with conn.cursor() as cur:

                groups = fetch_admin_groups_for_permissions(
                    user_id,
                    ["can_manage_groups", "can_manage_plans"]
                )

            log_event(
                "admin_view_groups_loaded",
                category="admin",
                severity="info",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Listado de grupos cargado desde panel admin.",
                metadata={
                    "groups_count": len(groups)
                }
            )

        except Exception as e:

            log_event(
                "admin_view_groups_error",
                category="admin",
                severity="error",
                scope="global",
                actor_user_id=user_id,
                target_user_id=user_id,
                message="Error cargando grupos desde panel admin.",
                metadata={
                    "error": str(e)
                }
            )

            await query.message.reply_text(
                f"❌ Error cargando grupos:\n{str(e)}"
            )

            return


        if not groups:

            await query.message.reply_text(
                "⚠️ No hay grupos registrados."
            )

            return


        texto = "📋 GRUPOS REGISTRADOS\n\n"


        try:

            for group_id, name, telegram_id in groups:

                texto += (

                    f"🆔 ID interno: {group_id}\n"
                    f"📦 Nombre: {name}\n"
                    f"📡 Telegram ID: {telegram_id}\n\n"

                )

        except Exception as e:

            print("ERROR construyendo texto:", e)

            await query.message.reply_text(
                f"❌ Error procesando grupos:\n{str(e)}"
            )

            return


        keyboard = [

            [InlineKeyboardButton(
                "⬅️ Volver",
                callback_data="menu_groups"
            )]

        ]


        await query.message.reply_text(

            texto,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    if data == "admin_view_payments":

        group_ids = get_admin_group_ids(
            user_id,
            ["can_view_payments", "can_manage_payments"]
        )


        try:

            with conn.cursor() as cur:

                if group_ids is None:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """)

                elif not group_ids:

                    payments = []

                else:

                    cur.execute("""

                        SELECT p.user_id,
                               g.name,
                               p.amount,
                               p.currency,
                               p.status,
                               p.payment_date
                        FROM payments p
                        LEFT JOIN groups g
                        ON p.group_id = g.id
                        WHERE p.group_id = ANY(%s)
                        ORDER BY p.payment_date DESC
                        LIMIT 20

                    """, (group_ids,))


                if group_ids is None or group_ids:

                    payments = cur.fetchall()

        except Exception as e:

            print("Error cargando pagos admin:", e)

            await query.message.reply_text(
                "❌ Error cargando pagos."
            )

            return


        if not payments:

            await query.message.reply_text(
                "⚠️ No hay pagos registrados."
            )

            return


        text = "💳 Últimos pagos\n\n"


        for payment_user_id, group_name, amount, currency, status, payment_date in payments:

            text += (
                f"Usuario: {payment_user_id}\n"
                f"Grupo: {group_name or '-'}\n"
                f"Importe: {amount or '-'} {currency or ''}\n"
                f"Estado: {status or '-'}\n"
                f"Fecha: {payment_date or '-'}\n\n"
            )


        await query.message.reply_text(text)

        return

    return NOT_HANDLED
