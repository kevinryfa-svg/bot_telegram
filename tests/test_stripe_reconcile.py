"""
Reconciliación con Stripe: lo que el webhook se perdió, se encuentra aquí.

Todo el sistema de renovación cuelga de users.stripe_subscription_id. Si el
webhook del alta se pierde, el cliente PAGA y sus renovaciones no se
atribuyen a nadie: no extienden su acceso, no le avisan, y el propietario no
ve un ingreso que sí entra.

Las reglas que se prueban: se ancla lo huérfano, se suelta solo lo que
Stripe da por muerto CON el acceso ya vencido, un error de red nunca se
interpreta como "está muerta", y el repaso no concede ni quita acceso ni
mueve fechas — un repaso automático que reparte accesos es uno que un día
reparte de más.
"""

import asyncio

import pytest
import stripe

import stripe_reconcile_service as srs


class FakeBot:
    def __init__(self):
        self.mensajes = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.mensajes.append((chat_id, text))
        return True


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


def suscripcion(sub_id, user_id, group_id, purpose="group_access",
                status="active"):
    """Como las que devuelve stripe.Subscription.list en producción."""

    return stripe.Subscription.construct_from({
        "id": sub_id,
        "status": status,
        "metadata": {
            "purpose": purpose,
            "telegram_id": str(user_id),
            "group_id": str(group_id),
        },
    }, "sk_test")


class ListaFalsa:
    def __init__(self, items):
        self._items = items

    def auto_paging_iter(self):
        return iter(self._items)


@pytest.fixture
def comunidad(clean_db):
    """Grupo 96 con tres socios: sin ancla, con la buena, y con una muerta."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (96, 'VIP Repaso', -1096, TRUE)"
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active, "
            "stripe_subscription_id) VALUES "
            # Paga en Stripe y perdió el ancla: el caso que este repaso arregla.
            "(9601, 96, NOW() + INTERVAL '10 days', TRUE, NULL), "
            # Todo en orden.
            "(9602, 96, NOW() + INTERVAL '10 days', TRUE, 'sub_ok_96'), "
            # Ancla vieja de una suscripción terminada, acceso caducado.
            "(9603, 96, NOW() - INTERVAL '30 days', FALSE, 'sub_muerta_96')"
        )

    return db


def test_an_orphan_subscription_gets_its_anchor_back(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([suscripcion("sub_nueva_96", 9601, 96)])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    resumen = srs.reconcile_subscriptions()

    assert resumen["ancladas"] == 1

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT stripe_subscription_id, expiration FROM users "
                    "WHERE user_id=9601")
        ancla, expiracion = cur.fetchone()

    assert ancla == "sub_nueva_96"
    assert expiracion is not None, (
        "el repaso ancla, no reparte acceso: la fecha la mueve la siguiente "
        "factura pagada, con su periodo real"
    )


def test_owner_addon_subscriptions_are_none_of_its_business(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([
            suscripcion("sub_addon", 9601, 96, purpose="owner_addon")
        ])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    resumen = srs.reconcile_subscriptions()

    assert resumen["revisadas"] == 0
    assert resumen["ancladas"] == 0


def test_a_healthy_anchor_is_left_alone(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([suscripcion("sub_ok_96", 9602, 96)])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    resumen = srs.reconcile_subscriptions()

    assert resumen["ancladas"] == 0
    assert resumen["ancla_distinta"] == 0


def test_a_different_anchor_is_reported_not_overwritten(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([suscripcion("sub_otra_96", 9602, 96)])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    resumen = srs.reconcile_subscriptions()

    assert resumen["ancla_distinta"] == 1

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT stripe_subscription_id FROM users WHERE user_id=9602")
        assert cur.fetchone()[0] == "sub_ok_96", (
            "pisar el ancla a ciegas es cómo se pierde la suscripción que sí "
            "está cobrando"
        )


def test_paying_in_stripe_without_local_access_screams(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([suscripcion("sub_fantasma", 999999, 96)])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    resumen = srs.reconcile_subscriptions()

    assert resumen["sin_socio"] == 1
    assert resumen["ancladas"] == 0, (
        "conceder acceso desde un repaso automático es lo que no se hace"
    )

    texto = srs.build_reconcile_report(resumen)
    assert "SIN acceso local" in texto


def test_dead_anchors_are_released_only_when_stripe_confirms(comunidad, monkeypatch):
    monkeypatch.setattr(srs.stripe.Subscription, "list",
                        lambda **k: ListaFalsa([]))

    monkeypatch.setattr(
        srs.stripe.Subscription, "retrieve",
        lambda sub_id: suscripcion(sub_id, 9603, 96, status="canceled")
    )

    resumen = srs.reconcile_subscriptions()

    assert resumen["liberadas"] == 1

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT stripe_subscription_id FROM users WHERE user_id=9603")
        assert cur.fetchone()[0] is None, (
            "sin soltar el ancla, ese socio no puede volver a suscribirse"
        )


def test_a_network_error_never_means_the_subscription_is_dead(comunidad, monkeypatch):
    monkeypatch.setattr(srs.stripe.Subscription, "list",
                        lambda **k: ListaFalsa([]))

    def explota(sub_id):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(srs.stripe.Subscription, "retrieve", explota)

    resumen = srs.reconcile_subscriptions()

    assert resumen["liberadas"] == 0

    with comunidad.conn.cursor() as cur:
        cur.execute("SELECT stripe_subscription_id FROM users WHERE user_id=9603")
        assert cur.fetchone()[0] == "sub_muerta_96", (
            "un error de red borraría el ancla de alguien que sigue pagando"
        )


def test_a_live_member_is_never_questioned(comunidad):
    """A quien tiene periodo vivo no se le pregunta nada: eso es de los webhooks."""

    candidatos = [fila[0] for fila in srs.fetch_dead_anchors()]

    assert candidatos == [9603]
    assert 9602 not in candidatos


def test_silence_when_everything_is_fine(comunidad, monkeypatch):
    monkeypatch.setattr(srs.stripe.Subscription, "list",
                        lambda **k: ListaFalsa([suscripcion("sub_ok_96", 9602, 96)]))
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    contexto = FakeContext()

    resumen = asyncio.run(
        srs.process_stripe_reconciliation(contexto, admin_id=4242)
    )

    assert resumen["revisadas"] == 1
    assert not contexto.bot.mensajes, (
        "un informe que casi siempre dice 'todo bien' se deja de leer justo "
        "antes del día que importa"
    )


def test_the_report_reaches_the_admin_when_it_matters(comunidad, monkeypatch):
    monkeypatch.setattr(
        srs.stripe.Subscription, "list",
        lambda **k: ListaFalsa([suscripcion("sub_nueva_96", 9601, 96)])
    )
    monkeypatch.setattr(srs, "fetch_dead_anchors", lambda limit=None: [])

    contexto = FakeContext()

    asyncio.run(srs.process_stripe_reconciliation(contexto, admin_id=4242))

    chat, texto = contexto.bot.mensajes[0]

    assert chat == 4242
    assert "Reancladas" in texto


def test_the_kill_switch_and_the_schedule(comunidad, monkeypatch):
    monkeypatch.setattr(srs, "RECONCILE_ENABLED", False)

    assert srs.reconcile_subscriptions()["revisadas"] == 0

    source = open("main.py", encoding="utf-8").read()

    assert "schedule_stripe_reconcile_job(telegram_app)" in source

    pos = source.index("def schedule_stripe_reconcile_job")
    trozo = source[pos:pos + 700]

    assert "run_daily" in trozo


def test_the_repair_never_touches_money_or_dates():
    """La regla que hace confiable el repaso: no concede, no quita, no cobra."""

    source = open("stripe_reconcile_service.py", encoding="utf-8").read()

    assert "Subscription.modify" not in source, (
        "el repaso no toca suscripciones: solo lee"
    )
    assert "INSERT INTO payments" not in source
    assert "SET expiration" not in source
