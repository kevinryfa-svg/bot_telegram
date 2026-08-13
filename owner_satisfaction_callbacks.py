"""
owner_satisfaction_callbacks: tramo extraído de callback_router.py.

Prefijos: owner_satisfaction_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

from audit_log_service import (
    log_event,
    record_beta_event,
)
from datetime import datetime
from db import conn
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message
from user_activity_logger import log_user_event_by_ids


# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_owner_panel_nav_keyboard(*args, **kwargs):
    from callback_router import build_owner_panel_nav_keyboard as impl
    return impl(*args, **kwargs)


def build_owner_satisfaction_panel_keyboard(*args, **kwargs):
    from callback_router import build_owner_satisfaction_panel_keyboard as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def normalize_customer_satisfaction_campaign_id(*args, **kwargs):
    from callback_router import normalize_customer_satisfaction_campaign_id as impl
    return impl(*args, **kwargs)


def user_has_group_permission_any(*args, **kwargs):
    from callback_router import user_has_group_permission_any as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

def get_customer_satisfaction_audience_label(audience):

    labels = {
        "global": "todos los usuarios elegibles",
        "users": "usuarios",
        "owners": "propietarios",
        "group_admins": "admins de grupo"
    }

    return labels.get(audience, audience)


def fetch_customer_satisfaction_recipients(audience, group_id=None):

    queries = []
    params = []

    group_filter_users = ""
    group_filter_admins = ""

    if group_id:
        group_filter_users = " AND group_id=%s"
        group_filter_admins = " AND group_id=%s"

    if audience in ("global", "users"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM users
            WHERE user_id IS NOT NULL
            {group_filter_users}
        """)
        if group_id:
            params.append(group_id)

    if audience in ("global", "owners"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM admins
            WHERE role='GROUP_OWNER'
            AND is_active=TRUE
            AND user_id IS NOT NULL
            {group_filter_admins}
        """)
        if group_id:
            params.append(group_id)

    if audience in ("global", "group_admins"):
        queries.append(f"""
            SELECT DISTINCT user_id
            FROM admins
            WHERE COALESCE(is_active, TRUE)=TRUE
            AND COALESCE(is_super_admin, FALSE)=FALSE
            AND COALESCE(role, '') <> 'GROUP_OWNER'
            AND user_id IS NOT NULL
            {group_filter_admins}
        """)
        if group_id:
            params.append(group_id)

    if audience == "global" and not group_id:
        queries.append("""
            SELECT DISTINCT user_id
            FROM commercial_requests
            WHERE user_id IS NOT NULL
        """)

    if not queries:
        return []

    with conn.cursor() as cur:
        cur.execute(" UNION ".join(queries), tuple(params))
        return sorted({row[0] for row in cur.fetchall() if row[0]})


def create_customer_satisfaction_survey(
    created_by,
    audience,
    group_id=None,
    send_mode="pending",
    campaign_id=None
):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:

        cur.execute("""

            INSERT INTO customer_satisfaction_surveys
            (
                title,
                description,
                audience,
                status,
                created_by,
                group_id,
                campaign_id,
                send_mode
            )
            VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
            RETURNING id

        """, (
            "Encuesta de satisfacción beta",
            "Encuesta rápida de satisfacción para mejorar el bot.",
            audience,
            created_by,
            group_id,
            campaign_id,
            send_mode
        ))

        return cur.fetchone()[0]


def fetch_customer_satisfaction_survey(survey_id):

    with conn.cursor() as cur:
        cur.execute("""

            SELECT id,
                   audience,
                   status,
                   group_id,
                   COALESCE(campaign_id, 'default'),
                   COALESCE(send_mode, 'pending')
            FROM customer_satisfaction_surveys
            WHERE id=%s
            LIMIT 1

        """, (survey_id,))
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "audience": row[1],
        "status": row[2],
        "group_id": row[3],
        "campaign_id": row[4],
        "send_mode": row[5]
    }


def fetch_customer_satisfaction_completed_user_ids(audience, group_id=None):

    with conn.cursor() as cur:
        cur.execute("""

            SELECT DISTINCT r.user_id
            FROM customer_satisfaction_responses r
            JOIN customer_satisfaction_surveys s ON s.id=r.survey_id
            WHERE r.completed_at IS NOT NULL
            AND s.audience=%s
            AND COALESCE(s.group_id, 0)=COALESCE(%s, 0)
            AND r.user_id IS NOT NULL

        """, (audience, group_id))
        return {row[0] for row in cur.fetchall() if row[0]}


def fetch_customer_satisfaction_sent_user_ids(audience, group_id=None, campaign_id=None):

    params = [audience, group_id]
    campaign_filter = ""

    if campaign_id is not None:
        campaign_filter = "AND COALESCE(cs.campaign_id, 'default')=%s"
        params.append(normalize_customer_satisfaction_campaign_id(campaign_id))

    with conn.cursor() as cur:
        cur.execute(f"""

            SELECT DISTINCT cs.user_id
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            {campaign_filter}
            AND cs.user_id IS NOT NULL

        """, tuple(params))
        return {row[0] for row in cur.fetchall() if row[0]}


def fetch_customer_satisfaction_failed_user_ids(audience, group_id=None, campaign_id=None):

    params = [audience, group_id]
    campaign_filter = ""

    if campaign_id is not None:
        campaign_filter = "AND COALESCE(cs.campaign_id, 'default')=%s"
        params.append(normalize_customer_satisfaction_campaign_id(campaign_id))

    with conn.cursor() as cur:
        cur.execute(f"""

            SELECT DISTINCT cs.user_id
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            {campaign_filter}
            AND cs.status='failed'
            AND cs.user_id IS NOT NULL

        """, tuple(params))
        return {row[0] for row in cur.fetchall() if row[0]}


def build_customer_satisfaction_targeting(audience, mode, group_id=None, campaign_id=None):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    recipients = set(fetch_customer_satisfaction_recipients(audience, group_id=group_id))
    completed_users = fetch_customer_satisfaction_completed_user_ids(audience, group_id=group_id)
    sent_current_cycle = fetch_customer_satisfaction_sent_user_ids(
        audience,
        group_id=group_id,
        campaign_id=campaign_id
    )
    sent_any_cycle = fetch_customer_satisfaction_sent_user_ids(
        audience,
        group_id=group_id,
        campaign_id=None
    )
    failed_current_cycle = fetch_customer_satisfaction_failed_user_ids(
        audience,
        group_id=group_id,
        campaign_id=campaign_id
    )

    if mode == "resend_incomplete":
        targets = (sent_current_cycle | failed_current_cycle) & recipients
        targets -= completed_users
        skipped_already_sent = 0
    elif mode == "never_sent":
        targets = recipients - completed_users - sent_any_cycle
        skipped_already_sent = len(recipients - completed_users - targets)
    else:
        targets = recipients - completed_users - sent_current_cycle
        skipped_already_sent = len(recipients - completed_users - targets)

    return {
        "recipients": sorted(recipients),
        "targets": sorted(targets),
        "completed_users": sorted(completed_users & recipients),
        "sent_current_cycle": sorted(sent_current_cycle & recipients),
        "sent_any_cycle": sorted(sent_any_cycle & recipients),
        "failed_current_cycle": sorted(failed_current_cycle & recipients),
        "total": len(recipients),
        "target_count": len(targets),
        "skipped_completed": len(completed_users & recipients),
        "skipped_already_sent": skipped_already_sent
    }


def reserve_customer_satisfaction_delivery(
    survey_id,
    user_id,
    group_id,
    campaign_id,
    created_by,
    allow_existing=False
):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:
        cur.execute("""

            INSERT INTO customer_satisfaction_sent
            (
                survey_id,
                group_id,
                user_id,
                campaign_id,
                status,
                sent_at,
                created_by,
                updated_at
            )
            VALUES (%s, %s, %s, %s, 'sent', NOW(), %s, NOW())
            ON CONFLICT (survey_id, COALESCE(group_id, 0), user_id, COALESCE(campaign_id, 'default'))
            DO NOTHING
            RETURNING id

        """, (survey_id, group_id, user_id, campaign_id, created_by))
        row = cur.fetchone()

        if row:
            return True

        if allow_existing:
            cur.execute("""

                UPDATE customer_satisfaction_sent
                SET status='sent',
                    sent_at=NOW(),
                    failed_at=NULL,
                    failure_reason=NULL,
                    updated_at=NOW()
                WHERE survey_id=%s
                AND COALESCE(group_id, 0)=COALESCE(%s, 0)
                AND user_id=%s
                AND COALESCE(campaign_id, 'default')=%s

            """, (survey_id, group_id, user_id, campaign_id))
            return True

        return False


def mark_customer_satisfaction_delivery_failed(survey_id, user_id, group_id, campaign_id, error):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    reason = str(error)[:300]

    with conn.cursor() as cur:
        cur.execute("""

            UPDATE customer_satisfaction_sent
            SET status='failed',
                failed_at=NOW(),
                failure_reason=%s,
                updated_at=NOW()
            WHERE survey_id=%s
            AND COALESCE(group_id, 0)=COALESCE(%s, 0)
            AND user_id=%s
            AND COALESCE(campaign_id, 'default')=%s

        """, (reason, survey_id, group_id, user_id, campaign_id))


def mark_customer_satisfaction_delivery_skipped(
    survey_id,
    user_id,
    group_id,
    campaign_id,
    created_by,
    status
):

    if status not in ("skipped_completed", "skipped_already_sent"):
        return

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)

    with conn.cursor() as cur:
        cur.execute("""

            INSERT INTO customer_satisfaction_sent
            (
                survey_id,
                group_id,
                user_id,
                campaign_id,
                status,
                created_by,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (survey_id, COALESCE(group_id, 0), user_id, COALESCE(campaign_id, 'default'))
            DO UPDATE SET status=EXCLUDED.status,
                          updated_at=NOW()

        """, (survey_id, group_id, user_id, campaign_id, status, created_by))


def update_customer_satisfaction_sent_counts(
    survey_id,
    sent_count,
    failed_count,
    skipped_completed_count=0,
    skipped_already_sent_count=0
):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE customer_satisfaction_surveys
            SET status='sent',
                sent_at=NOW(),
                sent_count=%s,
                failed_count=%s,
                skipped_completed_count=%s,
                skipped_already_sent_count=%s
            WHERE id=%s

        """, (
            sent_count,
            failed_count,
            skipped_completed_count,
            skipped_already_sent_count,
            survey_id
        ))


def mark_customer_satisfaction_survey_sending(survey_id):

    with conn.cursor() as cur:
        cur.execute("""

            UPDATE customer_satisfaction_surveys
            SET status='sending'
            WHERE id=%s
            AND status='draft'
            RETURNING id

        """, (survey_id,))
        return cur.fetchone() is not None


def build_customer_satisfaction_delivery_status_text(audience="global", group_id=None, campaign_id="default"):

    campaign_id = normalize_customer_satisfaction_campaign_id(campaign_id)
    targeting = build_customer_satisfaction_targeting(
        audience,
        "pending",
        group_id=group_id,
        campaign_id=campaign_id
    )

    with conn.cursor() as cur:
        cur.execute("""

            SELECT COUNT(*)
            FROM customer_satisfaction_sent cs
            JOIN customer_satisfaction_surveys s ON s.id=cs.survey_id
            WHERE s.audience=%s
            AND COALESCE(cs.group_id, 0)=COALESCE(%s, 0)
            AND COALESCE(cs.campaign_id, 'default')=%s
            AND cs.status='failed'

        """, (audience, group_id, campaign_id))
        failed_count = cur.fetchone()[0]

    scope_text = "global" if group_id is None else f"comunidad {group_id}"

    sent_without_response = len(set(targeting["sent_current_cycle"]) - set(targeting["completed_users"]))
    never_sent = len(set(targeting["recipients"]) - set(targeting["sent_any_cycle"]))

    return (
        "📊 Estado de envíos de satisfacción\n\n"
        f"Ámbito: {scope_text}\n"
        f"Audiencia: {get_customer_satisfaction_audience_label(audience)}\n"
        f"Campaña: {campaign_id}\n\n"
        f"Usuarios elegibles: {targeting['total']}\n"
        f"Completaron: {targeting['skipped_completed']}\n"
        f"Enviados sin responder: {sent_without_response}\n"
        f"Nunca enviados: {never_sent}\n"
        f"Fallidos: {failed_count}\n"
        f"Pendientes de enviar: {targeting['target_count']}\n\n"
        "Para que sea justo, el bot nunca reenvía por defecto a usuarios que ya respondieron."
    )



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


async def handle_owner_satisfaction_callbacks(update, context, query, user_id, data):

    if data in (
        "owner_satisfaction_send_pending",
        "owner_satisfaction_resend_incomplete",
        "owner_satisfaction_send_never_sent",
        "owner_satisfaction_force_new_cycle"
    ):

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para enviar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        mode_by_callback = {
            "owner_satisfaction_send_pending": "pending",
            "owner_satisfaction_resend_incomplete": "resend_incomplete",
            "owner_satisfaction_send_never_sent": "never_sent",
            "owner_satisfaction_force_new_cycle": "pending"
        }
        mode = mode_by_callback[data]
        campaign_id = "default"

        if data == "owner_satisfaction_force_new_cycle":
            campaign_id = f"group_{group_id}_cycle_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        survey_id = create_customer_satisfaction_survey(
            user_id,
            "global",
            group_id=group_id,
            send_mode=mode,
            campaign_id=campaign_id
        )
        targeting = build_customer_satisfaction_targeting(
            "global",
            mode,
            group_id=group_id,
            campaign_id=campaign_id
        )

        mode_text = {
            "pending": "Enviar a pendientes",
            "resend_incomplete": "Reenviar a no completados",
            "never_sent": "Enviar solo a nunca enviados"
        }.get(mode, mode)

        await send_clean_message(
            context,
            query.message.chat_id,
            "📤 Confirmar encuesta de comunidad\n\n"
            f"Modo: {mode_text}\n"
            f"Comunidad: {group_id}\n"
            f"Campaña: {campaign_id}\n\n"
            f"Se enviará la encuesta a {targeting['target_count']} usuarios.\n"
            f"Se omitirán {targeting['skipped_completed']} usuarios que ya la completaron.\n"
            f"Se omitirán {targeting['skipped_already_sent']} usuarios que ya la recibieron en este ciclo.\n\n"
            "¿Confirmas el envío?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar envío", callback_data=f"owner_satisfaction_confirm_{survey_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="owner_panel_satisfaction")]
            ])
        )

        return


    if data == "owner_satisfaction_delivery_status":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups", "can_view_logs"]
        )

        if not group_id:

            await query.message.reply_text(
                "⛔ No tienes permiso para ver encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )

            return

        await send_clean_message(
            context,
            query.message.chat_id,
            build_customer_satisfaction_delivery_status_text("global", group_id=group_id),
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return


    if data.startswith("owner_satisfaction_confirm_"):

        survey_id = extract_commercial_request_id(
            data,
            "owner_satisfaction_confirm_"
        )

        if survey_id is None:
            await query.message.reply_text("❌ Encuesta no válida.")
            return

        survey = fetch_customer_satisfaction_survey(survey_id)

        if not survey or not survey["group_id"]:
            await query.message.reply_text(
                "❌ Encuesta de comunidad no encontrada.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        if not user_has_group_permission_any(
            user_id,
            survey["group_id"],
            ["can_manage_groups", "can_view_logs"]
        ):
            await query.message.reply_text(
                "⛔ No tienes permiso para enviar encuestas de esta comunidad.",
                reply_markup=build_owner_panel_nav_keyboard()
            )
            return

        if survey["status"] != "draft":
            await query.message.reply_text(
                "⚠️ Esta encuesta ya fue enviada o está en proceso. No se duplicará.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        if not mark_customer_satisfaction_survey_sending(survey_id):
            await query.message.reply_text(
                "⚠️ Esta encuesta ya se está enviando o ya fue enviada. No se duplicará.",
                reply_markup=build_owner_satisfaction_panel_keyboard()
            )
            return

        targeting = build_customer_satisfaction_targeting(
            survey["audience"],
            survey["send_mode"],
            group_id=survey["group_id"],
            campaign_id=survey["campaign_id"]
        )
        sent_count = 0
        failed_count = 0

        for skipped_user_id in targeting["completed_users"]:
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_completed"
            )

        already_sent_users = set(targeting["sent_current_cycle"]) - set(targeting["targets"])
        already_sent_users -= set(targeting["completed_users"])

        for skipped_user_id in sorted(already_sent_users):
            mark_customer_satisfaction_delivery_skipped(
                survey_id,
                skipped_user_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                "skipped_already_sent"
            )

        for recipient_id in targeting["targets"]:
            reserved = reserve_customer_satisfaction_delivery(
                survey_id,
                recipient_id,
                survey["group_id"],
                survey["campaign_id"],
                user_id,
                allow_existing=survey["send_mode"] == "resend_incomplete"
            )

            if not reserved:
                continue

            try:
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=(
                        "Queremos mejorar esta comunidad. Responde esta encuesta rápida de 1 a 5.\n\n"
                        "Tus respuestas ayudan a mejorar acceso, soporte, pagos y seguridad."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Responder encuesta", callback_data=f"satisfaction_start_{survey_id}")]
                    ])
                )
                sent_count += 1
                log_user_event_by_ids(
                    recipient_id,
                    "survey_sent",
                    event_key="customer_satisfaction_group",
                    group_id=survey["group_id"],
                    metadata={
                        "survey_id": survey_id,
                        "campaign_id": survey["campaign_id"],
                        "send_mode": survey["send_mode"]
                    }
                )
            except Exception as e:
                failed_count += 1
                mark_customer_satisfaction_delivery_failed(
                    survey_id,
                    recipient_id,
                    survey["group_id"],
                    survey["campaign_id"],
                    e
                )
                log_event(
                    "survey_send_failed",
                    category="satisfaction",
                    severity="warning",
                    actor_user_id=user_id,
                    target_user_id=recipient_id,
                    group_id=survey["group_id"],
                    message="No se pudo entregar una encuesta de comunidad.",
                    metadata={"survey_id": survey_id, "error": str(e)[:200]}
                )

        update_customer_satisfaction_sent_counts(
            survey_id,
            sent_count,
            failed_count,
            targeting["skipped_completed"],
            targeting["skipped_already_sent"]
        )

        log_event(
            "survey_sent",
            category="satisfaction",
            severity="info",
            actor_user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de comunidad enviada.",
            metadata={
                "survey_id": survey_id,
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )
        record_beta_event(
            "survey_sent",
            severity="info",
            user_id=user_id,
            group_id=survey["group_id"],
            message="Encuesta de comunidad enviada.",
            metadata={
                "survey_id": survey_id,
                "campaign_id": survey["campaign_id"],
                "send_mode": survey["send_mode"],
                "sent_count": sent_count,
                "failed_count": failed_count,
                "skipped_completed": targeting["skipped_completed"],
                "skipped_already_sent": targeting["skipped_already_sent"]
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Encuesta de comunidad enviada\n\n"
            f"Enviados: {sent_count}\n"
            f"Fallidos: {failed_count}\n"
            f"Omitidos por completada: {targeting['skipped_completed']}\n"
            f"Omitidos por ya enviada: {targeting['skipped_already_sent']}",
            reply_markup=build_owner_satisfaction_panel_keyboard()
        )

        return

    return NOT_HANDLED
