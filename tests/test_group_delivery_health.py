"""
Una comunidad que no puede dar acceso no debe seguir vendiendo.

Para crear el enlace de acceso, Telegram exige que el bot sea administrador del
grupo con permiso de invitar. groups.bot_is_admin existía para eso, pero solo se
escribía al registrar la comunidad y nunca volvía a FALSE: una comunidad
degradada seguía en el mercado y todas sus compras cobraban sin poder entregar.

Lo delicado aquí es lo contrario del fallo: un corte de red o un dato viejo no
deben bloquear una venta legítima. Casi todas las pruebas de este fichero son de
eso.
"""

import pytest

import group_delivery_health_service as gh


# =========================
# LEER LA RESPUESTA DE TELEGRAM
# =========================

def test_the_group_creator_can_always_deliver():
    """
    El creador tiene todos los permisos y Telegram no siempre los enumera, así
    que exigir can_invite_users lo habría marcado como roto.
    """

    puede, estado, _ = gh.evaluate_membership(
        {"ok": True, "result": {"status": "creator"}}
    )

    assert puede is True
    assert estado == "creator"


def test_an_admin_with_the_invite_permission_can_deliver():
    puede, _, _ = gh.evaluate_membership(
        {"ok": True, "result": {"status": "administrator",
                                "can_invite_users": True}}
    )

    assert puede is True


def test_an_admin_without_the_invite_permission_cannot_deliver():
    """Ser administrador no basta: hace falta ese permiso concreto."""

    puede, _, detalle = gh.evaluate_membership(
        {"ok": True, "result": {"status": "administrator",
                                "can_invite_users": False}}
    )

    assert puede is False
    assert "invitar" in detalle


@pytest.mark.parametrize("estado", ["member", "left", "kicked", "restricted"])
def test_a_bot_that_is_not_an_admin_cannot_deliver(estado):
    puede, _, _ = gh.evaluate_membership(
        {"ok": True, "result": {"status": estado}}
    )

    assert puede is False


def test_a_network_failure_is_not_a_loss_of_permissions():
    """
    Lo más importante del módulo: None es "no se sabe", y no se sabe no puede
    costar una venta.
    """

    puede, _, _ = gh.evaluate_membership(None)

    assert puede is None


def test_a_refusal_from_telegram_is_information():
    """
    Si Telegram contesta y contesta que no (grupo borrado, bot expulsado), eso sí
    es un dato, no una duda.
    """

    puede, _, detalle = gh.evaluate_membership(
        {"ok": False, "description": "chat not found"}
    )

    assert puede is False
    assert "chat not found" in detalle


# =========================
# CONTRA BASE DE DATOS REAL
# =========================

@pytest.fixture
def comunidad(clean_db, monkeypatch):
    """Una comunidad de pago activa, con propietario."""

    db = clean_db
    group_id, owner_id = 61, 6101

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_free_group, bot_is_admin) "
            "VALUES (%s, 'VIP Entrega', -1061, TRUE, FALSE, TRUE)",
            (group_id,),
        )

    avisos = []

    monkeypatch.setattr(gh, "get_group_owner_user_id", lambda gid: owner_id)
    monkeypatch.setattr(
        gh, "send_telegram_message",
        lambda token, chat, text, reply_markup=None: (
            avisos.append((chat, text)), {"ok": True}
        )[1],
    )
    monkeypatch.setattr(gh, "notify_super_admins", lambda *a, **k: 0)

    return {"db": db, "group_id": group_id, "owner_id": owner_id, "avisos": avisos}


def bot_is_admin(db, group_id):
    with db.conn.cursor() as cur:
        cur.execute("SELECT bot_is_admin FROM groups WHERE id=%s", (group_id,))
        return cur.fetchone()[0]


def responder(monkeypatch, membership):
    monkeypatch.setattr(
        gh, "fetch_bot_membership", lambda token, chat, bot_id: membership
    )


ADMIN_OK = {"ok": True, "result": {"status": "administrator",
                                   "can_invite_users": True}}
SIN_PERMISO = {"ok": True, "result": {"status": "administrator",
                                      "can_invite_users": False}}


def comprobar(env):
    return gh.check_group_delivery(
        env["group_id"], "VIP Entrega", -1061, bot_user_id=999
    )


def test_one_failed_check_does_not_close_the_community(comunidad, monkeypatch):
    """
    Un solo fallo no basta. Cerrar la comunidad a la primera convertiría
    cualquier hipo de Telegram en ventas perdidas.
    """

    env = comunidad
    responder(monkeypatch, SIN_PERMISO)

    resultado = comprobar(env)

    assert resultado["can_deliver"] is not False
    assert gh.group_can_deliver_access(env["group_id"]) is True
    assert env["avisos"] == [], "no se avisa al propietario por un fallo suelto"


def test_two_failed_checks_do_close_it_and_warn_the_owner(comunidad, monkeypatch):
    env = comunidad
    responder(monkeypatch, SIN_PERMISO)

    comprobar(env)
    resultado = comprobar(env)

    assert resultado["can_deliver"] is False
    assert gh.group_can_deliver_access(env["group_id"]) is False

    al_propietario = [t for c, t in env["avisos"] if c == env["owner_id"]]

    assert al_propietario, "el propietario no se enteró de que no puede vender"
    assert "Invitar usuarios" in al_propietario[0], (
        "el aviso tiene que decir qué permiso activar, no solo que algo falla"
    )


def test_closing_it_also_updates_the_flag_the_rest_of_the_bot_reads(comunidad, monkeypatch):
    """
    bot_is_admin lo consultan otras partes del bot y se quedaba en TRUE para
    siempre.
    """

    env = comunidad
    responder(monkeypatch, SIN_PERMISO)

    assert bot_is_admin(env["db"], env["group_id"]) is True

    comprobar(env)
    comprobar(env)

    assert bot_is_admin(env["db"], env["group_id"]) is False


def test_the_owner_is_not_pestered_on_every_round(comunidad, monkeypatch):
    """
    El trabajo pasa cada seis horas. Repetir el mismo aviso cada vuelta acaba en
    que el propietario silencia al bot.
    """

    env = comunidad
    responder(monkeypatch, SIN_PERMISO)

    comprobar(env)
    comprobar(env)
    avisos_tras_romperse = len(env["avisos"])

    comprobar(env)
    comprobar(env)

    assert len(env["avisos"]) == avisos_tras_romperse


def test_it_reopens_and_says_so_when_the_permission_comes_back(comunidad, monkeypatch):
    env = comunidad

    responder(monkeypatch, SIN_PERMISO)
    comprobar(env)
    comprobar(env)
    env["avisos"].clear()

    responder(monkeypatch, ADMIN_OK)
    resultado = comprobar(env)

    assert resultado["can_deliver"] is True
    assert gh.group_can_deliver_access(env["group_id"]) is True
    assert bot_is_admin(env["db"], env["group_id"]) is True

    al_propietario = [t for c, t in env["avisos"] if c == env["owner_id"]]

    assert al_propietario, "se arregló y nadie se lo dijo"
    assert "vuelve" in al_propietario[0].lower()


def test_a_healthy_community_is_not_announced_as_recovered(comunidad, monkeypatch):
    """Solo se avisa de la recuperación si antes se avisó de la avería."""

    env = comunidad
    responder(monkeypatch, ADMIN_OK)

    comprobar(env)
    comprobar(env)

    assert env["avisos"] == []


def test_an_unreachable_telegram_changes_nothing(comunidad, monkeypatch):
    """
    Se había marcado como sana. Un corte de red no puede pasarla a rota.
    """

    env = comunidad

    responder(monkeypatch, ADMIN_OK)
    comprobar(env)

    responder(monkeypatch, None)
    resultado = comprobar(env)

    assert resultado["can_deliver"] is None
    assert gh.group_can_deliver_access(env["group_id"]) is True
    assert env["avisos"] == []


# =========================
# A QUIÉN SE REPASA
# =========================

def test_free_communities_are_left_out(clean_db):
    """
    Sin dinero de por medio no hay nada que proteger, y gastaría cuota de
    Telegram sin motivo.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (62, 'Gratis', -1062, TRUE, TRUE), "
            "       (63, 'De pago', -1063, TRUE, FALSE)"
        )

    ids = [row[0] for row in gh.fetch_groups_to_check()]

    assert 63 in ids
    assert 62 not in ids


def test_inactive_communities_are_left_out(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (64, 'Apagada', -1064, FALSE, FALSE)"
        )

    assert 64 not in [row[0] for row in gh.fetch_groups_to_check()]


def test_communities_without_a_telegram_chat_are_left_out(clean_db):
    """No se puede preguntar por un grupo que no tiene chat asociado."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (65, 'Sin chat', NULL, TRUE, FALSE)"
        )

    assert 65 not in [row[0] for row in gh.fetch_groups_to_check()]


def test_the_least_recently_checked_go_first(clean_db, monkeypatch):
    """
    Con un lote limitado, el orden decide a quién se deja sin comprobar nunca.
    """

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (66, 'A', -1066, TRUE, FALSE), (67, 'B', -1067, TRUE, FALSE)"
        )
        # 66 ya se comprobó; 67 nunca.
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver, checked_at) "
            "VALUES (66, TRUE, NOW())"
        )

    ids = [row[0] for row in gh.fetch_groups_to_check()]

    assert ids.index(67) < ids.index(66)


# =========================
# LA PREGUNTA QUE HACE EL COBRO
# =========================

def test_an_unknown_community_is_allowed_to_sell(clean_db):
    """
    Ante la falta de datos se deja vender: bloquear por no saber haría más daño
    que dejar pasar la compra, que además ya avisa al comprador si falla la
    entrega.
    """

    assert gh.group_can_deliver_access(9999) is True


def test_a_broken_database_does_not_block_every_sale(monkeypatch):
    """
    Si esto devolviera False al fallar, una base de datos con hipo cerraría la
    tienda entera.
    """

    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(gh, "conn", BrokenConn())

    assert gh.group_can_deliver_access(1) is True
    assert gh.fetch_groups_to_check() == []
    assert gh.record_health(1, False, "x", "y", 1, True, False) is False
    assert gh.set_group_bot_is_admin(1, False) is False


def test_the_five_payment_methods_all_ask_before_charging():
    """
    Cinco caminos de cobro. Si el guardián se pone en cuatro, el quinto sigue
    cobrando sin poder entregar.
    """

    source = open("callback_router.py", encoding="utf-8").read()

    for funcion in (
        "create_checkout_for_user",
        "create_paypal_group_checkout_for_user",
        "create_revolut_group_checkout_for_user",
        "create_changenow_group_checkout_for_user",
        "create_guardarian_group_checkout_for_user",
    ):
        inicio = source.index(f"async def {funcion}(")
        cuerpo = source[inicio:inicio + 4000]

        assert "group_delivery_blocks_purchase" in cuerpo, (
            f"{funcion} cobra sin comprobar que se puede entregar"
        )


def test_the_refusal_message_is_translated():
    from i18n_service import t

    es = t("purchase.cannot_deliver", "es", group="VIP Fitness")
    en = t("purchase.cannot_deliver", "en", group="VIP Fitness")

    assert "VIP Fitness" in es and "VIP Fitness" in en
    assert es != en
    assert "cobramos" in es
    assert "charging" in en


# =========================
# EL GUARDIÁN, EJECUTADO DE VERDAD
# =========================
# Las comprobaciones de arriba miran el servicio. Esto ejecuta la función que
# decide si se cobra o no, que es donde está el dinero.

import asyncio

import callback_router as cr


class FakeBot:
    """Un bot cuyo get_chat_member se puede dictar desde el test."""

    id = 999

    def __init__(self, member=None, error=None):
        self._member = member
        self._error = error
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        if self._error:
            raise self._error
        return self._member

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append((chat_id, text))


class Member:
    def __init__(self, status, can_invite_users=None):
        self.status = status
        self.can_invite_users = can_invite_users


class Context:
    def __init__(self, bot):
        self.bot = bot


def marcar_rota(group_id):
    """Deja la comunidad guardada como que no puede entregar."""

    gh.record_health(
        group_id, False, "administrator", "sin permiso para invitar",
        consecutive_failures=gh.FAILURES_BEFORE_BROKEN,
        mark_broken=True, clear_broken=False
    )


def bloquea(bot, group_id=61):
    return asyncio.run(
        cr.group_delivery_blocks_purchase(Context(bot), 5000, 5000, group_id)
    )


def test_a_healthy_community_charges_without_asking_telegram(comunidad, monkeypatch):
    """
    El camino normal no debe pagar una llamada extra a Telegram en cada compra.
    """

    env = comunidad

    bot = FakeBot(error=AssertionError("no se debía preguntar a Telegram"))

    assert bloquea(bot, env["group_id"]) is False
    assert bot.sent == []


def test_a_broken_community_does_not_take_the_money(comunidad, monkeypatch):
    env = comunidad
    marcar_rota(env["group_id"])

    bot = FakeBot(member=Member("administrator", can_invite_users=False))

    assert bloquea(bot, env["group_id"]) is True

    al_comprador = [t for c, t in bot.sent if c == 5000]

    assert al_comprador, "se rechazó la compra sin decirle nada al comprador"
    assert "no te cobramos" in al_comprador[0]


def test_a_stale_broken_flag_does_not_cost_a_legitimate_sale(comunidad, monkeypatch):
    """
    Consta rota, pero el propietario ya lo ha arreglado. Se vuelve a preguntar
    antes de rechazar, así que la venta sigue adelante.
    """

    env = comunidad
    marcar_rota(env["group_id"])

    bot = FakeBot(member=Member("administrator", can_invite_users=True))

    assert bloquea(bot, env["group_id"]) is False
    assert gh.group_can_deliver_access(env["group_id"]) is True, (
        "la reconsulta tiene que dejar el estado al día, no solo dejar pasar"
    )


def test_an_unreachable_telegram_lets_the_sale_through(comunidad, monkeypatch):
    """
    Ante la duda se vende: el comprador ya recibe aviso y botón si falla la
    entrega, así que bloquear por no saber hace más daño.
    """

    env = comunidad
    marcar_rota(env["group_id"])

    bot = FakeBot(error=RuntimeError("Telegram no contesta"))

    assert bloquea(bot, env["group_id"]) is False


def test_an_unknown_community_is_not_blocked(comunidad):
    bot = FakeBot(error=AssertionError("no se debía preguntar a Telegram"))

    assert bloquea(bot, 999999) is False
