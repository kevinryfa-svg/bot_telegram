"""
Un import dentro de una función puede romper la función entera.

Python decide si un nombre es local mirando TODA la función: si en cualquier
línea hay un `import asyncio`, entonces `asyncio` es local desde la primera
línea, y cualquier uso anterior revienta con UnboundLocalError. No falla al
importar el módulo, no lo ve el compilador, no lo ve una lectura por encima: se
cae en producción, y solo por la rama que lo usa.

Aquí había dos, encontrados el mismo día:

  callback_router.button()   Un `import asyncio` escrito para una copia de
                             seguridad convertía en local el asyncio de toda la
                             función, y rompía el `asyncio.create_task` de 7000
                             líneas antes: el botón de «reintentar
                             verificación» de quien acaba de dar de alta su
                             comunidad.

  stripe_handler             Un `from bot_config import TOKEN` dentro del
                             procesador de pagos dejaba sin TOKEN a los tres
                             avisos anteriores del MISMO cobro.

Importar dentro de una función es legítimo —es como se rompen los ciclos de
importación en este proyecto—. Lo que no vale es que ese nombre YA esté
importado arriba.
"""

import ast
import pathlib

import pytest


def _nombres(nodo):
    for alias in nodo.names:
        yield (alias.asname or alias.name).split(".")[0]


def _sombras(ruta):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))

    arriba = set()

    for nodo in arbol.body:

        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            arriba.update(_nombres(nodo))

    encontrados = []

    for funcion in ast.walk(arbol):

        if not isinstance(funcion, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for nodo in ast.walk(funcion):

            if not isinstance(nodo, (ast.Import, ast.ImportFrom)):
                continue

            for nombre in _nombres(nodo):

                if nombre in arriba:

                    encontrados.append(
                        f"{ruta.name}:{nodo.lineno} — {funcion.name}() vuelve a "
                        f"importar «{nombre}», que ya está importado arriba"
                    )

    return encontrados


def test_no_function_shadows_a_module_level_import():
    sombras = []

    for ruta in sorted(pathlib.Path(".").glob("*.py")):
        sombras.extend(_sombras(ruta))

    assert sombras == [], (
        "Un import dentro de una función hace ese nombre local para TODA la "
        "función, y los usos anteriores revientan con UnboundLocalError:\n  "
        + "\n  ".join(sombras)
    )


# =========================
# NOMBRES QUE NO EXISTEN
# =========================
# El mismo día que los imports en la sombra apareció esto: la pantalla que fija
# el precio de publicar una comunidad leía «text» sin haberlo definido —la
# variable se asigna más abajo, dentro de OTRAS ramas del mismo manejador—. No
# es un error de sintaxis, así que arrancaba perfecto y reventaba con NameError
# solo cuando alguien escribía el precio: la pantalla que decide lo que cobra la
# plataforma por su propio producto se quedaba muda.
#
# pyflakes lo dice en un segundo. Vale la pena tenerlo puesto.

def test_no_module_uses_a_name_that_does_not_exist():
    # Instalado a propósito en CI (ver .github/workflows/ci.yml): si esta
    # prueba se omitiera allí, sería exactamente igual que no existir.
    pyflakes = pytest.importorskip("pyflakes.api")

    from pyflakes import reporter as pyflakes_reporter

    import io

    salida, errores = io.StringIO(), io.StringIO()

    reporter = pyflakes_reporter.Reporter(salida, errores)

    for ruta in sorted(pathlib.Path(".").glob("*.py")):
        pyflakes.checkPath(str(ruta), reporter=reporter)

    graves = [
        linea for linea in salida.getvalue().splitlines()
        if "undefined name" in linea
    ]

    assert graves == [], (
        "un nombre que no existe no falla al arrancar: falla en producción, y "
        "solo por la rama que lo usa:\n  " + "\n  ".join(graves)
    )
