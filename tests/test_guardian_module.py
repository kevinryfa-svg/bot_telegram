"""
Guardian vive en su propio módulo.

Primera fase de partir callback_router.py. Estos tests fijan lo que hace que la
separación siga siendo una separación: que no haya importación circular, que el
despacho siga cubriendo los mismos botones, y que el contrato entre los dos
archivos no se rompa sin que nadie se entere.
"""

import ast

import guardian_callbacks as gc


SOURCE = open(gc.__file__, encoding="utf-8").read()
TREE = ast.parse(SOURCE)


# =========================
# SIN IMPORTACIÓN CIRCULAR
# =========================

def test_the_module_does_not_import_the_router_at_module_level():
    """
    callback_router importa este módulo. Si este importase callback_router
    arriba, el bot no arrancaría.
    """

    for node in TREE.body:

        if isinstance(node, ast.ImportFrom):
            assert node.module != "callback_router", (
                "importación circular: guardian_callbacks importa callback_router "
                "a nivel de módulo"
            )

        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "callback_router"


def test_the_deferred_wrappers_exist_and_work():
    """
    Los cuatro ayudantes compartidos se quedaron en callback_router y se llaman
    de forma diferida. Si alguno desapareciera de allí, esto lo detecta.
    """

    import callback_router

    for name in (
        "build_owner_panel_nav_keyboard",
        "fetch_group_basic_info",
        "format_owner_addon_price",
        "user_has_group_permission_any",
    ):
        assert hasattr(gc, name), f"falta el envoltorio {name}"
        assert hasattr(callback_router, name), (
            f"{name} ya no está en callback_router: el envoltorio fallaría al llamarse"
        )


def test_the_router_can_be_imported_together_with_this_module():
    import callback_router
    import guardian_callbacks

    assert callback_router.handle_guardian_callbacks is (
        guardian_callbacks.handle_guardian_callbacks
    )


# =========================
# EL DESPACHO
# =========================

def test_the_router_delegates_the_guardian_prefix():
    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert 'if data.startswith("owner_guardian_"):' in router
    assert "await handle_guardian_callbacks(" in router


def test_the_dispatch_still_covers_every_guardian_prefix():
    """
    Cuenta los prefijos que atiende el despacho. Si una fase posterior mueve
    algo y se deja una rama por el camino, este número baja.
    """

    handler = next(
        node for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle_guardian_callbacks"
    )

    prefixes = set()

    for node in ast.walk(handler):

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and node.args
        ):
            argument = node.args[0]
            values = []

            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                values = [argument.value]

            elif isinstance(argument, ast.Tuple):
                values = [
                    element.value
                    for element in argument.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]

            prefixes.update(v for v in values if v.startswith("owner_guardian_"))

    assert len(prefixes) >= 26, (
        f"el despacho de Guardian solo cubre {len(prefixes)} prefijos; "
        "se ha perdido alguna rama"
    )


def test_every_path_of_the_handler_still_returns():
    """
    Quien llama retorna justo después de esta función, porque en el original
    todos los caminos del bloque acababan en return. Si alguien añadiese una
    rama que se saliera sin retornar, el original habría seguido evaluando las
    ramas siguientes y aquí no: esa es la única forma de que la extracción
    dejase de ser equivalente.
    """

    handler = next(
        node for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle_guardian_callbacks"
    )

    returns = [n for n in ast.walk(handler) if isinstance(n, ast.Return)]

    assert returns, "el despacho no retorna nunca"
    assert all(n.value is None for n in returns), (
        "un return con valor sugiere que el contrato con callback_router cambió"
    )

    # La última sentencia del cuerpo debe ser un return incondicional.
    assert isinstance(handler.body[-1], ast.Return)


# =========================
# LOS TEXTOS Y TECLADOS QUE SE MOVIERON
# =========================

def test_the_panel_builders_came_along():
    for name in (
        "build_owner_guardian_panel_keyboard",
        "build_owner_guardian_warnings_text",
        "build_owner_guardian_anti_links_text",
        "build_owner_guardian_forbidden_words_text",
        "build_owner_guardian_night_mode_text",
        "build_owner_guardian_log_events_text",
        "owner_can_use_guardian",
        "user_can_view_guardian_warnings",
    ):
        assert callable(getattr(gc, name, None)), f"falta {name}"


def test_the_addon_gate_still_guards_the_panel():
    """Guardian es un extra de pago: sin él, el panel no debe abrirse."""

    source = ast.unparse(
        next(
            node for node in ast.walk(TREE)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "handle_guardian_callbacks"
        )
    )

    assert "owner_can_use_guardian" in source
    assert "build_owner_guardian_addon_required_text" in source


def test_keyboards_keep_their_callbacks_pointing_at_guardian():
    rows = gc.build_owner_guardian_panel_keyboard(7).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert callbacks, "el panel de Guardian se quedó sin botones"
    assert any(c and c.startswith("owner_guardian_") for c in callbacks)

    for callback in callbacks:
        assert callback, "botón sin callback_data"
