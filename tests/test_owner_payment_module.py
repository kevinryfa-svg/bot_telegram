"""
El asistente de métodos de pago del propietario vive en su propio módulo.

Segunda fase de partir callback_router.py. A diferencia de Guardian, aquí no
había un bloque único con una condición propia: eran 16 ramas `if` seguidas.
Eso hace que el guardián de la llamada sea el punto delicado — si captura un
prefijo de más, un callback que antes caía hacia las ramas de después dejaría de
llegar. Estos tests fijan exactamente ese contrato.
"""

import ast

import owner_payment_callbacks as opc


SOURCE = open(opc.__file__, encoding="utf-8").read()
TREE = ast.parse(SOURCE)
ROUTER = open(
    __import__("callback_router").__file__, encoding="utf-8"
).read()


def dispatch_function():
    return next(
        node for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle_owner_payment_callbacks"
    )


# =========================
# EL CONTRATO DEL GUARDIÁN
# =========================

def test_the_guard_is_exactly_the_prefixes_the_module_handles():
    """
    Ni uno de más ni uno de menos. Uno de más robaría callbacks a las ramas
    posteriores; uno de menos dejaría un botón sin atender.
    """

    handled = set()

    for node in ast.walk(dispatch_function()):

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("owner_payment_")
        ):
            handled.add(node.args[0].value)

    assert set(opc.OWNER_PAYMENT_CALLBACK_PREFIXES) == handled, (
        "el guardián y las ramas atendidas no coinciden: "
        f"sobran {handled ^ set(opc.OWNER_PAYMENT_CALLBACK_PREFIXES)}"
    )


def test_the_guard_covers_the_sixteen_branches():
    assert len(opc.OWNER_PAYMENT_CALLBACK_PREFIXES) == 16
    assert len(set(opc.OWNER_PAYMENT_CALLBACK_PREFIXES)) == 16, "prefijo repetido"


def test_no_prefix_swallows_another():
    """
    Si un prefijo fuese prefijo de otro, el orden de las ramas decidiría cuál
    gana y la lista dejaría de describir el comportamiento.
    """

    prefixes = list(opc.OWNER_PAYMENT_CALLBACK_PREFIXES)

    for one in prefixes:
        for other in prefixes:
            if one is other:
                continue

            assert not other.startswith(one), f"{one} se come a {other}"


def test_every_prefix_belongs_to_a_real_provider():
    for prefix in opc.OWNER_PAYMENT_CALLBACK_PREFIXES:
        assert any(
            provider in prefix
            for provider in ("changenow", "guardarian", "paypal", "revolut")
        ), f"{prefix} no corresponde a ningún proveedor conocido"


# =========================
# LA DELEGACIÓN
# =========================

def test_the_router_delegates_using_the_shared_tuple():
    assert "data.startswith(OWNER_PAYMENT_CALLBACK_PREFIXES)" in ROUTER
    assert "await handle_owner_payment_callbacks(" in ROUTER


def test_the_router_no_longer_handles_these_prefixes_itself():
    """
    Si alguna rama se hubiese quedado atrás, se ejecutaría antes o después de la
    delegación y el comportamiento dependería del orden.
    """

    for prefix in opc.OWNER_PAYMENT_CALLBACK_PREFIXES:
        assert f'data.startswith("{prefix}")' not in ROUTER, (
            f"callback_router sigue atendiendo {prefix} por su cuenta"
        )


def test_every_path_of_the_dispatch_returns():
    """
    Quien llama retorna justo después. Eso solo es equivalente si todas las
    ramas retornan, como ocurría en el original.
    """

    handler = dispatch_function()
    returns = [n for n in ast.walk(handler) if isinstance(n, ast.Return)]

    assert returns
    assert all(n.value is None for n in returns), (
        "un return con valor sugiere que el contrato con callback_router cambió"
    )
    assert isinstance(handler.body[-1], ast.Return)


# =========================
# SIN IMPORTACIÓN CIRCULAR
# =========================

def test_the_module_does_not_import_the_router_at_module_level():
    for node in TREE.body:

        if isinstance(node, ast.ImportFrom):
            assert node.module != "callback_router"

        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "callback_router"


def test_the_deferred_wrappers_still_resolve():
    import callback_router

    for name in (
        "build_changenow_safe_summary",
        "build_guardarian_safe_summary",
        "build_owner_changenow_cancel_keyboard",
        "build_owner_guardarian_cancel_keyboard",
        "build_owner_panel_nav_keyboard",
        "build_owner_paypal_cancel_keyboard",
        "build_owner_paypal_safe_summary",
        "build_owner_revolut_cancel_keyboard",
        "build_owner_revolut_safe_summary",
        "clear_owner_payment_provider_wizard",
        "extract_commercial_request_id",
    ):
        assert hasattr(opc, name), f"falta el envoltorio {name}"
        assert hasattr(callback_router, name), (
            f"{name} ya no está en callback_router: el envoltorio fallaría"
        )


def test_provider_constants_come_from_the_real_source():
    """
    Se toman de plan_payment_provider_helpers, no de callback_router: así este
    módulo no depende del que lo importa.
    """

    from plan_payment_provider_helpers import (
        PLAN_PAYMENT_PROVIDER_CHANGENOW,
        PLAN_PAYMENT_PROVIDER_GUARDARIAN,
        PLAN_PAYMENT_PROVIDER_PAYPAL,
        PLAN_PAYMENT_PROVIDER_REVOLUT,
    )

    assert opc.OWNER_PAYMENT_PROVIDER_CHANGENOW == PLAN_PAYMENT_PROVIDER_CHANGENOW
    assert opc.OWNER_PAYMENT_PROVIDER_GUARDARIAN == PLAN_PAYMENT_PROVIDER_GUARDARIAN
    assert opc.OWNER_PAYMENT_PROVIDER_PAYPAL == PLAN_PAYMENT_PROVIDER_PAYPAL
    assert opc.OWNER_PAYMENT_PROVIDER_REVOLUT == PLAN_PAYMENT_PROVIDER_REVOLUT


# =========================
# LO QUE NO DEBE PERDERSE
# =========================

def test_secrets_are_still_encrypted_before_saving():
    """
    Este módulo guarda credenciales de cobro de terceros. El cifrado y su
    comprobación previa tienen que seguir ahí.
    """

    source = ast.unparse(dispatch_function())

    assert "has_payment_encryption_key" in source, (
        "se perdió la comprobación de que hay clave de cifrado"
    )
    assert "encrypt_provider_config" in source, (
        "se perdió el cifrado de las credenciales"
    )
    assert "save_group_payment_provider_encrypted_config" in source


def test_secrets_are_never_echoed_in_full():
    source = ast.unparse(dispatch_function())

    assert "mask_secret_value" in source or "mask_provider_config" in source, (
        "se perdió el enmascarado de los secretos en los mensajes"
    )
