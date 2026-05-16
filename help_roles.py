# =========================
# HELP ROLES — USER TYPES
# =========================

ROLE_PUBLIC_BUYER = "public_buyer"
ROLE_GROUP_MEMBER = "group_member"
ROLE_GROUP_ADMIN = "group_admin"
ROLE_GROUP_OWNER_SHARED = "group_owner_shared"
ROLE_GROUP_OWNER_EXCLUSIVE = "group_owner_exclusive"
ROLE_EXCLUSIVE_GROUP_ADMIN = "exclusive_group_admin"
ROLE_SUPER_ADMIN = "super_admin"


# =========================
# HELP ROLES — LABELS
# =========================

ROLE_LABELS = {

    ROLE_PUBLIC_BUYER: {
        "es": "Usuario que quiere comprar una suscripción",
        "en": "User who wants to buy a subscription"
    },

    ROLE_GROUP_MEMBER: {
        "es": "Usuario suscrito a un grupo",
        "en": "Subscribed group user"
    },

    ROLE_GROUP_ADMIN: {
        "es": "Admin de grupo",
        "en": "Group admin"
    },

    ROLE_GROUP_OWNER_SHARED: {
        "es": "Dueño de grupo en bot compartido",
        "en": "Group owner on shared bot"
    },

    ROLE_GROUP_OWNER_EXCLUSIVE: {
        "es": "Dueño con bot exclusivo",
        "en": "Owner with exclusive bot"
    },

    ROLE_EXCLUSIVE_GROUP_ADMIN: {
        "es": "Admin de grupo en bot exclusivo",
        "en": "Group admin on exclusive bot"
    },

    ROLE_SUPER_ADMIN: {
        "es": "Super admin del sistema",
        "en": "System super admin"
    }
}


# =========================
# HELP ROLES — HELPERS
# =========================

def normalize_help_role(role):

    role = str(role or "").strip().lower()

    valid_roles = set(ROLE_LABELS.keys())

    if role in valid_roles:

        return role


    return ROLE_PUBLIC_BUYER



def get_role_label(role, language="es"):

    role = normalize_help_role(role)
    language = str(language or "es").strip().lower()

    labels = ROLE_LABELS.get(role, {})

    return labels.get(
        language,
        labels.get("es", role)
    )



def list_help_roles():

    return list(ROLE_LABELS.keys())
