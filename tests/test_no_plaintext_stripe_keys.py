"""
Nadie debe volver a guardar claves de Stripe de terceros sin cifrar.

El alta de creadores pedía la STRIPE_SECRET_KEY del creador y la escribía en
claro en group_payment_settings, para después no usarla en ningún cobro: el
propio mensaje final admitía que el checkout quedaba "pendiente de conectar".
Era código inalcanzable, pero bastaba una llamada para activarlo.

Estos tests fijan la decisión: mientras no exista el cobro con la cuenta del
creador, no se piden sus credenciales.
"""

import re

import callback_router as cr
import commercial_form_handler as cfh
import migrations_service as ms


CREATOR_SETUP_SOURCE = open(cfh.__file__, encoding="utf-8").read()


def test_the_creator_setup_no_longer_asks_for_a_stripe_secret_key():
    assert "creator_setup_waiting_stripe_secret" not in CREATOR_SETUP_SOURCE
    assert "creator_setup_waiting_webhook_secret" not in CREATOR_SETUP_SOURCE


def test_the_creator_setup_no_longer_writes_the_secret_columns():
    for column in ("owner_stripe_secret_key", "owner_stripe_webhook_secret"):
        assert column not in CREATOR_SETUP_SOURCE, (
            f"{column} vuelve a escribirse en el alta de creadores"
        )


def test_no_wizard_can_route_to_a_stripe_credential_step():
    """
    La entrada "stripe" en el mapa de estados era la trampa: reactivaba la
    recogida de credenciales con una sola llamada.
    """

    source = open(cr.__file__, encoding="utf-8").read()

    match = re.search(
        r"def start_creator_setup_state.*?\n    context\.user_data\[\"creator_setup\"\]",
        source,
        re.DOTALL,
    )

    assert match, "no se encontró start_creator_setup_state"

    # Se miran solo las líneas de código: el comentario que explica por qué no
    # existe la entrada menciona "stripe" a propósito.
    code = "\n".join(
        line
        for line in match.group(0).splitlines()
        if not line.strip().startswith("#")
    )

    assert '"stripe":' not in code


def test_nothing_reads_the_plaintext_secret_columns():
    """Se seleccionaban para descartarlas: leerlas no aportaba nada."""

    source = open(cr.__file__, encoding="utf-8").read()

    match = re.search(
        r"def get_group_payment_settings.*?return cur\.fetchone\(\)",
        source,
        re.DOTALL,
    )

    assert match, "no se encontró get_group_payment_settings"
    assert "owner_stripe_secret_key" not in match.group(0)
    assert "owner_stripe_webhook_secret" not in match.group(0)


def test_a_migration_clears_any_key_stored_by_older_versions():
    statements = [
        statement
        for _, name, statements in ms.MIGRATIONS
        if "stripe" in name
        for statement in statements
    ]

    assert statements, "falta la migración que limpia las claves"

    joined = " ".join(statements)

    assert "owner_stripe_secret_key = NULL" in joined
    assert "owner_stripe_webhook_secret = NULL" in joined


def test_the_migration_actually_clears_a_stored_key(db_module):
    """Contra base de datos real: una clave guardada debe quedar en NULL."""

    with db_module.conn.cursor() as cur:
        cur.execute("DELETE FROM group_payment_settings WHERE commercial_request_id=9999")
        cur.execute(
            """
            INSERT INTO group_payment_settings
            (group_id, commercial_request_id, owner_user_id, stripe_mode,
             owner_stripe_secret_key, owner_stripe_webhook_secret, is_configured)
            VALUES (1, 9999, 1, 'owner_stripe',
                    'sk_live_NoDeberiaEstarAqui', 'whsec_NoDeberiaEstarAqui', TRUE)
            """
        )

    stripe_migration = next(
        migration for migration in ms.MIGRATIONS if "stripe" in migration[1]
    )

    ok, _ = ms.apply_migration(
        90000 + stripe_migration[0],
        f"{stripe_migration[1]}_reejecutada_en_test",
        stripe_migration[2],
    )

    assert ok

    with db_module.conn.cursor() as cur:
        cur.execute(
            "SELECT owner_stripe_secret_key, owner_stripe_webhook_secret, "
            "is_configured FROM group_payment_settings "
            "WHERE commercial_request_id=9999"
        )
        secret, webhook, configured = cur.fetchone()

    assert secret is None and webhook is None
    # La fila y su estado se conservan: solo desaparecen las credenciales.
    assert configured is True


def test_the_only_stripe_key_in_use_is_the_platform_one():
    """
    Si algún día se conecta el cobro del creador, será por Stripe Connect y no
    guardando su clave secreta. Hasta entonces, una sola clave en juego.
    """

    import glob

    assignments = []

    for path in glob.glob("*.py") + glob.glob("payment_providers/*.py"):
        for number, line in enumerate(open(path, encoding="utf-8"), start=1):
            if re.search(r"^\s*stripe\.api_key\s*=", line):
                assignments.append(f"{path}:{number}")

    assert len(assignments) == 1, (
        f"stripe.api_key se asigna en varios sitios: {assignments}"
    )
