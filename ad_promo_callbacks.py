"""
El panel de publicidad del administrador: campañas, copys y difusión.

Cuarta fase de partir callback_router.py. Aquí vive todo el asunto de las
campañas promocionales: crearlas, elegir origen y destino, generar y rotar
copys, poner marca de agua, probar el envío, diagnosticar y borrar.

Dos cosas que condicionan cómo se ha hecho, y que conviene no perder:

1. El despacho tiene que quedarse DONDE ESTABA, no al principio de button().
   Justo encima de esta región hay dos puertas de permisos que no terminan y
   caen a propósito hacia estas ramas: una comprueba que quien pulsa es super
   administrador, y la otra que la comunidad tiene contratado el extra de
   publicidad. Subir el despacho se saltaría las dos.

2. El corte NO puede hacerse por el prefijo "admin_ad". Existe
   admin_add_group —añadir grupo, que no tiene nada que ver con publicidad— y
   comparte esas nueve letras. La primera versión de este corte se lo llevaba
   por delante. El prefijo real es admin_ad_promo, más las ramas ad_promo_ del
   mismo asunto.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar uno
ajeno. Sin esas dos propiedades el orden importaría y no se podría extraer.
"""

from ai_service import (
    generate_ai_response,
    is_ai_enabled,
)
from audit_log_service import log_event
from datetime import (
    datetime,
    timedelta,
)
from db import conn
from group_service import (
    format_community_kind_capitalized,
    normalize_community_type,
)
from rbac_helpers import (
    get_admin_group_ids,
    is_super_admin,
)
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from ui_menu_helpers import send_clean_message


# =========================
# CONSTANTES DEL PANEL DE PUBLICIDAD
# =========================
# Viven aquí y las importa callback_router, no al revés: son datos de este
# asunto, y un envoltorio diferido no sirve para una constante —la primera
# versión de este corte las envolvió como si fuesen funciones y ", ".join()
# sobre una función revienta.

AD_PROMO_CAMPAIGN_FIELDS = [
    "id",
    "paid_group_id",
    "source_chat_id",
    "source_chat_title",
    "source_chat_type",
    "promo_group_telegram_id",
    "promo_group_title",
    "promo_group_type",
    "is_active",
    "is_paused",
    "auto_capture_enabled",
    "randomize_media",
    "ai_copy_enabled",
    "batch_size",
    "interval_minutes",
    "max_posts",
    "delete_old_posts",
    "bot_link",
    "marketplace_link",
    "default_caption",
    "offer_text",
    "price_text",
    "cta_text",
    "tone",
    "watermark_mode",
    "watermark_text",
    "watermark_position",
    "watermark_max_file_size_mb",
    "watermark_max_duration_seconds",
    "watermark_opacity",
    "last_offer_check_at",
    "next_offer_check_at",
    "last_run_at",
    "next_run_at",
    "created_by_user_id",
    "updated_by_user_id",
    "consecutive_failures",
    "last_error_text",
    "paused_reason",
    "created_at",
    "updated_at"
]


AD_PROMO_CAPTION_ANGLES = [
    ("descubrimiento", "Explora comunidades gratuitas y premium desde un solo bot."),
    ("gratis primero", "Invita a empezar por grupos gratuitos y decidir después."),
    ("premium/exclusividad", "Presenta premium como opción para una experiencia más completa, sin promesas falsas."),
    ("comodidad", "Explica que el bot centraliza comunidades, accesos y planes."),
    ("conversión suave", "Anima a mirar lo disponible antes de decidir."),
    ("urgencia moderada", "Sugiere revisar comunidades activas sin presión agresiva."),
    ("comunidad", "Enmarca la oferta como una red organizada de grupos."),
    ("comparación", "Contrasta gratis para empezar y premium para ir más allá."),
    ("curiosidad", "Crea curiosidad por descubrir qué comunidades hay disponibles."),
    ("bot ecosystem", "Haz protagonista al bot como puerta de entrada a varias comunidades.")
]


AD_PROMO_CREATE_STEPS = [
    ("batch_size", "¿Cuántos vídeos por tanda? Ejemplo: 5"),
    ("interval_minutes", "¿Cada cuántos minutos publicar? Ejemplo: 60"),
    ("max_posts", "Cupo máximo de posts visibles antes de borrar antiguos. Ejemplo: 50"),
    ("price_text", "Texto de precio si quieres mostrarlo. Ejemplo: Opciones premium desde 9,99 EUR/mes."),
    ("offer_text", "Texto de oferta opcional. Ejemplo: Explora gratis primero y revisa opciones premium desde el bot."),
    ("cta_text", "CTA. Ejemplo: Abre el bot y descubre las comunidades disponibles."),
    ("bot_link", "Link manual al bot/marketplace o escribe auto para generarlo automáticamente.")
]


AD_PROMO_MEDIA_FIELDS = [
    "id",
    "campaign_id",
    "paid_group_id",
    "source_chat_id",
    "source_message_id",
    "telegram_file_id",
    "file_unique_id",
    "media_type",
    "duration",
    "width",
    "height",
    "file_size",
    "original_caption",
    "is_active",
    "usage_count",
    "last_sent_at",
    "created_at"
]


AD_PROMO_WATERMARK_POSITIONS = {
    "bottom_right": "Abajo derecha",
    "bottom_left": "Abajo izquierda",
    "top_right": "Arriba derecha",
    "top_left": "Arriba izquierda",
    "center": "Centro"
}



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# Estos nombres los usa también el resto de callback_router, así que no se
# mueven. Se importan aquí dentro de la función y no arriba porque callback_router
# importa este módulo: hacerlo arriba sería un import circular.

def build_ad_promo_ai_prompt(*args, **kwargs):
    from callback_router import build_ad_promo_ai_prompt as impl
    return impl(*args, **kwargs)


def build_ad_promo_ai_system_prompt(*args, **kwargs):
    from callback_router import build_ad_promo_ai_system_prompt as impl
    return impl(*args, **kwargs)


def build_ad_promo_campaign_detail_keyboard(*args, **kwargs):
    from callback_router import build_ad_promo_campaign_detail_keyboard as impl
    return impl(*args, **kwargs)


def build_ad_promo_campaign_detail_text(*args, **kwargs):
    from callback_router import build_ad_promo_campaign_detail_text as impl
    return impl(*args, **kwargs)


def build_ad_promo_forward_fallback_keyboard(*args, **kwargs):
    from callback_router import build_ad_promo_forward_fallback_keyboard as impl
    return impl(*args, **kwargs)


def build_ad_promo_forward_keyboard(*args, **kwargs):
    from callback_router import build_ad_promo_forward_keyboard as impl
    return impl(*args, **kwargs)


def build_ad_promo_promo_choice_keyboard(*args, **kwargs):
    from callback_router import build_ad_promo_promo_choice_keyboard as impl
    return impl(*args, **kwargs)


def build_ad_promo_promo_choice_text(*args, **kwargs):
    from callback_router import build_ad_promo_promo_choice_text as impl
    return impl(*args, **kwargs)


def build_ad_promo_watermark_keyboard(*args, **kwargs):
    from callback_router import build_ad_promo_watermark_keyboard as impl
    return impl(*args, **kwargs)


def count_ad_promo_media(*args, **kwargs):
    from callback_router import count_ad_promo_media as impl
    return impl(*args, **kwargs)


def delete_old_ad_promo_posts(*args, **kwargs):
    from callback_router import delete_old_ad_promo_posts as impl
    return impl(*args, **kwargs)


def extract_commercial_request_id(*args, **kwargs):
    from callback_router import extract_commercial_request_id as impl
    return impl(*args, **kwargs)


def fetch_ad_promo_campaign(*args, **kwargs):
    from callback_router import fetch_ad_promo_campaign as impl
    return impl(*args, **kwargs)


def fetch_group_basic_info(*args, **kwargs):
    from callback_router import fetch_group_basic_info as impl
    return impl(*args, **kwargs)


def format_commercial_datetime(*args, **kwargs):
    from callback_router import format_commercial_datetime as impl
    return impl(*args, **kwargs)


def format_location_review_reason_preview(*args, **kwargs):
    from callback_router import format_location_review_reason_preview as impl
    return impl(*args, **kwargs)


def get_selected_group_for_permissions(*args, **kwargs):
    from callback_router import get_selected_group_for_permissions as impl
    return impl(*args, **kwargs)


def normalize_ad_promo_watermark_mode(*args, **kwargs):
    from callback_router import normalize_ad_promo_watermark_mode as impl
    return impl(*args, **kwargs)


def normalize_ad_promo_watermark_position(*args, **kwargs):
    from callback_router import normalize_ad_promo_watermark_position as impl
    return impl(*args, **kwargs)


def owner_can_use_ad_promo(*args, **kwargs):
    from callback_router import owner_can_use_ad_promo as impl
    return impl(*args, **kwargs)


def parse_ad_promo_int(*args, **kwargs):
    from callback_router import parse_ad_promo_int as impl
    return impl(*args, **kwargs)


def row_to_ad_promo_campaign(*args, **kwargs):
    from callback_router import row_to_ad_promo_campaign as impl
    return impl(*args, **kwargs)


def row_to_ad_promo_media(*args, **kwargs):
    from callback_router import row_to_ad_promo_media as impl
    return impl(*args, **kwargs)


def sanitize_ad_promo_text(*args, **kwargs):
    from callback_router import sanitize_ad_promo_text as impl
    return impl(*args, **kwargs)


def save_ad_promo_copy_variant(*args, **kwargs):
    from callback_router import save_ad_promo_copy_variant as impl
    return impl(*args, **kwargs)


def save_ad_promo_wizard_chat(*args, **kwargs):
    from callback_router import save_ad_promo_wizard_chat as impl
    return impl(*args, **kwargs)


def send_ad_promo_campaign_batch(*args, **kwargs):
    from callback_router import send_ad_promo_campaign_batch as impl
    return impl(*args, **kwargs)


def update_ad_promo_campaign(*args, **kwargs):
    from callback_router import update_ad_promo_campaign as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DEL PANEL DE PUBLICIDAD
# =========================

def fetch_ad_promo_campaigns(limit=20):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_CAMPAIGN_FIELDS)}
            FROM ad_promo_campaigns
            ORDER BY is_active DESC,
                     is_paused ASC,
                     updated_at DESC
            LIMIT %s

        """, (limit,))

        rows = cur.fetchall()


    return [row_to_ad_promo_campaign(row) for row in rows]


def fetch_visible_ad_promo_campaigns(user_id, group_id=None, limit=20):

    campaigns = fetch_ad_promo_campaigns(limit=limit)

    if is_super_admin(user_id):

        return campaigns


    visible_campaigns = []

    for campaign in campaigns:

        paid_group_id = campaign.get("paid_group_id")

        if group_id and paid_group_id != group_id:

            continue


        if owner_can_use_ad_promo(user_id, paid_group_id)[0]:

            visible_campaigns.append(campaign)


    return visible_campaigns


def delete_ad_promo_campaign(campaign_id):

    campaign = fetch_ad_promo_campaign(campaign_id)

    if not campaign:

        return None


    deleted_counts = {}

    try:

        with conn.cursor() as cur:

            for table_name, key in [
                ("ad_promo_sent_posts", "sent_posts"),
                ("ad_promo_media", "media"),
                ("ad_promo_copy_variants", "copy_variants")
            ]:

                cur.execute(f"""

                    DELETE FROM {table_name}
                    WHERE campaign_id=%s

                """, (campaign_id,))

                deleted_counts[key] = cur.rowcount


            cur.execute("""

                DELETE FROM ad_promo_campaigns
                WHERE id=%s

            """, (campaign_id,))

            deleted_counts["campaigns"] = cur.rowcount


        conn.commit()

    except Exception:

        conn.rollback()
        raise


    campaign["deleted_related_counts"] = deleted_counts

    return campaign


def fetch_ad_promo_media(campaign_id, limit=20):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(AD_PROMO_MEDIA_FIELDS)}
            FROM ad_promo_media
            WHERE campaign_id=%s
            ORDER BY is_active DESC,
                     created_at DESC
            LIMIT %s

        """, (
            campaign_id,
            limit
        ))

        rows = cur.fetchall()


    return [row_to_ad_promo_media(row) for row in rows]


AD_PROMO_TEMPLATE_CAPTIONS = [
    "🚀 Descubre nuevas comunidades desde un solo bot\n\nPuedes encontrar grupos gratuitos para empezar y opciones premium para quienes buscan una experiencia más completa.\n\n🎁 Gratis para empezar\n⭐ Premium si quieres más\n📲 Todo desde el bot",
    "👀 ¿Buscas comunidades privadas, gratuitas o premium?\n\nNuestro bot reúne diferentes grupos para que puedas descubrirlos desde un solo lugar. Explora primero, revisa las opciones y decide con calma.\n\nAbre el bot y mira qué hay disponible.",
    "🎁 Entra gratis, descubre más y decide después\n\nHay comunidades gratuitas para empezar sin pagar y opciones premium para quienes quieren ir un paso más allá.\n\nDesde el bot puedes ver grupos, planes y accesos disponibles.",
    "⭐ No todo tiene que empezar pagando\n\nEmpieza por comunidades gratuitas, descubre el ambiente y revisa desde el bot qué opciones premium están disponibles.\n\nGratis para empezar. Premium si quieres más.",
    "🤖 Un bot, varias comunidades\n\nEn lugar de buscar grupo por grupo, puedes explorar desde nuestro bot una selección de comunidades gratuitas y premium.\n\nExplora, entra gratis y mejora a premium si te interesa.",
    "📍 Explora una red de comunidades organizada\n\nDesde el bot puedes descubrir grupos gratuitos, revisar opciones premium y gestionar tus accesos sin perderte entre enlaces.\n\nAbre el menú y mira qué comunidades están activas.",
    "🔎 Mira primero, decide después\n\nPuedes empezar por grupos gratuitos y revisar las comunidades premium disponibles si buscas una experiencia más completa.\n\nTodo se gestiona desde el bot.",
    "🎁 Gratis para empezar, premium para ir más allá\n\nEl bot te permite descubrir comunidades disponibles, comparar opciones y entrar donde encaje contigo.\n\nAbre el bot y explora la red.",
    "📲 Tu punto de entrada a varias comunidades\n\nEncuentra grupos gratuitos para probar, opciones premium para una experiencia más cuidada y un menú centralizado para gestionar accesos.\n\nEmpieza explorando desde el bot.",
    "✨ Descubre qué comunidades están disponibles\n\nAbre el bot, revisa los grupos gratuitos y mira las opciones premium si quieres acceso más exclusivo.\n\nExplora primero. Decide después."
]


def generate_ad_promo_caption_variants(campaign, count=10):

    group = fetch_group_basic_info(campaign.get("paid_group_id"))
    group_name = group[1] if group else f"Comunidad {campaign.get('paid_group_id')}"
    variants = []


    if campaign.get("ai_copy_enabled") and is_ai_enabled():

        for angle, instruction in AD_PROMO_CAPTION_ANGLES[:count]:

            prompt = build_ad_promo_ai_prompt(
                campaign,
                group_name,
                angle=angle,
                instruction=instruction
            )
            ok, answer = generate_ai_response(
                prompt,
                system_prompt=build_ad_promo_ai_system_prompt()
            )

            if ok and answer:

                variants.append((answer, "ai"))


    for template in AD_PROMO_TEMPLATE_CAPTIONS:

        if len(variants) >= count:

            break


        variants.append((template, "template"))


    saved = []
    saved_sources = set()

    for text, source in variants[:count]:

        saved_text = save_ad_promo_copy_variant(
            campaign.get("id"),
            text,
            source=source
        )

        if saved_text:

            saved.append(saved_text)
            saved_sources.add(source)


    if len(saved_sources) > 1:

        source_summary = "mixed"

    elif saved_sources:

        source_summary = next(iter(saved_sources))

    else:

        source_summary = "none"


    return saved, source_summary


def regenerate_ad_promo_copy_variants(campaign_id):

    campaign = fetch_ad_promo_campaign(campaign_id)

    if not campaign:

        return {
            "ok": False,
            "reason": "not_found",
            "disabled_count": 0,
            "generated_count": 0,
            "source": "none"
        }


    with conn.cursor() as cur:

        cur.execute("""

            UPDATE ad_promo_copy_variants
            SET is_active=FALSE
            WHERE campaign_id=%s
            AND is_active=TRUE

        """, (campaign_id,))

        disabled_count = cur.rowcount


    saved, source = generate_ad_promo_caption_variants(campaign, count=10)

    if not saved:

        return {
            "ok": False,
            "reason": "no_generated",
            "disabled_count": disabled_count,
            "generated_count": 0,
            "source": source
        }


    return {
        "ok": True,
        "disabled_count": disabled_count,
        "generated_count": len(saved),
        "source": source
    }


def fetch_ad_promo_copy_variants(campaign_id, limit=10):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   text,
                   source,
                   is_active,
                   usage_count,
                   last_used_at,
                   created_at
            FROM ad_promo_copy_variants
            WHERE campaign_id=%s
            ORDER BY created_at DESC
            LIMIT %s

        """, (
            campaign_id,
            limit
        ))

        return cur.fetchall()


def disable_ad_promo_copy_variant(variant_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE ad_promo_copy_variants
            SET is_active=FALSE
            WHERE id=%s
            RETURNING campaign_id

        """, (variant_id,))

        row = cur.fetchone()


    return row[0] if row else None


def build_ad_promo_panel_text(campaigns=None):

    campaigns = campaigns if campaigns is not None else fetch_ad_promo_campaigns()
    active = len([campaign for campaign in campaigns if campaign.get("is_active") and not campaign.get("is_paused")])
    paused = len([campaign for campaign in campaigns if campaign.get("is_paused")])

    return (
        "📣 Promoción automática\n\n"
        f"Campañas registradas: {len(campaigns)}\n"
        f"Activas: {active}\n"
        f"Pausadas: {paused}\n\n"
        "El bot solo puede usar vídeos que tenga capturados como file_id. "
        "No puede recorrer histórico antiguo con Bot API. "
        "A partir de ahora capturará los vídeos nuevos que vea en el grupo/canal fuente."
    )


def build_ad_promo_panel_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Campañas", callback_data="admin_ad_promo_campaigns")],
        [InlineKeyboardButton("➕ Crear campaña", callback_data="admin_ad_promo_create")],
        [InlineKeyboardButton("⬅️ Herramientas internas", callback_data="admin_global_tools")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_ad_promo_campaigns_text(campaigns):

    if not campaigns:

        return "📋 Campañas de promoción\n\nTodavía no hay campañas registradas."


    lines = ["📋 Campañas de promoción", ""]

    for campaign in campaigns:

        group = fetch_group_basic_info(campaign.get("paid_group_id"))
        group_name = group[1] if group else f"Grupo {campaign.get('paid_group_id')}"
        media_summary = count_ad_promo_media(campaign.get("id"))
        status = "pausada" if campaign.get("is_paused") else "activa" if campaign.get("is_active") else "inactiva"
        lines.extend([
            f"#{campaign.get('id')} · {group_name}",
            f"Estado: {status}",
            f"Fuente: {campaign.get('source_chat_id') or '-'}",
            f"Destino promo: {campaign.get('promo_group_telegram_id') or '-'}",
            f"Vídeos activos: {media_summary.get('active')}",
            f"Próxima tanda: {format_commercial_datetime(campaign.get('next_run_at')) if campaign.get('next_run_at') else '-'}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_ad_promo_campaigns_keyboard(campaigns):

    keyboard = []

    for campaign in campaigns:

        keyboard.append([InlineKeyboardButton(
            f"⚙️ Campaña #{campaign.get('id')}",
            callback_data=f"admin_ad_promo_campaign_{campaign.get('id')}"
        )])


    keyboard.extend([
        [InlineKeyboardButton("➕ Crear campaña", callback_data="admin_ad_promo_create")],
        [InlineKeyboardButton("⬅️ Promoción automática", callback_data="admin_ad_promo")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_ad_promo_delete_campaign_text(campaign):

    return (
        "⚠️ ¿Seguro que quieres eliminar esta campaña?\n\n"
        f"Campaña: #{campaign.get('id')}\n\n"
        "Esta acción elimina solo la campaña promocional.\n\n"
        "Puede eliminar también sus filas relacionadas de promoción:\n"
        "- vídeos promocionales capturados\n"
        "- posts promocionales enviados\n"
        "- variantes de copy/captions\n\n"
        "No elimina la comunidad de pago.\n"
        "No elimina usuarios.\n"
        "No elimina pagos.\n"
        "No elimina suscripciones.\n"
        "No elimina invite links ni códigos de acceso."
    )


def build_ad_promo_delete_campaign_keyboard(campaign_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Sí, eliminar campaña",
            callback_data=f"admin_ad_promo_delete_campaign_yes_{campaign_id}"
        )],
        [InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"admin_ad_promo_campaign_{campaign_id}"
        )]
    ])


def build_ad_promo_watermark_text(campaign):

    mode = normalize_ad_promo_watermark_mode(campaign.get("watermark_mode"))
    position = normalize_ad_promo_watermark_position(campaign.get("watermark_position"))

    return (
        "💧 Marca de agua\n\n"
        "Estado actual:\n"
        f"- Modo: {mode}\n"
        f"- Texto: {campaign.get('watermark_text') or 'auto'}\n"
        f"- Posición: {AD_PROMO_WATERMARK_POSITIONS.get(position)}\n"
        f"- Límite tamaño: {campaign.get('watermark_max_file_size_mb') or 50} MB\n"
        f"- Límite duración: {campaign.get('watermark_max_duration_seconds') or 180} segundos\n"
        f"- Opacidad: {campaign.get('watermark_opacity') or 0.65}\n\n"
        "Modo caption añade una línea discreta al texto. Modo vídeo intenta incrustarla con ffmpeg y usa fallback seguro si no se puede."
    )


def format_ad_promo_watermark_statuses(result):

    statuses = result.get("watermark_statuses") or []

    if not statuses:

        return ""


    labels = {
        "embedded": "🎬 Marca incrustada en el vídeo",
        "caption": "📝 Marca añadida solo al caption",
        "skipped_limits": "⚠️ Marca en vídeo omitida por límites",
        "unavailable": "⚠️ ffmpeg no disponible; marca solo en caption",
        "failed": "⚠️ Falló ffmpeg; marca solo en caption",
        "none": "🚫 Marca de agua desactivada"
    }
    lines = ["", "Marca de agua:"]

    for status in statuses[:3]:

        status_key = status.get("status")
        lines.append(labels.get(status_key, status_key or "-"))

        if status.get("message"):

            lines.append(status.get("message")[:500])


    return "\n".join(lines)


def build_ad_promo_test_result_text(result, watermark=False):

    if result.get("ok"):

        migration_notice = result.get("migration_notice")

        return (
            "✅ Prueba enviada correctamente\n\n"
            f"Enviados: {result.get('sent', 0)}\n"
            f"Fallidos: {result.get('failed', 0)}"
            + (f"\n\n{migration_notice}" if migration_notice else "")
            + (format_ad_promo_watermark_statuses(result) if watermark else "")
        )


    reason = result.get("reason")

    if reason == "no_media":

        return (
            "⚠️ No hay vídeos activos para esta campaña.\n\n"
            "El bot todavía no ha capturado vídeos del grupo/canal fuente.\n"
            "Para solucionarlo:\n"
            "1. Asegúrate de que el bot está en el grupo/canal fuente.\n"
            "2. Publica o reenvía un vídeo nuevo allí para que el bot lo capture.\n"
            "3. Vuelve a revisar la biblioteca de vídeos."
        )


    if reason == "no_active_media":

        return (
            "⚠️ Hay vídeos guardados, pero ninguno está activo.\n\n"
            "Activa al menos un vídeo en la biblioteca antes de ejecutar la prueba."
        )


    if reason == "send_failed":

        error = result.get("error") or "Sin detalle técnico disponible."
        migration_notice = result.get("migration_notice")

        return (
            "❌ La prueba no se pudo enviar.\n\n"
            f"Enviados: {result.get('sent', 0)}\n"
            f"Fallidos: {result.get('failed', 0)}\n"
            + (f"{migration_notice}\n" if migration_notice else "")
            + f"Error: {str(error)[:500]}"
            + (format_ad_promo_watermark_statuses(result) if watermark else "")
        )


    return (
        "⚠️ No se envió ningún vídeo.\n\n"
        f"Enviados: {result.get('sent', 0)}\n"
        f"Fallidos: {result.get('failed', 0)}\n"
        f"Estado: {reason or 'nothing_sent'}"
        + (format_ad_promo_watermark_statuses(result) if watermark else "")
    )


def build_ad_promo_test_result_keyboard(campaign, result, watermark=False):

    campaign_id = campaign.get("id")
    retry_callback = (
        f"admin_ad_promo_watermark_test_{campaign_id}"
        if watermark
        else f"admin_ad_promo_test_{campaign_id}"
    )
    keyboard = []
    reason = result.get("reason")

    if reason in ("no_media", "no_active_media"):

        keyboard.append([InlineKeyboardButton("📚 Ver biblioteca", callback_data=f"admin_ad_promo_library_{campaign_id}")])


    if reason != "no_active_media":

        keyboard.append([InlineKeyboardButton("🔁 Reintentar prueba", callback_data=retry_callback)])


    if reason == "send_failed":

        keyboard.append([InlineKeyboardButton("⚙️ Revisar configuración", callback_data=f"admin_ad_promo_campaign_{campaign_id}")])


    keyboard.append([InlineKeyboardButton("🔙 Volver campaña", callback_data=f"admin_ad_promo_campaign_{campaign_id}")])

    if watermark:

        keyboard.append([InlineKeyboardButton("💧 Marca de agua", callback_data=f"admin_ad_promo_watermark_{campaign_id}")])


    return InlineKeyboardMarkup(keyboard)


def build_ad_promo_library_text(campaign, media_rows):

    media_summary = count_ad_promo_media(campaign.get("id"))
    lines = [
        f"📚 Biblioteca campaña #{campaign.get('id')}",
        "",
        f"Total vídeos: {media_summary.get('total')}",
        f"Activos: {media_summary.get('active')}",
        f"Inactivos: {media_summary.get('inactive')}",
        f"Última captura: {format_commercial_datetime(media_summary.get('last_capture')) if media_summary.get('last_capture') else '-'}",
        f"Source chat ID: {campaign.get('source_chat_id') or '-'}",
        f"Captura automática: {'ON' if campaign.get('auto_capture_enabled') else 'OFF'}",
        "",
        "Para capturar vídeos, publica un vídeo nuevo en el grupo/canal fuente mientras el bot está dentro y con permisos.",
        ""
    ]

    if not media_summary.get("active"):

        lines.append("No hay vídeos activos. El bot solo puede publicar vídeos que haya capturado como file_id.")
        lines.append("")


    if not media_rows:

        lines.append("Todavía no hay vídeos capturados.")

    for media in media_rows:

        lines.extend([
            f"#{media.get('id')} · {'activo' if media.get('is_active') else 'inactivo'}",
            f"Mensaje fuente: {media.get('source_message_id') or '-'}",
            f"Uso: {media.get('usage_count') or 0}",
            f"Último envío: {format_commercial_datetime(media.get('last_sent_at')) if media.get('last_sent_at') else '-'}",
            f"Caption original: {format_location_review_reason_preview(media.get('original_caption'))}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_ad_promo_library_keyboard(campaign, media_rows):

    keyboard = []

    for media in media_rows[:10]:

        if media.get("is_active"):

            keyboard.append([InlineKeyboardButton(
                f"🚫 Desactivar vídeo #{media.get('id')}",
                callback_data=f"admin_ad_promo_media_off_{media.get('id')}"
            )])


    keyboard.extend([
        [InlineKeyboardButton("🎥 Captura ON/OFF", callback_data=f"admin_ad_promo_capture_{campaign.get('id')}")],
        [InlineKeyboardButton("⬅️ Campaña", callback_data=f"admin_ad_promo_campaign_{campaign.get('id')}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def fetch_ad_promo_campaign_diagnostics(campaign_id):

    campaign = fetch_ad_promo_campaign(campaign_id)

    if not campaign:

        return None


    with conn.cursor() as cur:

        cur.execute("""

            SELECT COUNT(*),
                   MAX(created_at)
            FROM ad_promo_media
            WHERE campaign_id=%s
            AND is_active=TRUE

        """, (campaign_id,))
        media_count_active, last_capture_at = cur.fetchone()

        cur.execute("""

            SELECT COUNT(*)
            FROM ad_promo_sent_posts
            WHERE campaign_id=%s
            AND sent_at >= NOW() - INTERVAL '24 hours'

        """, (campaign_id,))
        sent_24h = cur.fetchone()[0]

        cur.execute("""

            SELECT COUNT(*),
                   MAX(sent_at)
            FROM ad_promo_sent_posts
            WHERE campaign_id=%s
            AND sent_at >= NOW() - INTERVAL '7 days'

        """, (campaign_id,))
        sent_7d, last_sent_at = cur.fetchone()

        cur.execute("""

            SELECT COUNT(*)
            FROM ad_promo_sent_posts
            WHERE campaign_id=%s
            AND delete_error IS NOT NULL
            AND sent_at >= NOW() - INTERVAL '7 days'

        """, (campaign_id,))
        delete_errors_7d = cur.fetchone()[0]

        cur.execute("""

            SELECT COUNT(*)
            FROM ad_promo_copy_variants
            WHERE campaign_id=%s
            AND is_active=TRUE

        """, (campaign_id,))
        active_copy_variants = cur.fetchone()[0]


    send_errors_7d = 0

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT COUNT(*)
                FROM audit_logs
                WHERE event_type='ad_promo_send_failed'
                AND created_at >= NOW() - INTERVAL '7 days'
                AND metadata->>'campaign_id'=%s

            """, (str(campaign_id),))

            send_errors_7d = cur.fetchone()[0]

    except Exception:

        send_errors_7d = 0


    batch_size = int(campaign.get("batch_size") or 1)
    missing_link = not campaign.get("bot_link") and not campaign.get("marketplace_link")

    return {
        "campaign": campaign,
        "media_count_active": media_count_active or 0,
        "sent_24h": sent_24h or 0,
        "sent_7d": sent_7d or 0,
        "send_errors_7d": send_errors_7d or 0,
        "delete_errors_7d": delete_errors_7d or 0,
        "last_sent_at": last_sent_at,
        "last_capture_at": last_capture_at,
        "next_run_at": campaign.get("next_run_at"),
        "active_copy_variants": active_copy_variants or 0,
        "media_below_batch_size": int(media_count_active or 0) < batch_size,
        "missing_link": missing_link
    }


def format_ad_promo_campaign_diagnostics(diagnostics):

    campaign = diagnostics.get("campaign")
    group = fetch_group_basic_info(campaign.get("paid_group_id"))
    group_name = group[1] if group else f"Grupo {campaign.get('paid_group_id')}"
    status = "pausada" if campaign.get("is_paused") else "activa" if campaign.get("is_active") else "inactiva"
    alerts = []


    if diagnostics.get("media_count_active") == 0:

        alerts.append("⚠️ No hay vídeos capturados.")


    if diagnostics.get("media_below_batch_size"):

        alerts.append("⚠️ Hay menos vídeos activos que batch_size.")


    if diagnostics.get("missing_link"):

        alerts.append("⚠️ No hay bot_link ni marketplace_link.")


    if diagnostics.get("send_errors_7d"):

        alerts.append("⚠️ Hay errores recientes de envío.")


    if diagnostics.get("delete_errors_7d"):

        alerts.append("⚠️ Hay errores recientes de borrado.")


    if campaign.get("is_active") and campaign.get("is_paused"):

        alerts.append("⚠️ La campaña está activa pero pausada.")


    if (
        campaign.get("is_active")
        and not campaign.get("is_paused")
        and diagnostics.get("last_sent_at")
        and campaign.get("interval_minutes")
    ):

        elapsed = datetime.now() - diagnostics.get("last_sent_at")
        threshold = timedelta(minutes=max(int(campaign.get("interval_minutes") or 60) * 2, 120))

        if elapsed > threshold:

            alerts.append("⚠️ No se ha enviado nada en más de lo esperado para su frecuencia.")


    if not alerts:

        alerts.append("✅ Sin alertas críticas.")


    return (
        "📊 Diagnóstico de campaña\n\n"
        f"Campaña: {group_name}\n"
        f"Estado: {status}\n"
        f"Vídeos activos capturados: {diagnostics.get('media_count_active')}\n"
        f"Vídeos enviados últimas 24h: {diagnostics.get('sent_24h')}\n"
        f"Vídeos enviados últimos 7 días: {diagnostics.get('sent_7d')}\n"
        f"Errores de envío últimos 7 días: {diagnostics.get('send_errors_7d')}\n"
        f"Errores de borrado últimos 7 días: {diagnostics.get('delete_errors_7d')}\n"
        f"Último envío: {format_commercial_datetime(diagnostics.get('last_sent_at')) if diagnostics.get('last_sent_at') else '-'}\n"
        f"Próximo envío: {format_commercial_datetime(diagnostics.get('next_run_at')) if diagnostics.get('next_run_at') else '-'}\n"
        f"Última captura: {format_commercial_datetime(diagnostics.get('last_capture_at')) if diagnostics.get('last_capture_at') else '-'}\n"
        f"Captions activos: {diagnostics.get('active_copy_variants')}\n"
        f"Link CTA configurado: {'no' if diagnostics.get('missing_link') else 'sí'}\n"
        f"IA textos: {'ON' if campaign.get('ai_copy_enabled') else 'OFF'}\n"
        f"Random: {'ON' if campaign.get('randomize_media') else 'OFF'}\n\n"
        "Alertas:\n"
        + "\n".join(alerts)
    )


def build_ad_promo_diagnostics_keyboard(campaign_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Enviar prueba", callback_data=f"admin_ad_promo_test_{campaign_id}")],
        [InlineKeyboardButton("📝 Generar captions", callback_data=f"admin_ad_promo_generate_captions_{campaign_id}")],
        [InlineKeyboardButton("🎲 Optimizar rotación", callback_data=f"admin_ad_promo_optimize_rotation_{campaign_id}")],
        [InlineKeyboardButton("🔙 Volver campaña", callback_data=f"admin_ad_promo_campaign_{campaign_id}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def build_ad_promo_copy_variants_text(campaign, rows):

    if not rows:

        return "📋 Captions de campaña\n\nTodavía no hay captions guardados."


    lines = [f"📋 Captions campaña #{campaign.get('id')}", ""]

    for variant_id, text, source, is_active, usage_count, last_used_at, created_at in rows:

        status = "activo" if is_active else "inactivo"
        preview = sanitize_ad_promo_text(text).replace("\n", " ")[:140]
        lines.extend([
            f"#{variant_id} · {source or '-'} · {status}",
            f"Uso: {usage_count or 0}",
            f"Último uso: {format_commercial_datetime(last_used_at) if last_used_at else '-'}",
            f"Texto: {preview}",
            ""
        ])


    return "\n".join(lines)[:3900]


def build_ad_promo_copy_variants_keyboard(campaign, rows):

    keyboard = []

    for variant_id, _text, _source, is_active, _usage_count, _last_used_at, _created_at in rows:

        if is_active:

            keyboard.append([InlineKeyboardButton(
                f"🚫 Desactivar caption #{variant_id}",
                callback_data=f"admin_ad_promo_copy_off_{variant_id}"
            )])


    keyboard.extend([
        [InlineKeyboardButton("📝 Generar captions", callback_data=f"admin_ad_promo_generate_captions_{campaign.get('id')}")],
        [InlineKeyboardButton("🧠 Regenerar textos IA", callback_data=f"ad_promo_regenerate_copy_{campaign.get('id')}")],
        [InlineKeyboardButton("🔙 Volver campaña", callback_data=f"admin_ad_promo_campaign_{campaign.get('id')}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def optimize_ad_promo_rotation(campaign_id, actor_user_id=None):

    campaign = fetch_ad_promo_campaign(campaign_id)

    if not campaign:

        return None


    media_summary = count_ad_promo_media(campaign_id)
    media_count = int(media_summary.get("active") or 0)
    current_batch_size = int(campaign.get("batch_size") or 1)
    new_batch_size = current_batch_size
    new_max_posts = int(campaign.get("max_posts") or 50)
    updates = {"randomize_media": True}
    notes = ["Random: ON"]


    if media_count and current_batch_size > media_count:

        new_batch_size = media_count
        updates["batch_size"] = new_batch_size
        notes.append(f"Vídeos por tanda ajustado: {new_batch_size}")


    minimum_max_posts = max(new_batch_size * 3, 1)

    if new_max_posts < minimum_max_posts:

        new_max_posts = minimum_max_posts
        updates["max_posts"] = new_max_posts
        notes.append(f"Cupo máximo ajustado: {new_max_posts}")


    if media_count < current_batch_size:

        notes.append(f"Aviso: tienes solo {media_count} vídeos activos para tandas de {current_batch_size}.")

    elif media_count < current_batch_size * 2:

        notes.append(f"Aviso: conviene capturar más vídeos para reducir repeticiones. Activos: {media_count}.")


    updated = update_ad_promo_campaign(
        campaign_id,
        updates,
        actor_user_id=actor_user_id
    )

    return updated, notes


def deactivate_ad_promo_media(media_id):

    with conn.cursor() as cur:

        cur.execute("""

            UPDATE ad_promo_media
            SET is_active=FALSE
            WHERE id=%s
            RETURNING campaign_id

        """, (media_id,))

        row = cur.fetchone()


    return row[0] if row else None


AD_PROMO_GROUP_PAGE_SIZE = 8


AD_PROMO_SOURCE_FORWARD_TEXT = (
    "🔁 Reenvía aquí un mensaje del grupo/canal fuente.\n\n"
    "Si Telegram conserva el origen del reenvío, el bot detectará automáticamente de dónde vienen los vídeos promocionales.\n\n"
    "Si el bot no puede acceder a ese chat, añádelo como administrador y vuelve a intentarlo."
)


AD_PROMO_PROMO_FORWARD_TEXT = (
    "🔁 Reenvía aquí un mensaje del grupo/canal destino.\n\n"
    "Si Telegram conserva el origen del reenvío, el bot detectará automáticamente dónde debe publicar la publicidad.\n\n"
    "Si el bot no puede acceder a ese chat, añádelo como administrador y vuelve a intentarlo."
)


def fetch_ad_promo_selectable_groups(page=0, page_size=AD_PROMO_GROUP_PAGE_SIZE, user_id=None):

    page = max(int(page or 0), 0)
    offset = page * page_size
    params = [page_size + 1, offset]
    group_filter_sql = ""

    if user_id and not is_super_admin(user_id):

        group_ids = get_admin_group_ids(user_id, ["can_manage_groups"])

        if not group_ids:

            return [], False


        # get_admin_group_ids returns internal groups.id values, not Telegram chat ids.
        group_filter_sql = "AND id = ANY(%s)"
        params.insert(0, group_ids)

    query = """

        SELECT id,
               name,
               telegram_group_id,
               COALESCE(community_type, 'group'),
               COALESCE(is_active, TRUE)
        FROM groups
        WHERE COALESCE(is_active, TRUE)=TRUE
        {group_filter_sql}
        ORDER BY created_at DESC NULLS LAST,
                 id DESC
        LIMIT %s
        OFFSET %s

    """.format(group_filter_sql=group_filter_sql)


    try:

        with conn.cursor() as cur:

            cur.execute(query, params)

            rows = cur.fetchall()

    except Exception:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id,
                       COALESCE(community_type, 'group'),
                       COALESCE(is_active, TRUE)
                FROM groups
                WHERE COALESCE(is_active, TRUE)=TRUE
                {group_filter_sql}
                ORDER BY id DESC
                LIMIT %s
                OFFSET %s

            """.format(group_filter_sql=group_filter_sql), params)

            rows = cur.fetchall()


    if user_id and not is_super_admin(user_id):

        rows = [
            row
            for row in rows
            if owner_can_use_ad_promo(user_id, row[0])[0]
        ]


    return rows[:page_size], len(rows) > page_size


def fetch_ad_promo_selectable_group(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   COALESCE(community_type, 'group'),
                   COALESCE(is_active, TRUE)
            FROM groups
            WHERE id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def build_ad_promo_group_selection_text():

    return (
        "📣 Crear campaña de promoción\n\n"
        "Elige la comunidad de pago que quieres promocionar:"
    )


def build_ad_promo_group_selection_keyboard(page=0, user_id=None):

    rows, has_next = fetch_ad_promo_selectable_groups(page, user_id=user_id)
    keyboard = []


    for group_id, name, _telegram_group_id, community_type, _is_active in rows:

        kind = format_community_kind_capitalized(
            normalize_community_type(community_type)
        )
        display_name = (name or "Sin nombre")[:32]
        label = f"🔥 {display_name} · ID {group_id} · {kind}"

        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"admin_ad_promo_select_group_{group_id}"
        )])


    nav_row = []

    if page > 0:

        nav_row.append(InlineKeyboardButton(
            "⬅️ Anterior",
            callback_data=f"admin_ad_promo_create_page_{page - 1}"
        ))


    if has_next:

        nav_row.append(InlineKeyboardButton(
            "➡️ Siguiente",
            callback_data=f"admin_ad_promo_create_page_{page + 1}"
        ))


    if nav_row:

        keyboard.append(nav_row)


    keyboard.extend([
        [InlineKeyboardButton("🔙 Volver", callback_data="admin_ad_promo")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])

    return InlineKeyboardMarkup(keyboard)


def build_ad_promo_source_choice_text():

    return (
        "✅ Comunidad de pago seleccionada.\n\n"
        "Ahora vamos a elegir de dónde sacará el bot los vídeos promocionales.\n\n"
        "Normalmente será el mismo grupo/canal de pago, pero también puedes elegir otro canal fuente donde el bot vea vídeos.\n\n"
        "Elige una opción:"
    )


def build_ad_promo_source_choice_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📹 Usar esta misma comunidad como fuente", callback_data="admin_ad_promo_use_paid_as_source")],
        [InlineKeyboardButton("📋 Elegir otro grupo/canal fuente", callback_data="admin_ad_promo_source_picker")],
        [InlineKeyboardButton("🔁 Reenviar mensaje del grupo/canal fuente", callback_data="admin_ad_promo_retry_source_forward")],
        [InlineKeyboardButton("✍️ Introducir ID manualmente", callback_data="admin_ad_promo_manual_source")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
    ])


def fetch_ad_promo_managed_chats(page=0, page_size=AD_PROMO_GROUP_PAGE_SIZE):

    page = max(int(page or 0), 0)
    offset = page * page_size

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   COALESCE(community_type, 'group')
            FROM groups
            WHERE telegram_group_id IS NOT NULL
            AND COALESCE(is_active, TRUE)=TRUE
            ORDER BY id DESC
            LIMIT %s
            OFFSET %s

        """, (
            page_size + 1,
            offset
        ))

        rows = cur.fetchall()


    return rows[:page_size], len(rows) > page_size


def fetch_ad_promo_managed_chat_by_telegram_id(telegram_group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id,
                   COALESCE(community_type, 'group')
            FROM groups
            WHERE telegram_group_id=%s
            AND COALESCE(is_active, TRUE)=TRUE
            LIMIT 1

        """, (telegram_group_id,))

        return cur.fetchone()


def build_ad_promo_chat_picker_text(kind):

    if kind == "source":

        return (
            "📋 Seleccionar grupo/canal fuente\n\n"
            "Elige el grupo/canal desde donde el bot capturará vídeos nuevos."
        )


    return (
        "📋 Seleccionar grupo/canal destino\n\n"
        "Selecciona el grupo/canal gratuito donde se publicará la publicidad."
    )


def build_ad_promo_chat_picker_keyboard(kind, page=0):

    rows, has_next = fetch_ad_promo_managed_chats(page)
    keyboard = []
    select_prefix = (
        "admin_ad_promo_select_source_"
        if kind == "source"
        else "admin_ad_promo_select_promo_"
    )
    page_prefix = (
        "admin_ad_promo_source_picker_page_"
        if kind == "source"
        else "admin_ad_promo_promo_picker_page_"
    )


    for _group_id, name, telegram_group_id, community_type in rows:

        kind_cap = format_community_kind_capitalized(
            normalize_community_type(community_type)
        )
        display_name = (name or "Sin nombre")[:24]
        label = f"📡 {display_name} · {kind_cap} · TG {telegram_group_id}"

        keyboard.append([InlineKeyboardButton(
            label[:64],
            callback_data=f"{select_prefix}{telegram_group_id}"
        )])


    nav_row = []

    if page > 0:

        nav_row.append(InlineKeyboardButton(
            "⬅️ Anterior",
            callback_data=f"{page_prefix}{page - 1}"
        ))


    if has_next:

        nav_row.append(InlineKeyboardButton(
            "➡️ Siguiente",
            callback_data=f"{page_prefix}{page + 1}"
        ))


    if nav_row:

        keyboard.append(nav_row)


    retry_callback = (
        "admin_ad_promo_retry_source_forward"
        if kind == "source"
        else "admin_ad_promo_retry_promo_forward"
    )

    keyboard.extend([
        [InlineKeyboardButton("🔁 Reintentar reenvío", callback_data=retry_callback)],
        [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
    ])

    return InlineKeyboardMarkup(keyboard)


def parse_ad_promo_callback_int(data, prefix, minimum=None):

    if not isinstance(data, str) or not data.startswith(prefix):

        return None


    return parse_ad_promo_int(data.replace(prefix, "", 1), minimum=minimum)


def parse_ad_promo_campaign_suffix(data, prefix):

    if not isinstance(data, str) or not data.startswith(prefix):

        return None, None


    raw_value = data.replace(prefix, "", 1)

    if "_" not in raw_value:

        return None, None


    campaign_id_text, suffix = raw_value.split("_", 1)
    campaign_id = parse_ad_promo_int(campaign_id_text, minimum=1)

    return campaign_id, suffix if campaign_id else None



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "he atendido el botón" de "esto no es mío" sin tocar
# ningún return del código movido: cualquier rama que atienda hace un return
# normal (que devuelve None), y solo el final devuelve el centinela.
#
# No se usa un guardián por prefijo justamente por admin_add_group: startswith
# ("admin_ad") lo capturaría y dejaría de funcionar.

NOT_HANDLED = object()


async def handle_ad_promo_callbacks(update, context, query, user_id, data):

    if data == "admin_ad_promo":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )
        campaigns = fetch_visible_ad_promo_campaigns(user_id, group_id=group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_panel_text(campaigns),
            reply_markup=build_ad_promo_panel_keyboard()
        )

        return


    if data == "admin_ad_promo_campaigns":

        group_id = get_selected_group_for_permissions(
            context,
            user_id,
            ["can_manage_groups"]
        )
        campaigns = fetch_visible_ad_promo_campaigns(user_id, group_id=group_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_campaigns_text(campaigns),
            reply_markup=build_ad_promo_campaigns_keyboard(campaigns)
        )

        return


    if data == "admin_ad_promo_create":

        context.user_data.pop("ad_promo_wizard", None)
        context.user_data["ad_promo_create"] = {}

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_group_selection_text(),
            reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
        )

        return


    if data.startswith("admin_ad_promo_create_page_"):

        page = extract_commercial_request_id(
            data,
            "admin_ad_promo_create_page_"
        )

        if page is None:

            page = 0


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_group_selection_text(),
            reply_markup=build_ad_promo_group_selection_keyboard(page=page, user_id=user_id)
        )

        return


    if data.startswith("admin_ad_promo_select_group_"):

        group_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_select_group_"
        )
        group_row = fetch_ad_promo_selectable_group(group_id)

        if not group_row:

            await query.message.reply_text(
                "❌ Comunidad no encontrada.",
                reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
            )

            return


        context.user_data["ad_promo_create"] = {
            "paid_group_id": group_id
        }
        context.user_data["ad_promo_wizard"] = {
            "step": "source_choice",
            "data": {
                "paid_group_id": group_id
            }
        }

        await query.message.reply_text(
            build_ad_promo_source_choice_text(),
            reply_markup=build_ad_promo_source_choice_keyboard()
        )

        return


    if data == "admin_ad_promo_use_paid_as_source":

        wizard = context.user_data.get("ad_promo_wizard")
        paid_group_id = (wizard.get("data") or {}).get("paid_group_id") if wizard else None
        group_row = fetch_group_basic_info(paid_group_id) if paid_group_id else None

        if not wizard or not group_row:

            await query.message.reply_text(
                "⚠️ Primero elige la comunidad de pago.",
                reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
            )

            return


        _group_id, name, telegram_group_id, community_type = group_row

        if not telegram_group_id:

            await query.message.reply_text(
                "⚠️ Esta comunidad no tiene grupo/canal de Telegram vinculado. Elige otro origen o usa el reenvío/manual.",
                reply_markup=build_ad_promo_source_choice_keyboard()
            )

            return


        wizard = save_ad_promo_wizard_chat(
            wizard,
            "source",
            telegram_group_id,
            title=name,
            chat_type=community_type
        )
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            "✅ Usaremos esta misma comunidad como fuente de vídeos.\n\n"
            f"{build_ad_promo_promo_choice_text()}",
            reply_markup=build_ad_promo_promo_choice_keyboard()
        )

        return


    if data == "admin_ad_promo_choose_source":

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard:

            await query.message.reply_text(
                "⚠️ Primero elige la comunidad de pago.",
                reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
            )

            return


        wizard["step"] = "source_choice"
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            build_ad_promo_source_choice_text(),
            reply_markup=build_ad_promo_source_choice_keyboard()
        )

        return


    if data == "admin_ad_promo_manual_source":

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard:

            await query.message.reply_text(
                "⚠️ Primero elige la comunidad de pago.",
                reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
            )

            return


        wizard["step"] = "manual_source"
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            "✍️ Introduce el chat_id del grupo/canal fuente.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Volver", callback_data="admin_ad_promo_choose_source")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
            ])
        )

        return


    if data in (
        "admin_ad_promo_retry_source_forward",
        "admin_ad_promo_source_picker"
    ) or data.startswith("admin_ad_promo_source_picker_page_"):

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard:

            await query.message.reply_text(
                "⚠️ Primero elige la comunidad de pago.",
                reply_markup=build_ad_promo_group_selection_keyboard(page=0, user_id=user_id)
            )

            return


        if data == "admin_ad_promo_retry_source_forward":

            wizard["step"] = "source_forward"
            context.user_data["ad_promo_wizard"] = wizard

            await query.message.reply_text(
                AD_PROMO_SOURCE_FORWARD_TEXT,
                reply_markup=build_ad_promo_forward_keyboard(
                    "admin_ad_promo_manual_source",
                    back_callback="admin_ad_promo_choose_source"
                )
            )

            return


        page = 0

        if data.startswith("admin_ad_promo_source_picker_page_"):

            page = extract_commercial_request_id(
                data,
                "admin_ad_promo_source_picker_page_"
            ) or 0


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_chat_picker_text("source"),
            reply_markup=build_ad_promo_chat_picker_keyboard("source", page=page)
        )

        return


    if data.startswith("admin_ad_promo_select_source_"):

        wizard = context.user_data.get("ad_promo_wizard")
        telegram_group_id = parse_ad_promo_callback_int(
            data,
            "admin_ad_promo_select_source_"
        )
        chat_row = fetch_ad_promo_managed_chat_by_telegram_id(telegram_group_id)

        if not wizard or not chat_row:

            await query.message.reply_text(
                "❌ Grupo/canal fuente no encontrado.",
                reply_markup=build_ad_promo_chat_picker_keyboard("source")
            )

            return


        _group_id, name, chat_id, community_type = chat_row
        wizard = save_ad_promo_wizard_chat(
            wizard,
            "source",
            chat_id,
            title=name,
            chat_type=community_type
        )
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            "✅ Fuente configurada.\n\n"
            f"{build_ad_promo_promo_choice_text()}",
            reply_markup=build_ad_promo_promo_choice_keyboard()
        )

        return


    if data == "admin_ad_promo_choose_promo":

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard or not (wizard.get("data") or {}).get("source_chat_id"):

            await query.message.reply_text(
                "⚠️ Primero configura el grupo/canal fuente.",
                reply_markup=build_ad_promo_source_choice_keyboard()
            )

            return


        wizard["step"] = "promo_choice"
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            build_ad_promo_promo_choice_text(),
            reply_markup=build_ad_promo_promo_choice_keyboard()
        )

        return


    if data == "admin_ad_promo_manual_promo":

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard or not (wizard.get("data") or {}).get("source_chat_id"):

            await query.message.reply_text(
                "⚠️ Primero configura el grupo/canal fuente.",
                reply_markup=build_ad_promo_forward_keyboard("admin_ad_promo_manual_source")
            )

            return


        wizard["step"] = "manual_promo"
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            "✍️ Introduce el chat_id del grupo/canal gratuito donde se publicará la publicidad.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Volver a destino", callback_data="admin_ad_promo_choose_promo")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="admin_ad_promo_cancel")]
            ])
        )

        return


    if data in (
        "admin_ad_promo_retry_promo_forward",
        "admin_ad_promo_promo_picker"
    ) or data.startswith("admin_ad_promo_promo_picker_page_"):

        wizard = context.user_data.get("ad_promo_wizard")

        if not wizard or not (wizard.get("data") or {}).get("source_chat_id"):

            await query.message.reply_text(
                "⚠️ Primero configura el grupo/canal fuente.",
                reply_markup=build_ad_promo_forward_fallback_keyboard("source")
            )

            return


        if data == "admin_ad_promo_retry_promo_forward":

            wizard["step"] = "promo_forward"
            context.user_data["ad_promo_wizard"] = wizard

            await query.message.reply_text(
                AD_PROMO_PROMO_FORWARD_TEXT,
                reply_markup=build_ad_promo_forward_keyboard(
                    "admin_ad_promo_manual_promo",
                    back_callback="admin_ad_promo_choose_promo"
                )
            )

            return


        page = 0

        if data.startswith("admin_ad_promo_promo_picker_page_"):

            page = extract_commercial_request_id(
                data,
                "admin_ad_promo_promo_picker_page_"
            ) or 0


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_chat_picker_text("promo"),
            reply_markup=build_ad_promo_chat_picker_keyboard("promo", page=page)
        )

        return


    if data.startswith("admin_ad_promo_select_promo_"):

        wizard = context.user_data.get("ad_promo_wizard")
        telegram_group_id = parse_ad_promo_callback_int(
            data,
            "admin_ad_promo_select_promo_"
        )
        chat_row = fetch_ad_promo_managed_chat_by_telegram_id(telegram_group_id)

        if not wizard or not chat_row:

            await query.message.reply_text(
                "❌ Grupo/canal destino no encontrado.",
                reply_markup=build_ad_promo_chat_picker_keyboard("promo")
            )

            return


        _group_id, name, chat_id, community_type = chat_row
        wizard = save_ad_promo_wizard_chat(
            wizard,
            "promo",
            chat_id,
            title=name,
            chat_type=community_type
        )
        context.user_data["ad_promo_wizard"] = wizard

        await query.message.reply_text(
            "✅ Grupo/canal gratuito configurado.\n\n"
            f"{AD_PROMO_CREATE_STEPS[0][1]}"
        )

        return


    if data == "admin_ad_promo_cancel":

        context.user_data.pop("ad_promo_wizard", None)
        context.user_data.pop("ad_promo_create", None)

        await query.message.reply_text(
            "❌ Creación de campaña cancelada.",
            reply_markup=build_ad_promo_panel_keyboard()
        )

        return


    if data.startswith("admin_ad_promo_watermark_mode_"):

        campaign_id, mode = parse_ad_promo_campaign_suffix(
            data,
            "admin_ad_promo_watermark_mode_"
        )
        mode = normalize_ad_promo_watermark_mode(mode)
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        campaign = update_ad_promo_campaign(
            campaign_id,
            {"watermark_mode": mode},
            actor_user_id=user_id
        )
        log_event(
            "ad_promo_watermark_mode_updated",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Modo de marca de agua actualizado.",
            metadata={"campaign_id": campaign_id, "watermark_mode": mode}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_watermark_text(campaign),
            reply_markup=build_ad_promo_watermark_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_watermark_position_"):

        campaign_id, position = parse_ad_promo_campaign_suffix(
            data,
            "admin_ad_promo_watermark_position_"
        )
        position = normalize_ad_promo_watermark_position(position)
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        campaign = update_ad_promo_campaign(
            campaign_id,
            {"watermark_position": position},
            actor_user_id=user_id
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_watermark_text(campaign),
            reply_markup=build_ad_promo_watermark_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_watermark_text_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_watermark_text_"
        )

        if not fetch_ad_promo_campaign(campaign_id):

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        context.user_data["ad_promo_edit"] = {
            "campaign_id": campaign_id,
            "field": "watermark_text"
        }

        await query.message.reply_text(
            "✏️ Escribe el nuevo texto de marca de agua, máximo 40 caracteres.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"admin_ad_promo_watermark_{campaign_id}")]
            ])
        )

        return


    if data.startswith("admin_ad_promo_watermark_opacity_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_watermark_opacity_"
        )

        if not fetch_ad_promo_campaign(campaign_id):

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        context.user_data["ad_promo_edit"] = {
            "campaign_id": campaign_id,
            "field": "watermark_opacity"
        }

        await query.message.reply_text(
            "🌫 Escribe la opacidad de la marca de agua.\n\n"
            "Puedes enviar un decimal de 0.1 a 1.0 o un porcentaje de 10 a 100.\n"
            "Ejemplos: 0.75, 75, 100",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"admin_ad_promo_watermark_{campaign_id}")]
            ])
        )

        return


    if data.startswith("admin_ad_promo_watermark_limits_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_watermark_limits_"
        )

        if not fetch_ad_promo_campaign(campaign_id):

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        context.user_data["ad_promo_edit"] = {
            "campaign_id": campaign_id,
            "field": "watermark_limits"
        }

        await query.message.reply_text(
            "⚙️ Envía límite de tamaño y duración como dos números.\n\nEjemplo: 50 180",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"admin_ad_promo_watermark_{campaign_id}")]
            ])
        )

        return


    if data.startswith("admin_ad_promo_watermark_test_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_watermark_test_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        result = await send_ad_promo_campaign_batch(
            context,
            campaign,
            test=True
        )

        await query.message.reply_text(
            build_ad_promo_test_result_text(result, watermark=True),
            reply_markup=build_ad_promo_test_result_keyboard(campaign, result, watermark=True)
        )

        return


    if data.startswith("admin_ad_promo_watermark_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_watermark_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_watermark_text(campaign),
            reply_markup=build_ad_promo_watermark_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_diagnostics_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_diagnostics_"
        )
        diagnostics = fetch_ad_promo_campaign_diagnostics(campaign_id)

        if not diagnostics:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        campaign = diagnostics.get("campaign")
        log_event(
            "ad_promo_diagnostics_viewed",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Diagnóstico de campaña promocional consultado.",
            metadata={"campaign_id": campaign_id}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            format_ad_promo_campaign_diagnostics(diagnostics),
            reply_markup=build_ad_promo_diagnostics_keyboard(campaign_id)
        )

        return


    if data.startswith("admin_ad_promo_generate_captions_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_generate_captions_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        saved, source = generate_ad_promo_caption_variants(campaign)
        log_event(
            "ad_promo_captions_generated",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Captions promocionales generados.",
            metadata={
                "campaign_id": campaign_id,
                "count": len(saved),
                "source": source
            }
        )

        await query.message.reply_text(
            f"✅ Se han generado {len(saved)} captions para esta campaña.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Ver captions", callback_data=f"admin_ad_promo_copy_variants_{campaign_id}")],
                [InlineKeyboardButton("🧪 Enviar prueba", callback_data=f"admin_ad_promo_test_{campaign_id}")],
                [InlineKeyboardButton("🔙 Volver campaña", callback_data=f"admin_ad_promo_campaign_{campaign_id}")]
            ])
        )

        return


    if data.startswith("ad_promo_regenerate_copy_yes_"):

        campaign_id = extract_commercial_request_id(
            data,
            "ad_promo_regenerate_copy_yes_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        result = regenerate_ad_promo_copy_variants(campaign_id)

        if not result.get("ok"):

            await query.message.reply_text(
                "❌ No he podido regenerar textos para esta campaña.",
                reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
            )

            return


        log_event(
            "ad_promo_copy_variants_regenerated",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Variantes de copy promocional regeneradas.",
            metadata={
                "campaign_id": campaign_id,
                "disabled_count": result.get("disabled_count"),
                "generated_count": result.get("generated_count"),
                "source": result.get("source")
            }
        )
        source_label = {
            "ai": "IA",
            "template": "template",
            "mixed": "mixed"
        }.get(result.get("source"), result.get("source") or "-")
        text = (
            "✅ Textos regenerados\n\n"
            f"Variantes antiguas desactivadas: {result.get('disabled_count')}\n"
            f"Nuevas variantes generadas: {result.get('generated_count')}\n"
            f"Fuente: {source_label}\n\n"
            "A partir de ahora la campaña usará textos nuevos orientados a conversión."
        )

        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁 Ver variantes", callback_data=f"admin_ad_promo_copy_variants_{campaign_id}")],
                [InlineKeyboardButton("⬅️ Volver a campaña", callback_data=f"admin_ad_promo_campaign_{campaign_id}")]
            ])
        )

        return


    if data.startswith("ad_promo_regenerate_copy_"):

        campaign_id = extract_commercial_request_id(
            data,
            "ad_promo_regenerate_copy_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        await query.message.reply_text(
            (
                "⚠️ Esto desactivará las variantes de texto actuales de esta campaña y generará nuevas variantes con el prompt mejorado.\n\n"
                "No se borrarán vídeos, campañas ni configuración de pagos.\n\n"
                "¿Continuar?"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sí, regenerar textos", callback_data=f"ad_promo_regenerate_copy_yes_{campaign_id}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"admin_ad_promo_campaign_{campaign_id}")]
            ])
        )

        return


    if data.startswith("admin_ad_promo_copy_variants_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_copy_variants_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        rows = fetch_ad_promo_copy_variants(campaign_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_copy_variants_text(campaign, rows),
            reply_markup=build_ad_promo_copy_variants_keyboard(campaign, rows)
        )

        return


    if data.startswith("admin_ad_promo_copy_off_"):

        variant_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_copy_off_"
        )
        campaign_id = disable_ad_promo_copy_variant(variant_id)

        if not campaign_id:

            await query.message.reply_text(
                "❌ Caption no encontrado.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        campaign = fetch_ad_promo_campaign(campaign_id)
        rows = fetch_ad_promo_copy_variants(campaign_id)
        log_event(
            "ad_promo_copy_variant_disabled",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id") if campaign else None,
            actor_user_id=user_id,
            message="Caption promocional desactivado.",
            metadata={
                "campaign_id": campaign_id,
                "variant_id": variant_id
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Caption desactivado.\n\n" + build_ad_promo_copy_variants_text(campaign, rows),
            reply_markup=build_ad_promo_copy_variants_keyboard(campaign, rows)
        )

        return


    if data.startswith("admin_ad_promo_optimize_rotation_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_optimize_rotation_"
        )
        result = optimize_ad_promo_rotation(
            campaign_id,
            actor_user_id=user_id
        )

        if not result:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        campaign, notes = result
        log_event(
            "ad_promo_rotation_optimized",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Rotación de campaña promocional optimizada.",
            metadata={
                "campaign_id": campaign_id,
                "notes": notes
            }
        )

        await query.message.reply_text(
            "✅ Rotación optimizada\n"
            + "\n".join(f"- {note}" for note in notes),
            reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_delete_campaign_yes_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_delete_campaign_yes_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "⚠️ La campaña ya no existe o ya fue eliminada.",
                reply_markup=build_ad_promo_campaigns_keyboard(fetch_ad_promo_campaigns())
            )

            return


        try:

            deleted_campaign = delete_ad_promo_campaign(campaign_id)

        except Exception as e:

            await query.message.reply_text(
                f"❌ No se pudo eliminar la campaña: {str(e)[:300]}",
                reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
            )

            return


        log_event(
            "ad_promo_campaign_deleted",
            category="marketing",
            severity="info",
            scope="group",
            group_id=deleted_campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Campaña de promoción automática eliminada.",
            metadata={
                "campaign_id": deleted_campaign.get("id"),
                "paid_group_id": deleted_campaign.get("paid_group_id"),
                "source_chat_id": deleted_campaign.get("source_chat_id"),
                "promo_group_telegram_id": deleted_campaign.get("promo_group_telegram_id"),
                "deleted_related_counts": deleted_campaign.get("deleted_related_counts")
            }
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Campaña eliminada correctamente.",
            reply_markup=build_ad_promo_campaigns_keyboard(fetch_ad_promo_campaigns())
        )

        return


    if data.startswith("admin_ad_promo_delete_campaign_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_delete_campaign_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "⚠️ La campaña no existe o ya fue eliminada.",
                reply_markup=build_ad_promo_campaigns_keyboard(fetch_ad_promo_campaigns())
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_delete_campaign_text(campaign),
            reply_markup=build_ad_promo_delete_campaign_keyboard(campaign_id)
        )

        return


    if data.startswith("admin_ad_promo_campaign_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_campaign_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text(
                "❌ Campaña no encontrada.",
                reply_markup=build_ad_promo_panel_keyboard()
            )

            return


        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_campaign_detail_text(campaign),
            reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_library_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_library_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        media_rows = fetch_ad_promo_media(campaign_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_library_text(campaign, media_rows),
            reply_markup=build_ad_promo_library_keyboard(campaign, media_rows)
        )

        return


    if data.startswith("admin_ad_promo_media_off_"):

        media_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_media_off_"
        )
        campaign_id = deactivate_ad_promo_media(media_id)

        if not campaign_id:

            await query.message.reply_text("❌ Vídeo no encontrado.")
            return


        campaign = fetch_ad_promo_campaign(campaign_id)
        media_rows = fetch_ad_promo_media(campaign_id)

        await send_clean_message(
            context,
            query.message.chat_id,
            "✅ Vídeo desactivado.\n\n" + build_ad_promo_library_text(campaign, media_rows),
            reply_markup=build_ad_promo_library_keyboard(campaign, media_rows)
        )

        return


    ad_promo_toggle_prefixes = {
        "admin_ad_promo_random_": "randomize_media",
        "admin_ad_promo_ai_": "ai_copy_enabled",
        "admin_ad_promo_capture_": "auto_capture_enabled"
    }

    for prefix, field in ad_promo_toggle_prefixes.items():

        if data.startswith(prefix):

            campaign_id = extract_commercial_request_id(data, prefix)
            campaign = fetch_ad_promo_campaign(campaign_id)

            if not campaign:

                await query.message.reply_text("❌ Campaña no encontrada.")
                return


            campaign = update_ad_promo_campaign(
                campaign_id,
                {field: not campaign.get(field)},
                actor_user_id=user_id
            )

            log_event(
                "ad_promo_campaign_updated",
                category="marketing",
                severity="info",
                scope="group",
                group_id=campaign.get("paid_group_id"),
                actor_user_id=user_id,
                message="Configuración de campaña promocional actualizada.",
                metadata={"campaign_id": campaign_id, "field": field}
            )

            await send_clean_message(
                context,
                query.message.chat_id,
                build_ad_promo_campaign_detail_text(campaign),
                reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
            )

            return


    if data.startswith("admin_ad_promo_pause_") or data.startswith("admin_ad_promo_resume_"):

        is_resume = data.startswith("admin_ad_promo_resume_")
        prefix = "admin_ad_promo_resume_" if is_resume else "admin_ad_promo_pause_"
        campaign_id = extract_commercial_request_id(data, prefix)
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        resume_updates = {"is_paused": not is_resume}

        if is_resume:

            # Al reanudar a mano se limpia el contador y el motivo, para que la
            # campaña no vuelva a autopausarse por los fallos ya resueltos.
            resume_updates["consecutive_failures"] = 0
            resume_updates["paused_reason"] = None

        campaign = update_ad_promo_campaign(
            campaign_id,
            resume_updates,
            actor_user_id=user_id
        )

        log_event(
            "ad_promo_campaign_resumed" if is_resume else "ad_promo_campaign_paused",
            category="marketing",
            severity="info",
            scope="group",
            group_id=campaign.get("paid_group_id"),
            actor_user_id=user_id,
            message="Campaña promocional reanudada." if is_resume else "Campaña promocional pausada.",
            metadata={"campaign_id": campaign_id}
        )

        await send_clean_message(
            context,
            query.message.chat_id,
            build_ad_promo_campaign_detail_text(campaign),
            reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
        )

        return


    if data.startswith("admin_ad_promo_test_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_test_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        result = await send_ad_promo_campaign_batch(
            context,
            campaign,
            test=True
        )

        await query.message.reply_text(
            build_ad_promo_test_result_text(result),
            reply_markup=build_ad_promo_test_result_keyboard(campaign, result)
        )

        return


    if data.startswith("admin_ad_promo_delete_old_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_delete_old_"
        )
        campaign = fetch_ad_promo_campaign(campaign_id)

        if not campaign:

            await query.message.reply_text("❌ Campaña no encontrada.")
            return


        result = await delete_old_ad_promo_posts(context, campaign)

        await query.message.reply_text(
            "🗑 Borrado rotativo ejecutado\n\n"
            f"Borrados: {result.get('deleted', 0)}\n"
            f"Fallidos: {result.get('failed', 0)}",
            reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
        )

        return


    ad_promo_edit_prefixes = {
        "admin_ad_promo_edit_offer_": ("offer_text", "Escribe el nuevo texto de oferta."),
        "admin_ad_promo_edit_price_": ("price_text", "Escribe el nuevo texto de precio."),
        "admin_ad_promo_edit_cta_": ("cta_text", "Escribe el nuevo CTA."),
        "admin_ad_promo_edit_frequency_": ("interval_minutes", "Escribe la nueva frecuencia en minutos, mínimo 5."),
        "admin_ad_promo_edit_batch_": ("batch_size", "Escribe cuántos vídeos por tanda, mínimo 1."),
        "admin_ad_promo_edit_maxposts_": ("max_posts", "Escribe el nuevo cupo máximo de posts visibles, mínimo 1."),
        "admin_ad_promo_edit_botlink_": ("bot_link", "Escribe el nuevo bot_link o auto.")
    }

    for prefix, (field, prompt) in ad_promo_edit_prefixes.items():

        if data.startswith(prefix):

            campaign_id = extract_commercial_request_id(data, prefix)

            if not fetch_ad_promo_campaign(campaign_id):

                await query.message.reply_text("❌ Campaña no encontrada.")
                return


            context.user_data["ad_promo_edit"] = {
                "campaign_id": campaign_id,
                "field": field
            }

            await query.message.reply_text(
                prompt,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"admin_ad_promo_campaign_{campaign_id}")]
                ])
            )

            return


    if data.startswith("admin_ad_promo_keep_offer_"):

        campaign_id = extract_commercial_request_id(
            data,
            "admin_ad_promo_keep_offer_"
        )
        campaign = update_ad_promo_campaign(
            campaign_id,
            {
                "last_offer_check_at": datetime.now(),
                "next_offer_check_at": datetime.now() + timedelta(hours=24)
            },
            actor_user_id=user_id
        )

        await query.message.reply_text(
            "✅ Se mantiene la configuración actual.",
            reply_markup=build_ad_promo_campaign_detail_keyboard(campaign)
        )

        return

    return NOT_HANDLED
