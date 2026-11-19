"""La ficha de solo lectura de una persona, para «no le deja entrar»."""

import pytest

import bootstrap_tasks as bt


@pytest.fixture
def persona(clean_db, monkeypatch):

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (1159, 'StarsVip', -1001159, TRUE)"
        )
        cur.execute(
            "INSERT INTO banned_users (user_id, group_id) VALUES (6726575989, 1159)"
        )
        cur.execute(
            "INSERT INTO bot_user_events (user_id, event_type, event_key) "
            "VALUES (6726575989, 'callback', 'group_user_promo_redeem_start_1159')"
        )

    preguntas = []

    def falso_estado(tg, uid):
        preguntas.append((tg, uid))
        return "BLOQUEADO en el grupo (para siempre)"

    monkeypatch.setattr(bt, "_estado_en_telegram", falso_estado)
    monkeypatch.setenv("BOOTSTRAP_USER_LOOKUP", "6726575989")

    return preguntas


def test_la_ficha_dice_el_veto_las_pulsaciones_y_telegram(persona):
    salida = bt.tarea_ficha_usuario()

    assert "Usuario 6726575989" in salida
    assert "Vetos: 1159 · StarsVip" in salida
    assert "group_user_promo_redeem_start_1159" in salida
    assert "Telegram, «StarsVip» (#1159): BLOQUEADO" in salida
    assert persona == [(-1001159, 6726575989)]


def test_sin_nada_lo_dice(clean_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_USER_LOOKUP", "123")
    monkeypatch.setattr(bt, "_estado_en_telegram", lambda tg, u: "fuera")

    salida = bt.tarea_ficha_usuario()

    assert "Vetos: ninguno" in salida
    assert "Accesos: ninguno" in salida


def test_es_de_solo_lectura():
    """Ni un INSERT, UPDATE ni DELETE en la tarea, ni una llamada que cambie Telegram."""

    import inspect

    fuente = inspect.getsource(bt.tarea_ficha_usuario) + inspect.getsource(
        bt._estado_en_telegram
    )

    for prohibido in ("INSERT", "UPDATE ", "DELETE", "banChatMember",
                      "unbanChatMember", "commit("):
        assert prohibido not in fuente, prohibido


def test_sin_variable_no_hace_nada(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_USER_LOOKUP", raising=False)

    assert "falta BOOTSTRAP_USER_LOOKUP" in bt.tarea_ficha_usuario()


def test_esta_registrada():
    assert bt.TAREAS["ficha_usuario"] is bt.tarea_ficha_usuario
