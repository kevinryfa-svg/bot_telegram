"""
«Ya puedo vender. ¿Y ahora quién viene?»

El panel del propietario responde a todo menos a eso. «¿Puedo vender?» dice si
la comunidad está lista, el embudo dice cuánta gente mira y cuánta paga, y los
ingresos dicen cuánto entra. Las tres pantallas dan por hecho que hay alguien
mirando — y cuando no lo hay, las tres enseñan ceros y ninguna dice qué hacer.

En producción eso es literal: hay UNA comunidad vendible, con su precio, su
cobro comprobado y su página pública indexable, y esa página no está enlazada
en ningún sitio. El bot no tiene tráfico: tiene conocidos.

Esta pantalla da lo único que falta ahí, que no es un consejo sino MATERIAL:

  EL ENLACE       El directo a la oferta de esa comunidad (?start=group_<id>),
                  que es un toque hasta el pago. Es lo que hay que pegar, y
                  hasta ahora el propietario no tenía forma de verlo.

  EL MENSAJE      Un texto listo para copiar, con el nombre, el precio y lo que
                  el bot garantiza. Se copia y se pega tal cual.

  DÓNDE           Tres sitios concretos, no «haz marketing».

LO QUE ESTE TEXTO NO HACE

No inventa nada sobre la comunidad. Si el propietario ha escrito una
descripción, va tal cual; si lo que hay es el relleno automático, se le pide que
la escriba él y se le dice por qué —el mensaje sin eso vende peor— pero no se
rellena con promesas que nadie ha hecho. Prometer «contenido exclusivo diario»
en nombre de otro es cómo se consiguen devoluciones y denuncias.

Y no se entrega el kit de una comunidad que todavía no puede cobrar: mandar
gente a un botón roto es peor que no mandar a nadie.
"""

import os

from start_offer_service import fetch_sellable_communities


BOT_USERNAME = os.environ.get("BOT_USERNAME", "TheStarVipBOT")


def enlace_directo(group_id):
    """Un toque desde cualquier sitio hasta la oferta de esa comunidad."""

    return f"https://t.me/{BOT_USERNAME}?start=group_{int(group_id)}"


def enlace_del_catalogo():
    """La página pública, si el bot tiene dirección. None si no la tiene."""

    base = (os.environ.get("SERVER_URL") or "").strip().rstrip("/")

    return f"{base}/comunidades" if base else None


def oferta_de(group_id):
    """La oferta de esta comunidad tal y como la vería un comprador.

    Se pregunta SIN exigir visibilidad de mercado: una comunidad puede estar
    lista para cobrar y no estar publicada, y en ese caso el enlace directo
    funciona igual. Es justo el caso en el que este kit más falta hace.
    """

    ofertas = fetch_sellable_communities(
        0, limit=1, solo_grupo=int(group_id), exigir_visibilidad=False
    )

    return ofertas[0] if ofertas else None


def mensaje_para_pegar(oferta):
    """El texto que el propietario copia y pega. Solo hechos."""

    from bootstrap_tasks import es_descripcion_de_relleno

    nombre = oferta.get("nombre") or "mi comunidad"
    descripcion = (oferta.get("descripcion") or "").strip()

    lineas = [f"{nombre} — {oferta.get('precio')}"]

    # La descripción del propietario va tal cual. La de relleno no: dice lo
    # mismo que las dos líneas siguientes y repetirlo no convence a nadie.
    if descripcion and not es_descripcion_de_relleno(descripcion):
        lineas.append("")
        lineas.append(descripcion)

    lineas.append("")
    lineas.append("Pagas con tarjeta y el enlace de entrada te llega al momento,")
    lineas.append("automático, sin esperar a que nadie lo apruebe.")
    lineas.append("")
    lineas.append(enlace_directo(oferta.get("group_id")))

    return "\n".join(lineas)


def build_launch_kit_text(group_id, group_name=None):
    """La pantalla entera. Nunca lanza: es una pantalla del panel."""

    try:

        oferta = oferta_de(group_id)

    except Exception as e:

        print("Kit de lanzamiento: error leyendo la oferta:", str(e)[:200])

        oferta = None


    nombre = group_name or f"Comunidad {group_id}"

    if not oferta:

        # Sin oferta vendible no hay nada que repartir. Y el sitio donde se
        # arregla ya existe, así que se manda ahí en vez de repetir aquí sus
        # comprobaciones: dos listas de condiciones acaban discrepando.
        return (
            f"📣 Traer compradores — {nombre}\n\n"
            "Todavía no. Esta comunidad no se puede comprar ahora mismo, así "
            "que repartir su enlace mandaría a la gente a un botón que no "
            "cobra.\n\n"
            "Abre «🚦 ¿Puedo vender?» ahí arriba: dice exactamente qué falta y "
            "cómo se arregla. En cuanto esté, vuelve aquí y te doy el enlace y "
            "el mensaje."
        )


    from bootstrap_tasks import es_descripcion_de_relleno

    descripcion = (oferta.get("descripcion") or "").strip()

    partes = [
        f"📣 Traer compradores — {oferta.get('nombre')}",
        "",
        "Puedes cobrar. Lo que falta es que alguien llegue, y eso no pasa solo.",
        "",
        "1️⃣ TU ENLACE",
        "",
        enlace_directo(oferta.get("group_id")),
        "",
        "Quien lo abre ve tu comunidad y el botón de pagar. Un toque.",
    ]

    catalogo = enlace_del_catalogo()

    if catalogo:

        partes += [
            "",
            "2️⃣ TU PÁGINA PÚBLICA",
            "",
            catalogo,
            "",
            "Es una página web normal: se puede compartir por WhatsApp, poner "
            "en una biografía o mandar por correo, y se ve bien.",
        ]

    partes += [
        "",
        "3️⃣ EL MENSAJE (cópialo tal cual)",
        "",
        "- - - - -",
        mensaje_para_pegar(oferta),
        "- - - - -",
    ]

    if not descripcion or es_descripcion_de_relleno(descripcion):

        partes += [
            "",
            "⚠️ Ese mensaje va sin descripción porque no has escrito ninguna, y "
            "yo no puedo inventarme qué hay dentro de tu comunidad. Escríbela "
            "en «✏️ Editar comunidad» —dos frases con lo que recibe quien "
            "entra— y este mensaje mejora solo.",
        ]

    partes += [
        "",
        "4️⃣ DÓNDE PEGARLO HOY",
        "",
        "• En tu canal o grupo gratuito, si tienes uno: es la gente que ya te "
        "conoce y la que más compra.",
        "• En tu biografía de Instagram, TikTok o X, como único enlace.",
        "• Contestando a quien te pregunta por privado cómo entrar: en vez de "
        "explicarlo, le pegas el enlace y paga solo.",
        "",
        "No hace falta anunciarse en ningún sitio de pago para las primeras "
        "ventas. Hace falta que el enlace esté donde ya te lee alguien.",
    ]

    return "\n".join(partes)
