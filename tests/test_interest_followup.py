"""
Seguimiento a quien miró una comunidad y no compró.

El bot escribía a quien nunca ha comprado nada y a quien empezó un pago sin
terminarlo. Entre esos dos casos quedaba el hueco más grande del embudo: quien
abre la ficha de una comunidad concreta, ve el precio y se va. Es la persona con
más intención de todas las que no han pagado.

Lo delicado aquí no es enviar, es NO enviar: un aviso comercial mal filtrado se
convierte en spam y se paga con bloqueos.
"""

import asyncio

import interest_followup_service as ifs


# =========================
# CONFIGURACIÓN SENSATA
# =========================

def test_it_waits_before_writing():
    """Escribir al minuto interrumpe a quien está decidiéndose."""

    assert ifs.INTEREST_AFTER_HOURS >= 1


def test_it_gives_up_after_a_while():
    """Escribir por algo que miró hace un mes es ruido."""

    assert 1 <= ifs.INTEREST_MAX_AGE_DAYS <= 30


def test_it_sends_in_small_batches():
    assert 1 <= ifs.INTEREST_BATCH_SIZE <= 200
    assert ifs.INTEREST_SEND_DELAY_SECONDS >= 0


# =========================
# EL MENSAJE
# =========================

def test_the_message_names_the_community_and_the_price():
    text = ifs.build_interest_text("VIP Fitness", price=(15, "EUR"))

    assert "VIP Fitness" in text
    assert "15 EUR" in text


def test_the_message_works_without_a_price():
    text = ifs.build_interest_text("VIP Fitness", price=None)

    assert "VIP Fitness" in text
    assert "None" not in text


def test_the_message_always_offers_a_way_out():
    """Un aviso comercial sin salida clara es spam."""

    text = ifs.build_interest_text("X", price=(9, "EUR"))

    assert "no te escribo más" in text.lower()


def test_the_message_is_translated():
    text = ifs.build_interest_text("VIP Fitness", price=(15, "EUR"), language="en")

    assert "Still thinking" in text
    assert "VIP Fitness" in text
    assert "no te escribo" not in text.lower()


def test_the_message_fits_in_one_telegram_message():
    assert len(ifs.build_interest_text("X" * 200, price=(15, "EUR"))) < 4096


# =========================
# LOS BOTONES
# =========================

def test_the_buttons_lead_to_the_community_support_and_the_opt_out():
    rows = ifs.build_interest_keyboard(7).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert "marketplace_group_7" in callbacks
    assert "public_support" in callbacks
    assert "reengagement_stop" in callbacks


def test_the_opt_out_button_uses_the_handler_that_already_exists():
    """
    Se reutiliza el opt-out del reenganche a propósito: "no me escribas más"
    debe valer para todos los avisos, no solo para el que se estaba leyendo.
    Y tiene que existir un handler, o el botón sería una promesa falsa.
    """

    import reengagement_service as rs

    rows = ifs.build_interest_keyboard(1).inline_keyboard
    callbacks = [b.callback_data for row in rows for b in row]

    assert rs.CALLBACK_REENGAGEMENT_STOP in callbacks

    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert "if data == CALLBACK_REENGAGEMENT_STOP:" in router, (
        "el botón de opt-out no tiene quien lo atienda"
    )


def test_no_button_is_dead():
    rows = ifs.build_interest_keyboard(1).inline_keyboard

    for row in rows:
        for button in row:
            assert button.text
            assert button.callback_data


def test_the_buttons_are_translated_but_keep_their_callbacks():
    rows = ifs.build_interest_keyboard(7, language="en").inline_keyboard

    labels = [b.text for row in rows for b in row]
    callbacks = [b.callback_data for row in rows for b in row]

    assert any("See the access" in label for label in labels)
    assert "marketplace_group_7" in callbacks


# =========================
# A QUIÉN SE ESCRIBE, Y SOBRE TODO A QUIÉN NO
# =========================

def seed(db_module, *, user_id, hours_ago=12, access=False, paid=False,
         transaction=False, banned=False, opted_out=False, already=False):

    with db_module.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO bot_user_events "
            "(user_id, event_type, event_key, group_id, created_at) "
            "VALUES (%s,'community_viewed','marketplace_group_777',777, "
            "NOW() - (%s || ' hours')::INTERVAL)",
            (user_id, str(hours_ago)),
        )

        if access:
            cur.execute(
                "INSERT INTO users (user_id, group_id, expiration, "
                "subscription_active) VALUES (%s,777,NOW()+INTERVAL '30 days',TRUE)",
                (user_id,),
            )

        if paid:
            cur.execute(
                "INSERT INTO payments (user_id, group_id, amount, currency, status) "
                "VALUES (%s,777,1500,'EUR','paid')",
                (user_id,),
            )

        if transaction:
            cur.execute(
                "INSERT INTO payment_transactions (user_id, group_id, provider, status) "
                "VALUES (%s,777,'stripe','pending')",
                (user_id,),
            )

        if banned:
            cur.execute(
                "INSERT INTO banned_users (user_id, group_id) VALUES (%s,777)",
                (user_id,),
            )

        if opted_out:
            cur.execute(
                "INSERT INTO user_reengagement (user_id, opted_out) VALUES (%s,TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET opted_out=TRUE",
                (user_id,),
            )

        if already:
            cur.execute(
                "INSERT INTO interest_followups (user_id, group_id) VALUES (%s,777)",
                (user_id,),
            )


def paying_community(db_module):
    with db_module.conn.cursor() as cur:
        cur.execute("DELETE FROM bot_user_events WHERE group_id=777")
        cur.execute("DELETE FROM interest_followups WHERE group_id=777")
        cur.execute("DELETE FROM plans WHERE group_id=777")
        cur.execute("DELETE FROM groups WHERE id=777")
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, "
            "is_free, is_free_group) VALUES (777,'VIP Fitness',-1777,TRUE,FALSE,FALSE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, price_id, duration_days, amount, "
            "currency, is_active) VALUES (777,'Mensual','p777',30,15,'EUR',TRUE)"
        )

    return db_module


def chosen(user_ids):
    return {
        row[0]
        for row in ifs.fetch_interested_users(limit=200)
        if row[0] in user_ids
    }


def test_someone_who_looked_and_did_nothing_is_written_to(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770001)

    assert 770001 in chosen({770001})


def test_someone_still_deciding_is_left_alone(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770002, hours_ago=0)

    assert 770002 not in chosen({770002})


def test_someone_who_already_has_access_is_not_written_to(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770003, access=True)

    assert 770003 not in chosen({770003})


def test_someone_who_already_paid_is_not_written_to(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770004, paid=True)

    assert 770004 not in chosen({770004})


def test_someone_who_started_paying_gets_the_other_reminder_instead(clean_db):
    """
    De quien empezó un checkout se encarga abandoned_checkout_service. Dos
    mensajes por lo mismo sobran.
    """

    paying_community(clean_db)
    seed(clean_db, user_id=770005, transaction=True)

    assert 770005 not in chosen({770005})


def test_a_banned_user_is_not_written_to(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770006, banned=True)

    assert 770006 not in chosen({770006})


def test_someone_who_asked_to_be_left_alone_is_left_alone(clean_db):
    """El opt-out es común a todos los avisos del bot, no solo al reenganche."""

    paying_community(clean_db)
    seed(clean_db, user_id=770007, opted_out=True)

    assert 770007 not in chosen({770007})


def test_nobody_is_written_to_twice_about_the_same_community(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770008, already=True)

    assert 770008 not in chosen({770008})


def test_free_communities_are_not_chased(clean_db):
    """No hay nada que vender: perseguir a alguien por un acceso gratis es ruido."""

    paying_community(clean_db)

    with clean_db.conn.cursor() as cur:
        cur.execute("UPDATE groups SET is_free_group=TRUE WHERE id=777")

    seed(clean_db, user_id=770009)

    assert 770009 not in chosen({770009})


def test_a_view_older_than_the_window_is_forgotten(clean_db):
    paying_community(clean_db)
    seed(clean_db, user_id=770010, hours_ago=24 * (ifs.INTEREST_MAX_AGE_DAYS + 5))

    assert 770010 not in chosen({770010})


# =========================
# EL ENVÍO
# =========================

def test_it_records_before_sending_so_nobody_gets_it_twice(clean_db):
    """
    Se marca antes de enviar a propósito: si el envío falla no se reintenta en
    bucle y nadie recibe el mismo mensaje dos veces.
    """

    paying_community(clean_db)
    seed(clean_db, user_id=770011)

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id=None, text=None, **kwargs):
            self.sent.append(chat_id)

    class Context:
        pass

    first, second = Context(), Context()
    first.bot, second.bot = FakeBot(), FakeBot()

    ifs.INTEREST_SEND_DELAY_SECONDS = 0

    asyncio.run(ifs.process_interest_followups(first))
    asyncio.run(ifs.process_interest_followups(second))

    assert 770011 in first.bot.sent
    assert 770011 not in second.bot.sent


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(ifs, "INTEREST_ENABLED", False)

    class Context:
        bot = None

    summary = asyncio.run(ifs.process_interest_followups(Context()))

    assert summary == {"targets": 0, "sent": 0, "skipped": 0, "failed": 0}


def test_a_broken_database_does_not_crash_the_job(monkeypatch):
    class BrokenConn:
        def cursor(self):
            raise RuntimeError("base de datos caída")

    monkeypatch.setattr(ifs, "conn", BrokenConn())

    assert ifs.fetch_interested_users() == []
    assert ifs.mark_followup_sent(1, 1) is False


# =========================
# EL REGISTRO DE LA VISITA
# =========================

def test_opening_a_community_is_recorded():
    """
    Sin este registro no hay a quién escribir: las pulsaciones de botón no se
    guardaban en ninguna parte.
    """

    router = open(
        __import__("callback_router").__file__, encoding="utf-8"
    ).read()

    assert '"community_viewed"' in router
    assert 'event_key=f"marketplace_group_{group_id}"' in router
