"""
El embudo de TODO el bot, no el de una comunidad.

El de cada comunidad responde «¿por qué no vende esta?». Este responde la
pregunta de arriba, la que decide en qué gastar el día siguiente: ¿no viene
nadie, se caen al ver el precio, o el cobro los está perdiendo? Tres problemas
con tres arreglos completamente distintos.
"""

import pytest

import platform_funnel_service as pfs


@pytest.fixture
def actividad(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (71, 'StarsVip', -1071, TRUE)"
        )
        # Cuatro llegan, dos miran, uno empieza a pagar, ninguno paga.
        cur.execute(
            "INSERT INTO bot_user_events (user_id, event_type, group_id) VALUES "
            "(7101, 'start', NULL), (7102, 'start', NULL), "
            "(7103, 'start', NULL), (7104, 'start', NULL), "
            "(7101, 'community_viewed', 71), (7102, 'community_viewed', 71), "
            "(7101, 'community_viewed', 71)"
        )
        cur.execute(
            "INSERT INTO payment_transactions (user_id, group_id, provider, "
            "status, purchase_type) VALUES (7101, 71, 'stripe', 'pending', "
            "'group_access')"
        )

    return db


def test_it_counts_people_not_clicks(actividad):
    numeros = pfs.fetch_platform_funnel()

    assert numeros["llegan"] == 4
    assert numeros["miran"] == 2, (
        "quien abre seis veces la misma ficha no son seis interesados"
    )
    assert numeros["empiezan"] == 1
    assert numeros["pagan"] == 0


def test_a_percentage_over_zero_is_not_zero():
    assert pfs.porcentaje(3, 6) == "50%"
    assert pfs.porcentaje(0, 6) == "0%"
    assert pfs.porcentaje(3, 0) is None, (
        "un porcentaje sobre cero no es un cero, es un «no se sabe»"
    )


def test_it_names_the_step_that_is_broken(actividad):
    texto = pfs.build_platform_funnel_text()

    assert "Llegan al bot: 4" in texto
    assert "Miran una comunidad: 2" in texto
    assert "no paga NINGUNO" in texto, (
        "llegan a la pasarela y no paga nadie: eso ya no es el producto"
    )


def test_with_nobody_arriving_it_says_so(clean_db):
    texto = pfs.build_platform_funnel_text()

    assert "no llega gente" in texto
    assert "Traer compradores" in texto, "y dónde está el material"


def test_it_only_diagnoses_the_topmost_problem(actividad):
    """Arreglar el paso de abajo con el de arriba roto no cambia nada."""

    texto = pfs.build_platform_funnel_text()

    assert texto.count("🚨") <= 1


def test_a_database_error_does_not_break_the_screen(monkeypatch):
    def revienta(*a, **k):
        raise RuntimeError("la base no contesta")

    monkeypatch.setattr(pfs, "fetch_platform_funnel", lambda days=30: {
        "llegan": 0, "miran": 0, "empiezan": 0, "pagan": 0
    })

    assert "Embudo del bot" in pfs.build_platform_funnel_text()
