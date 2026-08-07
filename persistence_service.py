"""
Estado de conversación que sobrevive a los reinicios.

Hasta ahora todo lo que el bot recordaba de una conversación vivía solo en
memoria (context.user_data). Cualquier reinicio —un despliegue, un reinicio de
Railway, una caída— lo borraba, y eso se notaba de verdad:

  - un alta de plan a medio rellenar se perdía y había que empezar de cero;
  - la comunidad seleccionada desaparecía, y el bot llegaba a decirle al
    propietario que no tenía permisos en su propio grupo;
  - el asistente perdía el hilo de la conversación.

Esta clase guarda user_data y chat_data en PostgreSQL, de forma que un reinicio
deja de borrar lo que el usuario estaba haciendo.

Se guarda con pickle en una columna binaria a propósito: no controlamos qué
tipos meten los manejadores en user_data, y JSON obligaría a convertirlos
perdiendo información. Nada de esto viene del usuario: son estructuras que
escribe el propio bot.
"""

import copy
import os
import pickle

from telegram.ext import Application, BasePersistence, PersistenceInput

from db import conn


# =========================
# CONFIGURACIÓN
# =========================

PERSISTENCE_ENABLED = os.environ.get(
    "PERSISTENCE_ENABLED", "true"
).strip().lower() not in ("0", "false", "no")

# Cada cuánto se vuelca a la base de datos. Más bajo = menos se pierde en una
# caída; más alto = menos escrituras.
PERSISTENCE_UPDATE_INTERVAL = float(
    os.environ.get("PERSISTENCE_UPDATE_INTERVAL", "30")
)

# Estado más viejo que esto es basura: un wizard a medias de hace semanas no
# hay que restaurarlo, confundiría más que ayudar.
PERSISTENCE_MAX_AGE_DAYS = int(
    os.environ.get("PERSISTENCE_MAX_AGE_DAYS", "7")
)

# Tope por entrada. Evita que un dato inesperadamente enorme llene la tabla.
PERSISTENCE_MAX_BYTES = int(
    os.environ.get("PERSISTENCE_MAX_BYTES", str(256 * 1024))
)


# =========================
# ACCESO A LA TABLA
# =========================

def serialize(data):

    return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize(payload):

    return pickle.loads(bytes(payload))


def load_scope(scope):
    """
    Devuelve {clave: datos} para 'user_data' o 'chat_data'.

    Nunca lanza: si la persistencia falla, el bot debe arrancar igual, solo
    sin memoria de conversaciones.
    """

    result = {}

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT entity_id, payload
                FROM bot_persistence
                WHERE scope=%s
                AND updated_at > NOW() - (%s || ' days')::INTERVAL

            """, (scope, str(max(PERSISTENCE_MAX_AGE_DAYS, 1))))

            rows = cur.fetchall()

    except Exception as e:

        print(f"Persistencia: no se pudo leer {scope}:", e)

        return {}


    broken = []

    for entity_id, payload in rows:

        try:

            result[int(entity_id)] = deserialize(payload)

        except Exception as e:

            # Un dato ilegible (formato viejo, clase que ya no existe) se
            # descarta: no debe impedir restaurar el resto.
            broken.append(int(entity_id))

            print(
                f"Persistencia: {scope} de {entity_id} ilegible, se descarta:",
                type(e).__name__
            )


    if broken:

        drop_entries(scope, broken)


    return result


def save_entry(scope, entity_id, data):
    """Guarda (o borra, si está vacío) el estado de una entidad."""

    if not data:

        drop_entries(scope, [entity_id])

        return True


    try:

        payload = serialize(data)

    except Exception as e:

        # Algo no serializable dentro de user_data: se avisa y se sigue. El
        # bot funciona, solo esa conversación no se recordará.
        print(
            f"Persistencia: {scope} de {entity_id} no se puede guardar:",
            type(e).__name__,
            str(e)[:200]
        )

        return False


    if len(payload) > PERSISTENCE_MAX_BYTES:

        print(
            f"Persistencia: {scope} de {entity_id} ocupa "
            f"{len(payload)} bytes y se omite (tope "
            f"{PERSISTENCE_MAX_BYTES})."
        )

        return False


    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO bot_persistence (scope, entity_id, payload, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (scope, entity_id)
                DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()

            """, (scope, int(entity_id), psycopg2_binary(payload)))

        return True

    except Exception as e:

        print(f"Persistencia: error guardando {scope} de {entity_id}:", e)

        return False


def psycopg2_binary(payload):
    """Envuelve los bytes para que psycopg2 los mande como BYTEA."""

    import psycopg2

    return psycopg2.Binary(payload)


def drop_entries(scope, entity_ids):

    if not entity_ids:

        return 0


    try:

        with conn.cursor() as cur:

            cur.execute(
                "DELETE FROM bot_persistence "
                "WHERE scope=%s AND entity_id = ANY(%s)",
                (scope, [int(i) for i in entity_ids])
            )

            return cur.rowcount

    except Exception as e:

        print(f"Persistencia: error borrando {scope}:", e)

        return 0


def prune_old_entries():
    """Borra estado caducado. Devuelve cuántas filas se han quitado."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM bot_persistence
                WHERE updated_at < NOW() - (%s || ' days')::INTERVAL

            """, (str(max(PERSISTENCE_MAX_AGE_DAYS, 1)),))

            return cur.rowcount

    except Exception as e:

        print("Persistencia: error limpiando estado caducado:", e)

        return 0


def count_entries():
    """Cuántas conversaciones hay guardadas, por ámbito."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT scope, COUNT(*)
                FROM bot_persistence
                GROUP BY scope

            """)

            return {row[0]: int(row[1]) for row in cur.fetchall()}

    except Exception as e:

        print("Persistencia: error contando entradas:", e)

        return {}


# =========================
# PERSISTENCIA PARA python-telegram-bot
# =========================

class PostgresPersistence(BasePersistence):
    """
    Guarda user_data y chat_data en PostgreSQL.

    bot_data y callback_data quedan fuera a propósito: bot_data no se usa para
    nada que deba sobrevivir, y callback_data solo aplica si se activan los
    callbacks arbitrarios, que este bot no usa.
    """

    def __init__(self, update_interval=None):

        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=True,
                user_data=True,
                callback_data=False
            ),
            update_interval=(
                update_interval
                if update_interval is not None
                else PERSISTENCE_UPDATE_INTERVAL
            )
        )


    # ---- lectura ----

    async def get_user_data(self):

        return load_scope("user_data")


    async def get_chat_data(self):

        return load_scope("chat_data")


    async def get_bot_data(self):

        return {}


    async def get_callback_data(self):

        return None


    async def get_conversations(self, name):

        # Este bot no usa ConversationHandler.
        return {}


    # ---- escritura ----

    async def update_user_data(self, user_id, data):

        save_entry("user_data", user_id, data)


    async def update_chat_data(self, chat_id, data):

        save_entry("chat_data", chat_id, data)


    async def update_bot_data(self, data):

        return None


    async def update_callback_data(self, data):

        return None


    async def update_conversation(self, name, key, new_state):

        return None


    # ---- borrado ----

    async def drop_user_data(self, user_id):

        drop_entries("user_data", [user_id])


    async def drop_chat_data(self, chat_id):

        drop_entries("chat_data", [chat_id])


    # ---- refresco ----
    # No hay estado externo que recargar: la fuente es esta misma tabla.

    async def refresh_user_data(self, user_id, user_data):

        return None


    async def refresh_chat_data(self, chat_id, chat_data):

        return None


    async def refresh_bot_data(self, bot_data):

        return None


    async def flush(self):

        return None


# =========================
# VALORES QUE NO SE PUEDEN GUARDAR
# =========================
# python-telegram-bot copia user_data con copy.deepcopy ANTES de entregarlo a
# la persistencia. Un solo valor no copiable (un lock, un objeto de red, un
# fichero abierto) hace que ese deepcopy falle, y entonces no se guarda el
# estado de NADIE: el volcado entero se cae antes de llegar a nuestro código.
#
# Se comprobó de verdad: con un lock en el user_data de un usuario, el volcado
# lanzaba TypeError y el resto de usuarios se quedaba sin guardar.

def is_copyable(value):

    try:

        copy.deepcopy(value)

        return True

    except Exception:

        return False


def drop_uncopyable_values(*data_dicts):
    """
    Quita solo las claves que impiden copiar el estado, dejando el resto.

    Devuelve la lista de (entidad, clave) retiradas, para poder registrarlo.
    """

    removed = []

    for data_dict in data_dicts:

        for entity_id, entity_data in list((data_dict or {}).items()):

            if not isinstance(entity_data, dict):

                continue


            if is_copyable(entity_data):

                continue


            for key, value in list(entity_data.items()):

                if not is_copyable(value):

                    entity_data.pop(key, None)

                    removed.append((entity_id, key))


    return removed


class ResilientApplication(Application):
    """
    Application que no se queda sin persistencia por un valor no copiable.

    Si el volcado falla, se retiran únicamente las claves culpables y se
    reintenta: se pierde ese dato concreto en vez de perder el estado de todas
    las conversaciones.
    """

    async def update_persistence(self):

        try:

            await super().update_persistence()

            return

        except Exception as e:

            print(
                "Persistencia: el volcado falló, buscando el dato culpable:",
                type(e).__name__,
                str(e)[:200]
            )


        removed = drop_uncopyable_values(self.user_data, self.chat_data)

        if removed:

            print(
                "Persistencia: retirados valores no guardables:",
                ", ".join(f"{entity}.{key}" for entity, key in removed[:10])
            )


        # El intento fallido ya consumió la lista de entidades pendientes, así
        # que sin volver a marcarlas el reintento no guardaría nada. Se marcan
        # todas: solo ocurre en el camino de error, que es excepcional.
        try:

            self.mark_data_for_update_persistence(
                chat_ids=list(self.chat_data.keys()),
                user_ids=list(self.user_data.keys())
            )

        except Exception as e:

            print("Persistencia: no se pudieron remarcar las entidades:", e)


        try:

            await super().update_persistence()

        except Exception as e:

            # Segundo fallo: se avisa y se sigue. El bot funciona igual, solo
            # no recordará estas conversaciones tras un reinicio.
            print(
                "Persistencia: el volcado volvió a fallar, se omite esta vez:",
                type(e).__name__,
                str(e)[:200]
            )


def build_persistence():
    """
    Devuelve la persistencia a usar, o None si está desactivada.

    Si construirla falla, se devuelve None: es mejor un bot sin memoria de
    conversaciones que un bot que no arranca.
    """

    if not PERSISTENCE_ENABLED:

        print("Persistencia: desactivada (PERSISTENCE_ENABLED).")

        return None


    try:

        persistence = PostgresPersistence()

        print(
            "Persistencia: estado de conversaciones en PostgreSQL "
            f"(volcado cada {PERSISTENCE_UPDATE_INTERVAL:g}s, "
            f"caduca a los {PERSISTENCE_MAX_AGE_DAYS} días)."
        )

        return persistence

    except Exception as e:

        print(
            "Persistencia: no se pudo activar, el bot seguirá sin recordar "
            "conversaciones tras un reinicio:",
            e
        )

        return None
