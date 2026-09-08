"""
admin_beta_callbacks: tramo extraído de callback_router.py.

Prefijos: admin_beta_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import (
    contar_eventos_sin_resolver,
    complete_active_beta_cycle,
    complete_expired_beta_cycles,
    create_beta_cycle,
    get_active_beta_cycle,
    get_beta_cycle_monitor_counts,
    get_latest_beta_cycle,
    list_beta_monitor_events,
    log_event,
    mark_beta_monitor_events_resolved,
    summarize_beta_monitor_events,
)
from rbac_helpers import is_super_admin
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def format_beta_cycle_row(*args, **kwargs):
    from callback_router import format_beta_cycle_row as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def build_beta_monitor_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Últimas 24h", callback_data="admin_beta_monitor_24h")],
        [InlineKeyboardButton("Críticos", callback_data="admin_beta_monitor_critical")],
        [InlineKeyboardButton("Warnings", callback_data="admin_beta_monitor_warning")],
        [InlineKeyboardButton("Pagos/accesos", callback_data="admin_beta_monitor_payments")],
        [InlineKeyboardButton("Códigos", callback_data="admin_beta_monitor_codes")],
        [InlineKeyboardButton("Backups", callback_data="admin_beta_monitor_backups")],
        [InlineKeyboardButton("🗓 Ciclo beta", callback_data="admin_beta_cycle")],
        [InlineKeyboardButton("▶️ Iniciar beta 1 semana", callback_data="admin_beta_cycle_start_beta_1")],
        [InlineKeyboardButton("🔁 Iniciar beta 2.0", callback_data="admin_beta_cycle_start_beta_2")],
        [InlineKeyboardButton("✅ Finalizar beta", callback_data="admin_beta_cycle_finish")],
        [InlineKeyboardButton("📋 Ver estado beta", callback_data="admin_beta_cycle_status")],
        [InlineKeyboardButton("🚀 Preparar lanzamiento final", callback_data="admin_beta_cycle_final_review")],
        # A LA CONFIRMACIÓN, NO A LA ACCIÓN. Este teclado se reutiliza en TODAS
        # las pantallas del monitor y este botón vive una fila encima de
        # «Volver»: cerraba 24 h de eventos —accesos no autorizados, fallos de
        # enlaces— de un toque y sin dejar constancia de quién lo hizo.
        [InlineKeyboardButton(
            "✔️ Marcar resueltos…",
            callback_data="admin_beta_monitor_resolve_ask"
        )],
        [InlineKeyboardButton("⬅️ Volver", callback_data="admin_back_main")]
    ])


# CUÁNTOS DE CUÁNTOS. Esta pantalla se traía 50 eventos, pintaba 30 y luego
# cortaba el texto a 3900 caracteres a pelo: el último evento salía partido a
# mitad de palabra y no había una sola señal de que faltaba nada. Quien la mira
# está buscando la avería de hoy, y creía estar viendo TODO lo que hay.
#
# Ahora se dice el recuento y se corta por evento entero, nunca por la mitad.
MAXIMO_EVENTOS_EN_PANTALLA = 30

# El límite de Telegram es 4096; se deja aire para la nota del final.
MAXIMO_CARACTERES = 3700


def format_beta_monitor_events_text(title, rows):

    if not rows:

        return f"{title}\n\nSin eventos registrados."


    total = len(rows)

    text = f"{title}\n\n"

    pintados = 0
    cortado_por_tamano = False


    for (
        event_id,
        created_at,
        event_type,
        severity,
        event_user_id,
        event_group_id,
        event_telegram_group_id,
        message,
        resolved
    ) in rows[:MAXIMO_EVENTOS_EN_PANTALLA]:

        status = "resuelto" if resolved else "pendiente"

        bloque = (
            f"#{event_id} · {event_type or '-'} · {severity or '-'} · {status}\n"
            f"Usuario: {event_user_id or '-'}\n"
            f"Grupo: {event_group_id or '-'} / {event_telegram_group_id or '-'}\n"
            f"Detalle: {message or '-'}\n"
            f"Fecha: {created_at or '-'}\n\n"
        )

        if len(text) + len(bloque) > MAXIMO_CARACTERES:

            cortado_por_tamano = True
            break

        text += bloque
        pintados += 1


    if pintados < total:

        text += (
            f"— Se enseñan {pintados} de {total}"
            + (" (no cabían más)" if cortado_por_tamano else "")
            + ". Filtra por gravedad o por tipo para ver el resto.\n"
        )


    return text


def format_beta_cycle_status_text():

    active_cycle = get_active_beta_cycle()
    latest_cycle = active_cycle or get_latest_beta_cycle()
    counts = get_beta_cycle_monitor_counts(hours=24)

    lines = [
        "🗓 Ciclo beta",
        "",
        format_beta_cycle_row(latest_cycle),
        "",
        "📊 Estado últimas 24h",
        f"Críticos abiertos: {counts.get('critical_open', 0)}",
        f"Warnings abiertos: {counts.get('warning_open', 0)}",
        f"Pagos: {counts.get('payments', 0)}",
        f"Accesos permitidos: {counts.get('access_allowed', 0)}",
        f"Códigos canjeados: {counts.get('codes', 0)}",
        f"Backups fallidos: {counts.get('backup_failed', 0)}",
        f"Tickets soporte: {counts.get('support_tickets', 0)}"
    ]

    return "\n".join(lines)


def format_final_launch_checklist():

    return (
        "🚀 Preparar lanzamiento final\n\n"
        "Antes de abrir comercialmente, revisa:\n\n"
        "☐ Bugs P0 cerrados\n"
        "☐ Bugs P1 cerrados o aceptados\n"
        "☐ Smoke test OK\n"
        "☐ Railway estable\n"
        "☐ Stripe probado\n"
        "☐ Backups probados\n"
        "☐ Soporte probado\n"
        "☐ Logs limpios\n\n"
        "Este checklist no cambia pagos, grupos ni datos de usuarios."
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_admin_beta_callbacks(update, context, query, user_id, data):

    if data.startswith("admin_beta_cycle"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data in (
            "admin_beta_cycle",
            "admin_beta_cycle_status"
        ):

            await query.message.reply_text(
                format_beta_cycle_status_text(),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data in (
            "admin_beta_cycle_start_beta_1",
            "admin_beta_cycle_start_beta_2"
        ):

            complete_expired_beta_cycles()

            phase = (
                "beta_2"
                if data == "admin_beta_cycle_start_beta_2"
                else "beta_1"
            )

            cycle, active_cycle = create_beta_cycle(
                created_by=user_id,
                phase=phase,
                duration_days=7
            )

            if active_cycle:

                await query.message.reply_text(
                    (
                        "⚠️ Ya hay un ciclo beta activo.\n\n"
                        f"{format_beta_cycle_row(active_cycle)}"
                    ),
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            if not cycle:

                await query.message.reply_text(
                    "⚠️ No se pudo iniciar el ciclo beta.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            phase_label = "Beta 2.0" if phase == "beta_2" else "Beta cerrada"

            log_event(
                "beta_cycle_started",
                category="beta",
                severity="info",
                message=f"{phase_label} iniciada",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": phase,
                    "ends_at": str(cycle[5])
                }
            )

            await query.message.reply_text(
                (
                    f"✅ {phase_label} iniciada hasta {cycle[5]}.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_finish":

            cycle = complete_active_beta_cycle(
                notes="Finalizada manualmente desde el panel beta."
            )

            if not cycle:

                await query.message.reply_text(
                    "⚠️ No hay una beta activa para finalizar.",
                    reply_markup=build_beta_monitor_keyboard()
                )

                return


            log_event(
                "beta_cycle_completed",
                category="beta",
                severity="info",
                message="Ciclo beta finalizado manualmente",
                actor_user_id=user_id,
                metadata={
                    "cycle_id": cycle[0],
                    "phase": cycle[3]
                }
            )

            await query.message.reply_text(
                (
                    "✅ Beta finalizada.\n\n"
                    f"{format_beta_cycle_row(cycle)}"
                ),
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        if data == "admin_beta_cycle_final_review":

            await query.message.reply_text(
                format_final_launch_checklist(),
                reply_markup=build_beta_monitor_keyboard()
            )

            return

    if data.startswith("admin_beta_monitor"):

        if not is_super_admin(user_id):

            await query.message.reply_text(
                "⛔ Esta acción solo está disponible para el propietario principal."
            )

            return


        if data == "admin_beta_monitor_resolve_ask":

            pendientes = contar_eventos_sin_resolver(hours=24)

            await query.message.reply_text(
                f"⚠️ Vas a marcar como resueltos {pendientes} evento(s) de las "
                "últimas 24 horas.\n\n"
                "Ahí dentro puede haber accesos no autorizados o fallos de "
                "entrega de enlaces. Después ya no aparecen en el monitor, y "
                "esto no se deshace.\n\n"
                "¿Seguro?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"🔴 Sí, marcar los {pendientes}",
                        callback_data="admin_beta_monitor_resolve_all"
                    )],
                    [InlineKeyboardButton(
                        "⬅️ No, volver al monitor",
                        callback_data="admin_beta_monitor_24h"
                    )],
                ])
            )

            return


        if data == "admin_beta_monitor_resolve_all":

            affected = mark_beta_monitor_events_resolved(hours=24)

            log_event(
                "beta_monitor_events_resolved",
                category="admin",
                severity="warning",
                scope="global",
                actor_user_id=user_id,
                message="Eventos del monitor marcados como resueltos en bloque.",
                metadata={"horas": 24, "afectados": int(affected or 0)},
            )

            await query.message.reply_text(
                f"✅ Eventos marcados como resueltos: {affected}",
                reply_markup=build_beta_monitor_keyboard()
            )

            return


        title = "📊 Monitor beta"
        severity = None
        event_types = None


        if data == "admin_beta_monitor_critical":

            title = "🚨 Monitor beta · Críticos"
            severity = "critical"

        elif data == "admin_beta_monitor_warning":

            title = "⚠️ Monitor beta · Warnings"
            severity = "warning"

        elif data == "admin_beta_monitor_payments":

            title = "💳 Monitor beta · Pagos/accesos"
            event_types = [
                "payment_confirmed",
                "payment_failed",
                "invite_link_created",
                "invite_link_failed",
                "access_allowed",
                "unauthorized_access"
            ]

        elif data == "admin_beta_monitor_codes":

            title = "🎟 Monitor beta · Códigos"
            event_types = [
                "group_code_redeemed",
                "group_code_failed"
            ]

        elif data == "admin_beta_monitor_backups":

            title = "🛡 Monitor beta · Backups"
            event_types = [
                "backup_message_failed",
                "backup_permission_error"
            ]


        if data == "admin_beta_monitor":

            text = summarize_beta_monitor_events(hours=6)

        else:

            rows = list_beta_monitor_events(
                hours=24,
                severity=severity,
                event_types=event_types,
                limit=50
            )
            text = format_beta_monitor_events_text(
                title,
                rows
            )


        await query.message.reply_text(
            text,
            reply_markup=build_beta_monitor_keyboard()
        )

        return

    return NOT_HANDLED
