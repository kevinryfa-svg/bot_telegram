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
import start_offer_service as sos


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


# =========================
# LA OTRA MITAD DEL NEGOCIO
# =========================
# Esta página vendía una sola cosa: entrar en las comunidades de otros. Pero
# quien la encuentra en un buscador puede ser justo la persona que tiene un
# canal privado y no sabe cómo cobrar por él — y esa persona vale más, porque
# paga por publicar y se queda. Hasta ahora solo se le hablaba cuando el
# catálogo estaba VACÍO, que es la única vez que no había nada más que
# enseñarle.

def test_the_page_also_speaks_to_whoever_has_a_community(catalogo):
    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    assert "¿Tienes tú una comunidad privada?" in html_page
    assert html_page.count("Publicar mi comunidad") >= 1, (
        "con catálogo lleno esta llamada no existía"
    )


def test_the_publishing_price_is_the_one_that_will_be_charged(catalogo):
    """La web no puede anunciar un precio que la pantalla de pago desmienta."""

    with catalogo.conn.cursor() as cur:
        cur.execute("DELETE FROM commercial_plans")
        cur.execute(
            "INSERT INTO commercial_plans (id, product_type, name, "
            "duration_days, amount, currency, is_active) VALUES "
            "(801, 'shared_bot_space', '1 mes', 30, 1999, 'EUR', TRUE), "
            "(802, 'shared_bot_space', '1 año', 365, 17999, 'EUR', TRUE)"
        )

    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    assert "19,99 EUR al mes" in html_page, (
        "el más barato por importe, y el importe va en céntimos en esa tabla"
    )
    assert "179,99" not in html_page, "«desde» es el más barato, no cualquiera"


def test_without_a_purchasable_plan_nothing_is_promised(catalogo):
    """Sin plan cobrable no se puede publicar: no se anuncia un precio."""

    with catalogo.conn.cursor() as cur:
        cur.execute("DELETE FROM commercial_plans")

    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    assert "desde" not in html_page.lower().split("¿tienes tú")[-1], (
        "un «desde» sin precio detrás es pedirle al lector que adivine"
    )
    assert "¿Tienes tú una comunidad privada?" in html_page, (
        "la invitación sigue teniendo sentido: se habla con el bot"
    )


def test_the_page_shows_the_discount_and_the_countdown(catalogo, monkeypatch):
    """Un precio rebajado sin decir que está rebajado es solo un precio."""

    creados = []

    def falso_precio(name, amount_major, currency, metadata=None,
                     recurring_interval_days=None):
        creados.append(name)
        return ("prod_x", "price_oferta_web")

    import stripe_catalog
    import weekly_offer_service as ofs

    monkeypatch.setattr(
        stripe_catalog, "create_stripe_product_and_price", falso_precio
    )

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET duration_days=7, amount=9 "
            "WHERE id = (SELECT MIN(id) FROM plans)"
        )
        cur.execute("SELECT MIN(id), group_id FROM plans GROUP BY group_id "
                    "ORDER BY 1 LIMIT 1")
        plan_id, group_id = cur.fetchone()

    plan = [p for p in ofs.planes_ofertables(group_id) if p["id"] == plan_id][0]

    ofs.crear_oferta(plan, percent=60, dias=5)

    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    assert "-60%" in html_page
    assert "quedan" in html_page or "ÚLTIMO DÍA" in html_page
    assert "3,60 EUR" in html_page, "y el precio ya rebajado, con sus céntimos"


def test_without_an_offer_there_is_no_badge(catalogo):
    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    assert "rebaja" not in html_page or "-60%" not in html_page


# =========================
# UNA PÁGINA POR COMUNIDAD
# =========================
# Había UNA dirección para todo el catálogo: sirve para enseñar la lista, no
# para compartir. Quien quiere recomendar SU comunidad mandaba un enlace donde
# había que buscarla entre las demás, y un buscador solo tenía una página que
# indexar para todo el escaparate.

def test_a_community_has_its_own_address(catalogo):
    ofertas = sos.fetch_sellable_communities(0, limit=5)
    oferta = ofertas[0]

    ruta = pcp.ruta_de_comunidad(oferta)

    assert ruta.startswith(f"/comunidades/{oferta['group_id']}"), (
        "el número va delante: es lo único que se usa para buscar"
    )

    pagina = pcp.build_community_page_html(
        oferta["group_id"], base_url="https://bot.ejemplo"
    )

    assert pagina is not None
    assert oferta["nombre"] in pagina


def test_the_preview_carries_its_name_and_price(catalogo):
    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    pagina = pcp.build_community_page_html(
        oferta["group_id"], base_url="https://bot.ejemplo"
    )

    import re

    titulo = re.search(r'<meta property="og:title" content="([^"]*)"', pagina)

    assert titulo, "sin og:title, el enlace se pega como una dirección pelada"
    assert oferta["nombre"] in titulo.group(1)
    assert oferta["precio"] in titulo.group(1), (
        "el precio en la vista previa: es lo que hace abrir el enlace"
    )


def test_the_link_survives_a_rename(catalogo):
    """Un enlace compartido que caduca porque otro editó un campo no es un
    enlace."""

    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "UPDATE groups SET name='Otro nombre distinto' WHERE id=%s",
            (oferta["group_id"],)
        )

    pagina = pcp.build_community_page_html(
        oferta["group_id"], base_url="https://bot.ejemplo"
    )

    assert pagina is not None, "el enlace viejo tiene que seguir funcionando"
    assert "Otro nombre distinto" in pagina


def test_a_community_that_cannot_be_bought_has_no_page(catalogo):
    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    with catalogo.conn.cursor() as cur:
        cur.execute(
            "UPDATE plans SET is_active=FALSE WHERE group_id=%s",
            (oferta["group_id"],)
        )

    assert pcp.build_community_page_html(oferta["group_id"]) is None, (
        "una página de algo que no se puede pagar es una promesa muerta"
    )


def test_the_sitemap_lists_every_community(catalogo):
    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    mapa = pcp.build_sitemap_xml("https://bot.ejemplo")

    assert "https://bot.ejemplo/comunidades<" in mapa.replace("</loc>", "<")
    assert pcp.ruta_de_comunidad(oferta) in mapa, (
        "una página que existe y no está en el mapa no la encuentra nadie"
    )


def test_the_catalogue_links_to_each_page(catalogo):
    html_page = pcp.build_public_catalog_html(base_url="https://bot.ejemplo")

    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    assert pcp.ruta_de_comunidad(oferta) in html_page


def test_the_route_answers_and_falls_back_to_the_catalogue(catalogo):
    import flask

    app = flask.Flask(__name__)
    pcp.register_public_catalog_routes(app)
    cliente = app.test_client()

    oferta = sos.fetch_sellable_communities(0, limit=5)[0]

    buena = cliente.get(pcp.ruta_de_comunidad(oferta))

    assert buena.status_code == 200
    assert oferta["nombre"] in buena.get_data(as_text=True)

    perdida = cliente.get("/comunidades/999999-lo-que-sea")

    assert perdida.status_code == 404
    assert "comunidad" in perdida.get_data(as_text=True).lower(), (
        "en vez de una página rota, el catálogo con lo que sí hay"
    )

    rara = cliente.get("/comunidades/esto-no-es-un-numero")

    assert rara.status_code == 404
