"""
«Ya puedo vender. ¿Y ahora quién viene?»

El panel del propietario responde a todo menos a eso: si está listo, cuánta
gente mira, cuánto entra. Las tres pantallas dan por hecho que hay alguien
mirando, y cuando no lo hay enseñan ceros y ninguna dice qué hacer.

En producción es literal: una comunidad vendible, con su cobro comprobado, y su
página pública sin un solo enlace apuntándole. Lo que falta ahí no es un
consejo, es material: el enlace, el mensaje y dónde pegarlo.

Lo que se vigila aquí es que ese material sea honesto —ni una promesa sobre
contenido que no ha escrito el propietario— y que no se reparta el enlace de
una comunidad que todavía no puede cobrar.
"""

import pytest

import owner_launch_kit_service as kit


@pytest.fixture
def comunidad(clean_db, monkeypatch):
    monkeypatch.setenv("BOT_USERNAME", "TheStarVipBOT")
    monkeypatch.setenv("SERVER_URL", "https://bot.ejemplo")

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(71, 'StarsVip', -1071, TRUE, TRUE, NULL)"
        )
        cur.execute(
            "INSERT INTO plans (id, group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(771, 71, 'Acceso 360 días', 'price_1x', 'price_1x', 360, 29, "
            "'EUR', TRUE)"
        )

    return db


def test_the_owner_gets_the_link_that_leads_to_paying(comunidad):
    texto = kit.build_launch_kit_text(71, "StarsVip")

    assert "https://t.me/TheStarVipBOT?start=group_71" in texto, (
        "es lo único que hay que pegar, y el propietario no tenía forma de "
        "verlo en ninguna pantalla"
    )
    assert "https://bot.ejemplo/comunidades" in texto
    assert "29" in texto, "con el precio: un mensaje sin precio no vende"


def test_it_never_invents_what_is_inside_the_community(comunidad):
    """La comunidad de producción no tiene descripción escrita por nadie."""

    texto = kit.build_launch_kit_text(71, "StarsVip")

    for promesa in ("exclusivo", "diario", "contenido", "señales", "VIP gratis"):
        assert promesa not in texto.lower(), (
            f"«{promesa}» es una promesa que no ha hecho el propietario"
        )

    assert "no puedo inventarme" in texto, (
        "y se le pide a él la descripción, diciéndole por qué"
    )


def test_the_owner_description_is_used_word_for_word(comunidad):
    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET preview_text=%s WHERE id=71",
            ("Análisis de mercado cada mañana y sala de dudas.",)
        )

    texto = kit.build_launch_kit_text(71, "StarsVip")

    assert "Análisis de mercado cada mañana y sala de dudas." in texto
    assert "no puedo inventarme" not in texto, (
        "ya la ha escrito: pedírsela otra vez es ruido"
    )


def test_the_filler_description_is_not_pasted_as_a_pitch(comunidad):
    """El relleno dice lo mismo que el propio mensaje; repetirlo no convence."""

    from bootstrap_tasks import FRASE_DE_RELLENO

    with comunidad.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET preview_text=%s WHERE id=71",
            (f"Acceso al grupo privado de StarsVip. Pagas y {FRASE_DE_RELLENO}.",)
        )

    texto = kit.build_launch_kit_text(71, "StarsVip")

    assert "no puedo inventarme" in texto, (
        "el relleno no es una descripción: hay que seguir pidiéndola"
    )


def test_a_community_that_cannot_charge_gets_no_link(comunidad):
    """Mandar gente a un botón roto es peor que no mandar a nadie."""

    with comunidad.conn.cursor() as cur:
        cur.execute("UPDATE plans SET is_active=FALSE WHERE id=771")

    texto = kit.build_launch_kit_text(71, "StarsVip")

    assert "?start=group_71" not in texto
    assert "¿Puedo vender?" in texto, "y se manda donde eso se arregla"


def test_the_paste_message_is_plain_text(comunidad):
    """Se copia y se pega en WhatsApp, no en un renderizador de Markdown."""

    mensaje = kit.mensaje_para_pegar(kit.oferta_de(71))

    # El guion bajo del enlace (group_71) es inevitable y no es formato: por
    # eso esta pantalla se manda SIN parse_mode, en texto pelado. Lo que no
    # puede llevar es marcado de verdad, que llegaría literal a WhatsApp.
    for caracter in ("*", "`", "[", "]"):
        assert caracter not in mensaje

    assert mensaje.strip().endswith("?start=group_71"), (
        "el enlace, al final: es lo que se pulsa"
    )


def test_the_screen_never_explodes(monkeypatch):
    """Es una pantalla del panel: un error de base no puede dejarla en blanco."""

    def revienta(*a, **k):
        raise RuntimeError("la base no contesta")

    monkeypatch.setattr(kit, "fetch_sellable_communities", revienta)

    texto = kit.build_launch_kit_text(71, "StarsVip")

    assert "StarsVip" in texto
