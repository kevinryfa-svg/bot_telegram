"""
Los que pulsaron «pagar» y se llevaron un error.

Desde finales de agosto hasta el 4 de octubre, los tres botones de la lista de
planes de StarsVip contestaban «⚠️ Este plan no está configurado para Stripe».
Quien llegó a pulsar uno es exactamente la persona que más quería comprar:
había visto el precio, había elegido plan y había apretado «💳 Tarjeta». El bot
le dijo que no.

Son identificables con precisión: cada pulsación queda en `bot_user_events`, y
los botones de pago con tarjeta llevan el identificador de precio de Stripe
(«price_…»). Todos esos botones estaban rotos, así que todo el que pulsó uno se
llevó el error. No hace falta adivinar.

Este servicio les escribe UNA vez, para siempre, con la verdad —fue culpa
nuestra, ya está arreglado, no se te cobró nada— y un botón que va directo a
pagar. No se envía solo: lo lanza una persona desde el panel, después de ver a
cuántos va y qué dice. Es un mensaje en nombre del negocio a clientes de
verdad, y eso lo decide quien firma.
"""

import asyncio
import os

from audit_log_service import log_event
from db import conn


# Desde cuándo estaba roto. La lista empezó a pintar el precio vigente con
# #367 (23/08/2026); se deja un margen hacia atrás porque el plan anual ya tenía
# price_id ≠ stripe_price_id antes de eso.
AVERIA_DESDE = os.environ.get("AVERIA_RESCATE_DESDE", "2026-08-15")

# Hasta cuándo: el despliegue del arreglo. Pulsar DESPUÉS ya funcionaba, y a
# esa gente no hay que pedirle perdón por nada.
AVERIA_HASTA = os.environ.get("AVERIA_RESCATE_HASTA", "2026-10-04 08:50")

RESCATE_PAUSA_SEGUNDOS = float(os.environ.get("AVERIA_RESCATE_PAUSA", "0.5"))

PAGADO = ("paid", "completed", "succeeded")


def _asegurar_tabla():

    with conn.cursor() as cur:

        cur.execute("""

            CREATE TABLE IF NOT EXISTS averia_rescue_sent (
                user_id BIGINT PRIMARY KEY,
                group_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT
            )

        """)

        conn.commit()


SQL_AFECTADOS = """

    WITH pulsaciones AS (

        SELECT e.user_id,
               MAX(e.created_at) AS cuando,
               (ARRAY_AGG(e.event_key ORDER BY e.created_at DESC))[1] AS boton
        FROM bot_user_events e
        WHERE e.event_type = 'callback'
          AND e.event_key LIKE 'price\\_%%'
          AND e.created_at >= %(desde)s::timestamp
          AND e.created_at <  %(hasta)s::timestamp
          AND e.user_id IS NOT NULL
        GROUP BY e.user_id

    ),

    -- De qué comunidad era el botón: el precio puede ser el de un plan o el de
    -- una de sus ofertas (vivas o ya terminadas).
    con_grupo AS (

        SELECT pu.user_id, pu.cuando, pu.boton,
               COALESCE(
                   (SELECT p.group_id FROM plans p
                     WHERE p.stripe_price_id = pu.boton OR p.price_id = pu.boton
                     LIMIT 1),
                   -- Alias `ofr` y no `po` a propósito: `po` marca las
                   -- consultas que ENSEÑAN el precio de una oferta, y esta
                   -- solo traduce un botón viejo a su comunidad. No promete
                   -- ningún importe (lo que se dice es el precio de HOY).
                   (SELECT p.group_id FROM plan_offers ofr
                      JOIN plans p ON p.id = ofr.plan_id
                     WHERE ofr.stripe_price_id = pu.boton
                     LIMIT 1)
               ) AS group_id
        FROM pulsaciones pu

    )

    SELECT c.user_id, c.group_id, COALESCE(g.name, 'la comunidad'), c.cuando
    FROM con_grupo c
    JOIN groups g ON g.id = c.group_id
    WHERE COALESCE(g.is_active, TRUE) = TRUE

      -- Quien ya pagó después (por otra vía, o tras el arreglo) no necesita
      -- disculpas: necesita que no le molesten.
      AND NOT EXISTS (
          SELECT 1 FROM payments pa
          WHERE pa.user_id = c.user_id AND pa.group_id = c.group_id
            AND LOWER(COALESCE(pa.status, '')) = ANY(%(pagado)s)
            AND pa.payment_date >= c.cuando
      )

      -- Ni quien tiene acceso vivo.
      AND NOT EXISTS (
          SELECT 1 FROM users u
          WHERE u.user_id = c.user_id AND u.group_id = c.group_id
            AND (COALESCE(u.subscription_active, FALSE) = TRUE
                 OR (u.expiration IS NOT NULL AND u.expiration > NOW()))
      )

      AND NOT EXISTS (SELECT 1 FROM banned_users b WHERE b.user_id = c.user_id)

      -- Quien pidió no recibir avisos, o bloqueó el bot, se respeta.
      AND NOT EXISTS (
          SELECT 1 FROM user_reengagement r
          WHERE r.user_id = c.user_id
            AND (COALESCE(r.opted_out, FALSE) = TRUE
                 OR COALESCE(r.is_blocked, FALSE) = TRUE)
      )

      -- Una vez y nunca más.
      AND NOT EXISTS (
          SELECT 1 FROM averia_rescue_sent s WHERE s.user_id = c.user_id
      )

    ORDER BY c.cuando DESC

"""


def fetch_afectados(limit=None):
    """[(user_id, group_id, nombre_comunidad, cuando_pulsó)]. [] ante la duda."""

    try:

        _asegurar_tabla()

        with conn.cursor() as cur:

            cur.execute(
                SQL_AFECTADOS + (" LIMIT %(limite)s" if limit else ""),
                {
                    "desde": AVERIA_DESDE,
                    "hasta": AVERIA_HASTA,
                    "pagado": list(PAGADO),
                    "limite": int(limit) if limit else None,
                }
            )

            return cur.fetchall() or []

    except Exception as e:

        conn.rollback()
        print("Rescate de la avería: no se pudo leer la lista:", str(e)[:200])

        return []


def contar_afectados():
    """Cuántos quedan por escribir. None si no se pudo contar."""

    try:
        _asegurar_tabla()
    except Exception as e:
        print("Rescate de la avería: no se pudo preparar la tabla:", str(e)[:200])
        return None

    filas = fetch_afectados()

    return len(filas)


def contar_ya_escritos():

    try:

        _asegurar_tabla()

        with conn.cursor() as cur:

            cur.execute(
                "SELECT COUNT(*) FROM averia_rescue_sent WHERE status = 'sent'"
            )

            return int((cur.fetchone() or [0])[0] or 0)

    except Exception:

        conn.rollback()
        return None


def _precio_de_entrada(group_id):
    """«3,60 EUR» — el más barato que se puede pagar HOY. None si no hay."""

    try:

        from start_offer_service import fetch_sellable_communities, formato_importe

        ofertas = fetch_sellable_communities(0, limit=10, solo_grupo=group_id)

        if not ofertas:
            return None

        o = ofertas[0]

        return formato_importe(o.get("amount"), o.get("currency"))

    except Exception as e:

        print("Rescate de la avería: no se pudo leer el precio:", str(e)[:200])
        return None


def build_rescue_text(nombre_comunidad, precio=None):
    """
    El mensaje. Corto, sin rodeos, y con la culpa donde corresponde.

    No promete nada que no sea verdad: no dice «te guardamos el precio» porque
    no hay tal cosa; dice el precio de HOY, que es el que se va a cobrar.
    """

    lineas = [
        f"Hola. Hace unos días intentaste entrar en {nombre_comunidad} y, al "
        "pulsar para pagar, el bot te contestó con un error.",
        "",
        "Era un fallo nuestro, no tuyo, y ya está arreglado. No se te cobró "
        "nada.",
    ]

    if precio:

        lineas += [
            "",
            f"Si sigues queriendo entrar, ahora mismo es desde {precio}. "
            "Pagas con tarjeta en la página segura de Stripe y recibes tu "
            "enlace de entrada aquí mismo, al momento.",
        ]

    else:

        lineas += [
            "",
            "Si sigues queriendo entrar, ya puedes pagar con normalidad y "
            "recibes tu enlace de entrada aquí mismo, al momento.",
        ]

    lineas += ["", "Perdona las molestias."]

    return "\n".join(lineas)


def build_rescue_keyboard(group_id):

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from reengagement_service import CALLBACK_REENGAGEMENT_STOP

    return InlineKeyboardMarkup([
        # A la lista de planes, que es justo lo que estaba roto y ahora
        # funciona: que lo vea con sus ojos.
        [InlineKeyboardButton(
            "💳 Ver planes y pagar",
            callback_data=f"group_{int(group_id)}"
        )],
        [InlineKeyboardButton(
            "🛟 Tengo una duda",
            callback_data="public_support"
        )],
        [InlineKeyboardButton(
            "🔕 No quiero más avisos",
            callback_data=CALLBACK_REENGAGEMENT_STOP
        )],
    ])


def _marcar(user_id, group_id, status):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO averia_rescue_sent (user_id, group_id, status)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING

            """, (int(user_id), int(group_id), status))

            conn.commit()

            return cur.rowcount > 0

    except Exception as e:

        conn.rollback()
        print("Rescate de la avería: no se pudo marcar:", str(e)[:200])

        return False


def build_preview_text():
    """Lo que ve el operador antes de pulsar «enviar». Nunca lanza."""

    try:

        afectados = fetch_afectados()
        ya = contar_ya_escritos()

    except Exception as e:

        return f"🛟 Rescate de la avería\n\nNo se pudo leer: {str(e)[:200]}"


    lineas = [
        "🛟 Rescate de la avería del cobro",
        "",
        "Desde finales de agosto hasta hoy, los tres botones de pago con "
        "tarjeta de la lista de planes contestaban «Este plan no está "
        "configurado para Stripe». Ya está arreglado.",
        "",
    ]

    if not afectados:

        lineas.append(
            "✅ No queda nadie por escribir."
            + (f" Ya se escribió a {ya}." if ya else "")
        )

        return "\n".join(lineas)


    lineas += [
        f"👥 {len(afectados)} persona(s) pulsaron «pagar» en esas semanas, se "
        "llevaron el error y no han comprado después.",
        "",
        "Son la gente con más intención de comprar que hay: vieron el precio, "
        "eligieron plan y pulsaron pagar.",
        "",
        "Se excluye a quien ya pagó, tiene acceso, está vetado, pidió no "
        "recibir avisos o bloqueó el bot. Cada persona recibe UN mensaje, una "
        "sola vez.",
        "",
        "— Así les llegará —",
        "",
    ]

    _uid, group_id, nombre, _cuando = afectados[0]

    lineas.append(build_rescue_text(nombre, _precio_de_entrada(group_id)))

    if ya:
        lineas += ["", f"(Ya se escribió antes a {ya}.)"]

    return "\n".join(lineas)


def build_preview_keyboard():

    from telegram import InlineKeyboardButton

    from admin_menu_catalog import build_admin_screen_keyboard

    cuantos = len(fetch_afectados())

    extra = []

    if cuantos:

        extra.append([InlineKeyboardButton(
            f"📨 Enviar a {cuantos} persona(s)",
            callback_data="admin_averia_rescue_send"
        )])

    return build_admin_screen_keyboard("admin_averia_rescue", extra=extra)


async def enviar_rescate(bot, actor_user_id=None):
    """
    Envía el mensaje a todos los afectados que quedan. Devuelve el resumen.

    Se marca ANTES de enviar: si el envío revienta a medias y se vuelve a
    pulsar, nadie recibe el mensaje dos veces. Un mensaje perdido es mejor que
    uno repetido en una disculpa.
    """

    from reengagement_service import is_blocked_error, mark_reengagement_blocked

    resumen = {"objetivo": 0, "enviados": 0, "bloqueados": 0, "fallidos": 0}

    afectados = fetch_afectados()

    resumen["objetivo"] = len(afectados)

    precios = {}

    for user_id, group_id, nombre, _cuando in afectados:

        if not _marcar(user_id, group_id, "sending"):
            continue

        if group_id not in precios:
            precios[group_id] = _precio_de_entrada(group_id)

        try:

            await bot.send_message(
                chat_id=int(user_id),
                text=build_rescue_text(nombre, precios[group_id]),
                reply_markup=build_rescue_keyboard(group_id),
            )

            estado = "sent"
            resumen["enviados"] += 1

        except Exception as e:

            if is_blocked_error(e):

                estado = "blocked"
                resumen["bloqueados"] += 1
                mark_reengagement_blocked(user_id, str(e)[:200])

            else:

                estado = "failed"
                resumen["fallidos"] += 1
                print(
                    f"Rescate de la avería: no se pudo escribir a {user_id}:",
                    str(e)[:200]
                )

        try:

            with conn.cursor() as cur:

                cur.execute(
                    "UPDATE averia_rescue_sent SET status = %s WHERE user_id = %s",
                    (estado, int(user_id))
                )

                conn.commit()

        except Exception:

            conn.rollback()

        if RESCATE_PAUSA_SEGUNDOS > 0:
            await asyncio.sleep(RESCATE_PAUSA_SEGUNDOS)


    log_event(
        "averia_rescue_sent",
        category="marketing",
        severity="warning",
        scope="global",
        actor_user_id=actor_user_id,
        message="Rescate de la avería del cobro enviado.",
        metadata=resumen,
    )

    print("Rescate de la avería:", resumen)

    return resumen


def describe_para_el_arranque():
    """Una línea para el registro del arranque: cuántos esperan."""

    cuantos = contar_afectados()

    if cuantos is None:
        return "Rescate de la avería: no se pudo contar."

    if not cuantos:
        return "Rescate de la avería: nadie pendiente."

    return (
        f"Rescate de la avería: {cuantos} persona(s) pulsaron pagar, se "
        "llevaron el error y esperan el mensaje. Se envía desde el panel "
        "(Panel global → 🛟 Rescate de la avería)."
    )
