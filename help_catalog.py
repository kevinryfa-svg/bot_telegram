from help_roles import (
    ROLE_PUBLIC_BUYER,
    ROLE_GROUP_MEMBER,
    ROLE_GROUP_ADMIN,
    ROLE_GROUP_OWNER_SHARED,
    ROLE_GROUP_OWNER_EXCLUSIVE,
    ROLE_EXCLUSIVE_GROUP_ADMIN,
    ROLE_SUPER_ADMIN
)


# =========================
# HELP CATALOG — SECTIONS
# =========================

SECTION_START = "start"
SECTION_SUBSCRIPTIONS = "subscriptions"
SECTION_ACCESS = "access"
SECTION_COMMANDS = "commands"
SECTION_BUTTONS = "buttons"
SECTION_AI = "ai"
SECTION_ADMIN = "admin"
SECTION_GROUP_MANAGEMENT = "group_management"
SECTION_EXCLUSIVE_BOT = "exclusive_bot"
SECTION_LANGUAGE = "language"
SECTION_SUPPORT = "support"


# =========================
# HELP CATALOG — ROLE SECTIONS
# =========================

HELP_SECTIONS_BY_ROLE = {

    ROLE_PUBLIC_BUYER: [
        SECTION_START,
        SECTION_SUBSCRIPTIONS,
        SECTION_ACCESS,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_GROUP_MEMBER: [
        SECTION_START,
        SECTION_ACCESS,
        SECTION_COMMANDS,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_GROUP_ADMIN: [
        SECTION_START,
        SECTION_COMMANDS,
        SECTION_BUTTONS,
        SECTION_GROUP_MANAGEMENT,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_GROUP_OWNER_SHARED: [
        SECTION_START,
        SECTION_SUBSCRIPTIONS,
        SECTION_COMMANDS,
        SECTION_BUTTONS,
        SECTION_GROUP_MANAGEMENT,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_GROUP_OWNER_EXCLUSIVE: [
        SECTION_START,
        SECTION_EXCLUSIVE_BOT,
        SECTION_SUBSCRIPTIONS,
        SECTION_COMMANDS,
        SECTION_BUTTONS,
        SECTION_GROUP_MANAGEMENT,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_EXCLUSIVE_GROUP_ADMIN: [
        SECTION_START,
        SECTION_COMMANDS,
        SECTION_BUTTONS,
        SECTION_GROUP_MANAGEMENT,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ],

    ROLE_SUPER_ADMIN: [
        SECTION_START,
        SECTION_ADMIN,
        SECTION_SUBSCRIPTIONS,
        SECTION_COMMANDS,
        SECTION_BUTTONS,
        SECTION_GROUP_MANAGEMENT,
        SECTION_EXCLUSIVE_BOT,
        SECTION_AI,
        SECTION_LANGUAGE,
        SECTION_SUPPORT
    ]
}


# =========================
# HELP CATALOG — SECTION CONTENT
# =========================

HELP_SECTION_CONTENT = {

    SECTION_START: {
        "title": {
            "es": "Primeros pasos",
            "en": "Getting started"
        },
        "body": {
            "es": (
                "Este bot permite gestionar accesos a grupos privados, "
                "suscripciones, links, administradores, avisos y funciones de IA."
            ),
            "en": (
                "This bot helps manage private group access, subscriptions, "
                "links, administrators, alerts and AI features."
            )
        }
    },

    SECTION_SUBSCRIPTIONS: {
        "title": {
            "es": "Suscripciones y pagos",
            "en": "Subscriptions and payments"
        },
        "body": {
            "es": (
                "Aquí el usuario puede comprar acceso a uno o varios grupos, "
                "consultar su suscripción, recuperar acceso y recibir un nuevo link."
            ),
            "en": (
                "Here users can buy access to one or more groups, check their subscription, "
                "recover access and receive a new link."
            )
        }
    },

    SECTION_ACCESS: {
        "title": {
            "es": "Acceso al grupo",
            "en": "Group access"
        },
        "body": {
            "es": (
                "El acceso se realiza mediante links únicos. Si un link se comparte, "
                "el sistema puede invalidarlo, avisar al usuario y proteger el grupo."
            ),
            "en": (
                "Access works through unique links. If a link is shared, "
                "the system can invalidate it, warn the user and protect the group."
            )
        }
    },

    SECTION_COMMANDS: {
        "title": {
            "es": "Comandos disponibles",
            "en": "Available commands"
        },
        "body": {
            "es": (
                "Los comandos dependerán del rol del usuario. "
                "Los usuarios normales verán opciones simples. "
                "Los admins y dueños verán herramientas de gestión."
            ),
            "en": (
                "Commands depend on the user role. "
                "Normal users see simple options. "
                "Admins and owners see management tools."
            )
        }
    },

    SECTION_BUTTONS: {
        "title": {
            "es": "Botones y menús",
            "en": "Buttons and menus"
        },
        "body": {
            "es": (
                "La interfaz debe ser sencilla: botones claros, pocas opciones por pantalla "
                "y navegación por secciones."
            ),
            "en": (
                "The interface should be simple: clear buttons, few options per screen "
                "and section-based navigation."
            )
        }
    },

    SECTION_AI: {
        "title": {
            "es": "Funciones de IA",
            "en": "AI features"
        },
        "body": {
            "es": (
                "La IA podrá ayudar a redactar mensajes, responder dudas, crear normas, "
                "analizar actividad y asistir a administradores o dueños de grupo según el plan."
            ),
            "en": (
                "AI can help write messages, answer questions, create rules, "
                "analyze activity and assist admins or group owners depending on the plan."
            )
        }
    },

    SECTION_ADMIN: {
        "title": {
            "es": "Panel de super admin",
            "en": "Super admin panel"
        },
        "body": {
            "es": (
                "El super admin podrá gestionar grupos, planes, usuarios, links, incidencias, "
                "permisos, IA y configuración general del sistema."
            ),
            "en": (
                "The super admin can manage groups, plans, users, links, incidents, "
                "permissions, AI and global system settings."
            )
        }
    },

    SECTION_GROUP_MANAGEMENT: {
        "title": {
            "es": "Gestión del grupo",
            "en": "Group management"
        },
        "body": {
            "es": (
                "Los dueños y admins podrán revisar usuarios, configurar mensajes, "
                "gestionar accesos y consultar incidencias del grupo."
            ),
            "en": (
                "Owners and admins can review users, configure messages, "
                "manage access and check group incidents."
            )
        }
    },

    SECTION_EXCLUSIVE_BOT: {
        "title": {
            "es": "Bot exclusivo con BotFather",
            "en": "Exclusive BotFather bot"
        },
        "body": {
            "es": (
                "En el plan exclusivo, el cliente puede usar su propio bot creado en BotFather, "
                "con marca propia, configuración propia e IA personalizada."
            ),
            "en": (
                "In the exclusive plan, the client can use their own BotFather bot, "
                "with custom branding, custom configuration and personalized AI."
            )
        }
    },

    SECTION_LANGUAGE: {
        "title": {
            "es": "Idioma",
            "en": "Language"
        },
        "body": {
            "es": (
                "Cada usuario podrá elegir idioma para ver menús, botones, mensajes y ayuda."
            ),
            "en": (
                "Each user can choose a language for menus, buttons, messages and help."
            )
        }
    },

    SECTION_SUPPORT: {
        "title": {
            "es": "Soporte",
            "en": "Support"
        },
        "body": {
            "es": (
                "Si algo no funciona, el usuario podrá pedir ayuda desde el propio bot."
            ),
            "en": (
                "If something does not work, the user can request help from inside the bot."
            )
        }
    }
}


# =========================
# HELP CATALOG — HELPERS
# =========================

def get_help_sections_for_role(role):

    return HELP_SECTIONS_BY_ROLE.get(
        role,
        HELP_SECTIONS_BY_ROLE[ROLE_PUBLIC_BUYER]
    )



def get_help_section(section):

    return HELP_SECTION_CONTENT.get(section)



def get_help_section_text(section, language="es"):

    data = get_help_section(section)

    if not data:

        return None


    title = data["title"].get(
        language,
        data["title"].get("es", section)
    )

    body = data["body"].get(
        language,
        data["body"].get("es", "")
    )

    return (
        f"📘 {title}\n\n"
        f"{body}"
    )
