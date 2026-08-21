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


# =========================
# PASAR UN PLAN A COBRAR POR STRIPE
# =========================
# En producción, lo ÚNICO a la venta cobraba por PayPal, y ese PayPal es el que
# tiene el webhook_id inválido: el bot se niega a cobrar (con razón, porque el
# pago no se podría confirmar y el acceso no se entregaría). Con eso, la
# conversión no podía ser otra cosa que cero.
#
# Esta tarea pasa esos planes a Stripe, que en este despliegue está verificado y
# funcionando, y les crea su precio con el importe que YA se anuncia.
#
# Qué NO hace: tocar planes de un proveedor que funciona. Si el método actual
# puede cobrar, cambiarlo es mover el dinero de sitio sin que nadie lo haya
# pedido.

def tarea_cobrar_por_stripe():
    """BOOTSTRAP_PLAN_PROVIDER='g<grupo>' o '<plan_id>', separados por comas."""

    crudo = (os.environ.get("BOOTSTRAP_PLAN_PROVIDER") or "").strip()

    if not crudo:
        return "cobrar_por_stripe: falta BOOTSTRAP_PLAN_PROVIDER, no se hace nada."

    from payment_access_service import MAX_PLAN_DURATION_DAYS
    from plan_price_service import crear_precio_stripe_para_plan

    resultados = []

    for objetivo in [t.strip() for t in crudo.split(",") if t.strip()]:

        if objetivo.lower().startswith("g"):

            condicion, valor = "group_id", objetivo[1:]

        else:

            condicion, valor = "id", objetivo

        try:

            valor = int(valor)

        except (TypeError, ValueError):

            resultados.append(f"«{objetivo}» no es un número")
            continue

        try:

            with conn.cursor() as cur:

                cur.execute(f"""

                    SELECT id, group_id,
                           COALESCE(NULLIF(name, ''), 'Plan'),
                           amount,
                           COALESCE(NULLIF(currency, ''), 'EUR'),
                           duration_days,
                           COALESCE(is_recurring, FALSE),
                           COALESCE(NULLIF(payment_provider, ''), 'stripe')
                    FROM plans
                    WHERE {condicion} = %s
                      AND COALESCE(is_active, TRUE) = TRUE
                      AND amount IS NOT NULL AND amount > 0
                      AND duration_days IS NOT NULL
                      AND duration_days > 0
                      AND duration_days <= %s

                """, (valor, MAX_PLAN_DURATION_DAYS))

                planes = cur.fetchall() or []

        except Exception as e:

            resultados.append(f"«{objetivo}»: error leyendo los planes ({e})")
            continue

        if not planes:

            resultados.append(f"«{objetivo}»: sin planes vendibles")
            continue

        for (plan_id, group_id, nombre, importe, moneda, dias, recurrente,
             proveedor) in planes:

            if (proveedor or "").strip().lower() == "stripe":

                resultados.append(f"plan #{plan_id} ya cobra por Stripe")
                continue

            plan = {
                "id": plan_id, "group_id": group_id, "name": nombre,
                "currency": moneda, "duration_days": dias,
                "is_recurring": bool(recurrente),
            }

            try:

                price_id = crear_precio_stripe_para_plan(plan, float(importe))

            except Exception as e:

                resultados.append(
                    f"plan #{plan_id}: Stripe no aceptó el precio ({str(e)[:120]})"
                )
                continue

            try:

                with conn.cursor() as cur:

                    # Proveedor y precio se escriben JUNTOS: dejar el proveedor
                    # cambiado sin precio válido es cambiar un cobro roto por
                    # otro.
                    from plan_price_service import moneda_valida_para_stripe

                    cur.execute("""

                        UPDATE plans
                        SET payment_provider = 'stripe',
                            currency = %s,
                            stripe_price_id = %s,
                            price_id = %s
                        WHERE id = %s

                    """, (
                        moneda_valida_para_stripe(moneda),
                        price_id,
                        price_id,
                        plan_id,
                    ))

                    conn.commit()

            except Exception as e:

                conn.rollback()

                resultados.append(f"plan #{plan_id}: error guardando ({e})")
                continue

            log_event(
                "bootstrap_plan_provider_switched",
                category="billing",
                severity="warning",
                scope="group",
                group_id=group_id,
                message="Plan pasado a cobrar por Stripe.",
                metadata={
                    "plan_id": plan_id,
                    "antes": proveedor,
                    "amount": float(importe),
                    "currency": moneda,
                    "stripe_price_id": price_id,
                },
            )

            resultados.append(
                f"plan #{plan_id} ({nombre}, {float(importe):.2f} {moneda}): "
                f"{proveedor} → stripe, con precio nuevo"
            )

    return "cobrar_por_stripe: " + " | ".join(resultados)


# =========================
# EL NOMBRE QUE VE EL COMPRADOR AL PAGAR
# =========================
# El nombre del plan viaja al producto de Stripe, así que es lo que se lee en la
# página de pago con la tarjeta ya en la mano. En producción se llamaba
# «PERMANENTE PAYPAL» — ni es permanente (360 días) ni cobra por PayPal (ya no),
# y leer eso justo antes de pagar 29 euros no invita a seguir.
#
# Al renombrar se BORRA el precio de Stripe a propósito: la reparación de
# arranque, que corre justo después, le crea uno nuevo con el nombre correcto y
# el importe que ya se anuncia. Sin ese paso, el nombre cambiaría en el bot y
# seguiría siendo el viejo en la pantalla donde de verdad importa.

def tarea_renombrar_plan():
    """BOOTSTRAP_PLAN_NAME='<plan_id>=<nombre nuevo>', separados por comas."""

    crudo = (os.environ.get("BOOTSTRAP_PLAN_NAME") or "").strip()

    if not crudo:
        return "renombrar_plan: falta BOOTSTRAP_PLAN_NAME, no se hace nada."

    resultados = []

    for trozo in [t.strip() for t in crudo.split(",") if t.strip()]:

        if "=" not in trozo:

            resultados.append(f"«{trozo}» no tiene la forma plan_id=nombre")
            continue

        plan_id, nombre = trozo.split("=", 1)
        nombre = nombre.strip()

        try:

            plan_id = int(plan_id.strip())

        except (TypeError, ValueError):

            resultados.append(f"«{trozo}» no empieza por un número de plan")
            continue

        if not nombre:

            resultados.append(f"plan #{plan_id}: un nombre vacío no es un nombre")
            continue

        from plan_price_service import diagnostico_de_plan

        # ¿De verdad le va a crear precio nuevo la reparación de arranque? Solo
        # si el plan está entre los vendibles por Stripe. Si no lo está,
        # borrarle el identificador no arregla nada: lo deja apoyado en el
        # precio viejo —con el nombre viejo— y encima el arranque prometería un
        # precio nuevo que no llega nunca. Eso fue exactamente lo que pasó la
        # primera vez que se usó esta tarea, y el log no dio ni una pista.
        antes = diagnostico_de_plan(plan_id)

        if antes is None:

            resultados.append(f"plan #{plan_id}: no existe")
            continue

        recrea_precio = bool(antes.get("vendible"))

        try:

            with conn.cursor() as cur:

                if recrea_precio:

                    cur.execute("""

                        UPDATE plans
                        SET name = %s,
                            stripe_price_id = NULL
                        WHERE id = %s

                    """, (nombre, plan_id))

                else:

                    cur.execute(
                        "UPDATE plans SET name = %s WHERE id = %s",
                        (nombre, plan_id),
                    )

                cambiado = cur.rowcount > 0
                conn.commit()

        except Exception as e:

            conn.rollback()

            resultados.append(f"plan #{plan_id}: error renombrando ({e})")
            continue

        if not cambiado:

            resultados.append(f"plan #{plan_id}: no existe")
            continue

        log_event(
            "bootstrap_plan_renamed",
            category="billing",
            severity="info",
            scope="global",
            message="Plan renombrado.",
            metadata={
                "plan_id": plan_id,
                "nombre": nombre,
                "precio_recreado": recrea_precio,
                "motivo": antes.get("motivo"),
            },
        )

        if recrea_precio:

            resultados.append(
                f"plan #{plan_id} → «{nombre}» (se le creará precio nuevo para "
                "que la página de pago diga lo mismo)"
            )

        else:

            resultados.append(
                f"plan #{plan_id} → «{nombre}», pero la página de pago seguirá "
                f"diciendo el nombre viejo porque este plan no se vende por "
                f"Stripe: {antes.get('motivo')}"
            )

    return "renombrar_plan: " + " | ".join(resultados)


# =========================
# MIRAR, SIN TOCAR NADA
# =========================
# Todas las tareas de aquí arriba cambian datos a ciegas: se pide un cambio, se
# lee una línea en el arranque y hay que creérsela. Cuando el resultado no es el
# esperado —un plan que se renombra y sigue enseñando el nombre viejo— no hay
# forma de averiguar por qué, porque las credenciales de la base no salen del
# servidor.
#
# Esta tarea no escribe NADA. Solo cuenta cómo está cada plan y, si no se
# vende, por qué no. Es la única de la lista que se puede dejar puesta sin
# miedo, y la primera que conviene usar antes de pedir un cambio.


def tarea_listar_planes():
    """BOOTSTRAP_PLAN_LIST='g<grupo>' o '<plan_id>' o 'todos', por comas."""

    from plan_price_service import (
        describe_plan,
        diagnostico_de_plan,
        ids_de_planes_del_grupo,
        planes_stripe_vendibles,
    )

    crudo = (os.environ.get("BOOTSTRAP_PLAN_LIST") or "").strip()

    if not crudo:
        return "listar_planes: falta BOOTSTRAP_PLAN_LIST, no se mira nada."

    ids = []

    for objetivo in [t.strip() for t in crudo.split(",") if t.strip()]:

        if objetivo.lower() == "todos":

            try:

                with conn.cursor() as cur:

                    # Con tope: esto va al log de arranque, no es un volcado de
                    # la base.
                    cur.execute("SELECT id FROM plans ORDER BY id LIMIT 60")

                    ids.extend(f[0] for f in (cur.fetchall() or []))

            except Exception as e:

                return f"listar_planes: error listando los planes ({e})"

            continue

        if objetivo.lower().startswith("g"):

            try:

                ids.extend(ids_de_planes_del_grupo(int(objetivo[1:])))

            except (TypeError, ValueError):

                ids.append(objetivo)

            continue

        ids.append(objetivo)

    # Una sola lectura de los vendibles para todos: la lista es la misma y
    # repetir la consulta por plan no cambiaría la respuesta.
    vendibles = planes_stripe_vendibles()

    lineas = []

    for identificador in ids:

        try:

            plan = diagnostico_de_plan(int(identificador), vendibles=vendibles)

        except (TypeError, ValueError):

            lineas.append(f"«{identificador}» no es un número de plan")
            continue

        lineas.append(
            describe_plan(plan) if plan
            else f"plan #{identificador}: no existe"
        )

    if not lineas:
        return "listar_planes: no hay ningún plan que mirar."

    return "listar_planes:\n  " + "\n  ".join(lineas)


# =========================
# APAGAR LO QUE NO SE PUEDE VENDER
# =========================
# Un plan activo que el escaparate nunca va a ofrecer no es neutro: aparece en
# las pantallas del propietario, dispara su alerta semanal y sigue ahí para que
# alguien lo «arregle» un día bajando su duración —y si su precio es más bajo
# que el del plan bueno, el escaparate pasaría a anunciar ESE, porque enseña el
# más barato. En producción hay uno así: «PERMANENTE OFERTA 7€», 1.300.000 días,
# en la única comunidad que vende, a 7 euros contra los 29 del plan que sí
# funciona.
#
# LA CONDICIÓN QUE HACE ESTO SEGURO: solo se apaga lo que NO se puede vender,
# comprobado con la misma lista que decide el escaparate. Un plan que funciona
# no se apaga aquí ni aunque se pida por su número.


def tarea_desactivar_plan():
    """BOOTSTRAP_PLAN_DISABLE='<plan_id>', por comas. Solo lo invendible."""

    from plan_price_service import diagnostico_de_plan

    crudo = (os.environ.get("BOOTSTRAP_PLAN_DISABLE") or "").strip()

    if not crudo:
        return "desactivar_plan: falta BOOTSTRAP_PLAN_DISABLE, no se hace nada."

    resultados = []

    for objetivo in [t.strip() for t in crudo.split(",") if t.strip()]:

        try:

            plan_id = int(objetivo)

        except (TypeError, ValueError):

            resultados.append(f"«{objetivo}» no es un número de plan")
            continue

        plan = diagnostico_de_plan(plan_id)

        if not plan:

            resultados.append(f"plan #{plan_id}: no existe")
            continue

        if plan.get("vendible"):

            # Esta es la línea que separa una limpieza de un apagón: un plan que
            # vende no se toca desde aquí ni pidiéndolo.
            resultados.append(
                f"plan #{plan_id} SE VENDE ahora mismo: no se apaga"
            )
            continue

        if not plan.get("is_active"):

            resultados.append(f"plan #{plan_id} ya estaba apagado")
            continue

        try:

            with conn.cursor() as cur:

                cur.execute(
                    "UPDATE plans SET is_active = FALSE WHERE id = %s",
                    (plan_id,),
                )

                conn.commit()

        except Exception as e:

            conn.rollback()

            resultados.append(f"plan #{plan_id}: error apagándolo ({e})")
            continue

        log_event(
            "bootstrap_plan_disabled",
            category="billing",
            severity="warning",
            scope="group",
            group_id=plan.get("group_id"),
            message="Plan invendible apagado.",
            metadata={
                "plan_id": plan_id,
                "nombre": plan.get("name"),
                "motivo": plan.get("motivo"),
            },
        )

        resultados.append(
            f"plan #{plan_id} «{plan.get('name')}» apagado ({plan.get('motivo')}). "
            "Para recuperarlo: edítalo en «Planes», pon una duración entre 1 y "
            "3650 días y vuelve a activarlo"
        )

    return "desactivar_plan: " + " | ".join(resultados)


TAREAS = {
    "listar_planes": tarea_listar_planes,
    "desactivar_plan": tarea_desactivar_plan,
    "descripcion_minima": tarea_descripcion_minima,
    "precio_publicacion": tarea_precio_publicacion,
    "precio_comunidad": tarea_precio_comunidad,
    "cobrar_por_stripe": tarea_cobrar_por_stripe,
    "renombrar_plan": tarea_renombrar_plan,
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
