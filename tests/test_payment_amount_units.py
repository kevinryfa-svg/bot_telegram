"""
Las unidades del dinero, de punta a punta.

plans.amount está en la unidad PRINCIPAL (el propietario teclea 15 para quince
euros: el asistente hace int(text) sobre "el PRECIO"). Las tablas de pagos y
transacciones van en la unidad MÍNIMA (céntimos), que es lo que asumen todas
las pantallas (dividen entre 100) y lo que mandan los webhooks.

Antes cada proveedor convertía por su cuenta, y tres de los cuatro se
equivocaban:

  - PayPal guardaba los euros tal cual y los comparaba contra los céntimos del
    webhook: TODOS los pagos de grupo se rechazaban por "amount mismatch".
    Nadie recibió nunca acceso pagando por PayPal.
  - Revolut mandaba los euros a una API que espera céntimos: un plan de 15 €
    generaba un pedido de 0,15 €. El cliente pagaba el 1% y recibía el acceso.
  - Guardarian y ChangeNOW guardaban euros que las pantallas dividían entre
    100: el comprador veía "0.15 EUR" tras pagar 15.

Nada de esto lo vieron las pruebas anteriores porque los dobles pasaban 1500 a
mano: otra vez el doble más permisivo que la realidad.
"""

import ast

import pytest

from payment_gateway_config import ZERO_DECIMAL_CURRENCIES, amount_to_minor_units


# =========================
# LA CONVERSIÓN
# =========================

def test_euros_to_cents():
    assert amount_to_minor_units(15, "EUR") == 1500
    assert amount_to_minor_units("15", "eur") == 1500


def test_zero_decimal_currencies_are_not_multiplied():
    """El yen no tiene céntimos: 15 JPY son 15 unidades mínimas."""

    assert amount_to_minor_units(15, "JPY") == 15
    assert "jpy" in ZERO_DECIMAL_CURRENCIES


def test_decimals_do_not_lose_a_cent():
    """
    En float, 19.99 * 100 da 1998.9999...: truncando se pierde un céntimo, y en
    dinero un céntimo perdido es una discusión con un cliente. Por eso Decimal.
    """

    assert amount_to_minor_units("19.99", "EUR") == 1999
    assert amount_to_minor_units(19.99, "EUR") == 1999


def test_missing_currency_defaults_to_two_decimals():
    assert amount_to_minor_units(15, None) == 1500
    assert amount_to_minor_units(15, "") == 1500


# =========================
# LA ECUACIÓN QUE ROMPÍA PAYPAL
# =========================

def test_stored_amount_equals_what_the_paypal_webhook_parses():
    """
    El fallo, expresado como ecuación. La transacción guarda X al crear el
    pedido; el webhook de PayPal convierte "15.00" a céntimos; la validación
    exige que coincidan. Antes: 15 != 1500, rechazo eterno.
    """

    from payment_providers.paypal_provider import paypal_amount_to_minor

    precio_del_plan = 15  # lo que teclea el propietario

    guardado = amount_to_minor_units(precio_del_plan, "EUR")
    del_webhook = paypal_amount_to_minor("15.00")

    assert guardado == del_webhook == 1500


def test_stripe_and_the_shared_converter_agree():
    """Stripe delega en la misma conversión: una sola fuente de verdad."""

    from stripe_catalog import to_stripe_unit_amount

    for amount, currency in ((15, "EUR"), (15, "JPY"), ("19.99", "USD")):
        assert to_stripe_unit_amount(amount, currency) == \
            amount_to_minor_units(amount, currency)


# =========================
# LOS CUATRO CREADORES DE PEDIDOS DE GRUPO
# =========================

def transaccion_usa_conversor(path, funcion_creadora):
    """
    ¿La llamada a create_payment_transaction dentro del creador pasa
    amount=amount_to_minor_units(...) o una variable derivada de él?

    Se comprueba con AST y no con grep: la lección de esta misma sesión es que
    el texto engaña (comentarios, imports) y el árbol no.
    """

    tree = ast.parse(open(path, encoding="utf-8").read())

    creador = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == funcion_creadora),
        None,
    )

    assert creador is not None, f"{path} ya no tiene {funcion_creadora}"

    # Variables asignadas desde el conversor dentro de la función.
    convertidas = set()

    for n in ast.walk(creador):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            if getattr(n.value.func, "id", None) == "amount_to_minor_units":
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        convertidas.add(t.id)

    for n in ast.walk(creador):

        if not isinstance(n, ast.Call):
            continue

        if getattr(n.func, "id", None) != "create_payment_transaction":
            continue

        kw = next((k for k in n.keywords if k.arg == "amount"), None)

        assert kw is not None, f"{funcion_creadora} no guarda amount"

        es_conversion_directa = (
            isinstance(kw.value, ast.Call)
            and getattr(kw.value.func, "id", None) == "amount_to_minor_units"
        )
        es_variable_convertida = (
            isinstance(kw.value, ast.Name) and kw.value.id in convertidas
        )

        assert es_conversion_directa or es_variable_convertida, (
            f"{funcion_creadora} guarda un amount sin pasar por el conversor: "
            "volvería a mezclar euros con céntimos"
        )

        return

    pytest.fail(f"{funcion_creadora} no llama a create_payment_transaction")


@pytest.mark.parametrize("path,funcion", [
    ("payment_providers/paypal_provider.py", "create_group_paypal_order"),
    ("payment_providers/revolut_provider.py", "create_group_revolut_order"),
    ("payment_providers/guardarian_provider.py", "create_group_guardarian_order"),
    ("payment_providers/changenow_provider.py", "create_group_changenow_order"),
])
def test_every_group_order_stores_minor_units(path, funcion):
    transaccion_usa_conversor(path, funcion)


def test_guardarian_still_sends_euros_to_its_api():
    """
    Guardarian es el único cuya API espera la unidad principal (from_amount
    "15"). La transacción se guarda en céntimos, pero lo que se le manda a
    Guardarian tiene que seguir siendo el importe del plan tal cual: si alguien
    "arregla" esto pasándole céntimos, pediría 1500 € por un plan de 15.
    """

    source = open("payment_providers/guardarian_provider.py", encoding="utf-8").read()
    tree = ast.parse(source)

    creador = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "create_group_guardarian_order"
    )

    llamadas = [
        n for n in ast.walk(creador)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "create_guardarian_transaction"
    ]

    assert llamadas, "el creador ya no llama a create_guardarian_transaction"

    # Segundo argumento posicional: amount_eur. Tiene que ser plan.get("amount")
    # sin conversión.
    arg = llamadas[0].args[1]

    assert isinstance(arg, ast.Call) and getattr(arg.func, "attr", None) == "get", (
        "a la API de Guardarian ya no se le manda el importe del plan tal cual"
    )


def test_revolut_sends_the_converted_amount_to_its_api():
    """La API de Revolut espera céntimos: el pedido va con el importe convertido."""

    source = open("payment_providers/revolut_provider.py", encoding="utf-8").read()

    assert "amount_minor = amount_to_minor_units(" in source


# =========================
# LA CADENA ENTERA, EN UNA LÍNEA
# =========================

def test_the_buyer_sees_the_price_the_owner_typed():
    """
    El propietario teclea 15. La transacción guarda 1500. El mensaje de compra
    divide entre 100 y muestra "15.00 EUR". Si cualquier eslabón cambia de
    unidad, esta prueba lo dice con el número exacto.
    """

    from purchase_message_service import format_purchase_amount

    tecleado = 15
    guardado = amount_to_minor_units(tecleado, "EUR")

    assert format_purchase_amount(guardado, "EUR") == "15.00 EUR"


def test_the_wizard_still_stores_major_units():
    """
    Todo lo anterior depende de que el asistente siga guardando euros. Si algún
    día pide céntimos, el conversor multiplicaría dos veces.
    """

    source = open("admin_input_handler.py", encoding="utf-8").read()

    paso_precio = source[source.index("PASO 4 — PRECIO"):]
    paso_precio = paso_precio[:600]

    assert "int(text)" in paso_precio, (
        "el asistente ya no parsea el precio con int(text): revisar la "
        "convención de unidades entera"
    )
    assert "* 100" not in paso_precio, (
        "el asistente convierte a céntimos al guardar: el conversor de los "
        "proveedores multiplicaría dos veces"
    )


# =========================
# Y LA OTRA UNIDAD: LOS DÍAS QUE ERAN MINUTOS
# =========================
# plans.duration_days está en DÍAS. Había en payment_service una función que la
# leía como MINUTOS cuando el valor era menor de 1440: con ella, el plan real de
# producción de «360 días» daba 360 minutos, seis horas de acceso por 29 euros.
# No la llamaba nadie —la concesión usa calculate_group_access_expiration, que
# lee días— pero estaba ahí, con nombre de utilidad general, esperando a que
# alguien la usara de buena fe.

def test_nothing_reads_plan_days_as_minutes():
    import pathlib

    sospechosos = []

    for ruta in pathlib.Path(".").glob("*.py"):

        fuente = ruta.read_text(encoding="utf-8")

        if "timedelta(" not in fuente or "1440" not in fuente:
            continue

        # Los códigos de acceso temporales SÍ se miden en minutos, y no salen de
        # plans.duration_days: se generan con callback_data gen_<minutos>.
        if "gen_1440" in fuente:
            continue

        sospechosos.append(ruta.name)

    assert sospechosos == [], (
        "algo vuelve a mezclar minutos con la duración de los planes: "
        f"{sospechosos}. plans.duration_days está SIEMPRE en días"
    )


def test_the_minutes_landmine_is_gone_for_good():
    import payment_service

    assert not hasattr(payment_service, "calculate_expiration_from_duration"), (
        "dos funciones con el mismo propósito y unidades contrarias no son una "
        "duplicación, son una trampa"
    )
