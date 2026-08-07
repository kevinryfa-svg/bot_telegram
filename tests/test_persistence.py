"""
Estado de conversación que sobrevive a los reinicios.

Todo lo que el bot recordaba de una conversación vivía en memoria, así que
cualquier despliegue borraba un wizard a medias o la comunidad seleccionada —
hasta el punto de decirle al propietario que no tenía permisos en su grupo.

Estos tests comprueban el reinicio de verdad: se guarda con una Application,
se levanta otra desde cero y se mira si el estado volvió.
"""

import datetime
import threading

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ApplicationBuilder, MessageHandler, filters

import persistence_service as ps


FAKE_TOKEN = "0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture
def offline_bot(monkeypatch):
    """Application.initialize() llama a getMe; aquí no hay red."""

    import telegram.ext._extbot as extbot

    async def noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(extbot.ExtBot, "initialize", noop)
    monkeypatch.setattr(extbot.ExtBot, "shutdown", noop)


@pytest.fixture
def empty_persistence(db_module, offline_bot):

    with db_module.conn.cursor() as cur:
        cur.execute("DELETE FROM bot_persistence")

    return ps


def build_app(handler=None):

    builder = (
        ApplicationBuilder()
        .token(FAKE_TOKEN)
        .persistence(ps.PostgresPersistence())
        .application_class(ps.ResilientApplication)
    )

    app = builder.build()

    if handler is not None:
        app.add_handler(MessageHandler(filters.ALL, handler))

    return app


def make_update(app, user_id, update_id=1, text="30"):

    user = User(id=user_id, first_name="U", is_bot=False)
    chat = Chat(id=user_id, type="private")
    message = Message(
        message_id=update_id,
        date=datetime.datetime.now(datetime.timezone.utc),
        chat=chat,
        from_user=user,
        text=text,
    )
    message.set_bot(app.bot)

    return Update(update_id=update_id, message=message)


# =========================
# LO QUE SE GUARDA Y SE RECUPERA
# =========================

def test_wizard_state_survives_a_restart(empty_persistence):
    """El caso que motivó todo esto: un alta de plan a medias."""

    user_id = 5001

    async def handler(update, context):
        context.user_data["adding_plan"] = True
        context.user_data["add_plan_step"] = "duracion"
        context.user_data["new_plan"] = {"name": "Mensual VIP", "amount": 15}

    async def run():
        app = build_app(handler)
        await app.initialize()
        await app.process_update(make_update(app, user_id))
        await app.update_persistence()
        await app.shutdown()

        # El reinicio: proceso nuevo, memoria vacía.
        restarted = build_app()
        await restarted.initialize()
        data = dict(restarted.user_data.get(user_id, {}))
        await restarted.shutdown()

        return data

    import asyncio

    data = asyncio.run(run())

    assert data.get("adding_plan") is True
    assert data.get("add_plan_step") == "duracion"
    assert data.get("new_plan") == {"name": "Mensual VIP", "amount": 15}


def test_selected_community_survives_a_restart(empty_persistence):
    """Perder esto hacía que el bot negase permisos a su propio dueño."""

    user_id = 5002

    async def handler(update, context):
        context.user_data["selected_group_id"] = 7
        context.user_data["selected_group_admin"] = 7

    async def run():
        app = build_app(handler)
        await app.initialize()
        await app.process_update(make_update(app, user_id))
        await app.update_persistence()
        await app.shutdown()

        restarted = build_app()
        await restarted.initialize()
        data = dict(restarted.user_data.get(user_id, {}))
        await restarted.shutdown()

        return data

    import asyncio

    data = asyncio.run(run())

    assert data.get("selected_group_id") == 7
    assert data.get("selected_group_admin") == 7


def test_finishing_a_wizard_clears_the_stored_state(empty_persistence):
    ps.save_entry("user_data", 5003, {"adding_plan": True})

    assert 5003 in ps.load_scope("user_data")

    ps.save_entry("user_data", 5003, {})

    assert 5003 not in ps.load_scope("user_data")


# =========================
# LO QUE NO DEBE ROMPER NADA
# =========================

def test_one_uncopyable_value_does_not_lose_everyone_elses_state(empty_persistence):
    """
    python-telegram-bot copia user_data con deepcopy antes de persistirlo. Sin
    protección, un solo valor no copiable tiraba el volcado completo y NADIE
    guardaba su estado.
    """

    bad_user, good_user = 6001, 6002

    async def handler(update, context):
        context.user_data["paso"] = "precio"

        if update.effective_user.id == bad_user:
            context.user_data["lock"] = threading.Lock()

    async def run():
        app = build_app(handler)
        await app.initialize()
        await app.process_update(make_update(app, bad_user, update_id=1))
        await app.process_update(make_update(app, good_user, update_id=2))
        await app.update_persistence()
        await app.shutdown()

    import asyncio

    asyncio.run(run())

    saved = ps.load_scope("user_data")

    assert saved.get(good_user) == {"paso": "precio"}, (
        "el estado de un usuario se perdió por un dato de otro"
    )

    # Del usuario problemático se pierde solo el dato imposible.
    assert saved.get(bad_user) == {"paso": "precio"}


def test_uncopyable_values_are_removed_one_by_one():
    data = {
        7001: {"bueno": "sí", "malo": threading.Lock()},
        7002: {"bueno": "también"},
    }

    removed = ps.drop_uncopyable_values(data)

    assert removed == [(7001, "malo")]
    assert data[7001] == {"bueno": "sí"}
    assert data[7002] == {"bueno": "también"}


def test_saving_something_unserializable_does_not_raise(empty_persistence):
    assert ps.save_entry("user_data", 7003, {"lock": threading.Lock()}) is False


def test_an_unreadable_row_does_not_block_the_good_ones(empty_persistence, db_module):
    import psycopg2

    ps.save_entry("user_data", 7004, {"paso": "precio"})

    with db_module.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_persistence (scope, entity_id, payload) "
            "VALUES ('user_data', 7005, %s)",
            (psycopg2.Binary(b"esto no es un pickle"),),
        )

    data = ps.load_scope("user_data")

    assert data.get(7004) == {"paso": "precio"}
    assert 7005 not in data

    # La fila ilegible se retira, no se reintenta en cada arranque.
    assert 7005 not in ps.load_scope("user_data")


def test_oversized_state_is_skipped(empty_persistence, monkeypatch):
    monkeypatch.setattr(ps, "PERSISTENCE_MAX_BYTES", 50)

    assert ps.save_entry("user_data", 7006, {"texto": "x" * 5000}) is False
    assert 7006 not in ps.load_scope("user_data")


def test_load_survives_a_broken_database(monkeypatch):
    """Si la persistencia falla, el bot debe arrancar igual, sin memoria."""

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(ps, "conn", BrokenConn())

    assert ps.load_scope("user_data") == {}
    assert ps.save_entry("user_data", 1, {"a": 1}) is False


# =========================
# CADUCIDAD
# =========================

def test_stale_state_is_not_restored(empty_persistence, db_module):
    ps.save_entry("user_data", 7007, {"adding_plan": True})

    with db_module.conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_persistence SET updated_at = NOW() - INTERVAL '60 days' "
            "WHERE entity_id=7007"
        )

    # Restaurar un wizard de hace dos meses confundiría más que ayudar.
    assert 7007 not in ps.load_scope("user_data")


def test_pruning_removes_only_the_stale_state(empty_persistence, db_module):
    ps.save_entry("user_data", 7008, {"reciente": True})
    ps.save_entry("user_data", 7009, {"viejo": True})

    with db_module.conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_persistence SET updated_at = NOW() - INTERVAL '60 days' "
            "WHERE entity_id=7009"
        )

    assert ps.prune_old_entries() == 1
    assert 7008 in ps.load_scope("user_data")


def test_counts_are_reported_by_scope(empty_persistence):
    ps.save_entry("user_data", 7010, {"a": 1})
    ps.save_entry("chat_data", 7011, {"b": 2})

    counts = ps.count_entries()

    assert counts.get("user_data") == 1
    assert counts.get("chat_data") == 1


# =========================
# CONFIGURACIÓN
# =========================

def test_persistence_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(ps, "PERSISTENCE_ENABLED", False)

    assert ps.build_persistence() is None


def test_only_user_and_chat_data_are_stored():
    store = ps.PostgresPersistence().store_data

    assert store.user_data is True
    assert store.chat_data is True

    # bot_data no guarda nada que deba sobrevivir y este bot no usa
    # callbacks arbitrarios.
    assert store.bot_data is False
    assert store.callback_data is False
