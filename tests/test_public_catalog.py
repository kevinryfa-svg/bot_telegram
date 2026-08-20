"""
La puerta pública: una dirección que se puede compartir.

Hasta ahora la única forma de llegar al bot era conocerse su usuario de
Telegram. Sin dirección que compartir no hay tráfico: hay conocidos.

Lo que se vigila aquí es lo que puede hacer daño de verdad en una página
pública: que el precio esté (sin precio no es un escaparate), que el enlace sea
el de un toque hasta pagar, que lo que escribe un propietario no llegue crudo al
HTML, y que sin nada que vender la página siga siendo honesta en vez de romperse.
"""

import pytest

import public_catalog_page as pcp


@pytest.fixture
def catalogo(clean_db):
    """Una comunidad vendible (61) y una que no debe salir (62)."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM group_delivery_health WHERE group_id IN (61,62)")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_marketplace_visible, preview_text) VALUES "
            "(61, 'VIP Trading', -1061, TRUE, TRUE, 'Señales diarias y directos.'), "
            "(62, 'Entrega rota', -1062, TRUE, TRUE, 'El bot no puede invitar.')"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
            "duration_days, amount, currency, is_active) VALUES "
            "(61, 'Mensual', 'price_61m', 'price_61m', 30, 25, 'EUR', TRUE), "
            "(62, 'Mensual', 'price_62m', 'price_62m', 30, 9, 'EUR', TRUE)"
        )
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, bot_status) "
            "VALUES (62, FALSE, 'member')"
        )

    return db


def test_the_page_shows_the_price_and_the_one_tap_link(catalogo):
    pagina = pcp.build_public_catalog_html()

    assert "VIP Trading" in pagina
    assert "25 EUR/mes" in pagina, "una página sin precio no es un escaparate"
    assert "Señales diarias y directos." in pagina

    assert "?start=group_61" in pagina, (
        "el enlace tiene que ser el directo de esa comunidad, no el bot a secas"
    )


def test_what_cannot_be_delivered_is_not_published(catalogo):
    pagina = pcp.build_public_catalog_html()

    assert "Entrega rota" not in pagina, (
        "hereda los filtros del escaparate: no se publica lo que no se entrega"
    )
    assert "?start=group_62" not in pagina


def test_what_an_owner_writes_cannot_inject_html(catalogo):
    """El nombre y la descripción los escribe una persona en Telegram."""

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET name='<script>alert(1)</script>', "
            "preview_text='<img src=x onerror=alert(2)>' WHERE id=61"
        )

    pagina = pcp.build_public_catalog_html()

    assert "<script>alert(1)</script>" not in pagina
    assert "<img src=x onerror" not in pagina
    assert "&lt;script&gt;" in pagina, "se enseña escapado, no se borra"


def test_an_empty_catalogue_is_honest_instead_of_broken(clean_db):
    pagina = pcp.build_public_catalog_html()

    assert "Todavía no hay comunidades publicadas" in pagina
    assert "Publicar mi comunidad" in pagina, (
        "sin nada que vender, la única llamada que tiene sentido es la oferta "
        "al otro lado: publicar"
    )
    assert "<html" in pagina, "sigue siendo una página, no un error"


def test_a_database_failure_still_serves_a_page(catalogo, monkeypatch):
    def explota(*args, **kwargs):
        raise RuntimeError("base de datos caída")

    monkeypatch.setattr(pcp, "fetch_sellable_communities", explota)

    pagina = pcp.build_public_catalog_html()

    assert "<html" in pagina, "una web caída no vende nada"
    assert "Todavía no hay comunidades publicadas" in pagina


def test_the_page_is_self_contained_and_shareable(catalogo):
    pagina = pcp.build_public_catalog_html(base_url="https://ejemplo.test/")

    # Ni una petición a otro dominio: el estilo va dentro.
    assert "<style>" in pagina
    assert "http://" not in pagina.split("<style>")[0].replace(
        "http://www.w3.org", ""
    )

    # Y las etiquetas para que un enlace pegado se vea como algo.
    assert 'property="og:title"' in pagina
    assert 'name="viewport"' in pagina
    assert 'rel="canonical" href="https://ejemplo.test/comunidades"' in pagina


def test_the_route_is_mounted_and_the_status_page_is_untouched():
    fuente = open("main.py", encoding="utf-8").read()

    assert "register_public_catalog_routes" in fuente

    pos = fuente.index("register_public_catalog_routes")

    assert "try:" in fuente[pos - 300:pos], (
        "si la página pública falla al montarse, el bot tiene que arrancar igual"
    )

    # La raíz sigue sirviendo la versión desplegada: es como se comprueba desde
    # fuera qué hay en producción.
    assert '@app.route("/")' in fuente
    assert "describe_running_build" in fuente


def test_the_page_survives_a_community_without_description(catalogo):
    with catalogo.conn.cursor() as cur:
        cur.execute("UPDATE groups SET preview_text=NULL WHERE id=61")

    pagina = pcp.build_public_catalog_html()

    assert "VIP Trading" in pagina
    assert "25 EUR/mes" in pagina
    assert "None" not in pagina, (
        "una descripción vacía no puede acabar imprimiendo «None» en la web"
    )


def test_the_route_answers_with_html_and_a_short_cache(catalogo):
    """La ruta de verdad, con el cliente de pruebas de Flask.

    Probar solo el generador de HTML deja fuera justo lo que se rompe en una
    ruta: el tipo de contenido, las cabeceras y el código de estado.
    """

    from flask import Flask

    app = Flask(__name__)
    pcp.register_public_catalog_routes(app)

    respuesta = app.test_client().get("/comunidades")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["Content-Type"]
    assert "charset=utf-8" in respuesta.headers["Content-Type"].lower(), (
        "sin esto, un nombre con acentos se ve roto en el navegador"
    )
    assert "max-age=60" in respuesta.headers.get("Cache-Control", "")

    cuerpo = respuesta.get_data(as_text=True)

    assert "VIP Trading" in cuerpo
    assert "?start=group_61" in cuerpo


# =========================
# QUE SE PUEDA ENCONTRAR
# =========================
# Una página pública que ningún buscador tiene por qué mirar es una página
# privada con otra dirección.

def test_robots_allows_the_catalogue_and_hides_the_money_routes(catalogo):
    from flask import Flask

    app = Flask(__name__)
    pcp.register_public_catalog_routes(app)

    respuesta = app.test_client().get("/robots.txt")

    assert respuesta.status_code == 200
    assert "text/plain" in respuesta.headers["Content-Type"]

    cuerpo = respuesta.get_data(as_text=True)

    assert "Allow: /comunidades" in cuerpo
    assert "Disallow: /create-checkout-session" in cuerpo, (
        "las rutas de cobro no pintan nada en un índice"
    )
    assert "Disallow: /webhook/" in cuerpo


def test_the_sitemap_points_at_the_catalogue(catalogo):
    from flask import Flask

    app = Flask(__name__)
    pcp.register_public_catalog_routes(app)

    respuesta = app.test_client().get("/sitemap.xml")

    assert respuesta.status_code == 200
    assert "xml" in respuesta.headers["Content-Type"]

    cuerpo = respuesta.get_data(as_text=True)

    assert "/comunidades</loc>" in cuerpo
    assert cuerpo.startswith("<?xml")

    # Las comunidades no se listan una a una: sus enlaces llevan a Telegram, no
    # a esta web, y en un mapa de este sitio no pintan nada.
    assert "t.me" not in cuerpo


def test_robots_says_where_the_sitemap_is(catalogo):
    cuerpo = pcp.build_robots_txt("https://ejemplo.test/")

    assert "Sitemap: https://ejemplo.test/sitemap.xml" in cuerpo
