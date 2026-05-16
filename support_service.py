from datetime import datetime

from db import conn


# =========================
# SUPPORT SERVICE — ISSUE TYPES
# =========================

SUPPORT_NO_LINK = "no_link"
SUPPORT_LINK_NOT_WORKING = "link_not_working"
SUPPORT_PAID_NO_ACCESS = "paid_no_access"
SUPPORT_RENEWAL_HELP = "renewal_help"
SUPPORT_OTHER = "other"


SUPPORT_ISSUE_LABELS = {

    SUPPORT_NO_LINK: "No recibí el link",
    SUPPORT_LINK_NOT_WORKING: "Mi link no funciona",
    SUPPORT_PAID_NO_ACCESS: "He pagado y no tengo acceso",
    SUPPORT_RENEWAL_HELP: "Quiero renovar",
    SUPPORT_OTHER: "Otro problema"
}


# =========================
# SUPPORT SERVICE — HELPERS
# =========================

def normalize_support_issue(issue_type):

    issue_type = str(issue_type or "").strip().lower()

    if issue_type in SUPPORT_ISSUE_LABELS:

        return issue_type


    return SUPPORT_OTHER



def get_support_issue_label(issue_type):

    issue_type = normalize_support_issue(issue_type)

    return SUPPORT_ISSUE_LABELS.get(
        issue_type,
        SUPPORT_ISSUE_LABELS[SUPPORT_OTHER]
    )



def build_support_intro_text():

    return (
        "🆘 Soporte\n\n"
        "Elige el problema que tienes y te ayudaremos paso a paso."
    )



def build_support_issue_text(issue_type):

    issue_type = normalize_support_issue(issue_type)
    label = get_support_issue_label(issue_type)

    if issue_type == SUPPORT_NO_LINK:

        return (
            f"🆘 {label}\n\n"
            "Primero revisa si el pago se completó correctamente.\n"
            "Si el pago fue correcto, usa la opción de recuperar acceso."
        )


    if issue_type == SUPPORT_LINK_NOT_WORKING:

        return (
            f"🆘 {label}\n\n"
            "Los links suelen ser de un solo uso o pueden caducar.\n"
            "Puedes solicitar un nuevo acceso desde Mi cuenta."
        )


    if issue_type == SUPPORT_PAID_NO_ACCESS:

        return (
            f"🆘 {label}\n\n"
            "Si has pagado y no recibiste acceso, necesitamos revisar tu caso.\n"
            "Pulsa en contactar soporte para avisar al administrador."
        )


    if issue_type == SUPPORT_RENEWAL_HELP:

        return (
            f"🆘 {label}\n\n"
            "Puedes renovar tu suscripción desde Mi cuenta o desde el menú de compra."
        )


    return (
        f"🆘 {label}\n\n"
        "Describe tu problema para que podamos ayudarte."
    )



def build_support_admin_alert_text(user_id, issue_type, extra_text=None):

    label = get_support_issue_label(issue_type)

    text = (
        "🆘 NUEVA SOLICITUD DE SOPORTE\n\n"
        f"Usuario: {user_id}\n"
        f"Problema: {label}\n"
        f"Fecha: {datetime.now()}"
    )

    if extra_text:

        text += f"\n\nDetalle:\n{extra_text}"


    return text


# =========================
# SUPPORT SERVICE — DB PLACEHOLDER
# =========================

def create_support_ticket(user_id, issue_type, extra_text=None):

    issue_type = normalize_support_issue(issue_type)

    # De momento no escribe en DB. Queda preparado para una tabla support_tickets.

    return {
        "user_id": user_id,
        "issue_type": issue_type,
        "extra_text": extra_text,
        "created_at": datetime.now()
    }
