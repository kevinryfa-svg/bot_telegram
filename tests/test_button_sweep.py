"""
Se pulsan TODOS los botones del bot y ninguno puede reventar.

Un bot es una superficie de cientos de botones, y el fallo típico no es una
excepción escandalosa: es un botón concreto que responde con un error mudo
mientras el resto funciona. Nadie lo encuentra hasta que un cliente lo pulsa.

Este barrido descubre los callbacks estáticos leyendo el código —cada
`InlineKeyboardButton(callback_data="...")` con texto literal— y los pulsa
uno a uno contra una base de datos real, con la red cortada. Cualquier
excepción o cuelgue es un fallo con nombre y línea.

Lo que ha cazado esta herramienta durante la sesión, para que quede claro que
no es decorado: una variable usada antes de asignarse en el camino de las
peticiones HTTP, y el cambio de stripe 15.x que rompía TODOS los cobros
(los recursos del SDK dejaron de ser diccionarios).

Los botones con callback dinámico (f-strings con ids dentro) no salen aquí:
esos se prueban en el test de su propia pantalla, con datos reales.
"""

import ast
import asyncio
import glob
import os
import pathlib
import sys
import traceback

import pytest
from unittest.mock import AsyncMock, MagicMock

import callback_router as cr


RAIZ = pathlib.Path(cr.__file__).parent

UID, GID, TGID = 8761243211, 990001, -1990001


def descubrir_callbacks():
    """Todos los callback_data literales del proyecto, ordenados."""

    encontrados = set()

    for fichero in glob.glob(str(RAIZ / "*.py")):

        try:

            arbol = ast.parse(
                pathlib.Path(fichero).read_text(encoding="utf-8"), fichero
            )

        except Exception:

            continue

        for nodo in ast.walk(arbol):

            nombre = (getattr(getattr(nodo, "func", None), "attr", None)
                      or getattr(getattr(nodo, "func", None), "id", None))

            if not isinstance(nodo, ast.Call) or nombre != "InlineKeyboardButton":
                continue

            for kw in nodo.keywords:

                if (kw.arg == "callback_data"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):

                    encontrados.add(kw.value.value)

    return sorted(c for c in encontrados if len(c) > 2)


def preparar_datos(db):
    """Un grupo, un plan y un usuario administrador para que haya qué pulsar."""

    with db.conn.cursor() as cur:

        cur.execute(
            "INSERT INTO groups (id, name, telegram_group_id) VALUES (%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (GID, "Grupo Barrido", TGID)
        )
        cur.execute(
            "INSERT INTO users (user_id, group_id, expiration) "
            "VALUES (%s,%s,NOW()+INTERVAL '30 days') ON CONFLICT DO NOTHING",
            (UID, GID)
        )

        try:

            cur.execute(
                "INSERT INTO admins (user_id, group_id, is_active) "
                "VALUES (%s,%s,TRUE) ON CONFLICT DO NOTHING",
                (UID, GID)
            )

        except Exception:

            pass

        cur.execute("SELECT COUNT(*) FROM plans WHERE group_id=%s", (GID,))

        if not cur.fetchone()[0]:

            cur.execute(
                "INSERT INTO plans (group_id, name, price_id, stripe_price_id, "
                "duration_days, amount, currency) "
                "VALUES (%s,'Plan Barrido','price_barrido','price_barrido',30,10,'EUR')",
                (GID,)
            )


def hacer_update(callback):
    """Un update de Telegram falso, con todo lo que tocan los handlers."""

    msg = MagicMock()
    msg.chat_id = UID
    msg.message_id = 1
    msg.text = "texto"
    msg.caption = None
    msg.chat = MagicMock(id=UID, type="private")
    msg.reply_markup = None
    msg.delete = AsyncMock()
    msg.reply_text = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.reply_video = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.reply_document = AsyncMock()
    msg.edit_reply_markup = AsyncMock()

    usuario = MagicMock(id=UID, username="admin", first_name="Admin",
                        full_name="Admin", is_bot=False)

    query = MagicMock()
    query.data = callback
    query.from_user = usuario
    query.message = msg
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.edit_message_caption = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user = usuario
    update.effective_chat = msg.chat
    update.message = None
    update.effective_message = msg

    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []

    return update, context


class RespuestaFalsa:
    """Ninguna llamada del barrido sale a la red."""

    status_code = 200
    text = '{"ok":true,"result":{"message_id":1}}'

    def json(self):

        return {
            "ok": True,
            "result": {
                "message_id": 1,
                "invite_link": "https://t.me/joinchat/barrido",
                "id": "x",
                "url": "https://example.invalid",
                "status": "ok",
            },
        }

    def raise_for_status(self):

        return None


@pytest.fixture
def barrido(clean_db, monkeypatch):
    """Datos mínimos y red cortada."""

    import requests
    import time as _time

    preparar_datos(clean_db)

    for nombre in ("post", "get", "request", "put", "patch", "delete"):

        if hasattr(requests, nombre):
            monkeypatch.setattr(requests, nombre,
                                lambda *a, **k: RespuestaFalsa())

    # Los reintentos con espera convertirían el barrido en algo eterno.
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)

    return clean_db


def test_every_static_button_answers_without_blowing_up(barrido):
    callbacks = descubrir_callbacks()

    assert len(callbacks) > 200, (
        "el descubrimiento de botones se ha roto: deberían salir cientos"
    )

    errores = []

    async def pulsar_todos():

        for callback in callbacks:

            update, context = hacer_update(callback)

            try:

                await asyncio.wait_for(cr.button(update, context), timeout=20)

            except asyncio.TimeoutError:

                errores.append((callback, "TIMEOUT: el handler se cuelga", "-"))

            except Exception as e:

                tb = traceback.extract_tb(sys.exc_info()[2])
                marco = next(
                    (fr for fr in reversed(tb)
                     if str(RAIZ) in fr.filename),
                    tb[-1]
                )
                errores.append((
                    callback,
                    f"{type(e).__name__}: {str(e)[:150]}",
                    f"{os.path.basename(marco.filename)}:{marco.lineno}",
                ))

    asyncio.run(pulsar_todos())

    detalle = "\n".join(
        f"  {cb} → {msg} ({loc})" for cb, msg, loc in errores[:15]
    )

    assert not errores, (
        f"{len(errores)} de {len(callbacks)} botones revientan al pulsarlos:\n"
        f"{detalle}\n\n"
        "Un botón que responde con un error mudo no lo encuentra nadie hasta "
        "que lo pulsa un cliente."
    )
