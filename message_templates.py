# =========================
# MESSAGE TEMPLATES — GROUP REGISTRATION
# =========================

def bot_needs_admin_permissions_text():

    return (
        "⚠️ Necesito permisos de administrador.\n\n"
        "Por favor asígnamelos en los próximos 30 segundos.\n\n"
        "Si no, abandonaré el grupo automáticamente."
    )



def bot_leaving_group_text():

    return (
        "⚠️ No tengo permisos de administrador.\n\n"
        "Saldré del grupo en este momento."
    )



def admin_bot_leaving_group_text(group_name, group_id):

    return (
        "⚠️ BOT SALIENDO DEL GRUPO\n\n"
        f"Grupo: {group_name}\n"
        f"ID: {group_id}\n\n"
        "No fue asignado como administrador."
    )



def admin_new_group_registered_text(group_name, group_id):

    return (
        "✅ NUEVO GRUPO DETECTADO\n\n"
        f"Nombre: {group_name}\n"
        f"ID: {group_id}\n\n"
        "Grupo registrado correctamente."
    )



def admin_bot_added_by_unauthorized_user_text(group_name, group_id, added_by):

    return (
        "⚠️ BOT AÑADIDO POR USUARIO NO AUTORIZADO\n\n"
        f"Grupo: {group_name}\n"
        f"ID: {group_id}\n"
        f"Usuario: {added_by}\n\n"
        "El grupo será registrado igualmente."
    )


# =========================
# MESSAGE TEMPLATES — EXPIRATIONS
# =========================

def admin_user_expired_removed_text(user_id, group_id):

    return (
        "⛔ Usuario expirado eliminado\n\n"
        f"User ID: {user_id}\n"
        f"Grupo ID: {group_id}"
    )


# =========================
# MESSAGE TEMPLATES — WARNINGS / BANS
# =========================

def user_permanent_ban_shared_links_text():

    return (
        "⛔ Has sido baneado permanentemente.\n\n"
        "Motivo: Compartir links repetidamente."
    )



def admin_user_banned_warnings_text(user_id, warnings):

    return (
        "⛔ USUARIO BANEADO\n\n"
        f"User ID: {user_id}\n"
        f"Motivo: {warnings}/3 advertencias."
    )



def user_shared_link_warning_text(warnings, new_link):

    return (
        f"⚠️ AVISO {warnings}/3\n\n"
        "Hemos detectado que has compartido tu link.\n\n"
        "Tu link anterior ha sido invalidado.\n"
        "Aquí tienes uno nuevo:\n\n"
        f"{new_link}\n\n"
        "Si llegas a 3 avisos serás baneado."
    )



def admin_shared_link_warning_text(owner_id, warnings, intruder_id):

    return (
        "⚠️ LINK COMPARTIDO\n\n"
        f"Usuario: {owner_id}\n"
        f"Aviso: {warnings}/3\n"
        f"Intruso: {intruder_id}"
    )


# =========================
# MESSAGE TEMPLATES — ACCESS REVIEW
# =========================

def unauthorized_access_detected_text(first_name, username, user_id):

    username_text = username if username else "Sin username"

    if username_text != "Sin username" and not str(username_text).startswith("@"):

        username_text = f"@{username_text}"


    return (
        "🚨 ACCESO NO AUTORIZADO DETECTADO\n\n"
        f"Usuario: {first_name}\n"
        f"Username: {username_text}\n"
        f"ID: {user_id}\n\n"
        "Ha entrado con un link no registrado.\n\n"
        "¿Deseas permitirlo o expulsarlo?"
    )
