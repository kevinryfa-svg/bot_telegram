"""
Ninguna rama del router puede quedar muerta detrás de otra.

El fallo real de una función de miles de líneas no es que sea fea: es que una
rama repetida —o una más general escrita antes— deja muerta a la de después, y
nadie lo ve. En esta sesión pasó dos veces: dos bloques `section == "security"`
duplicados, y una rama `mysub_stoprenew_` que se comía a `mysub_stoprenew_go_`.

Esta prueba lo detecta leyendo el código: recorre las cadenas de `if`
consecutivos y avisa cuando una condición anterior QUE CORTA EL FLUJO hace
inalcanzable a una posterior.

Vive en la suite y no en un script suelto a propósito: la herramienta que
encontró esos dos fallos no puede depender de que alguien se acuerde de
ejecutarla. Aquí corre en cada PR.

La comprobación de "corta el flujo" es la que evita falsos positivos: el
router usa un patrón de dos fases —un `if` fija los permisos requeridos sin
cortar, y otro de más abajo actúa—, y sin ella esas parejas legítimas
aparecerían como ramas muertas.
"""

import ast
import pathlib

import callback_router


RAIZ = pathlib.Path(callback_router.__file__).parent


def literal(node):

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    return None


def conditions(test):
    """[(tipo, variable, valor)] de un test, aplanando los 'or'."""

    out = []

    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):

        for value in test.values:
            out.extend(conditions(value))

        return out


    if isinstance(test, ast.Compare) and len(test.ops) == 1:

        left, op, right = test.left, test.ops[0], test.comparators[0]
        var = getattr(left, "id", None) or getattr(left, "attr", None)
        val = literal(right)

        if isinstance(op, ast.Eq) and var and val is not None:
            return [("eq", var, val)]

        if isinstance(op, ast.In) and val is None:

            v = literal(left)
            rvar = getattr(right, "id", None) or getattr(right, "attr", None)

            if v is not None and rvar:
                return [("in", rvar, v)]


    if (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
            and test.func.attr == "startswith" and test.args):

        var = (getattr(test.func.value, "id", None)
               or getattr(test.func.value, "attr", None))
        arg = test.args[0]
        vals = []

        if literal(arg) is not None:
            vals = [literal(arg)]

        elif isinstance(arg, ast.Tuple):
            vals = [literal(e) for e in arg.elts if literal(e) is not None]

        if var and vals:
            return [("prefix", var, v) for v in vals]


    return out


def shadows(earlier, later):
    """¿La condición anterior hace inalcanzable a la posterior?"""

    ekind, evar, eval_ = earlier
    lkind, lvar, lval = later

    if evar != lvar:
        return None

    if ekind == "eq" and lkind == "eq" and eval_ == lval:
        return "duplicada"

    if ekind == "prefix" and lkind == "eq" and lval.startswith(eval_):
        return f"cubierta por startswith({eval_!r})"

    if (ekind == "prefix" and lkind == "prefix"
            and lval.startswith(eval_) and lval != eval_):
        return f"cubierta por startswith({eval_!r})"

    if ekind == "prefix" and ekind == lkind and eval_ == lval:
        return "duplicada"

    return None


def terminates(body):
    """¿Esta rama corta el flujo?

    Si no corta, la ejecución sigue a los if siguientes y esos NO son
    inalcanzables. Sin esto se marcaban como muertas ramas correctas.
    """

    if not body:
        return False

    for st in body:

        if isinstance(st, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            return True

    last = body[-1]

    if isinstance(last, ast.If):
        return terminates(last.body) and terminates(last.orelse)

    if isinstance(last, (ast.Try, ast.With, ast.AsyncWith)):
        return terminates(getattr(last, "body", []))

    return False


def walk_chain(stmts, path, findings):
    """Trata los if consecutivos de una secuencia como una cadena."""

    seen = []

    for st in stmts:

        if isinstance(st, ast.If):

            node = st

            while True:

                cuts = terminates(node.body)

                for c in conditions(node.test):

                    for prev_c, prev_line, prev_cuts in seen:

                        if not prev_cuts:
                            continue

                        why = shadows(prev_c, c)

                        if why:
                            findings.append(
                                (node.test.lineno, prev_line, c, why, path)
                            )

                    seen.append((c, node.test.lineno, cuts))

                walk_chain(node.body, path, findings)

                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    node = node.orelse[0]

                else:
                    walk_chain(node.orelse, path, findings)
                    break

        elif isinstance(st, (ast.For, ast.While, ast.With, ast.Try,
                             ast.AsyncWith, ast.AsyncFor)):

            for field in ("body", "orelse", "finalbody"):
                walk_chain(getattr(st, field, []) or [], path, findings)

            for h in getattr(st, "handlers", []) or []:
                walk_chain(h.body, path, findings)


def collect_unreachable():
    """[(fichero:función, línea muerta, línea que la tapa, motivo)]."""

    ficheros = [RAIZ / "callback_router.py"] + sorted(
        RAIZ.glob("*_callbacks.py")
    )

    hallazgos = []

    for path in ficheros:

        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))

        for fn in ast.walk(tree):

            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):

                findings = []
                walk_chain(fn.body, f"{path.name}:{fn.name}", findings)

                for linea, tapada_por, cond, motivo, donde in findings:

                    hallazgos.append((donde, linea, tapada_por, motivo, cond))

    return hallazgos


def test_no_router_branch_is_dead_behind_another():
    hallazgos = collect_unreachable()

    detalle = "\n".join(
        f"  {donde} línea {linea}: {cond} — {motivo} (por la línea {tapada})"
        for donde, linea, tapada, motivo, cond in hallazgos[:15]
    )

    assert not hallazgos, (
        f"{len(hallazgos)} rama(s) del router quedan inalcanzables detrás de "
        f"otra:\n{detalle}\n\n"
        "Una rama muerta es un botón que no responde y que nadie va a "
        "encontrar leyendo: la específica va SIEMPRE antes que su prefijo."
    )


def test_the_detector_still_detects():
    """La red no vale nada si el detector se ha quedado ciego.

    Se le da un router de juguete con el fallo exacto que apareció dos veces
    en la sesión: el prefijo general antes que el específico.
    """

    codigo = (
        "async def button(data):\n"
        "    if data.startswith('mysub_stoprenew_'):\n"
        "        return 1\n"
        "    if data.startswith('mysub_stoprenew_go_'):\n"
        "        return 2\n"
    )

    tree = ast.parse(codigo)
    findings = []

    for fn in ast.walk(tree):

        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_chain(fn.body, "juguete:button", findings)

    assert len(findings) == 1
    assert "cubierta por startswith" in findings[0][3]


def test_the_two_phase_permission_pattern_is_not_a_false_positive():
    """Un if que NO corta el flujo no mata a los de abajo."""

    codigo = (
        "async def button(data):\n"
        "    if data == 'admin_x':\n"
        "        permisos = ['can_view']\n"
        "    if data == 'admin_x':\n"
        "        return 2\n"
    )

    tree = ast.parse(codigo)
    findings = []

    for fn in ast.walk(tree):

        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_chain(fn.body, "juguete:button", findings)

    assert findings == [], (
        "el router fija permisos en un if que no corta y actúa más abajo: "
        "marcar eso como rama muerta haría la prueba inservible"
    )
