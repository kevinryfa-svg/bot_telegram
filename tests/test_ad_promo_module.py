"""
Cuarta fase de partir callback_router.py: el panel de publicidad.

Dos cosas concretas casi salen mal, y son las que más pruebas tienen aquí:

1. El corte por prefijo. "admin_ad" parece el prefijo natural del panel de
   publicidad, pero admin_add_group —añadir grupo, que no tiene nada que ver—
   comparte esas nueve letras. La primera versión de este corte se lo llevaba
   por delante. Por eso no hay guardián por prefijo: hay centinela.

2. La posición del despacho. Justo encima de la región hay dos puertas de
   permisos que no terminan y caen a propósito hacia estas ramas: super
   administrador y extra de publicidad contratado. Subir el despacho al principio
   de button() se saltaría las dos, que es un agujero de seguridad, no un fallo
   de refactor.

Y una regresión que encontró el golden master: la auditoría de botones del propio
bot leía solo callback_router.py, así que cada fase la dejaba más ciega.
"""

import ast
import inspect

import ad_promo_callbacks as apc


SOURCE = open(apc.__file__, encoding="utf-8").read()
TREE = ast.parse(SOURCE)
ROUTER_SOURCE = open("callback_router.py", encoding="utf-8").read()


# =========================
# EL CENTINELA
# =========================

def test_the_sentinel_is_its_own_object():
    """
    Tiene que ser un objeto propio: si fuese None o False, una rama que atiende
    el botón y retorna None se confundiría con "esto no es mío".
    """

    assert apc.NOT_HANDLED is not None
    assert apc.NOT_HANDLED is not False
    assert isinstance(apc.NOT_HANDLED, object)


def test_only_the_end_of_the_dispatch_returns_the_sentinel():
    """
    Si una rama intermedia devolviera el centinela, el router seguiría buscando
    un handler para un botón ya atendido.
    """

    handler = next(
        n for n in ast.walk(TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "handle_ad_promo_callbacks"
    )

    devuelven_centinela = [
        n.lineno for n in ast.walk(handler)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Name)
        and n.value.id == "NOT_HANDLED"
    ]

    assert len(devuelven_centinela) == 1, (
        f"el centinela se devuelve en {len(devuelven_centinela)} sitios"
    )

    ultimo = handler.body[-1]

    assert isinstance(ultimo, ast.Return), (
        "el centinela no es lo último de la función: alguna rama quedó después"
    )
    assert ultimo.value.id == "NOT_HANDLED"


def test_the_router_checks_the_sentinel_instead_of_returning_blindly():
    """
    Retornar siempre después de llamar dejaría muertos todos los botones de
    debajo.
    """

    assert "is not AD_PROMO_NOT_HANDLED" in ROUTER_SOURCE


# =========================
# EL CORTE, Y LA TRAMPA DEL PREFIJO
# =========================

def test_adding_a_group_is_not_treated_as_advertising():
    """
    admin_add_group empieza por "admin_ad" y no es publicidad. Sigue en el
    router.
    """

    assert '"admin_add_group"' in ROUTER_SOURCE, (
        "añadir grupo se ha ido con el panel de publicidad"
    )

    # Se miran los literales del código, no el texto del fichero: la explicación
    # de arriba menciona admin_add_group, y buscar la cadena a pelo daba positivo
    # por el propio comentario.
    literales = {
        n.value for n in ast.walk(TREE)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and not n.value.count("\n")
    }

    assert "admin_add_group" not in literales


def test_there_is_no_prefix_guard_that_would_swallow_it():
    """
    Un `data.startswith("admin_ad")` en el router capturaría admin_add_group y
    lo mandaría al módulo de publicidad, donde nadie lo atiende.
    """

    assert 'startswith("admin_ad")' not in ROUTER_SOURCE
    assert "AD_PROMO_CALLBACK_PREFIXES" not in ROUTER_SOURCE


def test_the_router_no_longer_handles_the_advertising_panel_itself():
    """Si se hubiese quedado una copia, se arreglaría en un sitio y no en otro."""

    # Ramas de primer nivel de button() que comparan con callbacks de publicidad.
    router_tree = ast.parse(ROUTER_SOURCE)
    button = next(
        n for n in ast.walk(router_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "button"
    )

    quedan = []

    for stmt in button.body:

        if not isinstance(stmt, ast.If):
            continue

        for c in ast.walk(stmt.test):
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                if c.value.startswith(("admin_ad_promo", "ad_promo_")):
                    quedan.append((stmt.lineno, c.value))

    assert not quedan, f"el router sigue atendiendo publicidad: {quedan[:5]}"


# =========================
# LAS DOS PUERTAS DE PERMISOS
# =========================

def test_the_dispatch_stays_behind_both_permission_gates():
    """
    Lo más importante del cambio. Las dos puertas caen a propósito hacia estas
    ramas; si el despacho se sube por encima, los botones de publicidad se
    ejecutan sin comprobar super administrador ni el extra contratado.
    """

    puerta_admin = ROUTER_SOURCE.index("if is_admin_callback(data):")
    puerta_addon = ROUTER_SOURCE.index("if is_ad_promo_ui_callback(data):")
    despacho = ROUTER_SOURCE.index("handle_ad_promo_callbacks(")

    assert despacho > puerta_admin, (
        "el despacho de publicidad se ejecuta antes de comprobar si es admin"
    )
    assert despacho > puerta_addon, (
        "el despacho de publicidad se ejecuta antes de comprobar el extra de pago"
    )


def test_the_gates_themselves_did_not_travel():
    """Son del router: las usan también otros paneles."""

    assert "is_admin_callback" not in SOURCE or "def is_admin_callback" not in SOURCE
    assert "def enforce_ad_promo_owner_addon_gate" not in SOURCE


# =========================
# QUE NADA QUEDE SIN DEFINIR
# =========================
# La fase 3 se rompió justo aquí: un ayudante quedó sin envolver y 23 de 30
# botones dieron NameError.

def test_the_module_does_not_import_the_router_at_module_level():
    """
    callback_router importa este módulo, así que importarlo arriba sería un
    import circular. Los envoltorios lo importan dentro de la función.
    """

    for node in TREE.body:

        if isinstance(node, (ast.Import, ast.ImportFrom)):

            nombres = [a.name for a in node.names]
            modulo = getattr(node, "module", None)

            assert modulo != "callback_router", (
                "import circular: se importa el router a nivel de módulo"
            )
            assert "callback_router" not in nombres


def test_no_name_in_the_module_is_left_undefined():
    """
    La comprobación general del fallo de la fase 3: cualquier nombre que el
    módulo use y no defina, importe ni envuelva.
    """

    import builtins

    definidos = set(dir(apc)) | set(dir(builtins))
    usados, asignados = set(), set()

    for node in ast.walk(TREE):

        if isinstance(node, ast.Name):
            (usados if isinstance(node.ctx, ast.Load) else asignados).add(node.id)

        if isinstance(node, ast.arg):
            asignados.add(node.arg)

        if isinstance(node, ast.ExceptHandler) and node.name:
            asignados.add(node.name)

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                asignados.add(alias.asname or alias.name.split(".")[0])

    faltan = sorted(usados - asignados - definidos)

    assert not faltan, f"nombres sin definir en el módulo: {faltan}"


def test_the_deferred_wrappers_still_resolve():
    """
    Un envoltorio que apunte a un nombre que ya no existe en el router solo
    falla al pulsar el botón, no al importar.
    """

    import callback_router as cr

    roto = []

    for node in TREE.body:

        if not isinstance(node, ast.FunctionDef):
            continue

        for sub in ast.walk(node):

            if isinstance(sub, ast.ImportFrom) and sub.module == "callback_router":

                for alias in sub.names:

                    if not hasattr(cr, alias.name):
                        roto.append(f"{node.name} -> {alias.name}")

    assert not roto, f"envoltorios que apuntan a nada: {roto}"


def test_the_constants_are_values_and_not_functions():
    """
    El fallo real de esta fase: cinco constantes se envolvieron como si fuesen
    funciones, y ", ".join() sobre una función revienta. Dos botones fallaron.
    """

    for nombre in (
        "AD_PROMO_CAMPAIGN_FIELDS",
        "AD_PROMO_CAPTION_ANGLES",
        "AD_PROMO_CREATE_STEPS",
        "AD_PROMO_MEDIA_FIELDS",
        "AD_PROMO_WATERMARK_POSITIONS",
    ):
        valor = getattr(apc, nombre)

        assert not callable(valor), f"{nombre} sigue siendo un envoltorio"
        assert len(valor) > 0

        # Y el router las usa desde aquí, no al contrario.
        import callback_router as cr

        assert getattr(cr, nombre) is valor, (
            f"{nombre} está duplicada: el router tiene su propia copia"
        )


# =========================
# LO QUE SE MOVIÓ
# =========================

def test_the_advertising_builders_came_along():
    assert callable(apc.build_ad_promo_campaigns_text)
    assert callable(apc.build_ad_promo_library_keyboard)
    assert callable(apc.fetch_ad_promo_campaign_diagnostics)
    assert callable(apc.optimize_ad_promo_rotation)


def test_the_local_prefix_tables_travelled_with_their_loops():
    """
    Dentro de la región había dos diccionarios locales y dos bucles que los
    recorren. Recomponer la región rama a rama los habría dejado atrás, y los
    bucles habrían dado NameError.
    """

    handler = next(
        n for n in ast.walk(TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "handle_ad_promo_callbacks"
    )

    asignadas = {
        t.id for n in ast.walk(handler) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }

    assert "ad_promo_toggle_prefixes" in asignadas
    assert "ad_promo_edit_prefixes" in asignadas


def test_the_router_got_smaller():
    lineas = len(ROUTER_SOURCE.splitlines())

    assert lineas < 47000, (
        f"el router tiene {lineas} líneas: la región no se ha quitado"
    )


# =========================
# LA AUDITORÍA VUELVE A VER LOS HANDLERS
# =========================

def test_the_button_audit_reads_the_extracted_modules_too():
    """
    La auditoría leía solo callback_router.py, así que cada fase del troceado la
    dejaba más ciega: empezaba a decir "callback sin handler" de botones que
    funcionan. Lo detectó el golden master, no yo.
    """

    from admin_button_audit import load_callback_router_source

    fuente = load_callback_router_source()

    # Un handler de cada módulo extraído tiene que ser visible.
    assert "handle_ad_promo_callbacks" in fuente
    assert "admin_ad_promo_campaigns" in fuente, (
        "la auditoría no ve los handlers de publicidad: los dará por inexistentes"
    )
    assert "handle_guardian_callbacks" in fuente or "guardian" in fuente


def test_the_audit_does_not_need_a_hand_written_list():
    """
    Se leen los *_callbacks.py por patrón para que la fase 5 no tenga que
    acordarse de tocar admin_button_audit.py.
    """

    fuente_audit = inspect.getsource(
        __import__("admin_button_audit").load_callback_router_source
    )

    assert "glob" in fuente_audit
    assert "_callbacks.py" in fuente_audit
