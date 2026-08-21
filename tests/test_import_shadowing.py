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
