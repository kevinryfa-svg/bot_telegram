"""
Dos cosas que le pasaban a quien YA había pagado.

La primera es de las que no revientan y enfadan: abrir «Mis accesos» a mirar
cuándo caduca le mataba el enlace de entrada que tenía guardado. La segunda es
de las que pierden al que todavía no ha pagado: nueve pantallas de error sin un
solo botón, una de ellas la primera pantalla del bot.
"""

import pytest


# =========================
# ABRIR LA PANTALLA NO PUEDE COSTARTE EL ENLACE
# =========================
# El botón «Enviarme otro enlace» llevaba EL MISMO callback que abrir la
# pantalla, así que no había forma de distinguirlos: cada visita revocaba y
# BORRABA todos los enlaces de esa persona y creaba uno nuevo. Quien lo tenía
# guardado o reenviado se lo encontraba muerto sin aviso.

def test_asking_for_another_link_is_its_own_action():
    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    assert 'data.startswith("mysubnew_")' in fuente, (
        "sin callback propio, pedir otro enlace y mirar la pantalla son lo mismo"
    )

    pos = fuente.index('t("mysub.btn_another_link", language)')
    trozo = fuente[pos:pos + 200]

    assert "mysubnew_" in trozo, "el botón tiene que usar la rama nueva"


def test_the_new_branch_cannot_be_swallowed_by_the_generic_one():
    """«mysubnew_1» no empieza por «mysub_», pero conviene que quede escrito."""

    assert not "mysubnew_1".startswith("mysub_")


def test_opening_the_screen_reuses_the_link_it_finds(clean_db):
    import mysub_callbacks as ms

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (95, 'StarsVip', -1095, TRUE)"
        )
        cur.execute(
            "INSERT INTO invite_links (user_id, group_id, telegram_group_id, "
            "invite_link) VALUES (9501, 95, -1095, 'https://t.me/+vivo')"
        )

    assert ms.buscar_enlace_vivo(9501, 95, -1095) == "https://t.me/+vivo"


def test_a_revoked_link_is_not_reused(clean_db):
    import mysub_callbacks as ms

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (95, 'StarsVip', -1095, TRUE)"
        )
        cur.execute(
            "INSERT INTO invite_links (user_id, group_id, telegram_group_id, "
            "invite_link, is_active, revoked_at) "
            "VALUES (9501, 95, -1095, 'https://t.me/+muerto', FALSE, NOW())"
        )

    assert ms.buscar_enlace_vivo(9501, 95, -1095) is None


def test_a_link_past_its_expiry_is_not_reused(clean_db):
    """Telegram lo caduca solo; la tabla no guarda esa fecha, se deduce."""

    import mysub_callbacks as ms

    with clean_db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id, is_active) "
            "VALUES (95, 'StarsVip', -1095, TRUE)"
        )
        cur.execute(
            "INSERT INTO invite_links (user_id, group_id, telegram_group_id, "
            "invite_link, created_at) VALUES "
            "(9501, 95, -1095, 'https://t.me/+viejo', NOW() - INTERVAL '40 days')"
        )

    assert ms.buscar_enlace_vivo(9501, 95, -1095) is None, (
        "reutilizar uno caducado sería dejar fuera a quien ha pagado"
    )


def test_not_knowing_means_giving_a_new_one(monkeypatch):
    """Sin poder mirarlo, mejor crear otro que dejarle sin enlace."""

    import mysub_callbacks as ms

    class Revienta:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr(ms, "conn", Revienta())

    assert ms.buscar_enlace_vivo(9501, 95, -1095) is None


def test_the_destruction_only_runs_when_a_new_one_is_needed():
    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    pos = fuente.index("# REVOCAR LINKS ANTIGUOS")
    trozo = fuente[pos:pos + 500]

    assert "if not enlace_vivo:" in trozo, (
        "revocar y borrar corría en CADA visita a la pantalla"
    )


def test_the_saved_row_is_not_inserted_twice():
    """invite_links tiene UNIQUE (user_id, group_id)."""

    fuente = open("mysub_callbacks.py", encoding="utf-8").read()

    pos = fuente.index("# GUARDAR LINK NUEVO")
    trozo = fuente[pos:pos + 700]

    assert "if not enlace_vivo:" in trozo


# =========================
# NUEVE PANTALLAS DE ERROR SIN SALIDA
# =========================

def test_no_buyer_error_screen_is_a_dead_end():
    fuente = open("callback_router.py", encoding="utf-8").read()

    for mensaje in ("❌ Comunidad no encontrada o no disponible.",
                    "❌ Error cargando planes."):

        desde = 0

        while True:

            pos = fuente.find(mensaje, desde)

            if pos == -1:
                break

            # La llamada se cierra poco después: el teclado tiene que estar ahí.
            trozo = fuente[pos:pos + 300]

            assert "reply_markup" in trozo, (
                f"«{mensaje}» sigue siendo un callejón en la posición {pos}"
            )

            desde = pos + 1


def test_the_payment_errors_say_nobody_charged_you():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert fuente.count("Error cargando planes. No se te ha cobrado nada.") >= 2, (
        "en una pantalla de error de compra, lo primero que hay que decir es "
        "que no se ha cobrado"
    )


def test_the_first_screen_of_the_bot_has_a_way_out():
    fuente = open("start_handler.py", encoding="utf-8").read()

    pos = fuente.index("No he podido cargar las comunidades")
    trozo = fuente[max(0, pos - 700):pos + 700]

    assert "build_recover_navigation_keyboard" in trozo, (
        "quien llega desde un anuncio y se topa con esto no tiene a dónde ir"
    )
    assert "reply_markup=teclado" in trozo


def test_a_community_with_nothing_on_sale_is_told_plainly():
    fuente = open("callback_router.py", encoding="utf-8").read()

    assert "configurado como gratuito ni tiene planes activos" not in fuente, (
        "eso describe la base de datos, no lo que le pasa al comprador"
    )
    assert "todavía no tiene ningún acceso a la venta" in fuente
