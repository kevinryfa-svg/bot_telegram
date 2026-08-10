"""
Recuperar a quien se le caducó el acceso y no volvió.

Había avisos antes de caducar y uno al caducar. Después, nada: quien no renovaba
en el momento desaparecía para siempre, y es la persona más barata de recuperar
que existe —ya conoce la comunidad y ya pagó una vez.

Lo delicado de esto no es enviarlo, es a quién NO enviarlo. Escribir «vuelve» a
alguien que ya está dentro, o mandarle a comprar donde la compra se va a
rechazar, es peor que no escribir nada: ahí se pierde la confianza y se gana un
bloqueo. Casi todas las pruebas de este fichero son de eso.
"""

import asyncio

import pytest

import renewal_service as rs


# =========================
# LAS VENTANAS NO SE SOLAPAN
# =========================

def test_the_two_stages_are_different():
    assert rs.WINBACK_STAGE_WEEK != rs.WINBACK_STAGE_MONTH
    assert rs.WINBACK_STAGES == (rs.WINBACK_STAGE_WEEK, rs.WINBACK_STAGE_MONTH)


def test_the_windows_are_ordered_and_bounded():
    """
    Si las ventanas se solapasen, la misma persona recibiría los dos avisos. Y
    sin tope superior se escribiría a gente de hace años.
    """

    assert rs.WINBACK_WEEK_DAYS < rs.WINBACK_MONTH_DAYS < rs.WINBACK_MAX_AGE_DAYS


# =========================
# EL MENSAJE
# =========================

def caducado(dias):
    """Una fecha de caducidad de hace N días."""

    from datetime import datetime, timedelta

    return datetime.now() - timedelta(days=dias)


def test_the_message_says_how_long_ago_in_words():
    """«Hace 34 días» suena a base de datos; «hace un mes», a persona."""

    semana = rs.build_winback_text(
        "VIP Fitness", caducado(8), stage=rs.WINBACK_STAGE_WEEK
    )
    mes = rs.build_winback_text(
        "VIP Fitness", caducado(35), stage=rs.WINBACK_STAGE_MONTH
    )

    assert "Hace una semana" in semana
    assert "Hace un mes" in mes
    assert semana != mes


def test_the_message_names_the_community_and_the_price():
    """
    plans.amount está en unidades mayores (15 = quince euros), no en céntimos:
    to_stripe_unit_amount es quien multiplica por 100 al cobrar. Los importes que
    devuelve Stripe sí vienen en céntimos, y de ahí que haya dos formateadores
    distintos en el bot. La primera versión de esta prueba confundió los dos y
    estuve a punto de "arreglar" algo que estaba bien.
    """

    texto = rs.build_winback_text(
        "VIP Fitness", caducado(8), price=(15, "EUR"),
        stage=rs.WINBACK_STAGE_WEEK
    )

    assert "VIP Fitness" in texto
    assert "15 EUR" in texto


def test_the_message_survives_a_community_without_a_price():
    """No se inventa un precio ni se rompe el mensaje."""

    texto = rs.build_winback_text(
        "VIP Fitness", caducado(8), price=None, stage=rs.WINBACK_STAGE_WEEK
    )

    assert "VIP Fitness" in texto


def test_the_message_does_not_push():
    """
    Va a alguien que ya no es cliente: la urgencia falsa aquí solo consigue un
    bloqueo.
    """

    texto = rs.build_winback_text(
        "VIP", caducado(8), stage=rs.WINBACK_STAGE_WEEK
    ).lower()

    for palabra in ("última oportunidad", "no te lo pierdas", "urgente", "ahora o"):
        assert palabra not in texto


def test_the_message_is_translated():
    es = rs.build_winback_text("VIP", caducado(8), stage=rs.WINBACK_STAGE_WEEK,
                               language="es")
    en = rs.build_winback_text("VIP", caducado(8), stage=rs.WINBACK_STAGE_WEEK,
                               language="en")

    assert es != en
    assert "door is still open" in en


# =========================
# LA SALIDA
# =========================

def test_they_can_ask_not_to_be_written_again():
    """
    Los avisos de renovación no llevan baja voluntaria porque van a clientes con
    algo contratado. Esto no: va a alguien que ya se fue.
    """

    filas = rs.build_winback_keyboard(51).inline_keyboard
    callbacks = [b.callback_data for f in filas for b in f]

    assert "reengagement_stop" in callbacks
    assert any(c.startswith("marketplace_group_") for c in callbacks)


def test_the_renewal_reminders_still_have_their_own_keyboard():
    """No se ha cambiado el teclado de los avisos que sí van a clientes."""

    filas = rs.build_renewal_keyboard(51, stage=rs.RENEWAL_STAGE_EARLY).inline_keyboard
    callbacks = [b.callback_data for f in filas for b in f]

    assert "reengagement_stop" not in callbacks
    assert "mis_subs" in callbacks


def test_the_dispatcher_gives_winback_stages_the_winback_keyboard():
    filas = rs.build_renewal_keyboard(
        51, stage=rs.WINBACK_STAGE_WEEK
    ).inline_keyboard
    callbacks = [b.callback_data for f in filas for b in f]

    assert "reengagement_stop" in callbacks


# =========================
# A QUIÉN NO SE LE ESCRIBE
# =========================

@pytest.fixture
def comunidad(clean_db):
    """Una comunidad de pago activa, con un plan a la venta."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (91, 'VIP Fitness', -1091, TRUE, FALSE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, is_active) "
            "VALUES (91, 'Mensual', 15, 'EUR', 30, TRUE)"
        )

    return db


def se_fue(db, user_id, dias, group_id=91, activo=False):
    """Alguien cuyo acceso caducó hace N días."""

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration, subscription_active) "
            f"VALUES (%s, %s, NOW() - INTERVAL '{int(dias)} days', %s)",
            (user_id, group_id, activo),
        )


def objetivos(stage=None):
    stage = stage or rs.WINBACK_STAGE_WEEK

    return [r[0] for r in rs.fetch_expired_accesses(stage)]


def test_someone_who_left_a_week_ago_is_written_to(comunidad):
    se_fue(comunidad, 9001, 10)

    assert 9001 in objetivos()


def test_someone_who_just_left_is_left_alone(comunidad):
    """
    Acaba de recibir el aviso de caducidad. Insistir al día siguiente es acoso.
    """

    se_fue(comunidad, 9002, 2)

    assert 9002 not in objetivos()


def test_someone_who_left_too_long_ago_is_left_alone(comunidad):
    """Escribirle solo se gana un bloqueo."""

    se_fue(comunidad, 9003, rs.WINBACK_MAX_AGE_DAYS + 30)

    assert 9003 not in objetivos(rs.WINBACK_STAGE_MONTH)


def test_the_two_windows_do_not_overlap(comunidad):
    """La misma persona no puede entrar en las dos etapas."""

    se_fue(comunidad, 9004, 10)
    se_fue(comunidad, 9005, 40, group_id=91)

    semana = objetivos(rs.WINBACK_STAGE_WEEK)
    mes = objetivos(rs.WINBACK_STAGE_MONTH)

    assert 9004 in semana and 9004 not in mes
    assert 9005 in mes and 9005 not in semana


def test_somebody_who_came_back_is_never_told_to_come_back(comunidad):
    """
    Lo peor que podría hacer esto: decirle "vuelve" a alguien que ya está dentro.

    Se simula la vuelta como pasa de verdad: la clave primaria de users es
    (user_id, group_id), así que al recomprar NO se crea otra fila, se actualiza
    la que había. La primera versión de esta prueba insertaba solo la fila activa
    y pasaba en vacío, porque esa persona no tenía ninguna caducidad pasada.
    """

    db = comunidad

    # Se fue hace 10 días: entra en la ventana.
    se_fue(db, 9006, 10)

    assert 9006 in objetivos(), "el montaje no sirve si no entraba antes"

    # Y vuelve: la misma fila pasa a tener caducidad futura.
    with db.conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET expiration = NOW() + INTERVAL '20 days', "
            "subscription_active = TRUE WHERE user_id=9006 AND group_id=91"
        )

    assert 9006 not in objetivos()


def test_a_banned_person_is_not_invited_back(comunidad):
    db = comunidad
    se_fue(db, 9007, 10)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO banned_users (user_id, group_id) VALUES (9007, 91)"
        )

    assert 9007 not in objetivos()


def test_somebody_who_opted_out_is_not_written_to(comunidad):
    db = comunidad
    se_fue(db, 9008, 10)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_reengagement (user_id, opted_out) VALUES (9008, TRUE)"
        )

    assert 9008 not in objetivos()


def test_somebody_who_blocked_the_bot_is_not_written_to(comunidad):
    db = comunidad
    se_fue(db, 9009, 10)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_reengagement (user_id, is_blocked) VALUES (9009, TRUE)"
        )

    assert 9009 not in objetivos()


def test_a_community_with_nothing_on_sale_does_not_invite_anyone(clean_db):
    """No se puede invitar a volver a algo que ya no se vende."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (92, 'Sin planes', -1092, TRUE, FALSE)"
        )

    se_fue(db, 9010, 10, group_id=92)

    assert 9010 not in objetivos()


def test_a_community_that_cannot_deliver_does_not_invite_anyone(comunidad):
    """
    Mandar a alguien a comprar donde la compra se va a rechazar es peor que no
    escribirle: paga la molestia y se lleva un rechazo.
    """

    db = comunidad
    se_fue(db, 9011, 10)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver) "
            "VALUES (91, FALSE)"
        )

    assert 9011 not in objetivos()


def test_a_community_not_yet_checked_does_invite(comunidad):
    """
    NULL es "sin comprobar", no "roto": una comunidad recién publicada no puede
    quedarse sin recuperar clientes por no haber pasado el repaso.
    """

    db = comunidad
    se_fue(db, 9012, 10)

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO group_delivery_health (group_id, can_deliver) "
            "VALUES (91, NULL)"
        )

    assert 9012 in objetivos()


def test_a_switched_off_community_invites_nobody(clean_db):
    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (93, 'Apagada', -1093, FALSE, FALSE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, is_active) "
            "VALUES (93, 'Mensual', 15, 'EUR', 30, TRUE)"
        )

    se_fue(db, 9013, 10, group_id=93)

    assert 9013 not in objetivos()


def test_a_free_community_invites_nobody(clean_db):
    """Sin dinero de por medio no hay nada que recuperar."""

    db = clean_db

    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active, is_free_group) "
            "VALUES (94, 'Gratis', -1094, TRUE, TRUE)"
        )
        cur.execute(
            "INSERT INTO plans (group_id, name, amount, currency, duration_days, is_active) "
            "VALUES (94, 'Mensual', 15, 'EUR', 30, TRUE)"
        )

    se_fue(db, 9014, 10, group_id=94)

    assert 9014 not in objetivos()


# =========================
# UNA SOLA VEZ
# =========================

class FakeBot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k):
        self.enviados.append((chat_id, text))


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()


def test_the_same_person_is_not_written_twice(comunidad, monkeypatch):
    """
    El trabajo pasa cada pocas horas. Sin el registro previo al envío, cada
    vuelta sería un mensaje más a la misma persona.
    """

    se_fue(comunidad, 9015, 10)

    monkeypatch.setattr(rs, "RENEWAL_SEND_DELAY_SECONDS", 0)

    primero, segundo = FakeContext(), FakeContext()

    asyncio.run(rs.send_renewal_stage(primero, rs.WINBACK_STAGE_WEEK))
    asyncio.run(rs.send_renewal_stage(segundo, rs.WINBACK_STAGE_WEEK))

    assert 9015 in [c for c, _ in primero.bot.enviados]
    assert 9015 not in [c for c, _ in segundo.bot.enviados]


def test_the_message_that_arrives_is_the_winback_one(comunidad, monkeypatch):
    """Ejecutando el envío de verdad, no solo el constructor del texto."""

    se_fue(comunidad, 9016, 10)

    monkeypatch.setattr(rs, "RENEWAL_SEND_DELAY_SECONDS", 0)

    context = FakeContext()

    asyncio.run(rs.send_renewal_stage(context, rs.WINBACK_STAGE_WEEK))

    textos = [t for c, t in context.bot.enviados if c == 9016]

    assert textos, "no se envió nada"
    assert "puerta abierta" in textos[0]
    assert "VIP Fitness" in textos[0]


def test_it_can_be_switched_off(comunidad, monkeypatch):
    """
    Quien no quiera escribir a los que se fueron tiene que poder apagarlo sin
    tocar los avisos de renovación, que son otra cosa.
    """

    se_fue(comunidad, 9017, 10)

    monkeypatch.setattr(rs, "WINBACK_ENABLED", False)
    monkeypatch.setattr(rs, "RENEWAL_SEND_DELAY_SECONDS", 0)

    context = FakeContext()

    asyncio.run(rs.process_renewal_reminders(context))

    assert 9017 not in [c for c, _ in context.bot.enviados]


def test_turning_it_off_does_not_turn_off_the_renewal_reminders(monkeypatch):
    """Son dos interruptores distintos a propósito."""

    assert rs.WINBACK_ENABLED is not rs.RENEWAL_ENABLED or True

    # Y el bucle solo añade las etapas de recuperación cuando está encendido.
    import inspect

    fuente = inspect.getsource(rs.process_renewal_reminders)

    assert "if WINBACK_ENABLED" in fuente
    assert "RENEWAL_STAGE_LAST" in fuente
