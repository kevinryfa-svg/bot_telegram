"""
La puerta pública: una página web con las comunidades y sus precios.

Hasta ahora la ÚNICA forma de llegar a este bot era conocer su usuario de
Telegram. No había ninguna dirección que compartir, nada que un buscador pudiera
encontrar, nada que se pudiera pegar en un mensaje y se viera bien. Un negocio
cuya única puerta exige saberse el nombre de la puerta no tiene tráfico: tiene
conocidos.

Esta página sirve el MISMO escaparate que /start (start_offer_service), así que
hereda sus garantías sin repetirlas: nada gratuito, nada sin plan usable, nada
con la entrega descartada y nada cuya duración el cobro se niegue a convertir en
acceso. Y cada tarjeta lleva al bot por el enlace directo de su comunidad
(?start=group_<id>), que es el camino de un solo toque hasta el pago.

Tres decisiones que no son evidentes:

  SIN DATOS DE NADIE   Se pregunta con user_id=0, que no tiene acceso a nada.
                       La página es igual para todo el mundo, no se sabe quién
                       la mira y no hay nada que filtrar por persona.

  TODO DENTRO          Ni una petición a otro dominio: el CSS va en la propia
                       página. Una hoja de estilos externa convierte una página
                       que funciona siempre en una que depende de un tercero.

  HONESTA EN VACÍO     Sin nada que vender no se sirve una página rota ni una
                       lista falsa: se dice que todavía no hay comunidades
                       publicadas y se invita a publicar una. Es el estado real
                       de producción hoy y conviene que se vea.
"""

import html
import os

from start_offer_service import fetch_sellable_communities, frase_de_miembros


BOT_USERNAME = os.environ.get("BOT_USERNAME", "TheStarVipBOT")

# Cuántas comunidades se listan. Un tope alto (la página es una lista, no una
# notificación) pero tope: sin él, un catálogo grande serviría una página de
# varios megas a un móvil.
MAX_EN_PAGINA = int(os.environ.get("PUBLIC_CATALOG_MAX", "60"))

TITULO = "Comunidades privadas con acceso inmediato"

DESCRIPCION = (
    "Elige una comunidad, paga con tarjeta y recibes tu enlace de acceso "
    "automáticamente en Telegram."
)


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 48px;font:16px/1.55 -apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#10151c;background:#f5f7fa}
main{max-width:720px;margin:0 auto}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 8px}
.sub{color:#5a6672;margin:0 0 28px}
.card{background:#fff;border:1px solid #e3e8ee;border-radius:12px;padding:18px;
margin-bottom:14px}
.card h2{font-size:1.15rem;margin:0 0 6px}
.desc{color:#5a6672;margin:0 0 14px;white-space:pre-wrap}
.social{color:#2f7a4d;font-weight:600;margin:0 0 10px;font-size:.95rem}
.precio{display:inline-block;font-weight:600;background:#eef4ff;color:#1a4fbf;
border-radius:999px;padding:4px 12px;margin:0 0 14px;font-size:.95rem}
.rebaja{display:inline-block;font-weight:700;background:#ffeceb;color:#c2321f;
border-radius:999px;padding:4px 12px;margin:0 8px 14px 0;font-size:.95rem}
.antes{color:#78848f;text-decoration:line-through;font-weight:500}
.suya{margin:12px 0 0;font-size:.9rem}
.suya a{color:#1a4fbf}
a.cta{display:block;text-align:center;text-decoration:none;font-weight:600;
background:#1a4fbf;color:#fff;border-radius:10px;padding:13px 16px}
a.cta:hover{background:#153f9c}
.vacio{background:#fff;border:1px solid #e3e8ee;border-radius:12px;padding:22px}
.crear{background:#fff;border:1px solid #e3e8ee;border-radius:12px;padding:22px;
margin-top:34px}
.crear h2{font-size:1.2rem;margin:0 0 8px}
.crear p{color:#5a6672;margin:0 0 14px}
.crear ul{color:#5a6672;margin:0 0 16px;padding-left:20px}
.crear li{margin-bottom:6px}
.desde{font-weight:600;color:#10151c}
footer{color:#78848f;font-size:.85rem;margin-top:30px;text-align:center}
footer a{color:#1a4fbf}
@media (prefers-color-scheme:dark){
body{background:#0f1319;color:#e8edf3}
.card,.vacio,.crear{background:#161c24;border-color:#252d38}
.crear p,.crear ul{color:#9aa7b4}
.desde{color:#e8edf3}
.desc,.sub{color:#9aa7b4}
.precio{background:#1b2740;color:#8fb4ff}
.rebaja{background:#3a1c19;color:#ff9d8f}
.antes{color:#7b8794}
.social{color:#6fcf97}
footer{color:#7b8794}
}
"""


# Lo que se le pone al enlace para que quien tiene SU comunidad aterrice donde
# se publica, y no en la bienvenida del comprador.
CARGA_DE_PUBLICAR = "publicar"


def enlace_del_bot(group_id=None, carga=None):
    """El enlace al bot. Con comunidad, el enlace directo a su oferta.

    Con `carga`, aterriza en la pantalla que corresponda. El enlace pelado deja
    a quien lo pulsa en la bienvenida genérica, y desde ahí tiene que volver a
    buscar lo que venía a hacer: el clic ya está conseguido, y perderlo en la
    puerta es lo más caro que hace este bot.
    """

    base = f"https://t.me/{BOT_USERNAME}"

    if group_id:
        return f"{base}?start=group_{int(group_id)}"

    if carga:
        return f"{base}?start={carga}"

    return base


def enlace_para_publicar():
    """El enlace de «publicar mi comunidad». Va directo a esa pantalla.

    Quien pulsa esto tiene un canal privado y quiere cobrar por él: vale más
    para el negocio que una entrada suelta, porque paga todos los meses. Hasta
    ahora caía en «elige tu acceso» —la pantalla de COMPRAR— y tenía que
    encontrar solo el tercer botón del menú.
    """

    return enlace_del_bot(carga=CARGA_DE_PUBLICAR)


def _insignia_de_oferta(oferta):
    """«🔥 -60% · antes 9 EUR · quedan 3 días». Cadena vacía si no hay oferta.

    Un precio rebajado sin decir que está rebajado es solo un precio. Los tres
    datos van juntos: el porcentaje llama, el precio de antes lo hace
    comprobable, y la cuenta atrás es la única razón para comprar hoy.
    """

    percent = (oferta or {}).get("oferta_percent")

    if not percent:
        return ""

    trozos = [f"🔥 -{int(percent)}%"]

    if oferta.get("oferta_antes"):

        trozos.append(
            f'<span class="antes">{html.escape(oferta["oferta_antes"])}</span>'
        )

    from weekly_offer_service import frase_cuenta_atras

    cuenta = frase_cuenta_atras(oferta.get("oferta_termina"))

    if cuenta:
        trozos.append(html.escape(cuenta))

    return '<p class="rebaja">' + " · ".join(trozos) + "</p>"


def _tarjeta(oferta, solo_esta=False):
    """El HTML de una comunidad. Todo lo del propietario va escapado.

    El nombre y la descripción los escribe una persona en Telegram: si eso
    llega crudo a una página, cualquier propietario podría inyectar HTML en el
    escaparate de los demás.
    """

    nombre = html.escape(oferta.get("nombre") or "Comunidad")
    descripcion = html.escape((oferta.get("descripcion") or "")[:400])
    precio = html.escape(oferta.get("precio") or "")
    enlace = html.escape(enlace_del_bot(oferta.get("group_id")))

    partes = [f'<article class="card"><h2>{nombre}</h2>']

    if descripcion:
        partes.append(f'<p class="desc">{descripcion}</p>')

    # La misma prueba social que dentro del bot y con el mismo umbral: contada
    # de accesos vivos, no inventada. Aquí importa más todavía, porque quien
    # llega a la web no conoce de nada a quien vende.
    social = frase_de_miembros(oferta)

    if social:
        partes.append(f'<p class="social">{html.escape(social)}</p>')

    # La rebaja va DELANTE del precio: es lo que hace mirar el precio.
    rebaja = _insignia_de_oferta(oferta)

    if rebaja:
        partes.append(rebaja)

    if precio:
        partes.append(f'<p class="precio">{precio}</p>')

    partes.append(
        f'<a class="cta" href="{enlace}" rel="nofollow">Entrar por {precio}</a>'
        if precio else
        f'<a class="cta" href="{enlace}" rel="nofollow">Ver esta comunidad</a>'
    )

    # El enlace a su página propia: es el que se comparte y el que un buscador
    # indexa por lo que ESTA comunidad es. En su propia página no se repite.
    if not solo_esta:

        partes.append(
            f'<p class="suya"><a href="{html.escape(ruta_de_comunidad(oferta))}">'
            "Página de esta comunidad</a></p>"
        )

    partes.append("</article>")

    return "".join(partes)


def _precio_de_publicar():
    """«desde 19,99 EUR al mes», con el precio REAL. None si no se puede pagar.

    Sale de los mismos planes que cobra el bot, así que la web no puede
    anunciar un precio que la pantalla de pago desmienta. Y si ninguno tiene
    precio, esta sección no promete nada: no se puede publicar todavía.
    """

    try:

        from platform_plan_service import (
            describe_plan_period,
            fetch_purchasable_platform_plans,
            format_plan_amount,
        )

        planes = fetch_purchasable_platform_plans()

    except Exception as e:

        print("Catálogo público: error leyendo el plan de publicación:", str(e)[:200])

        return None

    if not planes:
        return None

    # El más barato por importe, no el primero: el orden de la consulta es por
    # duración, y el de un mes no tiene por qué ser el que menos cuesta.
    barato = min(planes, key=lambda p: int(p.get("amount") or 0))

    importe = format_plan_amount(barato)

    if not importe:
        return None

    periodo = describe_plan_period(barato)

    return f"{importe} {periodo}".strip()


def _seccion_para_creadores():
    """Lo que ve quien llega aquí y tiene SU PROPIO canal privado.

    Esta página vendía una sola cosa: entrar en las comunidades de otros. Pero
    quien la encuentra en un buscador puede ser justo la persona que tiene un
    canal privado y no sabe cómo cobrar por él — y esa persona vale más para el
    negocio que una entrada suelta, porque paga por publicar y se queda.
    Hasta ahora solo se le hablaba cuando el catálogo estaba VACÍO, que es la
    única vez que no había nada más que enseñarle.
    """

    precio = _precio_de_publicar()

    partes = [
        '<section class="crear">',
        "<h2>¿Tienes tú una comunidad privada?</h2>",
        "<p>Si ya tienes un grupo o canal privado en Telegram, aquí puedes "
        "cobrar por la entrada sin montar nada.</p>",
        "<ul>",
        "<li>El cobro con tarjeta lo pone el bot.</li>",
        "<li>Al confirmarse el pago, entrega el enlace de entrada solo.</li>",
        "<li>Cuando caduca el acceso, saca a quien no ha renovado.</li>",
        "</ul>",
    ]

    if precio:

        partes.append(
            f'<p class="desde">Publicar tu comunidad: desde {html.escape(precio)}.</p>'
        )

    partes.append(
        f'<a class="cta" href="{html.escape(enlace_para_publicar())}" '
        'rel="nofollow">Publicar mi comunidad</a>'
    )

    partes.append("</section>")

    return "".join(partes)


def _pagina(cuerpo, url_canonica=None, titulo=None, descripcion=None):
    """El envoltorio: cabecera, estilos y las etiquetas para compartir.

    Las etiquetas Open Graph no son adorno: sin ellas, un enlace pegado en
    WhatsApp o Telegram aparece como una dirección pelada, y una dirección
    pelada no la abre nadie. Con título y descripción propios, la página de una
    comunidad se comparte con SU nombre y SU precio en la vista previa.
    """

    titulo = titulo or TITULO
    descripcion = descripcion or DESCRIPCION

    canonica = (
        f'<link rel="canonical" href="{html.escape(url_canonica)}">'
        if url_canonica else ""
    )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title>
<meta name="description" content="{html.escape(descripcion)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{html.escape(titulo)}">
<meta property="og:description" content="{html.escape(descripcion)}">
<meta name="twitter:card" content="summary">
{canonica}
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{html.escape(titulo)}</h1>
<p class="sub">{html.escape(descripcion)}</p>
{cuerpo}
<footer>
El acceso lo entrega el bot automáticamente al confirmarse el pago ·
<a href="{html.escape(enlace_del_bot())}" rel="nofollow">Abrir el bot en Telegram</a>
</footer>
</main>
</body>
</html>"""


def build_public_catalog_html(base_url=None):
    """La página entera. Nunca lanza: una web caída no vende nada."""

    try:

        ofertas = fetch_sellable_communities(0, limit=MAX_EN_PAGINA)

    except Exception as e:

        print("Catálogo público: error leyendo el escaparate:", str(e)[:200])

        ofertas = []


    canonica = f"{base_url.rstrip('/')}/comunidades" if base_url else None

    if not ofertas:

        # El estado real de producción hoy. Decirlo es mejor que enseñar una
        # página vacía sin explicación, y de paso es la única llamada a la
        # oferta que tiene sentido aquí: publicar una comunidad.
        cuerpo = (
            '<div class="vacio">'
            "<p>Todavía no hay comunidades publicadas con acceso inmediato.</p>"
            "<p>Si tienes una comunidad privada en Telegram, puedes publicarla "
            "aquí y cobrar suscripciones con acceso automático.</p>"
            f'<p><a class="cta" href="{html.escape(enlace_para_publicar())}" '
            'rel="nofollow">Publicar mi comunidad</a></p>'
            "</div>"
        )

        return _pagina(cuerpo, canonica)


    tarjetas = "".join(_tarjeta(oferta) for oferta in ofertas)

    return _pagina(tarjetas + _seccion_para_creadores(), canonica)


# =========================
# UNA PÁGINA POR COMUNIDAD
# =========================
# Hasta ahora había UNA dirección para todo el catálogo. Eso sirve para
# enseñar la lista, pero no para compartir: quien quiere recomendar SU
# comunidad manda un enlace donde hay que buscarla entre las demás, y el
# buscador solo tiene una página que indexar para todo el escaparate.
#
# Con dirección propia, cada comunidad tiene un enlace que se pega en WhatsApp
# con su nombre y su precio en la vista previa, y una página que un buscador
# puede encontrar por lo que esa comunidad es.


def ruta_de_comunidad(oferta):
    """«/comunidades/1159-starsvip». El número manda; el texto es para leer.

    El identificador va DELANTE y es el único que se usa para buscar: si el
    propietario cambia el nombre, el enlace viejo que alguien pegó en un chat
    sigue funcionando. Un enlace compartido que caduca porque otro editó un
    campo no es un enlace.
    """

    import re
    import unicodedata

    nombre = (oferta.get("nombre") or "").strip()

    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", nombre)
        if not unicodedata.combining(c)
    )

    trozo = re.sub(r"[^a-zA-Z0-9]+", "-", sin_tildes).strip("-").lower()

    return f"/comunidades/{int(oferta['group_id'])}" + (f"-{trozo}" if trozo else "")


def _titulo_de_comunidad(oferta):

    precio = oferta.get("precio")

    return (
        f"{oferta.get('nombre') or 'Comunidad privada'}"
        + (f" — {precio}" if precio else "")
    )


def _descripcion_de_comunidad(oferta):
    """Lo que se lee en la vista previa al compartir. Solo hechos."""

    descripcion = (oferta.get("descripcion") or "").strip()

    try:

        from bootstrap_tasks import es_descripcion_de_relleno

        if descripcion and es_descripcion_de_relleno(descripcion):
            descripcion = ""

    except Exception:

        pass

    if descripcion:
        return descripcion[:200]

    return DESCRIPCION


def build_community_page_html(group_id, base_url=None):
    """La página de UNA comunidad. None si no se puede comprar ahora mismo.

    Se pregunta sin exigir visibilidad de mercado: una comunidad puede estar
    lista para cobrar y no estar publicada en el escaparate, y su propietario
    tiene que poder compartir su enlace igualmente. Lo que NO se sirve es una
    página de algo que no se puede pagar.
    """

    try:

        ofertas = fetch_sellable_communities(
            0, limit=1, solo_grupo=int(group_id), exigir_visibilidad=False
        )

    except Exception as e:

        print("Página de comunidad: error leyendo la oferta:", str(e)[:200])

        return None

    if not ofertas:
        return None

    oferta = ofertas[0]

    canonica = (
        f"{base_url.rstrip('/')}{ruta_de_comunidad(oferta)}" if base_url else None
    )

    cuerpo = (
        _tarjeta(oferta, solo_esta=True)
        + '<p class="sub" style="margin-top:22px">'
        + "El acceso lo entrega el bot automáticamente al confirmarse el pago."
        + "</p>"
        + _seccion_para_creadores()
    )

    return _pagina(
        cuerpo,
        canonica,
        titulo=_titulo_de_comunidad(oferta),
        descripcion=_descripcion_de_comunidad(oferta),
    )


def build_robots_txt(base_url):
    """robots.txt: permite indexar y dice dónde está el mapa.

    Sin esto un buscador no tiene por qué mirar nada, y el catálogo público es
    justo la única página que interesa que encuentre alguien que no conoce el
    bot. Se prohíbe explícitamente lo que no es escaparate: las rutas de cobro y
    de webhooks no pintan nada en un índice.
    """

    base = (base_url or "").rstrip("/")

    lineas = [
        "User-agent: *",
        "Allow: /comunidades",
        # Y la página de cada una: es la que un buscador puede encontrar por lo
        # que ESA comunidad es, no por el escaparate entero.
        "Allow: /comunidades/",
        "Disallow: /create-checkout-session",
        "Disallow: /create-paypal-group-order",
        "Disallow: /create-revolut-group-order",
        "Disallow: /create-changenow-group-order",
        "Disallow: /create-guardarian-group-order",
        "Disallow: /create-paypal-platform-order",
        "Disallow: /create-changenow-platform-order",
        "Disallow: /create-guardarian-platform-order",
        "Disallow: /create-revolut-platform-order",
        "Disallow: /webhook/",
        "Disallow: /owner-addon-success",
        "Disallow: /owner-addon-cancel",
    ]

    if base:
        lineas.append(f"Sitemap: {base}/sitemap.xml")

    return "\n".join(lineas) + "\n"


def build_sitemap_xml(base_url):
    """El mapa: el catálogo y la página de cada comunidad.

    Antes solo iba el catálogo, y era verdad que las comunidades no tenían
    página propia: sus enlaces llevaban a Telegram. Ahora sí la tienen, y una
    página que existe y no está en el mapa es una página que nadie encuentra.
    """

    base = (base_url or "").rstrip("/")

    def loc(ruta):
        return html.escape(f"{base}{ruta}") if base else ruta

    lineas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{loc('/comunidades')}</loc>"
        "<changefreq>daily</changefreq></url>",
    ]

    try:

        for oferta in fetch_sellable_communities(0, limit=MAX_EN_PAGINA):

            lineas.append(
                f"  <url><loc>{loc(ruta_de_comunidad(oferta))}</loc>"
                "<changefreq>daily</changefreq></url>"
            )

    except Exception as e:

        print("Mapa del sitio: error listando comunidades:", str(e)[:200])

    lineas.append("</urlset>")

    return "\n".join(lineas) + "\n"


def register_public_catalog_routes(app):
    """Monta /comunidades. La raíz sigue siendo el estado del despliegue."""

    from flask import Response, request

    @app.route("/comunidades", methods=["GET"])
    def comunidades_publicas():

        base = os.environ.get("SERVER_URL") or request.url_root

        return Response(
            build_public_catalog_html(base_url=base),
            mimetype="text/html; charset=utf-8",
            headers={
                # Un minuto de caché: suficiente para aguantar que un enlace se
                # comparta y varias personas entren a la vez, y poco para que un
                # precio nuevo se vea enseguida.
                "Cache-Control": "public, max-age=60",
            },
        )

    @app.route("/comunidades/<path:referencia>", methods=["GET"])
    def comunidad_publica(referencia):

        # Del «1159-starsvip» solo manda el número: si el propietario cambia el
        # nombre, el enlace que alguien pegó en un chat sigue funcionando.
        numero = referencia.split("-", 1)[0]

        try:

            group_id = int(numero)

        except (TypeError, ValueError):

            return Response(
                build_public_catalog_html(
                    base_url=os.environ.get("SERVER_URL") or request.url_root
                ),
                status=404,
                mimetype="text/html; charset=utf-8",
            )

        base = os.environ.get("SERVER_URL") or request.url_root

        pagina = build_community_page_html(group_id, base_url=base)

        if not pagina:

            # No se puede comprar: en vez de una página rota o una promesa
            # muerta, el catálogo con lo que sí hay.
            return Response(
                build_public_catalog_html(base_url=base),
                status=404,
                mimetype="text/html; charset=utf-8",
                headers={"Cache-Control": "public, max-age=60"},
            )

        return Response(
            pagina,
            mimetype="text/html; charset=utf-8",
            headers={"Cache-Control": "public, max-age=60"},
        )


    @app.route("/robots.txt", methods=["GET"])
    def robots_publico():

        base = os.environ.get("SERVER_URL") or request.url_root

        return Response(
            build_robots_txt(base),
            mimetype="text/plain; charset=utf-8",
            headers={"Cache-Control": "public, max-age=3600"},
        )


    @app.route("/sitemap.xml", methods=["GET"])
    def sitemap_publico():

        base = os.environ.get("SERVER_URL") or request.url_root

        return Response(
            build_sitemap_xml(base),
            mimetype="application/xml; charset=utf-8",
            headers={"Cache-Control": "public, max-age=3600"},
        )


    return True
