"""
Un comprador de mentira que pulsa los botones de verdad.

Ninguna prueba había pulsado nunca un botón de compra a través del router: se
comprobaba el escaparate por un lado y el servidor de cobro por otro, y el clic
—donde se decide si alguien llega a pagar— no lo ejecutaba nadie entero.

Esto simula lo justo de Telegram para que `callback_router.button` corra de
verdad: un bot que apunta todo lo que se le pide, un mensaje privado y una
pulsación. El servidor de cobro es el real (Flask en memoria); solo Stripe es de
mentira.
"""

import asyncio
import json


class Grabadora:
    """Cualquier método async que se le pida existe y apunta la llamada."""

    def __init__(self, registro, quien, chat_id=None):
        self._registro = registro
        self._quien = quien
        self.chat_id = chat_id
        self.message_id = len(registro) + 1
        self.id = 777000

    def __getattr__(self, nombre):

        if nombre.startswith("__"):
            raise AttributeError(nombre)

        async def metodo(*args, **kwargs):

            self._registro.append({
                "quien": self._quien, "metodo": nombre,
                "args": args, "kwargs": kwargs,
            })

            if nombre == "get_chat_member":

                class Miembro:
                    status = "left"

                return Miembro()

            if nombre == "create_chat_invite_link":

                class Enlace:
                    invite_link = "https://t.me/+enlace_de_prueba"

                return Enlace()

            if nombre == "get_chat":

                class Chat:
                    title = "StarsVip"
                    type = "supergroup"
                    id = kwargs.get("chat_id") or (args[0] if args else 0)

                return Chat()

            if nombre in ("get_me",):

                class Yo:
                    id = 777000
                    username = "TheStarVipBOT"

                return Yo()

            return Grabadora(self._registro, "respuesta", self.chat_id)

        return metodo


class Usuario:

    def __init__(self, user_id, idioma="es"):
        self.id = user_id
        self.username = f"comprador{user_id}"
        self.first_name = "Comprador"
        self.last_name = None
        self.language_code = idioma
        self.is_bot = False


class Chat:

    def __init__(self, chat_id):
        self.id = chat_id
        self.type = "private"


class Pulsacion:

    def __init__(self, data, usuario, mensaje):
        self.data = data
        self.from_user = usuario
        self.message = mensaje
        self.id = "q1"

    async def answer(self, *args, **kwargs):
        return True

    async def edit_message_text(self, *args, **kwargs):
        return await self.message.edit_text(*args, **kwargs)

    async def edit_message_reply_markup(self, *args, **kwargs):
        return await self.message.edit_reply_markup(*args, **kwargs)


class Actualizacion:

    def __init__(self, pulsacion):
        self.callback_query = pulsacion
        self.effective_user = pulsacion.from_user
        self.effective_chat = Chat(pulsacion.message.chat_id)
        self.effective_message = pulsacion.message
        self.message = None
        self.update_id = 1


class Contexto:

    def __init__(self, bot):
        self.bot = bot
        self.user_data = {}
        self.chat_data = {}
        self.bot_data = {}
        self.args = []
        self.job_queue = None
        self.application = None


def botones_de(llamada):
    """Todos los botones de una llamada al bot, sea cual sea su forma."""

    teclado = llamada["kwargs"].get("reply_markup")

    if teclado is None:
        return []

    filas = getattr(teclado, "inline_keyboard", None)

    if filas is None:
        return []

    return [b for fila in filas for b in fila]


def textos_de(llamada):

    k = llamada["kwargs"]

    for clave in ("text", "caption"):
        if k.get(clave):
            return str(k[clave])

    for a in llamada["args"]:
        if isinstance(a, str) and len(a) > 3:
            return a

    return ""


class Comprador:
    """Pulsa botones en el router real y apunta qué ve."""

    def __init__(self, user_id, idioma="es"):
        self.registro = []
        self.usuario = Usuario(user_id, idioma)
        self.bot = Grabadora(self.registro, "bot", chat_id=user_id)
        self.contexto = Contexto(self.bot)

    def pulsar(self, data):

        import callback_router

        antes = len(self.registro)

        mensaje = Grabadora(self.registro, "mensaje", chat_id=self.usuario.id)

        actualizacion = Actualizacion(
            Pulsacion(data, self.usuario, mensaje)
        )

        error = None

        try:
            asyncio.run(callback_router.button(actualizacion, self.contexto))
        except Exception as e:  # el error ES el dato
            error = f"{type(e).__name__}: {e}"

        return self.registro[antes:], error


def conectar_cobro_real(monkeypatch, app):
    """
    Las peticiones del bot a su propio servidor de cobro van al Flask real en
    memoria. Así se ejecuta el código de verdad de los dos lados.
    """

    import requests

    cliente = app.test_client()

    class Respuesta:

        def __init__(self, r):
            self.status_code = r.status_code
            self._r = r
            self.text = r.get_data(as_text=True)

        def json(self):
            return json.loads(self.text)

        @property
        def ok(self):
            return 200 <= self.status_code < 300

        def raise_for_status(self):
            if not self.ok:
                raise requests.HTTPError(f"{self.status_code}")

    original = requests.post

    def falso_post(url, *args, **kwargs):

        if "/create-checkout-session" in str(url):

            cuerpo = kwargs.get("json")

            if cuerpo is None and kwargs.get("data"):
                cuerpo = json.loads(kwargs["data"])

            r = cliente.post(
                "/create-checkout-session",
                data=json.dumps(cuerpo or {}),
                content_type="application/json",
            )

            return Respuesta(r)

        raise AssertionError(f"petición inesperada en una prueba: {url}")

    monkeypatch.setattr(requests, "post", falso_post)

    return original
