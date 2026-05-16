from datetime import datetime


# =========================
# FORMATTERS — USERS
# =========================

def format_user_display(user_id=None, username=None, first_name=None):

    parts = []


    if first_name:

        parts.append(str(first_name))


    if username:

        username = str(username)

        if not username.startswith("@"):

            username = "@" + username

        parts.append(username)


    if user_id is not None:

        parts.append(f"ID: {user_id}")


    if not parts:

        return "Usuario desconocido"


    return " | ".join(parts)


# =========================
# FORMATTERS — DATES
# =========================

def format_datetime(value):

    if value is None:

        return "Sin caducidad"


    if isinstance(value, str):

        return value


    try:

        return value.strftime("%d/%m/%Y %H:%M")

    except Exception:

        return str(value)


# =========================
# FORMATTERS — REMAINING TIME
# =========================

def format_tiempo_restante(expiration):

    if expiration is None:

        return "♾️ Permanente"


    tiempo_restante = expiration - datetime.now()

    total_segundos = int(
        tiempo_restante.total_seconds()
    )

    if total_segundos <= 0:

        return "Expirado"


    dias = total_segundos // 86400

    horas = (

        total_segundos % 86400

    ) // 3600

    minutos = (

        total_segundos % 3600

    ) // 60


    # Protección contra mostrar 0m cuando aún quedan segundos

    if dias == 0 and horas == 0 and minutos == 0:

        minutos = 1


    # Mostrar SIEMPRE días, horas y minutos

    return (

        f"{dias}d "

        f"{horas}h "

        f"{minutos}m"

    )


# =========================
# FORMATTERS — SUBSCRIPTION
# =========================

def format_subscription_line(user_id, group_id, expiration, username=None, first_name=None):

    user_text = format_user_display(
        user_id=user_id,
        username=username,
        first_name=first_name
    )

    expiration_text = format_datetime(
        expiration
    )


    return f"👤 {user_text}\n📌 Grupo: {group_id}\n⏳ Caduca: {expiration_text}"


# =========================
# FORMATTERS — GROUPS
# =========================

def format_group_line(group_id, name, telegram_group_id):

    return f"📌 {name}\nID interno: {group_id}\nTelegram ID: {telegram_group_id}"


# =========================
# FORMATTERS — PERMISSIONS
# =========================

def format_permission_value(value):

    return "✅" if value else "❌"
