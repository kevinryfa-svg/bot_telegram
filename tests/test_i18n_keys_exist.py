"""
Una clave de texto mal escrita se le enseña al comprador tal cual.

t() está hecho para no reventar: si la clave no existe, devuelve la clave. Eso
es lo correcto en producción —mejor un texto raro que un bot caído— y es
exactamente lo que hace el fallo invisible: nadie se entera de que a un
cliente le llegó «mysub.btn_recepits» en vez de «🧾 Mis pagos». No hay
excepción, no hay registro, no hay nada.

Esta prueba recorre el código, saca todas las llamadas t("clave") con texto
literal y exige que existan en el catálogo.

Lo que NO se puede exigir al revés: que toda clave del catálogo aparezca
literalmente en el código. Hay familias que se usan con clave calculada —las
tres etapas del aviso de cobro fallido, los motivos del cambio de plan, las
secciones de ayuda—, y una clave así no aparece nunca como literal. Exigirlo
borraría textos vivos. Para esas familias hay una comprobación aparte, hecha
a mano y con nombre, que es la única forma honesta de cubrirlas.
"""

import ast
import glob
import pathlib

import pytest

import i18n_service as i18n


RAIZ = pathlib.Path(i18n.__file__).parent


def claves_literales():
    """{clave: [fichero:línea]} de cada t("clave") con texto literal."""

    usadas = {}

    ficheros = (
        glob.glob(str(RAIZ / "*.py"))
        + glob.glob(str(RAIZ / "payment_providers" / "*.py"))
    )

    for fichero in ficheros:

        if fichero.endswith("i18n_service.py"):
            continue

        try:

            arbol = ast.parse(
                pathlib.Path(fichero).read_text(encoding="utf-8"), fichero
            )

        except Exception:

            continue

        for nodo in ast.walk(arbol):

            if not isinstance(nodo, ast.Call) or not nodo.args:
                continue

            nombre = (getattr(nodo.func, "id", None)
                      or getattr(nodo.func, "attr", None))

            if nombre != "t":
                continue

            primero = nodo.args[0]

            if isinstance(primero, ast.Constant) and isinstance(primero.value, str):

                usadas.setdefault(primero.value, []).append(
                    f"{pathlib.Path(fichero).name}:{nodo.lineno}"
                )

    return usadas


def test_every_literal_key_used_in_code_exists_in_the_catalog():
    usadas = claves_literales()

    assert len(usadas) > 100, (
        "el escáner de claves se ha roto: deberían salir más de cien"
    )

    faltan = {
        clave: sitios
        for clave, sitios in usadas.items()
        if clave not in i18n.TRANSLATIONS
    }

    detalle = "\n".join(
        f"  {clave} ← {', '.join(sitios[:3])}"
        for clave, sitios in list(faltan.items())[:15]
    )

    assert not faltan, (
        f"{len(faltan)} clave(s) de texto no existen en el catálogo y se le "
        f"enseñarían al usuario tal cual:\n{detalle}"
    )


# =========================
# LAS FAMILIAS DE CLAVE CALCULADA
# =========================
# Estas no aparecen como literal en ningún sitio: se construyen en tiempo de
# ejecución. Se listan a mano porque es la única forma de cubrirlas, y con el
# motivo delante para que quien borre una sepa qué rompe.

FAMILIAS_DINAMICAS = {
    "las tres etapas del aviso de cobro fallido (dunning_stage)": [
        "renewal.payment_failed",
        "renewal.payment_failed_retry",
        "renewal.payment_failed_last",
    ],
    "los motivos por los que no se puede cambiar de plan": [
        "mysub.switch_paypal",
        "mysub.switch_no_access",
    ],
    "los dos avisos de un referido convertido": [
        "referral.referrer_rewarded",
        "referral.invited_rewarded",
    ],
    "el aviso de devolución hecha": [
        "refund.done",
    ],
    "los títulos de los avisos de renovación por etapa": [
        "renewal.early_title",
        "renewal.soon_title",
    ],
}


@pytest.mark.parametrize("motivo,claves", list(FAMILIAS_DINAMICAS.items()))
def test_dynamic_key_families_are_complete(motivo, claves):
    for clave in claves:

        assert clave in i18n.TRANSLATIONS, (
            f"falta {clave}, que hace falta para {motivo}: se construye en "
            "tiempo de ejecución, así que su ausencia no la ve nadie hasta "
            "que le llega a un cliente"
        )

        traducciones = i18n.TRANSLATIONS[clave]

        assert traducciones.get("es") and traducciones.get("en"), (
            f"{clave} ({motivo}) tiene que estar en los dos idiomas"
        )


def test_the_dunning_stages_really_use_those_keys():
    """La lista de arriba no vale nada si el código usa otras claves."""

    fuente = (RAIZ / "group_subscription_service.py").read_text(encoding="utf-8")

    pos = fuente.index("def dunning_stage")
    trozo = fuente[pos:pos + 1500]

    for clave in FAMILIAS_DINAMICAS[
        "las tres etapas del aviso de cobro fallido (dunning_stage)"
    ]:

        assert f'"{clave}"' in trozo, (
            f"{clave} ya no se usa en dunning_stage: o el código cambió, o "
            "esta prueba está protegiendo un texto muerto"
        )
