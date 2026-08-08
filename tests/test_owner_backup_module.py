"""
Los backups del propietario viven en su propio módulo.

Tercera fase de partir callback_router.py, y la primera que no se podía hacer
como las dos anteriores. En Guardian y en los métodos de pago todas las ramas
terminaban en return, así que quien llamaba podía retornar siempre. Aquí hay una
puerta que comprueba el extra de pago y, si lo hay, CAE a propósito hacia las
ramas de abajo; y las condiciones son heterogéneas, así que tampoco valía un
guardián que fuese la unión exacta de unos prefijos.

De ahí el centinela. Estos tests fijan ese contrato, que es lo delicado: si el
centinela se rompe, o un botón deja de atenderse, o uno que antes caía hasta el
final de button() deja de llegar.
"""

import ast

import owner_backup_callbacks as obc


SOURCE = open(obc.__file__, encoding="utf-8").read()
TREE = ast.parse(SOURCE)
ROUTER = open(
    __import__("callback_router").__file__, encoding="utf-8"
).read()


def dispatch_function():
    return next(
        node for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle_owner_backup_callbacks"
    )


# =========================
# EL CENTINELA
# =========================

def test_the_sentinel_is_its_own_object():
    """
    No puede ser None ni False: los `return` del código movido devuelven None, y
    si el centinela fuese None todo parecería "no atendido" y cada botón de
    backups caería además hasta el mensaje genérico del final.
    """

    assert obc.NOT_HANDLED is not None
    assert obc.NOT_HANDLED is not False
    assert obc.NOT_HANDLED is not True
    assert obc.NOT_HANDLED != 0
    assert obc.NOT_HANDLED != ""


def test_only_the_end_of_the_dispatch_returns_the_sentinel():
    """
    Si una rama intermedia devolviese el centinela, ese botón se atendería y
    además seguiría evaluándose el resto de button(): salida duplicada.
    """

    handler = dispatch_function()

    returns_sentinel = [
        node for node in ast.walk(handler)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Name)
        and node.value.id == "NOT_HANDLED"
    ]

    assert len(returns_sentinel) == 1, (
        "el centinela debe devolverse en un único sitio, el final de la función"
    )

    last = handler.body[-1]

    assert isinstance(last, ast.Return)
    assert isinstance(last.value, ast.Name)
    assert last.value.id == "NOT_HANDLED"


def test_every_other_return_is_a_bare_return():
    """El código movido no se tocó: sus returns siguen siendo `return` a secas."""

    handler = dispatch_function()

    for node in ast.walk(handler):

        if not isinstance(node, ast.Return):
            continue

        if node is handler.body[-1]:
            continue

        assert node.value is None, (
            f"return con valor en la línea {node.lineno}: el contrato con "
            "callback_router asume que solo el final devuelve el centinela"
        )


def test_the_router_checks_the_sentinel_instead_of_returning_blindly():
    """
    Retornar siempre habría roto los owner_backup_* que no encajan con ninguna
    rama y que antes seguían hasta el resto de button().
    """

    assert "OWNER_BACKUP_NOT_HANDLED" in ROUTER
    assert "is not OWNER_BACKUP_NOT_HANDLED" in ROUTER
    assert 'if data.startswith("owner_backup_"):' in ROUTER


def test_the_router_imports_the_sentinel_from_this_module():
    """Dos centinelas distintos nunca serían iguales y todo parecería atendido."""

    import callback_router

    assert callback_router.OWNER_BACKUP_NOT_HANDLED is obc.NOT_HANDLED


# =========================
# LA PUERTA QUE CAE A PROPÓSITO
# =========================

def test_the_addon_gate_travelled_with_the_block():
    """
    La puerta resuelve la comunidad y comprueba el extra de pago antes de las
    ramas individuales. Si se hubiese quedado atrás, los botones de backups se
    abrirían sin comprobar nada.
    """

    source = ast.unparse(dispatch_function())

    assert "old_owner_backup_callbacks" in source, "se quedó atrás la puerta"
    assert "owner_can_use_backups" in source
    assert "build_owner_backup_addon_required_text" in source


def test_the_gate_still_comes_before_the_individual_branches():
    handler = dispatch_function()
    lines = {}

    for node in ast.walk(handler):

        if isinstance(node, ast.Name) and node.id == "old_owner_backup_callbacks":
            lines.setdefault("puerta", node.lineno)

        if (
            isinstance(node, ast.Compare)
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value == "owner_backup_panel"
        ):
            lines.setdefault("panel", node.lineno)

    assert "puerta" in lines and "panel" in lines
    assert lines["puerta"] < lines["panel"], (
        "la puerta del extra de pago dejó de ejecutarse antes de las ramas"
    )


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
    """
    La fase se hizo dos veces: la primera olvidó envolver
    get_selected_group_for_permissions y 23 de 30 botones morían con NameError.
    Esto lo detectaría antes de llegar a producción.
    """

    import callback_router

    for name in (
        "build_owner_backup_addon_required_keyboard",
        "build_owner_backup_addon_required_text",
        "build_owner_backup_panel_keyboard",
        "build_owner_panel_nav_keyboard",
        "extract_commercial_request_id",
        "fetch_group_basic_info",
        "format_commercial_datetime",
        "format_owner_backup_file_size",
        "format_owner_backup_frequency",
        "generate_backup_destination_token",
        "get_selected_group_for_permissions",
        "log_owner_backup_addon_gate",
        "owner_can_use_backups",
    ):
        assert hasattr(obc, name), f"falta el envoltorio {name}"
        assert hasattr(callback_router, name), (
            f"{name} ya no está en callback_router: el envoltorio fallaría"
        )


def test_no_name_in_the_module_is_left_undefined():
    """
    Comprobación general del fallo que se escapó: cualquier nombre que el módulo
    use y no defina, importe ni envuelva.
    """

    import builtins

    defined = set(dir(obc)) | set(dir(builtins))
    used, assigned = set(), set()

    for node in ast.walk(TREE):

        if isinstance(node, ast.Name):
            (used if isinstance(node.ctx, ast.Load) else assigned).add(node.id)

        if isinstance(node, ast.arg):
            assigned.add(node.arg)

        if isinstance(node, ast.ExceptHandler) and node.name:
            assigned.add(node.name)

        # Los envoltorios diferidos hacen `from callback_router import X as impl`
        # dentro de la función: eso también define un nombre.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assigned.add(alias.asname or alias.name.split(".")[0])

    missing = sorted(used - assigned - defined)

    assert not missing, f"nombres sin definir en el módulo: {missing}"


# =========================
# LO QUE SE MOVIÓ
# =========================

def test_the_backup_builders_came_along():
    for name in (
        "resolve_owner_backup_context",
        "format_backup_panel_text",
        "build_backup_panel_keyboard",
        "build_owner_backup_list_text",
        "build_owner_backup_view_text",
        "fetch_backup_owner_groups",
        "fetch_backup_recent_errors",
        "send_owner_backup_document",
    ):
        assert callable(getattr(obc, name, None)), f"falta {name}"


def test_the_router_no_longer_handles_backup_callbacks_itself():
    for callback in (
        '"owner_backup_panel"',
        '"owner_backup_activate"',
        '"owner_backup_pause"',
    ):
        assert f"data == {callback}" not in ROUTER, (
            f"callback_router sigue atendiendo {callback} por su cuenta"
        )
