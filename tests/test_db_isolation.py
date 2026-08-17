"""
Un test que escribe en una tabla que nadie limpia contamina a los demás.

Este fallo me ha mordido dos veces en una sola sesión, y las dos veces de la
peor manera posible: no rompiendo la suite, sino haciéndola MENTIR.

  - Al añadir los cupones de Stripe, la tabla nueva no estaba en la lista de
    limpieza: las filas de un test se sumaban a las del siguiente y una
    prueba de "no se crean cupones duplicados" pasaba con duplicados dentro.
  - Al añadir los descuentos de recuperación, el resto de un test dejaba a
    otro con "saltados == 0" cuando el número correcto era otro.

Un test contaminado que pasa es peor que un test que falla: da permiso para
desplegar.

La regla que se comprueba aquí: toda tabla en la que los tests escriben tiene
que estar en la lista de limpieza de conftest, o en la lista de excepciones de
abajo con su motivo escrito. Nada de "se me olvidó".

No se exige limpiar TODAS las tablas del esquema (hay decenas que ningún test
toca): se exige limpiar las que se usan, que es donde está el daño.
"""

import glob
import pathlib
import re

import pytest


RAIZ_TESTS = pathlib.Path(__file__).parent


# Tablas en las que se escribe y que NO hacen falta en la limpieza global,
# porque el propio test se encarga. El motivo va escrito: sin él, esta lista
# se convierte en el sitio donde se esconden los olvidos.
LIMPIEZA_PROPIA = {
    "bot_persistence": (
        "test_persistence.py tiene su fixture empty_persistence, que vacía "
        "la tabla antes de cada prueba"
    ),
    "group_payment_settings": (
        "test_no_plaintext_stripe_keys.py borra su propia fila por "
        "commercial_request_id antes de insertarla"
    ),
}


def tablas_de_limpieza():
    """Las tablas que conftest vacía antes de cada test."""

    fuente = (RAIZ_TESTS / "conftest.py").read_text(encoding="utf-8")

    inicio = fuente.index("tables = (")
    fin = fuente.index(")", inicio)

    return set(re.findall(r'"(\w+)"', fuente[inicio:fin]))


def tablas_escritas_por_los_tests():
    """{tabla: {ficheros}} de cada INSERT INTO de la carpeta de tests."""

    escritas = {}

    for fichero in sorted(glob.glob(str(RAIZ_TESTS / "*.py"))):

        nombre = pathlib.Path(fichero).name

        if nombre == pathlib.Path(__file__).name:
            continue

        texto = pathlib.Path(fichero).read_text(encoding="utf-8")

        for tabla in re.findall(r"INSERT INTO\s+(\w+)", texto, re.IGNORECASE):

            escritas.setdefault(tabla.lower(), set()).add(nombre)

    return escritas


def test_every_table_tests_write_to_is_cleaned_between_tests():
    limpias = tablas_de_limpieza()
    escritas = tablas_escritas_por_los_tests()

    assert len(escritas) > 10, (
        "el escáner de INSERT se ha roto: los tests escriben en más tablas"
    )

    huerfanas = {
        tabla: sorted(ficheros)
        for tabla, ficheros in escritas.items()
        if tabla not in limpias and tabla not in LIMPIEZA_PROPIA
    }

    detalle = "\n".join(
        f"  {tabla} ← {', '.join(ficheros[:3])}"
        for tabla, ficheros in huerfanas.items()
    )

    assert not huerfanas, (
        f"{len(huerfanas)} tabla(s) reciben INSERT en los tests y nadie las "
        f"vacía entre pruebas:\n{detalle}\n\n"
        "Añádelas a la lista de conftest, o a LIMPIEZA_PROPIA con el motivo. "
        "Un test contaminado que pasa da permiso para desplegar."
    )


def test_the_exceptions_are_still_real():
    """Una excepción que ya no se usa es una excepción que tapa el siguiente olvido."""

    escritas = tablas_escritas_por_los_tests()
    limpias = tablas_de_limpieza()

    sobrantes = [
        tabla for tabla in LIMPIEZA_PROPIA
        if tabla not in escritas and tabla not in limpias
    ]

    assert not sobrantes, (
        f"estas excepciones ya no corresponden a ningún INSERT de los tests: "
        f"{sobrantes}. Quítalas: la lista solo vale si está viva."
    )


def test_the_cleaning_list_covers_the_tables_this_session_added():
    """Las tablas nuevas de esta sesión, una por una.

    Se listan a mano y no por patrón porque el olvido concreto que hay que
    impedir es "he añadido una tabla y no he tocado conftest".
    """

    limpias = tablas_de_limpieza()

    nuevas = [
        "group_payment_provider_configs",
        "group_stripe_coupons",
        "creator_connect_accounts",
        "retention_offers",
        "owner_weekly_digests",
        "business_alerts",
        "dunning_notices",
        "member_return_offers",
        "delivery_recovery_notices",
        "refund_requests",
        "referrals",
        "upsell_offers",
    ]

    faltan = [tabla for tabla in nuevas if tabla not in limpias]

    assert not faltan, f"tablas sin limpieza entre tests: {faltan}"


def test_whoever_counts_audit_events_must_clear_their_own_first():
    """El registro de auditoría no se vacía entre pruebas, a propósito.

    audit_logs no recibe INSERT directo en los tests: se escribe llamando a
    log_event, así que el escáner de arriba no lo ve. Pero la contaminación es
    la misma, y ya me pasó: una prueba contaba eventos y le sumaba los que
    había dejado otra.

    La regla, comprobable: quien CUENTE eventos de auditoría tiene que borrar
    los suyos antes. Contar sin borrar es contar lo de los demás.
    """

    culpables = []

    for fichero in sorted(glob.glob(str(RAIZ_TESTS / "*.py"))):

        nombre = pathlib.Path(fichero).name

        if nombre == pathlib.Path(__file__).name:
            continue

        texto = pathlib.Path(fichero).read_text(encoding="utf-8")

        cuenta = re.search(
            r"COUNT\(\*\)\s*FROM\s+audit_logs", texto, re.IGNORECASE
        )

        if not cuenta:
            continue

        borra = re.search(r"DELETE\s+FROM\s+audit_logs", texto, re.IGNORECASE)

        if not borra:
            culpables.append(nombre)

    assert not culpables, (
        f"{culpables} cuentan eventos de auditoría sin borrar antes los "
        "suyos: acabarán contando los que deje otra prueba, y el día que eso "
        "pase la prueba pasará estando mal"
    )


@pytest.mark.parametrize("tabla,motivo", sorted(LIMPIEZA_PROPIA.items()))
def test_each_exception_has_a_written_reason(tabla, motivo):
    assert len(motivo) > 30, (
        f"{tabla} necesita un motivo de verdad, no una nota: quien lea esta "
        "lista dentro de un año tiene que poder decidir si sigue valiendo"
    )
