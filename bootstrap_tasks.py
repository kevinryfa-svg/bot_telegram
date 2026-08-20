"""
Tareas puntuales de puesta a punto, ejecutadas en el arranque y a petición.

Hay arreglos que no son de código sino de DATOS de producción: una comunidad sin
descripción, un plan sin precio. Desde fuera no hay forma de tocarlos —las
credenciales de la base no salen del servidor— y desde dentro solo se llega por
pantallas que exigen a una persona con Telegram delante.

Esto es la tercera vía: una lista de tareas con nombre que se activan poniendo
BOOTSTRAP_TASKS y se desactivan quitándola. Sin esa variable no se ejecuta
absolutamente nada, que es el estado normal.

LAS TRES REGLAS DE UNA TAREA DE ESTAS

  NO PISA NADA        Solo rellena huecos. Si el campo ya tiene algo escrito por
                      una persona, la tarea pasa de largo. Un arreglo automático
                      que sobrescribe una decisión ajena no es un arreglo.

  IDEMPOTENTE         Ejecutarla diez veces deja lo mismo que ejecutarla una. El
                      arranque se repite en cada despliegue y en cada reinicio.

  DEJA RASTRO         Cada cambio queda en audit_logs y en el log de arranque,
                      con qué se cambió y a qué valor. Un cambio de datos que no
                      se puede auditar es indistinguible de una corrupción.
"""

import os

from audit_log_service import log_event
from db import conn


def tareas_pedidas():
    """Los nombres pedidos por BOOTSTRAP_TASKS. Vacío = no se hace nada."""

    crudo = (os.environ.get("BOOTSTRAP_TASKS") or "").strip()

    if not crudo:
        return []

    return [t.strip() for t in crudo.split(",") if t.strip()]


# =========================
# DESCRIPCIÓN MÍNIMA HONESTA
# =========================
# Una comunidad sin descripción se ofrece con el nombre y el precio, y nadie
# paga por un nombre. Pero yo no sé qué hay dentro de la comunidad de nadie, así
# que este texto NO afirma ni una sola cosa sobre el contenido: solo dice lo que
# el propio bot garantiza y puede cumplir. Inventar «señales diarias» o
# «directos semanales» sería ponerle a un comprador una promesa que no ha hecho
# nadie.

# La frase por la que se reconoce el relleno. Va aquí y no repetida en el panel:
# si se copia, el día que cambie el texto el panel dejaría de reconocerlo y se
# tragaría el aviso más importante que tiene.
FRASE_DE_RELLENO = "recibes tu enlace de entrada"


def es_descripcion_de_relleno(texto):
    """¿Este texto es el de relleno, en vez de una descripción de verdad?"""

    limpio = (texto or "").strip()

    return (
        limpio.startswith("Acceso al grupo privado de ")
        and FRASE_DE_RELLENO in limpio
    )


def descripcion_minima(nombre_comunidad):
    """El texto de relleno. Cada frase es verdad y la cumple el bot."""

    return (
        f"Acceso al grupo privado de {nombre_comunidad}.\n\n"
        "En cuanto se confirma el pago recibes tu enlace de entrada "
        "automáticamente, sin esperar a que nadie te lo mande a mano. Puedes "
        "cancelar la renovación cuando quieras desde el propio bot."
    )


def tarea_descripcion_minima():
    """Rellena la descripción SOLO de las comunidades que no tienen ninguna."""

    cambiadas = []

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, COALESCE(NULLIF(name, ''), 'esta comunidad')
                FROM groups
                WHERE COALESCE(is_active, TRUE) = TRUE
                  AND COALESCE(is_free_group, FALSE) = FALSE
                  AND COALESCE(NULLIF(TRIM(preview_text), ''), '') = ''

            """)

            pendientes = cur.fetchall() or []


            for group_id, nombre in pendientes:

                texto = descripcion_minima(nombre)

                # El WHERE repite la condición: entre el SELECT y el UPDATE, el
                # propietario puede haber escrito la suya desde el panel, y esa
                # gana siempre.
                cur.execute("""

                    UPDATE groups
                    SET preview_text = %s
                    WHERE id = %s
                      AND COALESCE(NULLIF(TRIM(preview_text), ''), '') = ''

                """, (texto, group_id))

                if cur.rowcount > 0:
                    cambiadas.append((group_id, nombre))


            conn.commit()

    except Exception as e:

        conn.rollback()

        return f"descripcion_minima: ERROR ({str(e)[:160]})"


    for group_id, nombre in cambiadas:

        log_event(
            "bootstrap_default_description_set",
            category="marketing",
            severity="info",
            scope="group",
            group_id=group_id,
            message="Descripción por defecto puesta en una comunidad sin texto.",
            metadata={"group_id": group_id, "name": nombre},
        )


    if not cambiadas:
        return "descripcion_minima: nada que hacer (todas tienen descripción)."

    nombres = ", ".join(n for _g, n in cambiadas)

    return (
        f"descripcion_minima: {len(cambiadas)} comunidad(es) con descripción de "
        f"relleno ({nombres}). El propietario debe reemplazarla por la suya: "
        "esta no dice nada del contenido a propósito."
    )


# =========================
# PRECIO DEL PLAN DE PUBLICACIÓN
# =========================
# Sin precio, nadie puede pagar por publicar su comunidad y la única línea de
# ingresos que no depende de las ventas propias se queda muerta. La escala está
# anclada en el catálogo que ya existe —los servicios extra van de 9,99 a 24,99
# al mes— con el descuento habitual por comprometerse más tiempo.
#
# No es una verdad revelada: son tres toques cambiarlo en «Planes comerciales
# del bot → Precio de publicar comunidad», y solo afecta a altas nuevas.

PRECIOS_PUBLICACION_CENTIMOS = {
    30: 1999,     # 19,99 al mes
    90: 5399,     # 53,99 el trimestre (~10% menos por mes)
    180: 10199,   # 101,99 el semestre (~15% menos)
    365: 17999,   # 179,99 el año (~25% menos)
}


def tarea_precio_publicacion():
    """Pone precio a los planes de publicación que no lo tienen."""

    from platform_plan_service import PLATFORM_PLAN_PRODUCT

    puestos = []

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id, name, duration_days
                FROM commercial_plans
                WHERE product_type = %s
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND (amount IS NULL OR amount <= 0)

            """, (PLATFORM_PLAN_PRODUCT,))

            pendientes = cur.fetchall() or []


            for plan_id, nombre, dias in pendientes:

                centimos = PRECIOS_PUBLICACION_CENTIMOS.get(int(dias or 0))

                if not centimos:

                    # Una duración que no está en la escala no se inventa: un
                    # precio a ojo en un plan de verdad se lo come un cliente.
                    continue

                cur.execute("""

                    UPDATE commercial_plans
                    SET amount = %s, currency = 'EUR', stripe_price_id = NULL
                    WHERE id = %s
                      AND (amount IS NULL OR amount <= 0)

                """, (centimos, plan_id))

                if cur.rowcount > 0:
                    puestos.append((plan_id, nombre, centimos))


            conn.commit()

    except Exception as e:

        conn.rollback()

        return f"precio_publicacion: ERROR ({str(e)[:160]})"


    for plan_id, nombre, centimos in puestos:

        log_event(
            "bootstrap_platform_plan_price_set",
            category="billing",
            severity="info",
            scope="global",
            message="Precio inicial puesto a un plan de publicación.",
            metadata={
                "plan_id": plan_id,
                "name": nombre,
                "amount_cents": centimos,
            },
        )


    if not puestos:
        return "precio_publicacion: nada que hacer (ya tenían precio)."

    detalle = ", ".join(
        f"{nombre} {centimos / 100:.2f} EUR" for _p, nombre, centimos in puestos
    )

    return f"precio_publicacion: {len(puestos)} plan(es) con precio ({detalle})."


# =========================
# EL PRECIO DE UNA COMUNIDAD
# =========================
# El plan concreto y el importe se dicen por variable (BOOTSTRAP_PLAN_PRICE) y no
# se adivinan: cambiarle el precio a la comunidad de alguien es una decisión de
# su dueño, y una regla automática del tipo «sube todo lo que esté por debajo de
# X» acabaría tocando planes de terceros que no ha visto nadie.
#
# El cambio pasa por plan_price_service, que escribe el importe Y crea el precio
# de Stripe correspondiente: cambiar solo uno deja al bot anunciando una cosa y
# cobrando otra.

def tarea_precio_comunidad():
    """BOOTSTRAP_PLAN_PRICE='<plan_id>:<euros>[,<plan_id>:<euros>...]'."""

    crudo = (os.environ.get("BOOTSTRAP_PLAN_PRICE") or "").strip()

    if not crudo:
        return "precio_comunidad: falta BOOTSTRAP_PLAN_PRICE, no se hace nada."

    from plan_price_service import set_group_plan_price

    resultados = []

    for trozo in crudo.split(","):

        trozo = trozo.strip()

        if not trozo:
            continue

        if ":" not in trozo:

            resultados.append(f"«{trozo}» no tiene la forma plan_id:euros")
            continue

        objetivo, euros = trozo.split(":", 1)
        objetivo = objetivo.strip()

        try:

            euros = float(euros.strip().replace(",", "."))

        except (TypeError, ValueError):

            resultados.append(f"«{trozo}» no son números")
            continue

        # «g1159:29» apunta a la COMUNIDAD y deja que el servicio resuelva su
        # plan: los identificadores de plan no se pueden consultar desde fuera,
        # y el del grupo sí se conoce (sale en el enlace del escaparate).
        if objetivo.lower().startswith("g"):

            from plan_price_service import resolver_plan_de_grupo

            try:

                group_id = int(objetivo[1:])

            except (TypeError, ValueError):

                resultados.append(f"«{trozo}» no son números")
                continue

            plan_id, detalle = resolver_plan_de_grupo(group_id)

            resultados.append(detalle)

            if not plan_id:
                continue

        else:

            try:

                plan_id = int(objetivo)

            except (TypeError, ValueError):

                resultados.append(f"«{trozo}» no son números")
                continue

        _ok, detalle = set_group_plan_price(plan_id, euros)

        resultados.append(detalle)

    return "precio_comunidad: " + " | ".join(resultados)


TAREAS = {
    "descripcion_minima": tarea_descripcion_minima,
    "precio_publicacion": tarea_precio_publicacion,
    "precio_comunidad": tarea_precio_comunidad,
}


def run_bootstrap_tasks():
    """Ejecuta lo pedido. Devuelve una línea por tarea, para el arranque."""

    pedidas = tareas_pedidas()

    if not pedidas:
        return []

    lineas = []

    for nombre in pedidas:

        tarea = TAREAS.get(nombre)

        if not tarea:

            lineas.append(
                f"{nombre}: no existe esa tarea. Disponibles: "
                + ", ".join(sorted(TAREAS))
            )

            continue

        try:

            lineas.append(tarea())

        except Exception as e:

            lineas.append(f"{nombre}: ERROR inesperado ({str(e)[:160]})")

    return lineas
