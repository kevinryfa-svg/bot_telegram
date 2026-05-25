import json

from db import conn
from ai_context_builder import build_ai_context
from ai_intent_router import (
    AI_INTENT_ACCESS_RECOVERY,
    AI_INTENT_DIAGNOSTICS,
    AI_INTENT_GROUP_SETUP,
    AI_INTENT_MARKETPLACE_COPY,
    AI_INTENT_PAYMENT_HELP,
    AI_INTENT_PAYMENT_PROVIDER_SETUP,
    AI_INTENT_PRICING_ADVICE,
    AI_INTENT_SUPPORT_REPLY_DRAFT,
    AI_INTENT_SURVEY_ANALYSIS,
    AI_INTENT_USER_TRACKING_SUMMARY,
    classify_ai_intent
)
from ai_policy import (
    AI_ROLE_BUYER,
    AI_ROLE_GROUP_ADMIN,
    AI_ROLE_OWNER,
    AI_ROLE_SUPERADMIN,
    build_ai_policy_prompt,
    sanitize_ai_text
)
from ai_service import generate_ai_response


def record_ai_interaction(
    user_id,
    role,
    group_id,
    intent,
    question,
    response_summary,
    source_context_summary,
    success=True
):

    try:
        with conn.cursor() as cur:
            cur.execute("""

                INSERT INTO ai_interactions
                (
                    user_id,
                    role,
                    group_id,
                    intent,
                    question,
                    response_summary,
                    source_context_summary,
                    success
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id

            """, (
                user_id,
                role,
                group_id,
                intent,
                sanitize_ai_text(question)[:1000],
                sanitize_ai_text(response_summary)[:1000],
                sanitize_ai_text(source_context_summary)[:1500],
                success
            ))

            row = cur.fetchone()

        conn.commit()

        return row[0] if row else None

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print("ai_interaction_log_error:", str(exc)[:200])
        return None


def update_ai_feedback(interaction_id, rating):

    if rating not in ("up", "down", "report"):
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""

                UPDATE ai_interactions
                SET feedback_rating=%s
                WHERE id=%s

            """, (
                rating,
                interaction_id
            ))

        conn.commit()

        return True

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print("ai_feedback_update_error:", str(exc)[:200])
        return False


def build_ai_feedback_keyboard_rows(interaction_id):

    if not interaction_id:
        return []

    return [
        ("👍 Útil", f"ai_feedback_{interaction_id}_up"),
        ("👎 No útil", f"ai_feedback_{interaction_id}_down"),
        ("📝 Reportar problema", f"ai_feedback_{interaction_id}_report")
    ]


def build_rule_based_response(intent, role, context_key, group_id=None):

    if intent == AI_INTENT_ACCESS_RECOVERY:
        return (
            "Puedo ayudarte a recuperar el acceso.\n\n"
            "Pasos:\n"
            "1. Pulsa 🏠 Inicio.\n"
            "2. Entra en 🎟 Mis accesos / recuperar.\n"
            "3. Si acabas de pagar, espera unos minutos: el link se envía cuando el proveedor confirma el pago.\n"
            "4. Si no aparece, abre 🛟 Soporte e indica comunidad, método de pago y captura si la tienes.\n\n"
            "No puedo confirmar un pago sin revisar datos reales del sistema, pero sí puedo guiarte al flujo correcto."
        )

    if intent == AI_INTENT_PAYMENT_PROVIDER_SETUP:
        return (
            "Para configurar pagos de una comunidad:\n\n"
            "1. Ve a 🏪 Mis comunidades.\n"
            "2. Abre la comunidad.\n"
            "3. Entra en 💳 Planes y pagos del grupo.\n"
            "4. Abre 💳 Métodos de pago del grupo.\n\n"
            "Métodos:\n"
            "- Stripe: tarjeta global/plataforma o configuración futura por owner.\n"
            "- PayPal: checkout real si está configurado y verificado.\n"
            "- Revolut: checkout real si está configurado y verificado.\n"
            "- ChangeNOW.io / Cripto: pago cripto/intercambio, con revisión manual.\n"
            "- Guardarian: tarjeta EUR → USDT, automático solo con status finished confirmado.\n\n"
            "No pegues secrets en soporte. Usa solo el asistente de configuración del bot."
        )

    if intent == AI_INTENT_DIAGNOSTICS and role == AI_ROLE_SUPERADMIN:
        return (
            "Diagnóstico inicial:\n\n"
            "1. Revisa 🚨 errores recientes en 🧠 Centro IA o 📜 Logs del sistema.\n"
            "2. Si es pago, comprueba provider, payment_scope, status y webhook.\n"
            "3. Si es acceso, revisa invite_links, users.subscription_active y logs de entrada.\n"
            "4. Si es callback, ejecuta 🧪 Auditoría de botones.\n\n"
            "No veo suficiente información para afirmar una causa única sin revisar el contexto concreto."
        )

    if intent == AI_INTENT_SUPPORT_REPLY_DRAFT:
        return (
            "Borrador sugerido:\n\n"
            "Hola, gracias por avisar. Vamos a revisar tu caso con los datos del ticket.\n\n"
            "Por favor, confirma la comunidad, el método de pago o código usado y adjunta captura si la tienes. "
            "Si el problema es acceso, revisaremos pago activo, link generado y posible bloqueo por ubicación o permisos.\n\n"
            "Te responderemos en cuanto esté comprobado."
        )

    if intent == AI_INTENT_SURVEY_ANALYSIS:
        return (
            "Para analizar encuestas:\n\n"
            "1. Abre 😊 Encuestas de comunidad o 😊 Satisfacción de clientes.\n"
            "2. Revisa completadas, pendientes y fallidas.\n"
            "3. Mira las preguntas con peor media y respuestas de texto recientes.\n"
            "4. Usa esos datos para ajustar precio, descripción, soporte o onboarding.\n\n"
            "No reenvíes a usuarios que ya completaron la encuesta salvo ciclo nuevo confirmado."
        )

    if intent == AI_INTENT_USER_TRACKING_SUMMARY and role == AI_ROLE_SUPERADMIN:
        return (
            "Para seguimiento de usuarios:\n\n"
            "1. Abre 👁 Seguimiento de usuarios.\n"
            "2. Busca user_id o username.\n"
            "3. Revisa últimas acciones dentro del bot, pagos, soporte, encuestas y comunidades con actividad.\n\n"
            "Telegram no permite ver grupos externos donde el bot no participa."
        )

    if intent in (AI_INTENT_PRICING_ADVICE, AI_INTENT_MARKETPLACE_COPY, AI_INTENT_GROUP_SETUP):
        return (
            "Recomendación segura:\n\n"
            "Puedo ayudarte a preparar textos, revisar estructura de planes y detectar huecos de configuración, "
            "pero no cambiaré precios ni configuración automáticamente.\n\n"
            "Ruta útil: 🏪 Mis comunidades → comunidad → ⚙️ Configuración / 🖼 Marketplace / 💳 Planes."
        )

    if intent == AI_INTENT_PAYMENT_HELP:
        return (
            "Puedes pagar con los métodos activos de cada comunidad.\n\n"
            "Verás solo métodos configurados: Tarjeta/Stripe, PayPal, Revolut, ChangeNOW o Guardarian. "
            "Guardarian significa tarjeta en EUR con liquidación USDT al owner. ChangeNOW es cripto/intercambio y puede requerir revisión manual."
        )

    return (
        "No tengo suficiente información para confirmarlo.\n\n"
        "Puedo ayudarte con pagos, accesos, comunidades, soporte, encuestas y paneles del bot. "
        "Si es un caso concreto, abre soporte o indica comunidad/método/paso donde ocurre."
    )


def build_contextual_ai_answer(
    user_id,
    question,
    role=None,
    context_key=None,
    group_id=None,
    support_ticket_id=None,
    prefer_model=True
):

    context_data = build_ai_context(
        user_id,
        role=role,
        context_key=context_key,
        group_id=group_id,
        support_ticket_id=support_ticket_id
    )
    role = context_data.get("role") or role or AI_ROLE_BUYER
    context_key = context_data.get("context_key") or context_key
    intent = classify_ai_intent(question, context_key=context_key)
    policy_prompt = build_ai_policy_prompt(role, context_key)
    context_text = (
        policy_prompt
        + "\n\nCONTEXTO SEGURO DISPONIBLE:\n"
        + context_data.get("context_text", "")
    )
    fallback = build_rule_based_response(
        intent,
        role,
        context_key,
        group_id=group_id
    )
    ok = False
    answer = fallback

    if prefer_model:
        ok, model_answer = generate_ai_response(
            question,
            system_prompt=policy_prompt,
            context_text=context_text
        )

        if ok and model_answer:
            answer = model_answer

    answer = sanitize_ai_text(answer)
    interaction_id = record_ai_interaction(
        user_id=user_id,
        role=role,
        group_id=group_id,
        intent=intent,
        question=question,
        response_summary=answer[:1000],
        source_context_summary=context_data.get("context_summary") or json.dumps({}),
        success=ok or bool(fallback)
    )

    return {
        "ok": ok,
        "answer": answer,
        "fallback_used": not ok,
        "interaction_id": interaction_id,
        "intent": intent,
        "role": role,
        "context_key": context_key
    }
