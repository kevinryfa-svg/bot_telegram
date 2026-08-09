"""
Prueba social en la ficha de una comunidad.

Toda comunidad recién publicada le decía a cada visitante:

    ⭐ 0 favoritos
    👥 0 miembros

Eso no es información neutra: es el mejor argumento posible para no comprar, y
lo veía todo el mundo hasta que la comunidad arrancase. Ahora un cero
simplemente no se menciona, y cuando hay algo real que contar se cuenta.
"""

import callback_router as cr


# =========================
# LOS CEROS NO SE ANUNCIAN
# =========================

def test_a_brand_new_community_says_nothing_about_being_empty():
    lineas = cr.format_marketplace_social_proof({
        "member_count": 0,
        "favorites_count": 0,
        "recent_joins": 0,
    })

    assert lineas == []


def test_the_card_of_a_new_community_has_no_empty_lines():
    caption = cr.format_marketplace_group_caption({
        "name": "VIP Fitness",
        "community_type": "group",
        "category": "Fitness",
        "member_count": 0,
        "favorites_count": 0,
        "recent_joins": 0,
        "is_free_group": False,
        "marketplace_badge": "💎 Premium",
        "entry_amount": 15,
        "entry_currency": "EUR",
        "entry_duration_days": 30,
        "plan_count": 1,
        "preview_text": "Entrenos y dietas.",
        "preview_mode": "manual",
    })

    assert "0 miembros" not in caption
    assert "0 favoritos" not in caption
    assert "\n\n\n" not in caption, "quedó un hueco donde estaban los contadores"


def test_the_preview_of_a_new_community_has_no_gap():
    for modo in ("manual", "private", "dynamic", "hybrid"):

        caption = cr.format_marketplace_preview_caption({
            "name": "VIP Fitness",
            "community_type": "group",
            "category": "Fitness",
            "member_count": 0,
            "favorites_count": 0,
            "recent_joins": 0,
            "is_free_group": False,
            "marketplace_badge": "💎 Premium",
            "preview_mode": modo,
            "preview_text": "Entrenos.",
        })

        assert "Fitness\n\n" not in caption, f"hueco en modo {modo}"
        assert "0 miembros" not in caption


# =========================
# CUANDO SÍ HAY ALGO QUE CONTAR
# =========================

def test_real_numbers_are_shown():
    lineas = cr.format_marketplace_social_proof({
        "member_count": 148,
        "favorites_count": 23,
        "recent_joins": 9,
    })

    texto = "\n".join(lineas)

    assert "148 miembros" in texto
    assert "9 personas han entrado esta semana" in texto
    assert "23 favoritos" in texto


def test_singulars_are_not_embarrassing():
    texto = "\n".join(cr.format_marketplace_social_proof({
        "member_count": 1,
        "favorites_count": 1,
        "recent_joins": 1,
    }))

    assert "1 miembro" in texto and "1 miembros" not in texto
    assert "1 favorito" in texto and "1 favoritos" not in texto
    assert "1 persona ha entrado" in texto


def test_channels_have_subscribers_not_members():
    texto = "\n".join(cr.format_marketplace_social_proof(
        {"member_count": 5, "favorites_count": 0, "recent_joins": 0},
        members_label="suscriptores",
    ))

    assert "5 suscriptores" in texto

    uno = "\n".join(cr.format_marketplace_social_proof(
        {"member_count": 1, "favorites_count": 0, "recent_joins": 0},
        members_label="suscriptores",
    ))

    assert "1 suscriptor" in uno and "1 suscriptores" not in uno


def test_large_numbers_are_grouped():
    texto = "\n".join(cr.format_marketplace_social_proof({
        "member_count": 12500,
        "favorites_count": 0,
        "recent_joins": 0,
    }))

    assert "12.500 miembros" in texto


def test_broken_counters_do_not_break_the_card():
    lineas = cr.format_marketplace_social_proof({
        "member_count": "no es un número",
        "favorites_count": None,
        "recent_joins": "raro",
    })

    assert lineas == []


def test_missing_keys_are_treated_as_zero():
    assert cr.format_marketplace_social_proof({}) == []


# =========================
# DE DÓNDE SALEN LOS DATOS
# =========================

def test_recent_joins_comes_from_real_accesses():
    """
    Sale de los accesos concedidos en los últimos 7 días, no de un número
    inventado ni de un contador que se pueda inflar.
    """

    select = cr.get_marketplace_group_select()

    assert "recent_joins" in select
    assert "FROM users u2" in select
    assert "INTERVAL '7 days'" in select


def test_the_named_columns_line_up_with_the_field_list():
    """
    El dict se monta con zip(fields, row), así que una columna añadida a la
    consulta sin añadirla a la lista —o al revés— desplaza todos los valores en
    silencio y la ficha empieza a mostrar un dato en el sitio de otro.

    Se comprueba la alineación, no nombres concretos: fijar aquí el último campo
    hacía que la prueba fallara cada vez que se añadía uno, sin que hubiera nada
    roto.
    """

    import re

    source = open(cr.__file__, encoding="utf-8").read()
    bloque = re.search(
        r"def row_to_marketplace_group.*?return dict\(zip\(fields, row\)\)",
        source,
        re.DOTALL,
    ).group(0)

    campos = re.findall(r'^\s+"(\w+)",?$', bloque, re.MULTILINE)
    select = cr.get_marketplace_group_select()

    # Las columnas con alias explícito son las que se pueden comprobar: las demás
    # son expresiones sin nombre. Su orden relativo tiene que ser el mismo que en
    # la lista de campos.
    alias = re.findall(r"\)\s+AS\s+(\w+)", select)

    assert alias, "la consulta ya no tiene columnas con alias: revisar esta prueba"

    posiciones = [campos.index(a) for a in alias if a in campos]

    assert len(posiciones) == len(alias), (
        "hay columnas con alias en la consulta que no están en la lista de "
        f"campos: {[a for a in alias if a not in campos]}"
    )

    assert posiciones == sorted(posiciones), (
        "el orden de las columnas de la consulta no coincide con el de la lista "
        "de campos: los valores se asignarían al campo equivocado"
    )

    # Y la última columna de la consulta tiene que ser el último campo, que es
    # donde se cuela el desajuste al añadir algo nuevo.
    assert campos[-1] == alias[-1], (
        "la última columna de la consulta y el último campo no coinciden"
    )
