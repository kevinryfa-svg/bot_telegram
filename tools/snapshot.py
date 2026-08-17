"""
Retrato fiel de lo que produce cada botón, para poder comparar antes y después.

El barrido de la suite (tests/test_button_sweep.py) prueba que ningún botón
lanza una excepción. Para mover código de verdad hace falta más: poder
comparar, botón por botón, lo que SALÍA antes y lo que sale después. Con esta
herramienta se troceó una función de 24.000 líneas en 36 módulos sin cambiar
una sola pantalla.

No es un test y no debe serlo: exigiría un retrato de referencia versionado en
el repositorio, y ese fichero habría que regenerarlo en cada cambio
intencionado de texto. La friccíón haría que alguien lo regenerara sin mirar,
que es justo lo contrario de para lo que sirve. Se usa a mano, cuando toca.

    # antes de tocar nada
    TEST_DATABASE_URL=... python tools/snapshot.py /tmp/antes.json

    # después del cambio
    TEST_DATABASE_URL=... python tools/snapshot.py /tmp/despues.json

    python tools/snapshot_diff.py /tmp/antes.json /tmp/despues.json

Y la única regla al leer el diff: cada diferencia tiene que ser una que
esperabas. Si aparece una que no, ese es el fallo que ibas a desplegar.

Dos cosas que el retrato normaliza a propósito, porque cambian entre
ejecuciones sin que cambie el comportamiento: fechas/horas/duraciones y los
códigos generados al azar. Y la base de datos se deja en un estado fijo con
TRUNCATE ... RESTART IDENTITY: sin reiniciar los contadores, los ids crecen en
cada ejecución y acaban dentro de los callback_data (ai_feedback_292_up →
ai_feedback_309_up), así que dos ejecuciones del mismo código dejarían de
coincidir y el retrato no valdría para nada.
"""

import sys, ast, glob, json, asyncio, re, collections
from unittest.mock import AsyncMock, MagicMock
sys.path.insert(0, ".")
import psycopg2

import os

# La misma variable que usa la suite: nada de credenciales escritas dentro.
DSN = os.environ.get("TEST_DATABASE_URL")

if not DSN:
    raise SystemExit(
        "Define TEST_DATABASE_URL con una base de datos DESECHABLE: esta "
        "herramienta vacía tablas con TRUNCATE."
    )
import db
def _local():
    c = psycopg2.connect(DSN, sslmode="disable"); c.autocommit = True; return c
db._open_conn = _local; db.conn._conn = None

# --- nada de red ---
class FakeResp:
    status_code = 200
    text = '{"ok":true,"result":{"message_id":1,"invite_link":"https://t.me/joinchat/x"}}'
    def json(self):
        return {"ok": True, "result": {"message_id": 1, "invite_link": "https://t.me/joinchat/x",
                                       "id": "x", "url": "https://x", "status": "ok"}}
    def raise_for_status(self): pass
import requests, time as _time
requests.post = lambda *a, **k: FakeResp()
requests.get = lambda *a, **k: FakeResp()
requests.request = lambda *a, **k: FakeResp()
_time.sleep = lambda *a, **k: None

UID, GID, TGID = 8761243211, 1, -1001234567890

# --- estado fijo de la base de datos ---
FIXED_TABLES = [
    "invite_links","payments","payment_transactions","abandoned_checkout_reminders",
    "access_renewal_reminders","user_reengagement","bot_persistence","user_preferences",
    "users","plans","banned_users","admins","groups","database_backups",
]
# Se vacían TODAS las tablas con id autoincremental reiniciando el contador.
# Sin RESTART IDENTITY, los ids crecen en cada ejecución y aparecen dentro de
# callback_data (ai_feedback_292_up -> ai_feedback_309_up), así que dos
# ejecuciones del mismo código ya no coincidirían y el retrato no valdría para
# comparar nada.
with db.conn.cursor() as cur:
    cur.execute("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema='public' AND column_default LIKE 'nextval%'
    """)
    serial_tables = sorted({r[0] for r in cur.fetchall()})

for t in serial_tables + FIXED_TABLES:
    try:
        with db.conn.cursor() as cur:
            cur.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
    except Exception:
        try:
            with db.conn.cursor() as cur:
                cur.execute(f"DELETE FROM {t}")
        except Exception:
            pass

with db.conn.cursor() as cur:
    cur.execute("INSERT INTO groups (id,name,telegram_group_id,is_active) VALUES (%s,'Grupo Test',%s,TRUE)",(GID,TGID))
    cur.execute("INSERT INTO users (user_id,group_id,expiration,subscription_active) "
                "VALUES (%s,%s,'2099-01-01'::timestamp,TRUE)",(UID,GID))
    try: cur.execute("INSERT INTO admins (user_id,group_id,is_active,is_super_admin) VALUES (%s,%s,TRUE,TRUE)",(UID,GID))
    except Exception: pass
    cur.execute("INSERT INTO plans (group_id,name,price_id,stripe_price_id,duration_days,amount,currency,is_active) "
                "VALUES (%s,'Plan Test','price_x','price_x',30,10,'EUR',TRUE)",(GID,))


# TRUNCATE ... RESTART IDENTITY deja el contador en 1, y arriba se ha insertado
# el grupo con id=1 a mano sin avanzarlo: el siguiente insert automático pide el
# 1 otra vez y choca. Eso rompía la suite de tests al ejecutarse justo después.
with db.conn.cursor() as cur:
    cur.execute("SELECT setval(pg_get_serial_sequence('groups','id'), "
                "(SELECT GREATEST(COALESCE(MAX(id),0),1) FROM groups))")

import callback_router as cr

# Todos los callbacks estáticos del proyecto
cbs = set()
for f in glob.glob("*.py"):
    for n in ast.walk(ast.parse(open(f).read(), f)):
        if isinstance(n, ast.Call) and (getattr(n.func,'attr',None) or getattr(n.func,'id',None))=="InlineKeyboardButton":
            for kw in n.keywords:
                if kw.arg=="callback_data" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value,str):
                    cbs.add(kw.value.value)
cbs = sorted(c for c in cbs if len(c) > 2)

# Lo que varía entre ejecuciones y no es comportamiento: fechas, horas, ids.
NORM = [
    (re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}"), "<FECHA-HORA>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"), "<FECHA-HORA>"),
    (re.compile(r"\d{2}/\d{2}/\d{4}"), "<FECHA>"),
    (re.compile(r"\b\d+\s*(ms|s)\b"), "<DURACION>"),
    # Códigos generados al azar: cambian en cada ejecución por diseño.
    (re.compile(r"\bOWNER-[A-Z0-9]{6,}\b"), "OWNER-<CODIGO>"),
    (re.compile(r"\b[A-Z]{2,}-[A-Z0-9]{6,}\b"), "<CODIGO>"),
    # Sellos de tiempo compactos: nombre de fichero de copia, id de campaña.
    (re.compile(r"\d{8}-\d{6}"), "<SELLO>"),
    (re.compile(r"\d{14}"), "<SELLO>"),
    (re.compile(r"\d{8}_\d{6}_[0-9a-f]+"), "<SELLO>"),
    # Cuenta atrás en vivo del acceso: cambia entre dos ejecuciones seguidas.
    (re.compile(r"\d+d \d+h \d+m"), "<RESTANTE>"),
    # Códigos largos generados al azar, sin guion.
    (re.compile(r"\b[A-Z0-9]{16,}\b"), "<CODIGO>"),
]
def norm(text):
    text = str(text)
    for rx, rep in NORM:
        text = rx.sub(rep, text)
    return text

def kb_of(markup):
    if markup is None: return None
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None and isinstance(markup, dict):
        rows = markup.get("inline_keyboard")
    if rows is None: return "<markup?>"
    out = []
    for row in rows:
        out.append([
            (norm(b.text if hasattr(b,"text") else b.get("text")),
             norm(b.callback_data if hasattr(b,"callback_data") else b.get("callback_data")))
            for b in row
        ])
    return out

def make(cb, captured):
    msg = MagicMock()
    msg.chat_id = UID; msg.message_id = 1; msg.text = "texto"; msg.caption = None
    msg.chat = MagicMock(id=UID, type="private"); msg.reply_markup = None
    msg.delete = AsyncMock()
    async def reply_text(text=None, **k):
        captured.append(("reply_text", norm(text), kb_of(k.get("reply_markup"))))
        return MagicMock(message_id=1)
    msg.reply_text = AsyncMock(side_effect=reply_text)
    msg.edit_text = AsyncMock(); msg.reply_video = AsyncMock(); msg.reply_photo = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    u = MagicMock(id=UID, username="admin", first_name="Admin", full_name="Admin",
                  is_bot=False, language_code="es")
    q = MagicMock(); q.data = cb; q.from_user = u; q.message = msg
    async def answer(text=None, **k):
        if text: captured.append(("answer", norm(text), None))
    q.answer = AsyncMock(side_effect=answer)
    async def emt(text=None, **k):
        captured.append(("edit_message_text", norm(text), kb_of(k.get("reply_markup"))))
    q.edit_message_text = AsyncMock(side_effect=emt)
    q.edit_message_reply_markup = AsyncMock(); q.edit_message_caption = AsyncMock()
    upd = MagicMock(); upd.callback_query = q; upd.effective_user = u
    upd.effective_chat = msg.chat; upd.message = None; upd.effective_message = msg
    ctx = MagicMock(); ctx.user_data = {}; ctx.chat_data = {}; ctx.bot_data = {}; ctx.args = []
    bot = AsyncMock()
    async def send_message(chat_id=None, text=None, **k):
        captured.append(("send_message", norm(text), kb_of(k.get("reply_markup"))))
        return MagicMock(message_id=1)
    bot.send_message = AsyncMock(side_effect=send_message)
    ctx.bot = bot
    return upd, ctx

async def main():
    out = {}
    for cb in cbs:
        captured = []
        upd, ctx = make(cb, captured)
        try:
            await asyncio.wait_for(cr.button(upd, ctx), timeout=8)
            status = "ok"
        except asyncio.TimeoutError:
            status = "TIMEOUT"
        except Exception as e:
            status = f"EXC {type(e).__name__}: {str(e)[:120]}"
        out[cb] = {"status": status, "salida": captured}
    path = sys.argv[1] if len(sys.argv) > 1 else "snapshot.json"
    with open(path, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
    con_salida = sum(1 for v in out.values() if v["salida"])
    print(f"botones: {len(out)}   con salida capturada: {con_salida}   "
          f"sin salida: {len(out)-con_salida}")
    print(f"escrito en {path}")

asyncio.run(main())
