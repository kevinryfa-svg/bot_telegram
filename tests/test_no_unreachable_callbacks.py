"""
Ninguna rama del router debe quedar muerta detrás de otra.

El problema real de una función de despacho de 24.000 líneas no es que sea
larga: es que es una cadena lineal de `if`, y una condición repetida o más
general escrita antes deja inalcanzable a la de después sin que nadie lo note.
Esta sesión apareció exactamente eso — dos bloques `section == "security"`
duplicados dejaban Guardian invisible — y se arregló a mano.

Esta comprobación lo convierte en un fallo de CI en vez de en un hallazgo por
casualidad. Mientras el router siga siendo un archivo enorme, es la red que
cubre su modo de fallo característico.
"""

import ast

import pytest


ROUTER_FILES = (
    "callback_router.py",
    "admin_input_handler.py",
    "code_flow_handler.py",
    "commercial_form_handler.py",
    "help_handler.py",
    "support_handler.py",
    "account_handler.py",
)


def string_literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    return None


def conditions(test):
    """
    Condiciones comparables de un test, aplanando los `or`.

    Solo se entienden las formas que usa el router para despachar:
    `data == "x"`, `data.startswith("x")` y `data.startswith(("x", "y"))`.
    """

    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        found = []

        for value in test.values:
            found.extend(conditions(value))

        return found


    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        variable = (
            getattr(test.left, "id", None)
            or getattr(test.left, "attr", None)
        )
        value = string_literal(test.comparators[0])

        if isinstance(test.ops[0], ast.Eq) and variable and value is not None:
            return [("eq", variable, value)]


    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Attribute)
        and test.func.attr == "startswith"
        and test.args
    ):
        variable = (
            getattr(test.func.value, "id", None)
            or getattr(test.func.value, "attr", None)
        )

        argument = test.args[0]
        values = []

        if string_literal(argument) is not None:
            values = [string_literal(argument)]

        elif isinstance(argument, ast.Tuple):
            values = [
                string_literal(element)
                for element in argument.elts
                if string_literal(element) is not None
            ]

        if variable and values:
            return [("prefix", variable, value) for value in values]


    return []


def shadows(earlier, later):
    """¿La condición anterior deja inalcanzable a la posterior?"""

    earlier_kind, earlier_variable, earlier_value = earlier
    later_kind, later_variable, later_value = later

    if earlier_variable != later_variable:
        return None


    if earlier_kind == "eq" and later_kind == "eq" and earlier_value == later_value:
        return "condición duplicada"


    if earlier_kind == "prefix" and later_kind == "eq":
        if later_value.startswith(earlier_value):
            return f"ya la cubre startswith({earlier_value!r})"


    if earlier_kind == "prefix" and later_kind == "prefix":
        if later_value.startswith(earlier_value):
            return f"ya la cubre startswith({earlier_value!r})"


    return None


def terminates(body):
    """
    ¿Esta rama corta el flujo?

    Es la comprobación que evita el falso positivo importante: el router usa un
    patrón de dos fases — un `if` fija los permisos requeridos sin cortar, y
    otro `if` más abajo, con la misma condición, actúa. Sin esto, esas parejas
    correctas se marcaban como código muerto.
    """

    if not body:
        return False


    for statement in body:
        if isinstance(statement, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            return True


    last = body[-1]

    if isinstance(last, ast.If):
        return terminates(last.body) and terminates(last.orelse)


    if isinstance(last, (ast.Try, ast.With, ast.AsyncWith)):
        return terminates(getattr(last, "body", []))


    return False


def walk(statements, where, findings):
    """Recorre una secuencia tratando los `if` consecutivos como una cadena."""

    seen = []

    for statement in statements:

        if isinstance(statement, ast.If):
            node = statement

            while True:
                cuts = terminates(node.body)

                for condition in conditions(node.test):

                    for previous, previous_line, previous_cuts in seen:

                        # Si la anterior no corta, la ejecución llega igual a
                        # esta: no está muerta.
                        if not previous_cuts:
                            continue

                        why = shadows(previous, condition)

                        if why:
                            findings.append(
                                f"{where} línea {node.test.lineno}: "
                                f"{condition[1]} {condition[0]} {condition[2]!r} "
                                f"— {why} (línea {previous_line})"
                            )

                    seen.append((condition, node.test.lineno, cuts))


                walk(node.body, where, findings)

                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    node = node.orelse[0]

                else:
                    walk(node.orelse, where, findings)
                    break


        elif isinstance(
            statement,
            (ast.For, ast.While, ast.With, ast.Try, ast.AsyncWith, ast.AsyncFor)
        ):
            for field in ("body", "orelse", "finalbody"):
                walk(getattr(statement, field, []) or [], where, findings)

            for handler in getattr(statement, "handlers", []) or []:
                walk(handler.body, where, findings)


def unreachable_branches(path):

    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    findings = []

    for node in ast.walk(tree):

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk(node.body, f"{path}:{node.name}", findings)


    return findings


@pytest.mark.parametrize("path", ROUTER_FILES)
def test_no_callback_branch_is_unreachable(path):
    findings = unreachable_branches(path)

    assert not findings, (
        "Hay ramas de callback que nunca se ejecutan porque otra condición "
        "anterior ya las captura:\n  " + "\n  ".join(findings)
    )


# =========================
# EL DETECTOR, PROBADO
# =========================
# Una comprobación así solo vale si se sabe que detecta y que no exagera. Los
# dos casos vienen de código real de este repositorio.

def analyse_source(source, tmp_path):
    path = tmp_path / "muestra.py"
    path.write_text(source, encoding="utf-8")

    return unreachable_branches(str(path))


def test_it_catches_a_duplicated_branch(tmp_path):
    """La forma del fallo real: dos bloques iguales, el segundo muerto."""

    findings = analyse_source(
        "async def button(data):\n"
        "    if data == 'security':\n"
        "        return 1\n"
        "    if data == 'security':\n"
        "        return 2\n",
        tmp_path,
    )

    assert len(findings) == 1
    assert "duplicada" in findings[0]


def test_it_catches_a_prefix_swallowing_a_later_branch(tmp_path):
    findings = analyse_source(
        "async def button(data):\n"
        "    if data.startswith('admin_'):\n"
        "        return 1\n"
        "    if data == 'admin_backup':\n"
        "        return 2\n",
        tmp_path,
    )

    assert len(findings) == 1
    assert "startswith" in findings[0]


def test_it_does_not_flag_the_two_phase_permission_pattern(tmp_path):
    """
    El patrón correcto del router: el primer if solo fija permisos y no corta,
    así que el segundo sí se ejecuta. Marcarlo sería un falso positivo, y es el
    que tuvo esta comprobación en su primera versión.
    """

    findings = analyse_source(
        "async def button(data):\n"
        "    permissions = []\n"
        "    if data == 'edit_group_admins':\n"
        "        permissions = ['can_manage_admins']\n"
        "    group_id = resolve(permissions)\n"
        "    if data == 'edit_group_admins':\n"
        "        return group_id\n",
        tmp_path,
    )

    assert findings == []


def test_it_does_not_flag_different_variables(tmp_path):
    findings = analyse_source(
        "async def button(data, section):\n"
        "    if data == 'x':\n"
        "        return 1\n"
        "    if section == 'x':\n"
        "        return 2\n",
        tmp_path,
    )

    assert findings == []


def test_it_does_not_flag_branches_in_separate_functions(tmp_path):
    findings = analyse_source(
        "def one(data):\n"
        "    if data == 'x':\n"
        "        return 1\n"
        "def two(data):\n"
        "    if data == 'x':\n"
        "        return 2\n",
        tmp_path,
    )

    assert findings == []
