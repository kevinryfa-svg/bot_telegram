"""
Ningún camino puede dar un enlace de acceso que caduque en minutos.

Los enlaces de acceso duraban 180 segundos. Se arregló en el camino de compra y
quedaron seis sitios más con el valor puesto a mano, que es el patrón que ya ha
aparecido tres veces en este repositorio: se arregla donde duele y las otras
copias siguen rotas.

Los seis:
  - canje de un código;
  - reenvío del enlace propio desde el menú;
  - reenvío tras desbanear a alguien;
  - reenvío del enlace propio en el flujo de códigos;
  - reenvío masivo del administrador, que además eran 60 segundos: se pulsa un
    botón y todos los usuarios reciben un enlace que muere en un minuto;
  - el enlace nuevo que se da a quien ha compartido el suyo.

Esta prueba no comprueba un caso: comprueba que no queda ninguno, y que no se
pueda añadir otro sin que salte.
"""

import re

import pytest

from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    access_link_expire_seconds,
    format_access_link_validity,
)


# Los ficheros que crean enlaces de acceso para personas.
FUENTES = (
    "main.py",
    "callback_router.py",
    "code_flow_handler.py",
    "admin_input_handler.py",
    "invite_link_service.py",
    "payment_access_service.py",
    "stripe_handler.py",
)


def test_the_shared_value_is_long_enough_to_be_used():
    """
    Una hora es el mínimo por debajo del cual la gente que ya ha pagado se queda
    fuera sin más.
    """

    assert ACCESS_LINK_EXPIRE_SECONDS >= 3600
    assert access_link_expire_seconds() == ACCESS_LINK_EXPIRE_SECONDS


@pytest.mark.parametrize("path", FUENTES)
def test_no_file_hardcodes_a_link_expiry(path):
    """
    Cualquier número literal en expire_seconds es sospechoso: o es corto, o
    dejará de seguir al valor compartido cuando este cambie.
    """

    source = open(path, encoding="utf-8").read()

    literales = re.findall(r"expire_seconds\s*=\s*(\d+)", source)

    assert not literales, (
        f"{path} fija la caducidad del enlace a mano: {literales}. "
        "Debe usar ACCESS_LINK_EXPIRE_SECONDS."
    )


def test_every_link_creation_gets_an_expiry_from_the_shared_value():
    """
    Que no haya literales no basta: una llamada podría pasar una variable que
    valga cualquier cosa. Se comprueba que cada llamada recibe o el valor
    compartido, o una variable calculada a partir de él.
    """

    permitidos = {
        "ACCESS_LINK_EXPIRE_SECONDS",
        # Calculadas con access_link_expire_seconds() o acotadas por él.
        "expire_seconds",
        "max_expire",
    }

    problemas = []

    for path in FUENTES:

        source = open(path, encoding="utf-8").read()

        for llamada in re.finditer(
            r"create_telegram_invite_link\((.*?)\)", source, re.DOTALL
        ):
            argumentos = llamada.group(1)

            encontrado = re.search(
                r"expire_seconds\s*=\s*([A-Za-z_][A-Za-z_0-9]*)", argumentos
            )

            if not encontrado:

                # Sin el parámetro se usa el valor por omisión de la función, que
                # ya es el compartido.
                continue


            if encontrado.group(1) not in permitidos:

                problemas.append(f"{path}: expire_seconds={encontrado.group(1)}")


    assert not problemas, (
        f"caducidades de origen desconocido: {problemas}"
    )


def test_the_default_of_the_helper_follows_the_shared_value():
    """
    create_fresh_user_group_link no se llama hoy desde ninguna parte, pero su
    valor por omisión era 180: la primera llamada que se escriba sin pensar
    reviviría el fallo.
    """

    import inspect

    from invite_link_service import create_fresh_user_group_link

    firma = inspect.signature(create_fresh_user_group_link)
    defecto = firma.parameters["expire_seconds"].default

    assert defecto == ACCESS_LINK_EXPIRE_SECONDS


def test_the_bulk_resend_tells_people_how_long_they_have():
    """
    El reenvío masivo mandaba el enlace pelado. Con enlaces de un día, decirlo
    evita que se deje para luego creyendo que caduca en minutos.
    """

    import callback_router as cr

    linea = cr.build_link_validity_line()

    assert "24" in linea or "hora" in linea.lower()
    assert "un solo uso" in linea

    source = open("callback_router.py", encoding="utf-8").read()

    assert "🔗 Nuevo acceso VIP:\\n{link}" not in source, (
        "el reenvío masivo sigue mandando el enlace a secas"
    )
    assert "build_link_validity_line()" in source


def test_the_validity_line_is_translated():
    assert format_access_link_validity(86400, "es") != format_access_link_validity(
        86400, "en"
    )

    import callback_router as cr

    assert cr.build_link_validity_line("en") != cr.build_link_validity_line("es")


# =========================
# EL BOTÓN "PEDIR MI ENLACE", EJECUTADO
# =========================
# Es el peor de los seis: es el botón que se le ofrece a quien acaba de pagar y
# no ha recibido su enlace. Daba 180 segundos, así que la salida que se le
# ofrecía caducaba antes de que le diera tiempo a usarla.

def test_the_recovery_button_gives_a_link_that_lasts(clean_db, monkeypatch):
    """Se comprueba la caducidad que se le pide a Telegram de verdad."""

    import callback_router as cr

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (81, 'VIP Recuperar', -1081, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (8101, 81, NOW() + INTERVAL '30 days', TRUE)"
        )

    pedidos = []

    def falso_create(token, telegram_group_id, expire_seconds=None, member_limit=None,
                     community_type=None, return_details=False):
        pedidos.append(expire_seconds)
        resultado = {"invite_link": "https://t.me/+nuevo"}
        return resultado if return_details else resultado["invite_link"]

    monkeypatch.setattr(cr, "create_telegram_invite_link", falso_create)
    # Sin enlace previo, para que tenga que crear uno.
    monkeypatch.setattr(cr, "fetch_recent_community_access_invite_link",
                        lambda *a, **k: None)

    cr.recover_or_create_community_access_link(81, 8101)

    assert pedidos, "no se pidió ningún enlace"
    assert pedidos[0] >= 3600, (
        f"el enlace de recuperación dura {pedidos[0]} segundos: "
        "quien acaba de pagar se queda fuera otra vez"
    )


def test_the_link_never_outlives_the_access_it_opens(clean_db, monkeypatch):
    """
    Con dos horas de acceso restante, el enlace no puede valer un día: sería un
    enlace que abre una puerta ya cerrada.
    """

    import callback_router as cr

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (82, 'VIP Corto', -1082, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            "VALUES (8201, 82, NOW() + INTERVAL '2 hours', TRUE)"
        )

    pedidos = []

    def falso_create(token, telegram_group_id, expire_seconds=None, member_limit=None,
                     community_type=None, return_details=False):
        pedidos.append(expire_seconds)
        resultado = {"invite_link": "https://t.me/+corto"}
        return resultado if return_details else resultado["invite_link"]

    monkeypatch.setattr(cr, "create_telegram_invite_link", falso_create)
    monkeypatch.setattr(cr, "fetch_recent_community_access_invite_link",
                        lambda *a, **k: None)

    cr.recover_or_create_community_access_link(82, 8201)

    assert pedidos
    assert pedidos[0] <= 2 * 3600 + 60, (
        f"el enlace dura {pedidos[0]} segundos y el acceso solo dos horas"
    )
