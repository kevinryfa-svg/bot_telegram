"""
Comprobar que una comunidad todavía puede entregar lo que vende.

Para crear el enlace de acceso, Telegram exige que el bot sea administrador del
grupo con permiso de invitar. Si el propietario lo degrada o le quita ese
permiso, createChatInviteLink falla y el comprador se queda sin enlace.

Ese fallo ya está tapado por el lado del cliente —ahora recibe un aviso con un
botón para pedir el enlace en vez de silencio—, pero eso trata el síntoma: la
venta no debería haber ocurrido. Y groups.bot_is_admin no servía para detectarlo,
porque solo se escribe al registrar la comunidad y nunca vuelve a FALSE, así que
una comunidad degradada seguía en el mercado cobrando sin poder entregar.

Este módulo pregunta a Telegram de verdad, guarda el resultado, avisa al
propietario cuando se rompe y cuando se arregla, y da la respuesta que necesita
el camino de cobro para no aceptar dinero que no puede cumplir.

Dos decisiones que importan:

  - un fallo de red no es una pérdida de permisos. Solo se considera roto tras
    FAILURES_BEFORE_BROKEN comprobaciones seguidas con el mismo resultado, para
    no bloquear ventas legítimas por un corte pasajero;
  - ante la duda, se deja vender. Si no se puede saber el estado, bloquear la
    compra haría más daño que dejarla pasar: el aviso al comprador y el botón de
    pedir enlace ya cubren el caso de que falle la entrega.
"""

import requests

from db import conn
from audit_log_service import log_event
from bot_config import TOKEN, ADMIN_ID
from notification_service import notify_super_admins, send_telegram_message
from rbac_helpers import get_group_owner_user_id


# Cada cuánto se repasan todas las comunidades.
HEALTH_JOB_INTERVAL_SECONDS = 6 * 3600

# Cuántas comprobaciones seguidas fallidas hacen falta para darlo por roto.
FAILURES_BEFORE_BROKEN = 2

# Cada cuánto se puede repetir el aviso al propietario si sigue roto.
OWNER_REMINDER_HOURS = 24

# Cuántas comunidades se repasan por vuelta, para no agotar la cuota de
# Telegram en instalaciones con muchos grupos.
HEALTH_BATCH_LIMIT = 60

REQUEST_TIMEOUT_SECONDS = 15


# Estados en los que el bot sigue dentro del grupo con mando.
ADMIN_STATUSES = ("administrator", "creator")


# =========================
# PREGUNTAR A TELEGRAM
# =========================

def fetch_bot_membership(token, telegram_group_id, bot_user_id):
    """
    Devuelve la ficha del bot en el grupo, o None si no se pudo preguntar.

    None significa "no se sabe", que no es lo mismo que "no puede entregar".
    """

    try:

        response = requests.post(
            f"https://api.telegram.org/bot{token}/getChatMember",
            json={
                "chat_id": telegram_group_id,
                "user_id": bot_user_id
            },
            timeout=REQUEST_TIMEOUT_SECONDS
        ).json()

    except Exception as e:

        print("Salud de entrega: no se pudo preguntar a Telegram:", e)

        return None


    if not response.get("ok"):

        # Telegram ha contestado, y ha contestado que no. Eso sí es información:
        # el grupo puede no existir, o el bot puede haber sido expulsado.
        return {
            "ok": False,
            "description": str(response.get("description") or "")[:200]
        }


    return {
        "ok": True,
        "result": response.get("result") or {}
    }


def evaluate_membership(membership):
    """
    Traduce la respuesta de Telegram a (puede_entregar, estado, detalle).

    puede_entregar es None cuando no se ha podido averiguar.
    """

    if membership is None:

        return (None, None, "no se pudo consultar")


    if not membership.get("ok"):

        detalle = membership.get("description") or "Telegram rechazó la consulta"

        return (False, "unknown", detalle)


    result = membership.get("result") or {}
    status = result.get("status")


    if status not in ADMIN_STATUSES:

        return (
            False,
            status,
            f"el bot no es administrador (estado: {status})"
        )


    # Ser administrador no basta: hace falta el permiso concreto de invitar. El
    # creador del grupo los tiene todos y Telegram no siempre los enumera.
    if status == "creator":

        return (True, status, "administrador con todos los permisos")


    if result.get("can_invite_users") is False:

        return (
            False,
            status,
            "es administrador pero sin permiso para invitar"
        )


    return (True, status, "administrador con permiso de invitar")


# =========================
# GUARDAR EL RESULTADO
# =========================

def fetch_health(group_id):
    """Devuelve (can_deliver, consecutive_failures, broken_since, owner_notified_at)."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT can_deliver,
                       COALESCE(consecutive_failures, 0),
                       broken_since,
                       owner_notified_at
                FROM group_delivery_health
                WHERE group_id = %s

            """, (group_id,))

            return cur.fetchone()

    except Exception as e:

        print("Salud de entrega: error leyendo el estado:", e)

        return None


def record_health(group_id, can_deliver, bot_status, detail,
                  consecutive_failures, mark_broken, clear_broken,
                  mark_notified=False):
    """Guarda el resultado de una comprobación."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO group_delivery_health
                    (group_id, can_deliver, bot_status, detail,
                     consecutive_failures, checked_at, broken_since,
                     owner_notified_at)
                VALUES
                    (%s, %s, %s, %s, %s, NOW(),
                     CASE WHEN %s THEN NOW() ELSE NULL END,
                     CASE WHEN %s THEN NOW() ELSE NULL END)
                ON CONFLICT (group_id) DO UPDATE SET
                    can_deliver = EXCLUDED.can_deliver,
                    bot_status = EXCLUDED.bot_status,
                    detail = EXCLUDED.detail,
                    consecutive_failures = EXCLUDED.consecutive_failures,
                    checked_at = NOW(),
                    broken_since = CASE
                        WHEN %s THEN NULL
                        WHEN %s AND group_delivery_health.broken_since IS NULL THEN NOW()
                        ELSE group_delivery_health.broken_since
                    END,
                    owner_notified_at = CASE
                        WHEN %s THEN NULL
                        WHEN %s THEN NOW()
                        ELSE group_delivery_health.owner_notified_at
                    END

            """, (
                group_id, can_deliver, bot_status, detail,
                consecutive_failures, bool(mark_broken), bool(mark_notified),
                bool(clear_broken), bool(mark_broken),
                bool(clear_broken), bool(mark_notified)
            ))

            return True

    except Exception as e:

        print("Salud de entrega: error guardando el estado:", e)

        return False


def set_group_bot_is_admin(group_id, value):
    """
    Mantiene groups.bot_is_admin al día.

    Existía desde el principio pero solo se escribía al registrar, así que se
    quedaba en TRUE para siempre. Otras partes del bot lo consultan.
    """

    try:

        with conn.cursor() as cur:

            cur.execute(
                "UPDATE groups SET bot_is_admin = %s WHERE id = %s",
                (bool(value), group_id)
            )

            return True

    except Exception as e:

        print("Salud de entrega: error actualizando bot_is_admin:", e)

        return False


def owner_reminder_is_due(owner_notified_at):
    """
    Evita repetir el mismo aviso cada vuelta del trabajo.

    Se decide en SQL para no depender del reloj del proceso ni de la zona
    horaria con la que se guardó la marca.
    """

    if owner_notified_at is None:

        return True


    try:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT (NOW() - %s) > (%s * INTERVAL '1 hour')",
                (owner_notified_at, OWNER_REMINDER_HOURS)
            )

            row = cur.fetchone()

        return bool(row[0]) if row else True

    except Exception as e:

        print("Salud de entrega: error comprobando el último aviso:", e)

        # Ante la duda, no repetir: molestar al propietario cada seis horas es
        # peor que tardar un día en recordárselo.
        return False


# =========================
# COMUNIDADES A REPASAR
# =========================

def fetch_groups_to_check(limit=HEALTH_BATCH_LIMIT):
    """
    Comunidades activas que cobran por entrar.

    Las gratuitas quedan fuera: no hay dinero que perder si el enlace falla, y
    consumirían la cuota de Telegram sin necesidad. Se empieza por las que más
    tiempo llevan sin comprobar.
    """

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id,
                       g.name,
                       g.telegram_group_id
                FROM groups g
                LEFT JOIN group_delivery_health h
                       ON h.group_id = g.id
                WHERE COALESCE(g.is_active, TRUE) = TRUE
                  AND COALESCE(g.is_free_group, FALSE) = FALSE
                  AND g.telegram_group_id IS NOT NULL
                ORDER BY h.checked_at ASC NULLS FIRST,
                         g.id ASC
                LIMIT %s

            """, (limit,))

            return cur.fetchall() or []

    except Exception as e:

        print("Salud de entrega: error listando comunidades:", e)

        return []


# =========================
# AVISOS
# =========================

def build_broken_notice(group_name, detail):
    """
    Aviso al propietario. Va en su idioma de trabajo (español), no traducido:
    es un mensaje de administración, no del cliente.
    """

    return (
        "⚠️ No se puede dar acceso a tu comunidad\n\n"
        f"Comunidad: {group_name}\n"
        f"Motivo: {detail}\n\n"
        "El bot necesita ser administrador del grupo con el permiso "
        "«Invitar usuarios mediante enlace» para poder crear el enlace de "
        "acceso de cada persona que compra.\n\n"
        "Mientras siga así, las compras de esta comunidad se rechazan en vez de "
        "cobrar sin poder entregar.\n\n"
        "Cómo arreglarlo: abre el grupo → Administradores → el bot → activa "
        "«Invitar usuarios mediante enlace»."
    )


def build_recovered_notice(group_name):

    return (
        "✅ Tu comunidad vuelve a poder dar acceso\n\n"
        f"Comunidad: {group_name}\n\n"
        "El bot ya puede crear enlaces de acceso otra vez. Las compras vuelven "
        "a estar abiertas."
    )


def notify_owner(group_id, text):
    """Avisa al propietario y a los super administradores."""

    enviados = 0

    try:

        owner_user_id = get_group_owner_user_id(group_id)

        if owner_user_id:

            respuesta = send_telegram_message(TOKEN, owner_user_id, text)

            if respuesta and respuesta.get("ok"):

                enviados += 1

    except Exception as e:

        print("Salud de entrega: no se pudo avisar al propietario:", e)


    try:

        enviados += notify_super_admins(TOKEN, text, fallback_admin_id=ADMIN_ID)

    except Exception as e:

        print("Salud de entrega: no se pudo avisar a los super admins:", e)


    return enviados


# =========================
# UNA COMUNIDAD
# =========================

def apply_delivery_result(group_id, group_name, can_deliver, bot_status, detail,
                          notify=True):
    """
    Guarda el resultado de una comprobación y avisa si el estado ha cambiado.

    Vive aparte de quien pregunta a Telegram porque hay dos que preguntan: el
    trabajo periódico, que usa la API HTTP desde un hilo, y el camino de cobro,
    que usa el bot asíncrono. La decisión de qué guardar y a quién avisar tiene
    que ser la misma en los dos.
    """

    summary = {
        "group_id": group_id,
        "can_deliver": can_deliver,
        "changed": False,
        "notified": False,
        "detail": detail or ""
    }


    if can_deliver is None:

        # No se ha podido averiguar: no se toca nada. Marcarlo como roto por un
        # corte de red bloquearía ventas que sí se podían entregar.
        return summary


    anterior = fetch_health(group_id)
    antes_podia = anterior[0] if anterior else None
    fallos_previos = anterior[1] if anterior else 0
    avisado_en = anterior[3] if anterior else None


    if can_deliver:

        record_health(
            group_id, True, bot_status, detail,
            consecutive_failures=0,
            mark_broken=False,
            clear_broken=True
        )

        set_group_bot_is_admin(group_id, True)

        # Solo se avisa de la recuperación si antes se avisó de la avería.
        if antes_podia is False and notify:

            summary["changed"] = True

            if notify_owner(group_id, build_recovered_notice(group_name)):

                summary["notified"] = True


            log_event(
                "group_delivery_recovered",
                category="group",
                severity="info",
                scope="group",
                group_id=group_id,
                message="La comunidad vuelve a poder crear enlaces de acceso.",
                metadata={"bot_status": bot_status}
            )

        return summary


    fallos = int(fallos_previos or 0) + 1
    confirmado = fallos >= FAILURES_BEFORE_BROKEN

    # Estado efectivo: mientras no esté confirmado se sigue pudiendo vender. El
    # resumen devuelve esto y no el resultado crudo de la consulta, porque quien
    # lo lee es el guardián del cobro y tiene que ver lo mismo que está guardado.
    efectivo = (not confirmado) and (antes_podia is not False)

    record_health(
        group_id, efectivo, bot_status, detail,
        consecutive_failures=fallos,
        mark_broken=confirmado,
        clear_broken=False
    )

    summary["can_deliver"] = efectivo


    if not confirmado:

        # Primer fallo: se apunta, pero no se da por roto todavía.
        return summary


    set_group_bot_is_admin(group_id, False)


    if notify and owner_reminder_is_due(avisado_en):

        summary["changed"] = antes_podia is not False

        if notify_owner(group_id, build_broken_notice(group_name, detail)):

            summary["notified"] = True


        record_health(
            group_id, False, bot_status, detail,
            consecutive_failures=fallos,
            mark_broken=True,
            clear_broken=False,
            mark_notified=True
        )


        log_event(
            "group_delivery_broken",
            category="group",
            severity="warning",
            scope="group",
            group_id=group_id,
            message="La comunidad no puede crear enlaces de acceso.",
            metadata={
                "bot_status": bot_status,
                "detail": detail[:200],
                "consecutive_failures": fallos
            }
        )

    return summary


def check_group_delivery(group_id, group_name, telegram_group_id, bot_user_id,
                         token=TOKEN, notify=True):
    """
    Pregunta a Telegram por la API HTTP y aplica el resultado.

    Es la que usa el trabajo periódico, que corre fuera del bucle asíncrono.
    """

    membership = fetch_bot_membership(token, telegram_group_id, bot_user_id)
    can_deliver, bot_status, detail = evaluate_membership(membership)

    return apply_delivery_result(
        group_id,
        group_name,
        can_deliver,
        bot_status,
        detail,
        notify=notify
    )


async def recheck_group_delivery_live(context, group_id, group_name,
                                     telegram_group_id, notify=True):
    """
    Vuelve a preguntar en el momento de la compra, con el bot asíncrono.

    Existe para no rechazar una venta por un dato viejo: solo se llama cuando el
    estado guardado dice que la comunidad está rota, así que el camino normal de
    compra no paga ninguna llamada extra.

    Devuelve True, False o None (no se pudo saber).
    """

    try:

        member = await context.bot.get_chat_member(
            telegram_group_id,
            context.bot.id
        )

    except Exception as e:

        print("Salud de entrega: fallo la reconsulta en la compra:", str(e)[:200])

        return None


    membership = {
        "ok": True,
        "result": {
            "status": getattr(member, "status", None),
            "can_invite_users": getattr(member, "can_invite_users", None)
        }
    }

    can_deliver, bot_status, detail = evaluate_membership(membership)

    resultado = apply_delivery_result(
        group_id,
        group_name,
        can_deliver,
        bot_status,
        detail,
        notify=notify
    )

    return resultado["can_deliver"]


# =========================
# LA PREGUNTA QUE HACE EL COBRO
# =========================

def group_can_deliver_access(group_id, allow_unknown=True):
    """
    ¿Se puede entregar el acceso a esta comunidad?

    La usa el camino de cobro para no aceptar dinero que no podrá cumplir. Solo
    devuelve False cuando consta comprobado que no se puede: si no hay dato, se
    deja vender, porque bloquear una venta por falta de información hace más daño
    que dejarla pasar.
    """

    estado = fetch_health(group_id)


    if not estado:

        return True if allow_unknown else False


    if estado[0] is False:

        return False


    return True


def describe_group_delivery(group_id):
    """Estado legible para el panel del propietario."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT can_deliver, bot_status, detail, checked_at, broken_since
                FROM group_delivery_health
                WHERE group_id = %s

            """, (group_id,))

            row = cur.fetchone()

    except Exception as e:

        print("Salud de entrega: error describiendo el estado:", e)

        return "No se pudo consultar el estado de entrega."


    if not row:

        return "Todavía sin comprobar."


    can_deliver, bot_status, detail, checked_at, broken_since = row


    if can_deliver:

        return f"✅ Puede dar acceso ({detail or bot_status or 'correcto'})."


    texto = f"⚠️ No puede dar acceso: {detail or bot_status or 'motivo desconocido'}."


    if broken_since:

        try:

            texto += f" Desde {broken_since.strftime('%d/%m/%Y %H:%M')}."

        except Exception:

            pass


    return texto


# =========================
# EL REPASO COMPLETO
# =========================

async def process_group_delivery_health(context):
    """Repasa un lote de comunidades. La llama el trabajo periódico."""

    try:

        bot_user_id = context.bot.id

    except Exception as e:

        print("Salud de entrega: no se pudo obtener el id del bot:", e)

        return {"checked": 0, "broken": 0, "notified": 0}


    grupos = fetch_groups_to_check()

    resumen = {"checked": 0, "broken": 0, "notified": 0}


    for group_id, group_name, telegram_group_id in grupos:

        try:

            resultado = check_group_delivery(
                group_id,
                group_name or f"Comunidad {group_id}",
                telegram_group_id,
                bot_user_id
            )

        except Exception as e:

            print("Salud de entrega: error comprobando la comunidad", group_id, e)

            continue


        resumen["checked"] += 1

        if resultado["can_deliver"] is False:

            resumen["broken"] += 1


        if resultado["notified"]:

            resumen["notified"] += 1


    if resumen["broken"] or resumen["notified"]:

        log_event(
            "group_delivery_health_checked",
            category="group",
            severity="info",
            message="Repaso de la capacidad de entrega de las comunidades.",
            metadata=resumen
        )


    return resumen
