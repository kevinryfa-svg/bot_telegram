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


AI_FEEDBACK_USEFUL = "useful"
AI_FEEDBACK_NOT_USEFUL = "not_useful"
AI_FEEDBACK_PROBLEM = "problem"


FORBIDDEN_USER_FACING_TERMS = (
    "email",
    "correo",
    "bandeja de entrada",
    "spam",
    "inbox",
    "transferencia bancaria",
    "transferencias bancarias",
    "bitcoin",
    "ethereum",
    "suelen incluir",
    "normalmente puedes pagar"
)


DETERMINISTIC_INTENTS = (
    AI_INTENT_ACCESS_RECOVERY,
    AI_INTENT_PAYMENT_HELP,
    AI_INTENT_PAYMENT_PROVIDER_SETUP
)


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

    rating_map = {
        "up": (AI_FEEDBACK_USEFUL, True),
        "useful": (AI_FEEDBACK_USEFUL, True),
        "down": (AI_FEEDBACK_NOT_USEFUL, False),
        "not_useful": (AI_FEEDBACK_NOT_USEFUL, False),
        "report": (AI_FEEDBACK_PROBLEM, False),
        "problem": (AI_FEEDBACK_PROBLEM, False)
    }

    if rating not in rating_map:
        return False

    stored_rating, success = rating_map[rating]

    try:
        with conn.cursor() as cur:
            cur.execute("""

                UPDATE ai_interactions
                SET feedback_rating=%s,
                    success=%s
                WHERE id=%s
                RETURNING id

            """, (
                stored_rating,
                success,
                interaction_id
            ))
            row = cur.fetchone()

        conn.commit()

        return bool(row)

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print("ai_feedback_update_error:", str(exc)[:200])
        return False


def get_ai_interaction_feedback_context(interaction_id):

    try:
        with conn.cursor() as cur:
            cur.execute("""

                SELECT id, role, group_id, intent, feedback_rating
                FROM ai_interactions
                WHERE id=%s
                LIMIT 1

            """, (interaction_id,))
            row = cur.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "role": row[1],
            "group_id": row[2],
            "intent": row[3],
            "feedback_rating": row[4]
        }

    except Exception as exc:
        print("ai_feedback_context_error:", str(exc)[:200])
        return None


def build_ai_feedback_keyboard_rows(interaction_id):

    if not interaction_id:
        return []

    return [
        ("👍 Útil", f"ai_feedback_{interaction_id}_up"),
        ("👎 No útil", f"ai_feedback_{interaction_id}_down"),
        ("📝 Reportar problema", f"ai_feedback_{interaction_id}_report")
    ]


def response_has_forbidden_content(answer):

    text = str(answer or "").lower()

    return any(term in text for term in FORBIDDEN_USER_FACING_TERMS)


def build_payment_methods_answer(group_id=None, payment_methods=None):

    payment_methods = payment_methods or {}
    active_methods = payment_methods.get("active") or []

    if group_id:
        if active_methods:
            return (
                "Esta comunidad acepta solo los métodos que aparecen activos en el bot ahora mismo:\n\n"
                + "\n".join(f"- {method}" for method in active_methods)
                + "\n\nAl abrir un plan concreto, el bot mostrará únicamente los métodos disponibles para ese grupo."
            )

        return (
            "No veo métodos de pago activos para esta comunidad en el contexto seguro disponible.\n\n"
            "Abre el plan concreto desde el bot: ahí se muestran solo los métodos realmente disponibles. "
            "Si esperabas ver un método, el owner debe revisarlo en Métodos de pago del grupo."
        )

    return (
        "Depende de la comunidad.\n\n"
        "En este bot los métodos soportados son:\n"
        "- Stripe\n"
        "- PayPal\n"
        "- Revolut\n"
        "- ChangeNOW.io / Cripto\n"
        "- Guardarian / Tarjeta EUR → USDT\n"
        "- Códigos y promociones\n\n"
        "Cada propietario decide cuáles activa en su comunidad. Al abrir un plan concreto, el bot te mostrará solo los métodos disponibles para ese grupo."
    )


def build_rule_based_response(intent, role, context_key, group_id=None, question=None, payment_methods=None):

    question_text = str(question or "").lower()

    if "eur" in question_text and "usdt" in question_text or "guardarian" in question_text:
        return (
            "En este bot, EUR → USDT se refiere a Guardarian.\n\n"
            "El comprador paga con tarjeta en euros y el propietario recibe USDT en la wallet configurada. "
            "El acceso solo se activa automáticamente cuando Guardarian confirma el pago con estado finished. "
            "Algunos pagos pueden requerir verificación KYC/AML."
        )

    if "changenow" in question_text:
        return (
            "ChangeNOW es el método de pago cripto/intercambio dentro del bot.\n\n"
            "Puede permitir pagos cripto si el propietario lo tiene configurado. "
            "Según la configuración actual, algunos pagos pueden quedar en revisión manual antes de activar el acceso."
        )

    if (
        "cómo puedo pagar" in question_text
        or "como puedo pagar" in question_text
        or "qué métodos acepta" in question_text
        or "que métodos acepta" in question_text
        or "que metodos acepta" in question_text
        or (
            role == AI_ROLE_BUYER
            and intent == AI_INTENT_PAYMENT_PROVIDER_SETUP
            and "configur" not in question_text
        )
    ):
        return build_payment_methods_answer(group_id=group_id, payment_methods=payment_methods)

    if intent == AI_INTENT_ACCESS_RECOVERY:
        return (
            "Si ya pagaste y no recibiste el enlace, revisa primero Mis suscripciones dentro del bot.\n\n"
            "Pasos:\n"
            "1. Entra en Mis suscripciones.\n"
            "2. Comprueba si tu acceso aparece activo.\n"
            "3. Si aparece activo, usa la opción de recuperar o reenviar enlace.\n"
            "4. Si el pago está pendiente, espera la confirmación del proveedor.\n"
            "5. Si aparece pagado pero no recibes enlace, abre soporte desde el bot para que revisemos tu acceso.\n\n"
            "No se entrega acceso por canales externos: todo se revisa desde el bot."
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
        return build_payment_methods_answer(group_id=group_id, payment_methods=payment_methods)

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
    prefer_model=True,
    history=None
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
        group_id=group_id,
        question=question,
        payment_methods=context_data.get("payment_methods")
    )
    ok = False
    answer = fallback

    use_model = prefer_model and intent not in DETERMINISTIC_INTENTS

    if use_model:
        ok, model_answer = generate_ai_response(
            question,
            system_prompt=policy_prompt,
            context_text=context_text,
            history=history
        )

        if ok and model_answer:
            answer = model_answer

    if response_has_forbidden_content(answer):
        ok = False
        answer = fallback

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
