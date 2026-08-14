"""
Stripe Connect: el creador cobra en su cuenta, la plataforma su comisión.

La propiedad que más importa es INACTIVO-SEGURO: sin cuenta conectada Y
verificada, el checkout tiene que ser el de siempre, byte a byte — eso es lo
que protege a todas las comunidades que no usan Connect. Y la comisión tiene
que aplicarse a CADA cobro de una suscripción, renovaciones incluidas, que es
donde está el dinero de verdad.
"""

import pytest

import stripe_connect_service as scs


@pytest.fixture
def comunidad(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (85, 'VIP Connect', -1085, TRUE)"
        )

    return db


def conectar(db, habilitada=True):
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO creator_connect_accounts "
            "(group_id, owner_user_id, stripe_account_id, charges_enabled) "
            "VALUES (85, 777, 'acct_85', %s) "
            "ON CONFLICT (group_id) DO UPDATE SET charges_enabled=EXCLUDED.charges_enabled",
            (habilitada,),
        )


# =========================
# INACTIVO-SEGURO
# =========================

def test_without_an_account_the_checkout_is_untouched(comunidad):
    assert scs.connect_checkout_kwargs(85, True, 15, "EUR") == {}
    assert scs.connect_checkout_kwargs(85, False, 15, "EUR") == {}


def test_an_unverified_account_does_not_touch_the_checkout(comunidad):
    """Hasta que Stripe no pone charges_enabled, nada cambia: mandar un
    destination a una cuenta sin verificar rompería el cobro."""

    conectar(comunidad, habilitada=False)

    assert scs.connect_checkout_kwargs(85, True, 15, "EUR") == {}


# =========================
# LA COMISIÓN
# =========================

def test_subscriptions_carry_a_percent_fee_on_every_cycle(comunidad):
    conectar(comunidad)

    extra = scs.connect_checkout_kwargs(85, True, 15, "EUR")

    assert extra == {
        "subscription_data": {
            "application_fee_percent": 10.0,
            "transfer_data": {"destination": "acct_85"},
        }
    }, (
        "porcentual y en subscription_data: se aplica sola a CADA cobro, "
        "renovaciones incluidas"
    )


def test_one_time_payments_carry_the_fee_in_cents(comunidad):
    conectar(comunidad)

    extra = scs.connect_checkout_kwargs(85, False, 15, "EUR")

    assert extra["payment_intent_data"]["transfer_data"] == {
        "destination": "acct_85"
    }
    assert extra["payment_intent_data"]["application_fee_amount"] == 150, (
        "el 10% de 15 EUR son 150 CÉNTIMOS: la comisión vive en unidades "
        "menores, como todo el dinero de Stripe"
    )


def test_the_fee_is_tunable_by_env(comunidad, monkeypatch):
    conectar(comunidad)
    monkeypatch.setenv("STRIPE_CONNECT_FEE_PERCENT", "7.5")

    extra = scs.connect_checkout_kwargs(85, True, 15, "EUR")

    assert extra["subscription_data"]["application_fee_percent"] == 7.5


# =========================
# EL ALTA
# =========================

def test_onboarding_creates_an_express_account_and_a_link(comunidad, monkeypatch):
    import stripe

    creadas = {"accounts": [], "links": []}

    monkeypatch.setattr(
        scs.stripe.Account, "create",
        lambda **k: creadas["accounts"].append(k) or
        stripe.Account.construct_from({"id": "acct_new"}, "sk")
    )
    monkeypatch.setattr(
        scs.stripe.AccountLink, "create",
        lambda **k: creadas["links"].append(k) or
        stripe.AccountLink.construct_from(
            {"url": "https://connect.stripe.com/setup/x"}, "sk")
    )

    r = scs.start_connect_onboarding(85, 777)

    assert r["ok"] is True
    assert r["url"].startswith("https://connect.stripe.com/")

    assert creadas["accounts"][0]["type"] == "express"
    assert creadas["links"][0]["account"] == "acct_new"
    assert creadas["links"][0]["type"] == "account_onboarding"

    guardada = scs.fetch_connect_account(85)
    assert guardada["stripe_account_id"] == "acct_new"
    assert guardada["charges_enabled"] is False, (
        "recién creada NO puede cobrar: charges_enabled lo decide Stripe"
    )


def test_restarting_onboarding_reuses_the_same_account(comunidad, monkeypatch):
    import stripe

    conectar(comunidad, habilitada=False)

    cuentas_creadas = []
    monkeypatch.setattr(scs.stripe.Account, "create",
                        lambda **k: cuentas_creadas.append(k))
    monkeypatch.setattr(
        scs.stripe.AccountLink, "create",
        lambda **k: stripe.AccountLink.construct_from(
            {"url": "https://connect.stripe.com/setup/y"}, "sk")
    )

    r = scs.start_connect_onboarding(85, 777)

    assert r["ok"] is True
    assert not cuentas_creadas, (
        "reintentar el alta no puede crear una segunda cuenta"
    )


def test_platform_without_connect_degrades_with_a_message(comunidad, monkeypatch):
    def sin_connect(**k):
        raise RuntimeError("You can only create new accounts if you've signed up for Connect")

    monkeypatch.setattr(scs.stripe.Account, "create", sin_connect)

    r = scs.start_connect_onboarding(85, 777)

    assert r["ok"] is False
    assert r["error"] == "connect_no_disponible"
    assert scs.fetch_connect_account(85) is None, "nada a medias en la base"


def test_checking_status_trusts_stripe(comunidad, monkeypatch):
    import stripe

    conectar(comunidad, habilitada=False)

    monkeypatch.setattr(
        scs.stripe.Account, "retrieve",
        lambda aid: stripe.Account.construct_from(
            {"id": aid, "charges_enabled": True}, "sk")
    )

    cuenta = scs.refresh_connect_status(85)

    assert cuenta["charges_enabled"] is True
    assert scs.fetch_connect_account(85)["charges_enabled"] is True


# =========================
# EL CABLEADO
# =========================

def test_the_checkout_merges_connect_without_losing_the_subscription_data():
    source = open("checkout_routes.py", encoding="utf-8").read()

    pos = source.index("connect_checkout_kwargs(")
    trozo = source[pos:pos + 700]

    assert '"subscription_data" in extra_connect' in trozo
    assert 'session_kwargs["subscription_data"].update(' in trozo, (
        "un update plano pisaría la metadata y el trial de la suscripción"
    )

    # Y ocurre ANTES de crear la sesión.
    assert source.index("connect_checkout_kwargs(") < source.index(
        "session = stripe.checkout.Session.create(**session_kwargs)"
    )


def test_the_owner_screen_is_gated_to_the_owner():
    source = open("owner_panel_callbacks.py", encoding="utf-8").read()

    pos = source.index('"owner_stripe_connect"')
    trozo = source[pos:pos + 900]

    assert "is_super_admin(user_id) or get_group_owner_user_id" in trozo, (
        "conectar una cuenta bancaria es cosa del propietario y de nadie más"
    )
