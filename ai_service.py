import os


# =========================
# AI SERVICE — CONFIG
# =========================

AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# =========================
# AI SERVICE — AVAILABILITY
# =========================

def is_ai_enabled():

    return bool(
        OPENAI_API_KEY
    )


# =========================
# AI SERVICE — SYSTEM PROMPTS
# =========================

def build_default_system_prompt():

    return (
        "Eres un asistente integrado dentro de un bot de Telegram. "
        "Responde de forma clara, útil y breve. "
        "No inventes datos del sistema. "
        "Si falta información, pide el dato necesario."
    )



def build_admin_system_prompt():

    return (
        "Eres un asistente administrativo para el propietario de un bot de Telegram. "
        "Ayudas a revisar grupos, usuarios, suscripciones, incidencias y configuración. "
        "Prioriza seguridad, claridad y acciones reversibles. "
        "No ejecutes acciones críticas sin confirmación explícita."
    )



def build_group_owner_system_prompt(group_name=None):

    if group_name:

        return (
            "Eres un asistente para el dueño de un grupo de Telegram. "
            f"El grupo se llama: {group_name}. "
            "Ayudas a gestionar comunidad, normas, mensajes, suscripciones y soporte. "
            "Responde de forma profesional y práctica."
        )


    return (
        "Eres un asistente para el dueño de un grupo de Telegram. "
        "Ayudas a gestionar comunidad, normas, mensajes, suscripciones y soporte. "
        "Responde de forma profesional y práctica."
    )



def build_user_system_prompt(group_name=None):

    if group_name:

        return (
            "Eres un asistente para un usuario dentro de un grupo privado de Telegram. "
            f"El grupo se llama: {group_name}. "
            "Ayuda con dudas generales, normas del grupo y acceso, sin revelar datos privados."
        )


    return (
        "Eres un asistente para un usuario dentro de un grupo privado de Telegram. "
        "Ayuda con dudas generales, normas del grupo y acceso, sin revelar datos privados."
    )


# =========================
# AI SERVICE — REQUEST BUILDER
# =========================

def build_ai_messages(user_text, system_prompt=None, context_text=None):

    messages = [
        {
            "role": "system",
            "content": system_prompt or build_default_system_prompt()
        }
    ]


    if context_text:

        messages.append({
            "role": "system",
            "content": f"Contexto disponible:\n{context_text}"
        })


    messages.append({
        "role": "user",
        "content": user_text
    })


    return messages


# =========================
# AI SERVICE — RESPONSE PLACEHOLDER
# =========================

def generate_ai_response(user_text, system_prompt=None, context_text=None):

    if not is_ai_enabled():

        return (
            False,
            "⚠️ La IA todavía no está configurada. Falta OPENAI_API_KEY."
        )


    try:

        from openai import OpenAI

        client = OpenAI(
            api_key=OPENAI_API_KEY
        )

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=build_ai_messages(
                user_text,
                system_prompt=system_prompt,
                context_text=context_text
            ),
            temperature=0.4
        )

        text = response.choices[0].message.content

        return True, text

    except Exception as e:

        print(
            "Error generando respuesta IA:",
            e
        )

        return (
            False,
            "❌ Error generando respuesta con IA."
        )


# =========================
# AI SERVICE — SCOPES
# =========================

def get_ai_scope_for_role(role):

    role = str(role or "").strip().lower()


    if role in ["admin", "super_admin"]:

        return "admin"


    if role in ["group_owner", "owner"]:

        return "group_owner"


    if role in ["user", "member"]:

        return "user"


    return "default"



def build_system_prompt_for_scope(scope, group_name=None):

    scope = str(scope or "").strip().lower()


    if scope == "admin":

        return build_admin_system_prompt()


    if scope == "group_owner":

        return build_group_owner_system_prompt(
            group_name=group_name
        )


    if scope == "user":

        return build_user_system_prompt(
            group_name=group_name
        )


    return build_default_system_prompt()
