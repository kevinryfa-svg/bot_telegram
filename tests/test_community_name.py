"""
Cómo se llama esta comunidad: una pregunta, una respuesta.

Preguntar el nombre de un grupo estaba escrito tres veces —el router de
botones, el expulsador y el creador de precios de Stripe— y las tres resolvían
cosas distintas con el nombre vacío: None, «la comunidad», o ni preguntaban.
Donde más se notaba era en Stripe: el producto se creaba sin el nombre de la
comunidad y el comprador llegaba a la pantalla de pago sin saber qué compraba.
"""

import group_service as gs


def test_it_gives_the_name(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (71, 'StarsVip', -1071, TRUE)"
        )

    assert gs.nombre_de_comunidad(71) == "StarsVip"


def test_an_empty_name_is_no_name(clean_db):
    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (72, '', -1072, TRUE)"
        )

    assert gs.nombre_de_comunidad(72) is None
    assert gs.nombre_de_comunidad(72, por_defecto="la comunidad") == "la comunidad"


def test_a_community_that_is_not_there(clean_db):
    assert gs.nombre_de_comunidad(999999) is None
    assert gs.nombre_de_comunidad(None) is None


def test_a_broken_database_does_not_take_down_the_screen(monkeypatch):
    """Quedarse sin el nombre es un texto más pobre; quedarse sin la pantalla
    de compra es una venta perdida."""

    class Revienta:
        def cursor(self):
            raise RuntimeError("sin conexión")

    monkeypatch.setattr(gs, "conn", Revienta())

    assert gs.nombre_de_comunidad(71, por_defecto="la comunidad") == "la comunidad"


def test_nobody_asks_it_by_hand_any_more():
    """Tres definiciones de la misma pregunta son tres respuestas distintas."""

    import pathlib
    import re

    patron = re.compile(r"SELECT\s+(NULLIF\(\s*)?name.*FROM groups", re.I)

    culpables = []

    for ruta in sorted(pathlib.Path(".").glob("*.py")):

        if ruta.name == "group_service.py":
            continue

        for numero, linea in enumerate(
            ruta.read_text(encoding="utf-8").splitlines(), start=1
        ):

            if patron.search(linea):
                culpables.append(f"{ruta.name}:{numero}")

    assert culpables == [], (
        "usa group_service.nombre_de_comunidad() en vez de preguntarlo a mano: "
        + ", ".join(culpables)
    )
