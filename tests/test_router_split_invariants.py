"""
Las reglas que tiene que cumplir CUALQUIER tramo extraído de callback_router.

Se está partiendo un fichero de 51.861 líneas por fases. Cada fase anterior
descubrió una forma nueva de romperlo, y hasta ahora cada una tenía su propio
fichero de pruebas. Esto recoge las reglas que valen para todos y las aplica a
los módulos que haya, así que la siguiente fase queda cubierta sin escribir nada.

Las reglas salen de fallos que ocurrieron de verdad:

  fase 3  Un ayudante quedó sin envolver: 23 de 30 botones dieron NameError.
          -> ningún nombre sin definir, y todo envoltorio tiene que resolver.

  fase 4  Cinco constantes se envolvieron como funciones y ", ".join() sobre una
          función revienta: dos botones fallaron.
          -> ninguna constante envuelta como función.

  fase 4  El despacho no puede subir al principio de button(): encima hay puertas
          de permisos que caen a propósito hacia las ramas movidas.
          -> el despacho, después de las puertas.

  fase 5  Una constante puede ser alias de otra, y sus dependencias también
          tienen que llegar: el módulo no llegaba ni a importarse.
          -> el módulo importa de verdad.
"""

import ast
import importlib
import pathlib

import pytest


RAIZ = pathlib.Path(__file__).resolve().parent.parent

MODULOS = sorted(p.stem for p in RAIZ.glob("*_callbacks.py"))

ROUTER_SOURCE = (RAIZ / "callback_router.py").read_text(encoding="utf-8")
ROUTER_TREE = ast.parse(ROUTER_SOURCE)

# Tipo de cada nombre de módulo del router: función o constante.
TIPO_EN_ROUTER = {}
for _n in ROUTER_TREE.body:
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        TIPO_EN_ROUTER[_n.name] = "func"
    elif isinstance(_n, ast.Assign):
        for _t in _n.targets:
            if isinstance(_t, ast.Name):
                TIPO_EN_ROUTER[_t.id] = "const"


def arbol(nombre):
    return ast.parse((RAIZ / f"{nombre}.py").read_text(encoding="utf-8"))


def envoltorios(tree):
    """Los `def X(*args, **kwargs)` que reexportan algo del router."""

    out = {}

    for node in tree.body:

        if not isinstance(node, ast.FunctionDef):
            continue

        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and sub.module == "callback_router":
                for alias in sub.names:
                    out[node.name] = alias.name

    return out


def test_hay_modulos_extraidos():
    """Si esto falla, el glob no encuentra nada y todo lo demás pasa en vacío."""

    assert len(MODULOS) >= 5, f"solo se han encontrado {MODULOS}"


@pytest.mark.parametrize("nombre", MODULOS)
def test_el_modulo_importa(nombre):
    """
    La fase 5 dejó un módulo que no llegaba ni a importarse: una constante alias
    sin su dependencia. Un módulo que no importa tumba el bot entero al arrancar.
    """

    importlib.import_module(nombre)


@pytest.mark.parametrize("nombre", MODULOS)
def test_no_importa_el_router_a_nivel_de_modulo(nombre):
    """callback_router importa estos módulos: arriba sería circular."""

    for node in arbol(nombre).body:

        if isinstance(node, ast.ImportFrom):
            assert node.module != "callback_router", (
                f"{nombre} importa el router a nivel de módulo"
            )

        if isinstance(node, ast.Import):
            assert all(a.name != "callback_router" for a in node.names)


@pytest.mark.parametrize("nombre", MODULOS)
def test_ninguna_constante_esta_envuelta_como_funcion(nombre):
    """
    El fallo de la fase 4. Un envoltorio diferido devuelve una función, así que
    ", ".join(CONSTANTE) revienta y el botón falla al pulsarlo, no al importar.
    """

    malas = [
        w for w, destino in envoltorios(arbol(nombre)).items()
        if TIPO_EN_ROUTER.get(destino) == "const"
    ]

    assert not malas, (
        f"{nombre} envuelve constantes como si fuesen funciones: {malas}"
    )


@pytest.mark.parametrize("nombre", MODULOS)
def test_todos_los_envoltorios_resuelven(nombre):
    """
    Un envoltorio que apunta a un nombre que ya no existe en el router solo falla
    al pulsar el botón.
    """

    import callback_router as cr

    roto = [
        f"{w} -> {destino}"
        for w, destino in envoltorios(arbol(nombre)).items()
        if not hasattr(cr, destino)
    ]

    assert not roto, f"{nombre} tiene envoltorios que apuntan a nada: {roto}"


@pytest.mark.parametrize("nombre", MODULOS)
def test_ningun_nombre_queda_sin_definir(nombre):
    """La comprobación general del fallo de la fase 3."""

    import builtins

    modulo = importlib.import_module(nombre)
    tree = arbol(nombre)

    definidos = set(dir(modulo)) | set(dir(builtins))
    usados, asignados = set(), set()

    for node in ast.walk(tree):

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

    assert not faltan, f"{nombre} usa nombres sin definir: {faltan}"


@pytest.mark.parametrize("nombre", MODULOS)
def test_el_centinela_es_un_objeto_propio(nombre):
    """
    Si fuese None o False, una rama que atiende el botón y retorna None se
    confundiría con "esto no es mío" y el router seguiría buscando.
    """

    modulo = importlib.import_module(nombre)

    if not hasattr(modulo, "NOT_HANDLED"):
        pytest.skip(f"{nombre} no usa centinela")


    assert modulo.NOT_HANDLED is not None
    assert modulo.NOT_HANDLED is not False
    assert modulo.NOT_HANDLED is not True


@pytest.mark.parametrize("nombre", MODULOS)
def test_solo_el_final_devuelve_el_centinela(nombre):
    """
    Si una rama intermedia lo devolviera, el router buscaría otro handler para un
    botón ya atendido.
    """

    modulo = importlib.import_module(nombre)

    if not hasattr(modulo, "NOT_HANDLED"):
        pytest.skip(f"{nombre} no usa centinela")


    tree = arbol(nombre)

    handlers = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("handle_")
    ]

    assert handlers, f"{nombre} no tiene función handle_*"

    for handler in handlers:

        devoluciones = [
            n for n in ast.walk(handler)
            if isinstance(n, ast.Return)
            and isinstance(n.value, ast.Name)
            and n.value.id == "NOT_HANDLED"
        ]

        assert len(devoluciones) == 1, (
            f"{nombre}.{handler.name} devuelve el centinela en "
            f"{len(devoluciones)} sitios"
        )

        ultimo = handler.body[-1]

        assert isinstance(ultimo, ast.Return) and ultimo.value.id == "NOT_HANDLED", (
            f"en {nombre}.{handler.name} el centinela no es lo último: alguna "
            "rama quedó detrás y nunca se ejecuta"
        )


@pytest.mark.parametrize("nombre", MODULOS)
def test_el_router_comprueba_el_centinela(nombre):
    """
    Retornar siempre después de llamar al handler dejaría muertos todos los
    botones de debajo.
    """

    modulo = importlib.import_module(nombre)

    if not hasattr(modulo, "NOT_HANDLED"):
        pytest.skip(f"{nombre} no usa centinela")


    handler = next(
        n.name for n in arbol(nombre).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("handle_")
    )

    assert handler in ROUTER_SOURCE, f"el router no llama a {handler}"

    pos = ROUTER_SOURCE.index(f"{handler}(\n")
    trozo = ROUTER_SOURCE[pos:pos + 400]

    assert "is not" in trozo and "NOT_HANDLED" in trozo, (
        f"el router llama a {handler} sin comprobar el centinela"
    )


@pytest.mark.parametrize("nombre", MODULOS)
def test_el_despacho_va_detras_de_las_puertas_de_permisos(nombre):
    """
    La regla más importante, y la única cuyo incumplimiento sería un agujero de
    seguridad y no un fallo de refactor: encima de los tramos movidos hay puertas
    que comprueban super administrador y extras contratados, y que caen a
    propósito hacia las ramas de abajo.
    """

    modulo = importlib.import_module(nombre)

    if not hasattr(modulo, "NOT_HANDLED"):
        pytest.skip(f"{nombre} no usa centinela")


    handler = next(
        n.name for n in arbol(nombre).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("handle_")
    )

    despacho = ROUTER_SOURCE.index(f"{handler}(\n")

    for puerta in ("if is_admin_callback(data):",):

        if puerta not in ROUTER_SOURCE:
            continue


        # Solo se exige el orden a los tramos de administración: los del
        # propietario y los públicos no pasan por esa puerta.
        if not nombre.startswith(("admin_", "ad_promo")):
            continue


        assert despacho > ROUTER_SOURCE.index(puerta), (
            f"el despacho de {nombre} se ejecuta ANTES de {puerta.strip()}: "
            "los botones se atenderían sin comprobar permisos"
        )


# =========================
# LA TRAMPA DEL PREFIJO
# =========================
# Dos veces ha pasado que el prefijo obvio se tragaba otra cosa que solo
# comparte las primeras letras. Los dos casos, fijados:

@pytest.mark.parametrize("callback,motivo", [
    ("admin_add_group", "añadir grupo, no el panel de publicidad (admin_ad*)"),
    ("admin_payments_help", "ayuda de pagos, no la config de proveedores (admin_payment*)"),
])
def test_los_callbacks_que_solo_comparten_prefijo_siguen_en_el_router(callback, motivo):
    """
    Ninguno de estos se puede haber ido con un tramo por parecido de prefijo.
    """

    assert f'"{callback}"' in ROUTER_SOURCE, (
        f"{callback} ha salido del router: es {motivo}"
    )

    for nombre in MODULOS:

        literales = {
            n.value for n in ast.walk(arbol(nombre))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "\n" not in n.value
        }

        assert callback not in literales, (
            f"{callback} ha acabado en {nombre}: es {motivo}"
        )


def test_ningun_modulo_dejo_una_copia_de_sus_ramas_en_el_router():
    """
    Si una rama se quedara duplicada, se arreglaría en un sitio y no en el otro
    —el patrón que ya ha costado tres fallos en este repositorio.
    """

    button = next(
        n for n in ast.walk(ROUTER_TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "button"
    )

    # Callbacks que atiende cada módulo extraído.
    atendidos = {}

    for nombre in MODULOS:

        handlers = [
            n for n in arbol(nombre).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("handle_")
        ]

        for handler in handlers:
            for stmt in handler.body:
                if not isinstance(stmt, ast.If):
                    continue
                for c in ast.walk(stmt.test):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        if "_" in c.value and " " not in c.value:
                            atendidos[c.value] = nombre

    duplicados = []

    for stmt in button.body:

        if not isinstance(stmt, ast.If):
            continue

        for c in ast.walk(stmt.test):
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                if c.value in atendidos:
                    duplicados.append((c.value, atendidos[c.value], stmt.lineno))

    assert not duplicados, (
        f"el router sigue atendiendo callbacks ya movidos: {duplicados[:5]}"
    )
