import payment_gateway_config as cfg


def test_parse_env_bool_truthy():
    assert cfg.parse_env_bool("1") is True
    assert cfg.parse_env_bool("true") is True
    assert cfg.parse_env_bool("YES") is True
    assert cfg.parse_env_bool("on") is True
    assert cfg.parse_env_bool("enabled") is True


def test_parse_env_bool_falsy():
    assert cfg.parse_env_bool("0") is False
    assert cfg.parse_env_bool("nope") is False
    assert cfg.parse_env_bool("") is False


def test_parse_env_bool_default():
    assert cfg.parse_env_bool(None) is False
    assert cfg.parse_env_bool(None, default=True) is True


def test_default_enabled_providers():
    # Defaults documentados: Stripe/ChangeNOW/Guardarian activos; resto no.
    assert cfg.PROVIDER_DEFAULT_ENABLED[cfg.PAYMENT_PROVIDER_STRIPE] is True
    assert cfg.PROVIDER_DEFAULT_ENABLED[cfg.PAYMENT_PROVIDER_CHANGENOW] is True
    assert cfg.PROVIDER_DEFAULT_ENABLED[cfg.PAYMENT_PROVIDER_GUARDARIAN] is True
    assert cfg.PROVIDER_DEFAULT_ENABLED[cfg.PAYMENT_PROVIDER_PAYPAL] is False
    assert cfg.PROVIDER_DEFAULT_ENABLED[cfg.PAYMENT_PROVIDER_REVOLUT] is False


def test_is_payment_provider_enabled_uses_default(monkeypatch):
    monkeypatch.delenv("ENABLE_PAYPAL_PAYMENTS", raising=False)
    assert cfg.is_payment_provider_enabled(cfg.PAYMENT_PROVIDER_PAYPAL) is False

    monkeypatch.delenv("ENABLE_STRIPE_PAYMENTS", raising=False)
    assert cfg.is_payment_provider_enabled(cfg.PAYMENT_PROVIDER_STRIPE) is True


def test_is_payment_provider_enabled_env_override(monkeypatch):
    monkeypatch.setenv("ENABLE_PAYPAL_PAYMENTS", "true")
    assert cfg.is_payment_provider_enabled(cfg.PAYMENT_PROVIDER_PAYPAL) is True

    monkeypatch.setenv("ENABLE_STRIPE_PAYMENTS", "false")
    assert cfg.is_payment_provider_enabled(cfg.PAYMENT_PROVIDER_STRIPE) is False


def test_is_payment_provider_enabled_unknown():
    assert cfg.is_payment_provider_enabled("nonexistent") is False


def test_get_payment_provider_config_structure():
    conf = cfg.get_payment_provider_config(cfg.PAYMENT_PROVIDER_STRIPE)
    assert conf["provider"] == "stripe"
    assert conf["flag"] == "ENABLE_STRIPE_PAYMENTS"
    assert "STRIPE_SECRET_KEY" in conf["required_env"]
    assert isinstance(conf["missing_env"], list)


def test_list_payment_provider_configs_covers_all():
    configs = cfg.list_payment_provider_configs()
    providers = {c["provider"] for c in configs}
    assert providers == {
        "stripe", "paypal", "revolut", "crypto", "changenow", "guardarian"
    }
