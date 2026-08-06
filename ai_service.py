import os


# =========================
# AI SERVICE — CONFIG
# =========================

AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Límite de la respuesta. Telegram corta en ~4096 caracteres, así que una
# respuesta acotada llega entera en un solo mensaje y cuesta menos.
AI_MAX_TOKENS = int(
    os.environ.get("AI_MAX_TOKENS", "700")
)

# Sin timeout, una llamada colgada bloquea la respuesta al usuario.
AI_TIMEOUT_SECONDS = float(
    os.environ.get("AI_TIMEOUT_SECONDS", "30")
)

# Un fallo puntual de la API no debe traducirse en "error" para el usuario.
AI_MAX_ATTEMPTS = int(
    os.environ.get("AI_MAX_ATTEMPTS", "2")
)

# Turnos de conversación que recuerda el asistente (pares pregunta/respuesta).
AI_HISTORY_TURNS = int(
    os.environ.get("AI_HISTORY_TURNS", "6")
)

# Tope de la pregunta: evita que un texto pegado enorme dispare el coste.
AI_MAX_QUESTION_CHARS = int(
    os.environ.get("AI_MAX_QUESTION_CHARS", "1500")
)

AI_TEMPERATURE = float(
    os.environ.get("AI_TEMPERATURE", "0.4")
)


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
        "Eres un asistente integrado dentro de un bot de Telegram para gestionar "
        "grupos privados, accesos, suscripciones, pagos, links, soporte, manuales, "
        "roles, administradores y configuración del sistema. "
        "Solo puedes responder preguntas relacionadas con este bot, su funcionamiento, "
        "sus comandos, sus grupos, suscripciones, accesos, incidencias, soporte, IA interna "
        "o configuración. "
        "Si el usuario pregunta algo que no esté relacionado con el bot o la gestión de grupos, "
        "debes rechazarlo de forma breve y amable diciendo que solo puedes ayudar con temas "
        "relacionados con el bot. "
        "No inventes datos del sistema. "
        "No inventes comandos. "
        "Solo puedes mencionar comandos que aparezcan explícitamente en el contexto disponible. "
        "Si el usuario pide todos los comandos y no tienes una lista completa en el contexto, "
        "debes decir que solo puedes mostrar los comandos documentados actualmente en el manual. "
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

def sanitize_history(history):
    """
    Deja el historial en turnos válidos y acotados. Solo se aceptan mensajes
    de usuario y asistente: el contexto y las reglas van siempre en los
    mensajes de sistema que construimos nosotros, nunca desde el historial.
    """

    if not history:

        return []


    clean = []

    for item in history:

        if not isinstance(item, dict):

            continue


        role = item.get("role")
        content = item.get("content")

        if role not in ("user", "assistant"):

            continue


        if not content:

            continue


        clean.append({
            "role": role,
            "content": str(content)[:AI_MAX_QUESTION_CHARS]
        })


    if AI_HISTORY_TURNS > 0:

        clean = clean[-AI_HISTORY_TURNS:]


    return clean


def build_ai_messages(user_text, system_prompt=None, context_text=None, history=None):

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


    # Conversación previa: sin esto el asistente no entiende preguntas de
    # seguimiento como "¿y el de 30 días?" o "¿cuánto cuesta ese?".
    messages.extend(
        sanitize_history(history)
    )


    messages.append({
        "role": "user",
        "content": str(user_text or "")[:AI_MAX_QUESTION_CHARS]
    })


    return messages


# =========================
# AI SERVICE — RESPUESTA DEL MODELO
# =========================

def generate_ai_response(user_text, system_prompt=None, context_text=None, history=None):

    if not is_ai_enabled():

        return (
            False,
            "⚠️ La IA todavía no está configurada. Falta OPENAI_API_KEY."
        )


    messages = build_ai_messages(
        user_text,
        system_prompt=system_prompt,
        context_text=context_text,
        history=history
    )

    last_error = None


    for attempt in range(1, max(AI_MAX_ATTEMPTS, 1) + 1):

        try:

            from openai import OpenAI

            client = OpenAI(
                api_key=OPENAI_API_KEY,
                timeout=AI_TIMEOUT_SECONDS
            )

            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=messages,
                temperature=AI_TEMPERATURE,
                max_tokens=AI_MAX_TOKENS
            )

            text = response.choices[0].message.content


            if text and text.strip():

                return True, text


            last_error = "respuesta vacía del modelo"

        except Exception as e:

            last_error = f"{type(e).__name__}: {e}"

            print(
                "Error generando respuesta IA "
                f"(intento {attempt}/{max(AI_MAX_ATTEMPTS, 1)}):",
                type(e).__name__,
                str(e)[:300]
            )


    print(
        "IA: no se pudo generar respuesta.",
        str(last_error)[:300]
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
