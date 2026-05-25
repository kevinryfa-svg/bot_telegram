from ai_policy import AI_CONTEXT_SUPPORT_TICKET
from ai_response_service import build_contextual_ai_answer


def build_support_reply_suggestion(user_id, role, ticket_id, group_id=None):

    question = (
        "Resume este ticket de soporte, detecta el tipo de problema y prepara un borrador "
        "de respuesta amable. No envíes nada automáticamente. Si faltan datos, pide la "
        "información mínima necesaria."
    )

    return build_contextual_ai_answer(
        user_id=user_id,
        question=question,
        role=role,
        context_key=AI_CONTEXT_SUPPORT_TICKET,
        group_id=group_id,
        support_ticket_id=ticket_id
    )
