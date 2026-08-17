"""
Idioma del usuario y textos traducidos.

Dos cosas que faltaban y se notaban:

  - el idioma elegido vivía en un diccionario en memoria (help_handler), así
    que cualquier reinicio devolvía a todo el mundo al español. Elegir idioma
    no servía de nada más allá de un rato.
  - nadie preguntaba a Telegram. Telegram ya envía el idioma del cliente en
    cada mensaje, así que un comprador inglés podía atenderse en inglés desde
    su primer /start sin saber que existe un menú de idiomas.

Ahora la preferencia se guarda en la base de datos y, si no hay ninguna, se
deduce del idioma de Telegram.
"""


# =========================
# I18N SERVICE — SUPPORTED LANGUAGES
# =========================

DEFAULT_LANGUAGE = "es"

SUPPORTED_LANGUAGES = {

    "es": "Español",
    "en": "English",
    "pt": "Português",
    "fr": "Français",
    "it": "Italiano"
}


# =========================
# I18N SERVICE — HELPERS
# =========================

def normalize_language(language):

    language = str(language or DEFAULT_LANGUAGE).strip().lower()

    if language in SUPPORTED_LANGUAGES:

        return language


    return DEFAULT_LANGUAGE



def get_language_name(language):

    language = normalize_language(language)

    return SUPPORTED_LANGUAGES.get(
        language,
        SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]
    )



def list_supported_languages():

    return SUPPORTED_LANGUAGES


def language_from_telegram_code(language_code):
    """
    Traduce el language_code de Telegram a uno de los idiomas soportados.

    Telegram manda cosas como "en", "en-US", "pt-BR" o "es-ES": basta la parte
    anterior al guion. Si el idioma no está soportado, se devuelve None para
    que quien llama decida (normalmente, el idioma por defecto).
    """

    code = str(language_code or "").strip().lower()

    if not code:

        return None


    base = code.split("-")[0].split("_")[0]

    if base in SUPPORTED_LANGUAGES:

        return base


    return None


# =========================
# I18N SERVICE — PREFERENCIA DEL USUARIO
# =========================
# Se guarda en la base de datos: antes era un diccionario en memoria y cada
# reinicio devolvía a todo el mundo al español.

_LANGUAGE_CACHE = {}


def load_user_language(user_id, telegram_language_code=None):
    """
    Idioma del usuario: lo elegido, si no lo que dice Telegram, si no español.

    Nunca lanza: un problema de base de datos no debe impedir contestar.
    """

    if user_id in _LANGUAGE_CACHE:

        return _LANGUAGE_CACHE[user_id]


    stored = None

    try:

        from db import conn

        with conn.cursor() as cur:

            cur.execute(
                "SELECT language FROM user_preferences WHERE user_id=%s",
                (int(user_id),)
            )

            row = cur.fetchone()

            if row and row[0]:

                stored = normalize_language(row[0])

    except Exception as e:

        print("Idioma: no se pudo leer la preferencia:", e)


    if stored:

        _LANGUAGE_CACHE[user_id] = stored

        return stored


    detected = language_from_telegram_code(telegram_language_code)

    if detected:

        # Se guarda lo detectado para que no dependa de que Telegram lo mande
        # en cada actualización, y para poder cambiarlo luego a mano.
        save_user_language(user_id, detected, detected=True)

        return detected


    return DEFAULT_LANGUAGE


def save_user_language(user_id, language, detected=False):
    """Guarda la preferencia. Devuelve el idioma normalizado que queda."""

    language = normalize_language(language)

    _LANGUAGE_CACHE[user_id] = language

    try:

        from db import conn

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO user_preferences
                (user_id, language, language_is_detected, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET language=EXCLUDED.language,
                              language_is_detected=EXCLUDED.language_is_detected,
                              updated_at=NOW()

            """, (int(user_id), language, bool(detected)))

    except Exception as e:

        print("Idioma: no se pudo guardar la preferencia:", e)


    return language


def forget_cached_language(user_id):
    """Para tests y para forzar una relectura."""

    _LANGUAGE_CACHE.pop(user_id, None)


# =========================
# I18N SERVICE — TRANSLATIONS
# =========================

TRANSLATIONS = {

    # =========================
    # MENSAJES DE CLIENTE
    # =========================
    # Solo el camino del cliente está traducido: avisos de renovación,
    # caducidad, pago sin completar y los botones que llevan a comprar o a
    # pedir ayuda. Son los mensajes que deciden si un comprador extranjero
    # termina la compra.
    #
    # El panel de administración sigue en español a propósito: lo usa el
    # propietario, y traducir 50.000 líneas de panel a medias sería peor que
    # no traducirlo.

    # Lo que recibe el cliente justo después de pagar. Antes era una sola
    # línea con el enlace pelado: ni confirmación del pago, ni qué había
    # comprado, ni cuánto duraba, ni qué hacer si el enlace fallaba, ni un
    # botón. Es el mensaje más importante del bot y el que más dudas genera.

    "purchase.title": {
        "es": "✅ Pago confirmado",
        "en": "✅ Payment confirmed",
    },

    "purchase.community": {
        "es": "Comunidad: {group}",
        "en": "Community: {group}",
    },

    "purchase.plan": {
        "es": "Plan: {plan}",
        "en": "Plan: {plan}",
    },

    "purchase.amount": {
        "es": "Importe: {amount}",
        "en": "Amount: {amount}",
    },

    "purchase.until": {
        "es": "Tu acceso dura hasta el {date}.",
        "en": "Your access runs until {date}.",
    },

    "purchase.permanent": {
        "es": "Tu acceso no caduca.",
        "en": "Your access does not expire.",
    },

    "purchase.link_title": {
        "es": "🔗 Entra desde aquí:",
        "en": "🔗 Join from here:",
    },

    "purchase.link_validity": {
        "es": (
            "⏱ El enlace vale {validity} y solo lo puedes usar tú, una vez.\n"
            "Si caduca o no funciona, pide otro en «🎟 Mis accesos»."
        ),
        "en": (
            "⏱ The link is valid for {validity} and only you can use it, once.\n"
            "If it expires or fails, get another one from “🎟 My accesses”."
        ),
    },

    # Pago cobrado pero el enlace no se pudo crear (el bot ya no es admin del
    # grupo, el grupo se borró, Telegram falló). Antes se avisaba a los
    # administradores y al cliente NO se le decía nada: había pagado y recibía
    # silencio, que es la peor situación posible.

    # Devolución o disputa: se le retira el acceso. Se le dice por qué, aunque
    # la devolución la haya pedido él: quedarse fuera sin explicación acaba en un
    # ticket de soporte igualmente.

    "refund.notice": {
        "es": (
            "↩️ Devolución procesada\n\n"
            "Se ha devuelto el pago de tu acceso a {group}, así que tu acceso "
            "queda cancelado y he retirado tu enlace de entrada.\n\n"
            "Si es un error o quieres volver a entrar, escríbenos y lo vemos."
        ),
        "en": (
            "↩️ Refund processed\n\n"
            "The payment for your access to {group} has been refunded, so your "
            "access is cancelled and your join link has been revoked.\n\n"
            "If this is a mistake or you want to join again, write to us."
        ),
    },

    "refund.dispute_notice": {
        "es": (
            "⚠️ Acceso suspendido\n\n"
            "Tu banco ha abierto una reclamación sobre el pago de tu acceso a "
            "{group}, así que el acceso queda suspendido mientras se resuelve.\n\n"
            "Si ha sido un error, escríbenos y lo solucionamos."
        ),
        "en": (
            "⚠️ Access suspended\n\n"
            "Your bank has opened a dispute over the payment for your access to "
            "{group}, so the access is suspended while it is resolved.\n\n"
            "If this was a mistake, write to us and we will sort it out."
        ),
    },

    # El cobro salió bien y el acceso no se pudo conceder. No se le cuenta cuál
    # de los dos fallos internos ha sido —no le sirve de nada— sino lo único que
    # le importa: que el cobro consta, que no ha perdido el dinero y que hay
    # alguien mirándolo. Se distingue si se va a arreglar solo o no, porque decir
    # "espera" cuando hace falta una persona es hacerle perder la tarde.
    "purchase.incident_retrying": {
        "es": (
            "⏳ Cobro recibido, activando tu acceso\n\n"
            "Tu pago para {group} está registrado, pero se ha atascado al "
            "activar el acceso. Se está reintentando solo y lo normal es que se "
            "resuelva en unos minutos.\n\n"
            "No has perdido el dinero. Si en una hora sigues sin tu enlace, "
            "escríbenos y lo resolvemos a mano."
        ),
        "en": (
            "⏳ Payment received, activating your access\n\n"
            "Your payment for {group} is on record, but activating the access "
            "got stuck. It is retrying by itself and normally clears up within "
            "minutes.\n\n"
            "You have not lost your money. If you still have no link in an "
            "hour, message us and we will sort it out by hand."
        ),
    },

    "purchase.incident_manual": {
        "es": (
            "⏳ Cobro recibido, tu acceso necesita un momento\n\n"
            "Tu pago para {group} está registrado, pero hay un problema de "
            "configuración en la comunidad y el acceso no se puede activar "
            "solo.\n\n"
            "Ya hemos avisado a la persona responsable. No has perdido el "
            "dinero: te darán el acceso o te devolverán el pago. Si prefieres "
            "que lo miremos nosotros, escríbenos."
        ),
        "en": (
            "⏳ Payment received, your access needs a moment\n\n"
            "Your payment for {group} is on record, but there is a "
            "configuration problem in the community and the access cannot be "
            "activated automatically.\n\n"
            "The person in charge has already been notified. You have not lost "
            "your money: they will either grant the access or refund you. If "
            "you would rather we looked into it, message us."
        ),
    },

    # Ha pagado alguien con el acceso vetado. Se le ha cobrado, así que hay que
    # decírselo: cobrarle y callar es lo peor de las dos opciones. No se le da
    # ningún motivo del veto, que es cosa de la comunidad, pero sí la salida.
    "purchase.incident_banned": {
        "es": (
            "⏳ Cobro recibido, pero no podemos darte acceso\n\n"
            "Tu pago para {group} está registrado. No podemos activarte el "
            "acceso porque tu entrada a esta comunidad está vetada.\n\n"
            "No te quedes con el cargo: ya hemos avisado a la persona "
            "responsable para que te devuelva el pago. Escríbenos si quieres "
            "que lo sigamos nosotros."
        ),
        "en": (
            "⏳ Payment received, but we cannot give you access\n\n"
            "Your payment for {group} is on record. We cannot activate your "
            "access because you are barred from this community.\n\n"
            "You should not be left out of pocket: the person in charge has "
            "already been notified so they can refund you. Message us if you "
            "want us to follow it up."
        ),
    },

    "purchase.link_pending_title": {
        "es": "✅ Pago confirmado — falta darte el enlace",
        "en": "✅ Payment confirmed — your link is still pending",
    },

    "purchase.link_pending_body": {
        "es": (
            "Tu pago está registrado y tu acceso a {group} ya está activo, pero "
            "no he podido generar el enlace de entrada en este momento."
        ),
        "en": (
            "Your payment is registered and your access to {group} is already "
            "active, but I could not generate the join link right now."
        ),
    },

    "purchase.link_pending_what_now": {
        "es": (
            "Prueba a pedirlo con el botón de abajo. Si tampoco sale, ya hemos "
            "avisado al responsable de la comunidad y lo resolvemos: no has "
            "perdido el dinero ni el acceso."
        ),
        "en": (
            "Try the button below to request it. If that fails too, the "
            "community's owner has already been notified and we will sort it "
            "out: you have not lost your money or your access."
        ),
    },

    # Se rechaza la compra antes de cobrar, porque el bot ha perdido el permiso
    # de invitar y el enlace de acceso no se podría crear. Se le dice sin echarle
    # la culpa a nadie y sin dejarle con la sensación de que el bot está roto.
    # Tiene el acceso pagado y activo, pero el enlace no se puede crear ahora
    # mismo. Antes se le decía «asegúrate de que el bot es administrador del grupo
    # y tiene permisos para invitar usuarios»: una instrucción interna, sobre un
    # grupo que no es suyo y donde no puede tocar nada.
    "access.link_unavailable": {
        "es": (
            "⏳ Tu acceso está activo, pero el enlace no sale ahora mismo\n\n"
            "No es cosa tuya y no has perdido nada: {group} tiene un problema de "
            "configuración que impide crear enlaces de entrada.\n\n"
            "Ya hemos avisado a la persona responsable. Vuelve a pulsar «Pedir mi "
            "enlace» en un rato, o escríbenos y te avisamos en cuanto se arregle."
        ),
        "en": (
            "⏳ Your access is active, but the link will not generate right now\n\n"
            "This is not on you and you have not lost anything: {group} has a "
            "configuration problem that stops entry links from being created.\n\n"
            "The person in charge has already been notified. Try “Get my link” "
            "again in a while, or message us and we will tell you as soon as it "
            "is fixed."
        ),
    },

    "purchase.cannot_deliver": {
        "es": (
            "⏸ Ahora mismo no se puede entrar en {group}\n\n"
            "La comunidad tiene la entrada cerrada por un problema de "
            "configuración, así que no te cobramos: pagar sin poder entrar sería "
            "peor.\n\n"
            "Ya hemos avisado a la persona responsable. Inténtalo de nuevo más "
            "tarde y, si tienes prisa, escríbenos y te avisamos en cuanto se "
            "arregle."
        ),
        "en": (
            "⏸ Joining {group} is not possible right now\n\n"
            "The community's entrance is closed because of a configuration "
            "problem, so we are not charging you: paying without being able to "
            "get in would be worse.\n\n"
            "The person in charge has already been notified. Try again later, "
            "and if you are in a hurry just message us and we will tell you as "
            "soon as it is fixed."
        ),
    },

    "button.get_my_link": {
        "es": "🔗 Pedir mi enlace",
        "en": "🔗 Get my link",
    },

    "purchase.keep_this": {
        "es": "Guarda este mensaje: aquí tienes tu acceso y con quién hablar.",
        "en": "Keep this message: it has your access and who to talk to.",
    },

    "button.my_access_now": {
        "es": "🎟 Mis accesos",
        "en": "🎟 My accesses",
    },

    # Aviso a quien abrió la ficha de una comunidad y no compró. Entre "nunca ha
    # comprado nada" y "empezó a pagar" quedaba este hueco, que es el de más
    # intención de compra de los tres.

    "interest.title": {
        "es": "👀 ¿Te quedaste con la duda?",
        "en": "👀 Still thinking about it?",
    },

    "interest.body": {
        "es": "Estuviste viendo {group} y no llegaste a entrar.",
        "en": "You were looking at {group} and did not join.",
    },

    "interest.price": {
        "es": "El acceso sigue disponible desde {price}.",
        "en": "Access is still available from {price}.",
    },

    "interest.footer": {
        "es": (
            "Recibes tu enlace de entrada al instante tras el pago, y es "
            "personal y de un solo uso."
        ),
        "en": (
            "You get your access link instantly after paying, and it is "
            "personal and single-use."
        ),
    },

    "interest.opt_out": {
        "es": "Si no te interesa, dile al botón de abajo y no te escribo más.",
        "en": "Not interested? Use the button below and I won't write again.",
    },

    "button.see_access": {
        "es": "💳 Ver el acceso",
        "en": "💳 See the access",
    },

    "button.no_more_messages": {
        "es": "🔕 No me escribas más",
        "en": "🔕 Stop writing to me",
    },

    "renewal.expired_title": {
        "es": "⌛ Tu acceso ha caducado",
        "en": "⌛ Your access has expired",
    },

    "renewal.expired_body": {
        "es": "Se ha terminado tu acceso a {group}.",
        "en": "Your access to {group} has ended.",
    },

    "renewal.expired_price": {
        "es": "Puedes volver a entrar desde {price}.",
        "en": "You can join again from {price}.",
    },

    "renewal.expired_no_price": {
        "es": "Puedes volver a entrar cuando quieras.",
        "en": "You can join again whenever you like.",
    },

    "renewal.expired_footer": {
        "es": "Recuperas el acceso al instante tras el pago.",
        "en": "You get your access back instantly after paying.",
    },

    # Recuperar al que se fue. Va a alguien que ya NO es cliente, así que el tono
    # es distinto del aviso de renovación: sin urgencia falsa, sin reprocharle
    # nada, y con la puerta abierta para decir que no quiere más mensajes.
    "renewal.renewed": {
        "es": (
            "✅ Suscripción renovada\n\n"
            "Tu acceso a {group} sigue activo hasta el {until}.\n\n"
            "No tienes que hacer nada: se renovará solo. Puedes desactivar la "
            "renovación cuando quieras desde «Mis suscripciones»."
        ),
        "en": (
            "✅ Subscription renewed\n\n"
            "Your access to {group} is active until {until}.\n\n"
            "Nothing to do on your side: it renews itself. You can turn "
            "auto-renewal off any time from \"My subscriptions\"."
        ),
    },

    "renewal.renewed_priced": {
        "es": (
            "✅ Suscripción renovada\n\n"
            "🧾 Cobro: {price}\n"
            "Tu acceso a {group} sigue activo hasta el {until}.\n\n"
            "No tienes que hacer nada: se renovará solo. Puedes desactivar la "
            "renovación cuando quieras desde «Mis suscripciones»."
        ),
        "en": (
            "✅ Subscription renewed\n\n"
            "🧾 Charged: {price}\n"
            "Your access to {group} is active until {until}.\n\n"
            "Nothing to do on your side: it renews itself. You can turn "
            "auto-renewal off any time from \"My subscriptions\"."
        ),
    },

    "renewal.upsell_annual": {
        "es": (
            "⭐ Un gracias por quedarte\n\n"
            "Llevas ya varios meses en {group}. Su plan ANUAL sale por "
            "{price} — un {saving}% menos que pagar 12 meses a tu precio "
            "actual.\n\n"
            "Si te pasas, tu suscripción mensual se apaga sola al final del "
            "periodo ya pagado: sin cobros dobles y sin hacer nada más. Esta "
            "oferta solo aparece una vez."
        ),
        "en": (
            "⭐ A thank-you for staying\n\n"
            "You have been in {group} for months now. Its ANNUAL plan costs "
            "{price} — {saving}% less than paying 12 months at your current "
            "price.\n\n"
            "If you switch, your monthly subscription turns itself off at the "
            "end of the period you already paid: no double charges, nothing "
            "else to do. This offer only shows once."
        ),
    },

    "renewal.upsell_annual_button": {
        "es": "⭐ Ver el plan anual",
        "en": "⭐ See the annual plan",
    },

    "mysub.btn_receipts": {
        "es": "🧾 Mis pagos",
        "en": "🧾 My payments",
    },

    "mysub.btn_invite": {
        "es": "🎁 Invita y ganáis días",
        "en": "🎁 Invite a friend, both win days",
    },

    "mysub.btn_switch": {
        "es": "🔀 Cambiar de plan",
        "en": "🔀 Switch plan",
    },

    "mysub.switch_empty": {
        "es": (
            "🔀 En {group} no hay ahora mismo otro plan al que cambiarte.\n\n"
            "Si te interesa una duración distinta, dínoslo: se la pedimos a "
            "quien lleva la comunidad."
        ),
        "en": (
            "🔀 There's no other plan to switch to in {group} right now.\n\n"
            "If you'd like a different duration, tell us and we'll ask the "
            "community owner."
        ),
    },

    "mysub.switch_paypal": {
        "es": (
            "🔀 Tu suscripción de {group} se cobra por PayPal, y ahí el "
            "cambio de plan no puede ser automático: quedarían dos "
            "suscripciones cobrando a la vez.\n\n"
            "Hazlo en este orden y no pierdes nada: primero apaga la "
            "renovación desde esta misma pantalla —tu acceso sigue hasta el "
            "final del periodo pagado— y después elige el plan nuevo."
        ),
        "en": (
            "🔀 Your {group} subscription is charged through PayPal, where "
            "switching plans can't be automatic: you'd end up with two "
            "subscriptions charging at once.\n\n"
            "Do it in this order and you lose nothing: first turn off "
            "renewal on this screen — your access runs to the end of the "
            "period you already paid for — then pick the new plan."
        ),
    },

    "mysub.switch_no_access": {
        "es": (
            "🔀 El cambio de plan es para quien ya tiene acceso a {group}.\n\n"
            "Si tu acceso ha caducado, entra como una compra normal: ahí "
            "eliges el plan que quieras."
        ),
        "en": (
            "🔀 Switching plans is for members who already have access to "
            "{group}.\n\n"
            "If your access has expired, come in as a normal purchase — "
            "you'll pick whichever plan you want there."
        ),
    },

    "mysub.invite_text": {
        "es": (
            "🎁 Invita a {group} y ganáis días los dos\n\n"
            "Comparte tu enlace personal. Cuando quien entre por él pague, "
            "se os suman {days} días de acceso a cada uno — automáticamente, "
            "sin códigos ni avisos.\n\n"
            "{link}\n\n"
            "Invitados: {invited} · han pagado: {converted} · "
            "días ganados: {earned}"
        ),
        "en": (
            "🎁 Invite friends to {group} and you both win days\n\n"
            "Share your personal link. When someone who joins through it "
            "pays, you each get {days} extra days of access — automatically, "
            "no codes, no reminders.\n\n"
            "{link}\n\n"
            "Invited: {invited} · paid: {converted} · days earned: {earned}"
        ),
    },

    "refund.done": {
        "es": (
            "💸 Te hemos devuelto {amount} de tu pago en {group}.\n\n"
            "El abono aparece en tu método de pago en unos días, según tu "
            "banco. Si esperabas otra cosa, escríbenos y lo miramos."
        ),
        "en": (
            "💸 We've refunded {amount} from your payment in {group}.\n\n"
            "The credit shows up on your payment method within a few days, "
            "depending on your bank. If you expected something else, write to "
            "us and we'll look into it."
        ),
    },

    "incident.repaired": {
        "es": (
            "✅ Ya está: tu acceso a {group} está activo.\n\n"
            "Hubo un problema técnico al entregarlo después de tu pago y ya "
            "se ha resuelto. Gracias por la paciencia — aquí tienes tu enlace "
            "de entrada."
        ),
        "en": (
            "✅ All set: your access to {group} is active.\n\n"
            "There was a technical problem delivering it after your payment "
            "and it's now resolved. Thanks for your patience — here's your "
            "entry link."
        ),
    },

    "incident.repaired_button": {
        "es": "🔗 Entrar ahora",
        "en": "🔗 Come in now",
    },

    "recovery.left_with_access_until": {
        "es": (
            "👋 Ya no estás en {group}, pero tu acceso sigue activo hasta el "
            "{until}.\n\n"
            "Si ha sido un error —a veces es un toque de más en el móvil, o "
            "una limpieza de miembros mal apuntada—, aquí tienes tu enlace de "
            "entrada. Es de un solo uso y vale 24 horas."
        ),
        "en": (
            "👋 You're no longer in {group}, but your access is still active "
            "until {until}.\n\n"
            "If that was a mistake — sometimes it's one tap too many, or a "
            "member cleanup that hit the wrong person — here's your entry "
            "link. Single use, valid for 24 hours."
        ),
    },

    "recovery.left_with_access": {
        "es": (
            "👋 Ya no estás en {group}, pero tu acceso sigue activo.\n\n"
            "Si ha sido un error, aquí tienes tu enlace de entrada. Es de un "
            "solo uso y vale 24 horas."
        ),
        "en": (
            "👋 You're no longer in {group}, but your access is still "
            "active.\n\n"
            "If that was a mistake, here's your entry link. Single use, valid "
            "for 24 hours."
        ),
    },

    "recovery.delivery_fixed": {
        "es": (
            "✅ Ya puedes entrar en {group}.\n\n"
            "Hubo un problema para crear tu enlace de acceso y ya está "
            "resuelto. Tu acceso nunca dejó de estar activo — aquí tienes tu "
            "enlace, de un solo uso y válido 24 horas."
        ),
        "en": (
            "✅ You can come into {group} now.\n\n"
            "There was a problem creating your access link and it's now "
            "fixed. Your access never stopped being active — here's your "
            "link, single use and valid for 24 hours."
        ),
    },

    "recovery.return_button": {
        "es": "🔗 Volver a entrar",
        "en": "🔗 Come back in",
    },

    "referral.landing": {
        "es": (
            "👋 Te han invitado a {group}.\n\n"
            "Si entras por esta invitación, tú y quien te invitó ganáis días "
            "de acceso extra en cuanto completes tu suscripción."
        ),
        "en": (
            "👋 You've been invited to {group}.\n\n"
            "Join through this invitation and both you and your friend get "
            "extra days of access as soon as your subscription is complete."
        ),
    },

    "referral.landing_button": {
        "es": "👀 Ver la comunidad",
        "en": "👀 See the community",
    },

    "referral.referrer_rewarded": {
        "es": (
            "🎁 Tu invitación funcionó: alguien acaba de entrar en {group} "
            "por tu enlace.\n\n"
            "Te hemos sumado {days} días de acceso. Gracias por traer gente "
            "buena."
        ),
        "en": (
            "🎁 Your invitation worked: someone just joined {group} through "
            "your link.\n\n"
            "We've added {days} days of access to your subscription. Thanks "
            "for bringing good people in."
        ),
    },

    "referral.invited_rewarded": {
        "es": (
            "🎁 Por entrar en {group} con la invitación de un miembro, te "
            "hemos sumado {days} días de acceso extra.\n\n"
            "Y tú también tienes tu enlace para invitar: está en «Mis "
            "accesos»."
        ),
        "en": (
            "🎁 For joining {group} through a member's invitation, we've "
            "added {days} extra days of access.\n\n"
            "You have your own invite link too — it's in \"My access\"."
        ),
    },

    "mysub.receipts_title": {
        "es": "🧾 Tus pagos de {group}",
        "en": "🧾 Your payments for {group}",
    },

    "mysub.receipts_empty": {
        "es": "Todavía no hay pagos registrados aquí.",
        "en": "No payments recorded here yet.",
    },

    "mysub.receipts_footer": {
        "es": "Si algo no cuadra, escríbenos antes que a tu banco: se "
              "resuelve más rápido y sin disputas.",
        "en": "If something looks off, write to us before your bank: it gets "
              "solved faster and without disputes.",
    },

    "renewal.payment_failed_retry": {
        "es": (
            "⚠️ Seguimos sin poder cobrar tu renovación de {group}.\n\n"
            "Tu acceso está activo, pero el próximo intento es el {date} y "
            "los intentos se acaban. Cambia la tarjeta con el botón y lo "
            "resolvemos hoy."
        ),
        "en": (
            "⚠️ We still cannot charge your renewal for {group}.\n\n"
            "Your access is active, but the next attempt is on {date} and the "
            "attempts run out. Update your card with the button and let's fix "
            "this today."
        ),
    },

    "renewal.payment_failed_last": {
        "es": (
            "🚨 Último aviso: no hemos podido cobrar tu renovación de {group} "
            "y ya no habrá más intentos.\n\n"
            "Si no actualizas la tarjeta, perderás el acceso al terminar el "
            "periodo que ya tenías pagado. Se arregla en un toque."
        ),
        "en": (
            "🚨 Final notice: we could not charge your renewal for {group} "
            "and there will be no further attempts.\n\n"
            "If you don't update your card you'll lose access when the period "
            "you already paid for ends. It takes one tap to fix."
        ),
    },

    "renewal.ended_unpaid": {
        "es": (
            "😔 Tu suscripción a {group} se ha cerrado porque no pudimos "
            "cobrar la renovación.\n\n"
            "No hace falta escribirle a nadie: puedes volver cuando quieras "
            "desde el botón, con la tarjeta que prefieras."
        ),
        "en": (
            "😔 Your subscription to {group} has closed because we couldn't "
            "charge the renewal.\n\n"
            "No need to contact anyone: come back whenever you like using the "
            "button, with whichever card you prefer."
        ),
    },

    "renewal.ended_unpaid_button": {
        "es": "🔄 Volver a suscribirme",
        "en": "🔄 Subscribe again",
    },

    "renewal.payment_failed": {
        "es": (
            "⚠️ No hemos podido cobrar tu renovación de {group}.\n\n"
            "Tu acceso sigue activo y lo reintentaremos automáticamente en los "
            "próximos días. Lo más habitual es que la tarjeta haya caducado o "
            "no tenga saldo: revísala para no perder el acceso."
        ),
        "en": (
            "⚠️ We could not charge your renewal for {group}.\n\n"
            "Your access is still active and we will retry automatically over "
            "the next few days. Usually the card expired or has no funds: "
            "please check it so you do not lose access."
        ),
    },

    "renewal.cancelled_at_period_end": {
        "es": (
            "🔕 Renovación automática desactivada.\n\n"
            "Tu acceso a {group} sigue activo hasta el {until}: ese periodo ya "
            "está pagado y no se toca. No se te volverá a cobrar.\n\n"
            "Si cambias de idea, puedes reactivarla desde «Mis suscripciones» "
            "hasta el último día."
        ),
        "en": (
            "🔕 Auto-renewal turned off.\n\n"
            "Your access to {group} stays active until {until}: that period is "
            "already paid and stays yours. You will not be charged again.\n\n"
            "If you change your mind you can turn it back on from "
            "\"My subscriptions\" until the last day."
        ),
    },

    "renewal.reactivated": {
        "es": (
            "🔔 Renovación automática reactivada.\n\n"
            "Tu acceso a {group} se renovará solo al final de cada periodo, "
            "como antes."
        ),
        "en": (
            "🔔 Auto-renewal turned back on.\n\n"
            "Your access to {group} will renew itself at the end of each "
            "period, as before."
        ),
    },

    "start.paid_landing": {
        "es": (
            "✅ Pago recibido — bienvenido a {group}.\n\n"
            "Tu enlace de acceso te está esperando: pulsa el botón y entra."
        ),
        "en": (
            "✅ Payment received — welcome to {group}.\n\n"
            "Your access link is waiting: tap the button and come in."
        ),
    },

    "start.paid_button": {
        "es": "🔗 Recibir mi acceso",
        "en": "🔗 Get my access",
    },

    "start.cancelled_landing": {
        "es": (
            "El pago de {group} se quedó a medias.\n\n"
            "Si fue un despiste, lo retomas en un toque. Y si algo falló, "
            "cuéntanoslo y lo miramos."
        ),
        "en": (
            "Your payment for {group} was left halfway.\n\n"
            "If it was an accident, you can pick it up in one tap. And if "
            "something went wrong, tell us and we will look into it."
        ),
    },

    "start.retry_button": {
        "es": "💳 Retomar el pago",
        "en": "💳 Resume payment",
    },

    "start.problem_button": {
        "es": "💬 Tuve un problema",
        "en": "💬 I had a problem",
    },

    "abandoned.discount_title": {
        "es": "🎁 Un empujón para terminar",
        "en": "🎁 A little push to finish",
    },

    "abandoned.discount_body": {
        "es": (
            "Dejaste a medias tu compra de {group}. Termínala hoy con un "
            "{percent}% de descuento: teclea el código {code} en el pago "
            "con tarjeta."
        ),
        "en": (
            "You left your purchase of {group} halfway. Finish it today with "
            "{percent}% off: type the code {code} at the card checkout."
        ),
    },

    "abandoned.discount_expiry": {
        "es": "El código es solo tuyo y caduca en 24 horas.",
        "en": "The code is yours alone and expires in 24 hours.",
    },

    # =========================
    # «MIS ACCESOS» — el camino del comprador, en su idioma.
    # Los textos en español son BYTE A BYTE los literales que había: el golden
    # master con 0 diferencias es la prueba de que ningún usuario español nota
    # el cambio.
    # =========================

    "mysub.screen": {
        "es": (
            "📦 {group}\n\n"
            "{intro}"
            "⏳ Tiempo restante:\n"
            "{remaining}\n\n"
            "{renewal}"
            "⏱ El enlace vale {validity} "
            "y solo lo puedes usar tú, una vez.\n"
            "Si caduca, pide otro con el botón de abajo.\n\n"
            "🔗 Tu nuevo acceso:\n"
            "{link}"
        ),
        "en": (
            "📦 {group}\n\n"
            "{intro}"
            "⏳ Time left:\n"
            "{remaining}\n\n"
            "{renewal}"
            "⏱ The link is valid for {validity} "
            "and only you can use it, once.\n"
            "If it expires, ask for another with the button below.\n\n"
            "🔗 Your new access:\n"
            "{link}"
        ),
    },

    "mysub.permanent_intro": {
        "es": "✅ Tienes acceso permanente activo a este {kind}.\n\n",
        "en": "✅ You have permanent active access to this {kind}.\n\n",
    },

    "mysub.renewal_active": {
        "es": (
            "🔁 Renovación automática: activa. Se renueva sola al "
            "final de cada periodo.\n\n"
        ),
        "en": (
            "🔁 Auto-renewal: on. It renews itself at the end of each "
            "period.\n\n"
        ),
    },

    "mysub.renewal_off": {
        "es": (
            "🔕 Renovación automática: desactivada. Tu acceso termina "
            "al final del periodo ya pagado.\n\n"
        ),
        "en": (
            "🔕 Auto-renewal: off. Your access ends when the period you "
            "already paid finishes.\n\n"
        ),
    },

    "mysub.renewal_pp_active": {
        "es": (
            "🔁 Renovación automática (PayPal): activa. Se renueva "
            "sola al final de cada periodo.\n\n"
        ),
        "en": (
            "🔁 Auto-renewal (PayPal): on. It renews itself at the end of "
            "each period.\n\n"
        ),
    },

    "mysub.renewal_pp_off": {
        "es": (
            "🔕 Renovación automática: desactivada. Tu acceso llega "
            "hasta el final del periodo ya pagado; para volver "
            "después, suscríbete de nuevo.\n\n"
        ),
        "en": (
            "🔕 Auto-renewal: off. Your access runs until the end of the "
            "period you already paid; to come back later, subscribe "
            "again.\n\n"
        ),
    },

    "mysub.btn_another_link": {
        "es": "🔄 Enviarme otro enlace",
        "en": "🔄 Send me another link",
    },

    "mysub.btn_help": {
        "es": "💬 Ayuda sobre este menú",
        "en": "💬 Help with this menu",
    },

    "mysub.btn_back": {
        "es": "⬅️ Volver",
        "en": "⬅️ Back",
    },

    "mysub.btn_back_access": {
        "es": "⬅️ Volver a mi acceso",
        "en": "⬅️ Back to my access",
    },

    "mysub.btn_renew_on": {
        "es": "🔔 Reactivar renovación",
        "en": "🔔 Turn auto-renewal back on",
    },

    "mysub.btn_renew_off": {
        "es": "🔕 Desactivar renovación",
        "en": "🔕 Turn off auto-renewal",
    },

    "mysub.btn_yes_off": {
        "es": "Sí, desactivar",
        "en": "Yes, turn it off",
    },

    "mysub.save_offer": {
        "es": (
            "🎁 Antes de que te vayas…\n\n"
            "¿Y si te quedas con un {percent}% de descuento en tu PRÓXIMO "
            "cobro de {group}?\n\n"
            "Un solo toque, se aplica solo, y los cobros siguientes van a tu "
            "precio de siempre. Esta oferta solo aparece una vez."
        ),
        "en": (
            "🎁 Before you go…\n\n"
            "What if you stayed with {percent}% off your NEXT charge for "
            "{group}?\n\n"
            "One tap, it applies itself, and later charges stay at your usual "
            "price. This offer only shows once."
        ),
    },

    "mysub.save_offer_btn_take": {
        "es": "🎁 Quedarme con el descuento",
        "en": "🎁 Stay with the discount",
    },

    "mysub.save_offer_btn_leave": {
        "es": "Seguir con la cancelación",
        "en": "Continue cancelling",
    },

    "mysub.pause_btn": {
        "es": "⏸ Pausar 1 mes",
        "en": "⏸ Pause for 1 month",
    },

    "mysub.pause_done": {
        "es": (
            "⏸ Renovación en pausa.\n\n"
            "Durante un mes no se te cobrará nada. Tu acceso sigue hasta el "
            "final del periodo ya pagado, y los cobros (y tu acceso) vuelven "
            "solos al acabar la pausa — sin hacer nada.\n\n"
            "Si quieres volver antes, reanuda desde esta misma pantalla."
        ),
        "en": (
            "⏸ Renewal paused.\n\n"
            "For one month you will not be charged. Your access runs until "
            "the end of the period you already paid, and charges (and your "
            "access) come back on their own when the pause ends — nothing to "
            "do.\n\n"
            "If you want to come back sooner, resume from this same screen."
        ),
    },

    "mysub.pause_error": {
        "es": (
            "❌ No he podido pausar la renovación ahora mismo. "
            "Inténtalo de nuevo en un momento."
        ),
        "en": (
            "❌ I could not pause the renewal right now. "
            "Please try again in a moment."
        ),
    },

    "mysub.renewal_paused_line": {
        "es": (
            "⏸ Renovación automática: en pausa. No se te cobra nada y los "
            "cobros vuelven solos el {until}.\n\n"
        ),
        "en": (
            "⏸ Auto-renewal: paused. You are not being charged and billing "
            "resumes on its own on {until}.\n\n"
        ),
    },

    "mysub.resume_btn": {
        "es": "▶️ Reanudar renovación",
        "en": "▶️ Resume renewal",
    },

    "mysub.resume_done": {
        "es": (
            "▶️ Renovación reanudada: los cobros vuelven en tu siguiente "
            "ciclo, como antes de la pausa."
        ),
        "en": (
            "▶️ Renewal resumed: charges return on your next cycle, as "
            "before the pause."
        ),
    },

    "mysub.save_offer_done": {
        "es": (
            "🎉 Hecho: tu próximo cobro de {group} saldrá con un {percent}% "
            "de descuento.\n\n"
            "Tu renovación sigue activa y no tienes que hacer nada más."
        ),
        "en": (
            "🎉 Done: your next charge for {group} will carry {percent}% "
            "off.\n\n"
            "Your renewal stays active and there is nothing else to do."
        ),
    },

    "mysub.save_offer_error": {
        "es": (
            "❌ No he podido aplicar el descuento ahora mismo. Tu renovación "
            "sigue como estaba; puedes intentarlo de nuevo o continuar."
        ),
        "en": (
            "❌ I could not apply the discount right now. Your renewal is "
            "unchanged; you can try again or continue."
        ),
    },

    "mysub.stoprenew_confirm": {
        "es": (
            "🔕 ¿Desactivar la renovación automática?\n\n"
            "El periodo que ya has pagado no se toca: tu acceso sigue hasta "
            "su final. Simplemente no habrá más cobros."
        ),
        "en": (
            "🔕 Turn off auto-renewal?\n\n"
            "The period you already paid is untouched: your access runs to "
            "its end. There simply will be no more charges."
        ),
    },

    "mysub.stoprenew_done": {
        "es": (
            "🔕 Hecho: no se te volverá a cobrar.\n\n"
            "Tu acceso sigue activo hasta el final del periodo ya "
            "pagado, y puedes reactivar la renovación desde esta "
            "misma pantalla hasta el último día."
        ),
        "en": (
            "🔕 Done: you will not be charged again.\n\n"
            "Your access stays active until the end of the period you "
            "already paid, and you can turn renewal back on from this same "
            "screen until the last day."
        ),
    },

    "mysub.renewon_done": {
        "es": (
            "🔔 Hecho: tu acceso volverá a renovarse solo al final "
            "de cada periodo."
        ),
        "en": (
            "🔔 Done: your access will renew itself again at the end of "
            "each period."
        ),
    },

    "mysub.pp_confirm": {
        "es": (
            "🔕 ¿Desactivar la renovación automática?\n\n"
            "El periodo que ya has pagado no se toca: tu acceso sigue hasta "
            "su final y no habrá más cobros.\n\n"
            "⚠️ En PayPal la cancelación es definitiva: no se puede "
            "reactivar. Si más adelante quieres volver, tendrás que "
            "suscribirte de nuevo."
        ),
        "en": (
            "🔕 Turn off auto-renewal?\n\n"
            "The period you already paid is untouched: your access runs to "
            "its end and there will be no more charges.\n\n"
            "⚠️ With PayPal, cancelling is final: it cannot be turned back "
            "on. If you want to come back later, you will have to subscribe "
            "again."
        ),
    },

    "mysub.pp_done": {
        "es": (
            "🔕 Hecho: no se te volverá a cobrar.\n\n"
            "Tu acceso sigue activo hasta el final del periodo ya "
            "pagado. En PayPal la cancelación es definitiva: si más "
            "adelante quieres volver, suscríbete de nuevo."
        ),
        "en": (
            "🔕 Done: you will not be charged again.\n\n"
            "Your access stays active until the end of the period you "
            "already paid. With PayPal, cancelling is final: if you want to "
            "come back later, subscribe again."
        ),
    },

    "mysub.toggle_error_off": {
        "es": (
            "❌ No he podido desactivar la renovación ahora mismo. "
            "Inténtalo de nuevo en un momento."
        ),
        "en": (
            "❌ I could not turn off the renewal right now. "
            "Please try again in a moment."
        ),
    },

    "mysub.toggle_error_on": {
        "es": (
            "❌ No he podido reactivar la renovación ahora mismo. "
            "Inténtalo de nuevo en un momento."
        ),
        "en": (
            "❌ I could not turn the renewal back on right now. "
            "Please try again in a moment."
        ),
    },

    "mysub.unavailable": {
        "es": "⚠️ Esta opción ya no está disponible o no está configurada.",
        "en": "⚠️ This option is no longer available or not configured.",
    },

    "mysub.not_found": {
        "es": "❌ No encuentro esa comunidad.",
        "en": "❌ I cannot find that community.",
    },

    "mysub.no_active": {
        "es": "No tienes una suscripción activa para este {kind}.",
        "en": "You do not have an active subscription for this {kind}.",
    },

    "mysub.load_error": {
        "es": (
            "❌ No he podido cargar tu acceso ahora mismo.\n\n"
            "Inténtalo otra vez en un momento. Si sigue igual, escríbenos."
        ),
        "en": (
            "❌ I could not load your access right now.\n\n"
            "Try again in a moment. If it keeps happening, write to us."
        ),
    },

    "renewal.upcoming_priced": {
        "es": (
            "🔔 Aviso de renovación\n\n"
            "Tu suscripción a {group} se renovará el {until} por {price}.\n\n"
            "No tienes que hacer nada para seguir. Si no quieres continuar, "
            "desactiva la renovación antes de esa fecha con el botón de abajo: "
            "conservarás el acceso hasta el final del periodo ya pagado."
        ),
        "en": (
            "🔔 Renewal notice\n\n"
            "Your subscription to {group} will renew on {until} for {price}.\n\n"
            "Nothing to do if you want to stay. If not, turn off auto-renewal "
            "before that date with the button below: you keep access until the "
            "end of the period you already paid."
        ),
    },

    "renewal.upcoming": {
        "es": (
            "🔔 Aviso de renovación\n\n"
            "Tu suscripción a {group} se renovará el {until}.\n\n"
            "No tienes que hacer nada para seguir. Si no quieres continuar, "
            "desactiva la renovación antes de esa fecha con el botón de abajo."
        ),
        "en": (
            "🔔 Renewal notice\n\n"
            "Your subscription to {group} will renew on {until}.\n\n"
            "Nothing to do if you want to stay. If not, turn off auto-renewal "
            "before that date with the button below."
        ),
    },

    "renewal.upcoming_button": {
        "es": "⚙️ Gestionar mi suscripción",
        "en": "⚙️ Manage my subscription",
    },

    "renewal.update_card_button": {
        "es": "💳 Actualizar tarjeta",
        "en": "💳 Update card",
    },

    "renewal.cancelled_paypal": {
        "es": (
            "🔕 Renovación automática desactivada.\n\n"
            "Tu acceso a {group} sigue activo hasta el {until}: ese periodo ya "
            "está pagado y no se toca. No se te volverá a cobrar.\n\n"
            "En PayPal la cancelación es definitiva: si más adelante quieres "
            "volver, solo tienes que suscribirte de nuevo."
        ),
        "en": (
            "🔕 Auto-renewal turned off.\n\n"
            "Your access to {group} stays active until {until}: that period is "
            "already paid and stays yours. You will not be charged again.\n\n"
            "With PayPal, cancelling is final: if you want to come back later, "
            "just subscribe again."
        ),
    },

    "renewal.paused": {
        "es": (
            "⏸ Tu renovación de {group} está en pausa.\n\n"
            "Tu acceso sigue activo hasta el {until}. Revisa tu cuenta de "
            "PayPal para reanudarla si quieres seguir después de esa fecha."
        ),
        "en": (
            "⏸ Your renewal for {group} is paused.\n\n"
            "Your access is active until {until}. Check your PayPal account to "
            "resume it if you want to continue past that date."
        ),
    },

    "renewal.ended": {
        "es": (
            "👋 Tu suscripción a {group} ha terminado.\n\n"
            "Puedes volver cuando quieras: la comunidad sigue ahí y entrar de "
            "nuevo es un toque."
        ),
        "en": (
            "👋 Your subscription to {group} has ended.\n\n"
            "You can come back any time: the community is still there and "
            "rejoining takes one tap."
        ),
    },

    "winback.title": {
        "es": "👋 Te dejamos la puerta abierta",
        "en": "👋 The door is still open",
    },

    "winback.body": {
        "es": "{when} se te acabó el acceso a {group}, y no has vuelto.",
        "en": "Your access to {group} ran out {when}, and you have not come back.",
    },

    "winback.since_week": {
        "es": "Hace una semana",
        "en": "a week ago",
    },

    "winback.since_month": {
        "es": "Hace un mes",
        "en": "a month ago",
    },

    "winback.price": {
        "es": "Volver a entrar cuesta {price}.",
        "en": "Coming back costs {price}.",
    },

    "winback.footer": {
        "es": (
            "Si te sigue interesando, entras otra vez en un toque. Y si no, "
            "dilo con el último botón y no te volvemos a escribir."
        ),
        "en": (
            "If you are still interested, you can join again in one tap. And if "
            "not, say so with the last button and we will not write again."
        ),
    },

    "renewal.soon_title": {
        "es": "⏳ Tu acceso caduca pronto",
        "en": "⏳ Your access expires soon",
    },

    "renewal.early_title": {
        "es": "🔔 Aviso de renovación",
        "en": "🔔 Renewal reminder",
    },

    "renewal.body": {
        "es": "Tu acceso a {group} termina {when}.",
        "en": "Your access to {group} ends {when}.",
    },

    "renewal.price": {
        "es": "Renovar cuesta {price}.",
        "en": "Renewing costs {price}.",
    },

    "renewal.footer": {
        "es": (
            "Si renuevas antes de que caduque, no pierdes el acceso ni tienes "
            "que volver a entrar desde cero."
        ),
        "en": (
            "If you renew before it expires you keep your access and do not "
            "have to start over."
        ),
    },

    "validity.hours": {
        "es": "{hours} horas",
        "en": "{hours} hours",
    },

    "validity.one_hour": {
        "es": "1 hora",
        "en": "1 hour",
    },

    "validity.minutes": {
        "es": "{minutes} minutos",
        "en": "{minutes} minutes",
    },

    "validity.one_minute": {
        "es": "1 minuto",
        "en": "1 minute",
    },

    "time.under_an_hour": {
        "es": "en menos de una hora",
        "en": "in less than an hour",
    },

    "time.very_soon": {
        "es": "muy pronto",
        "en": "very soon",
    },

    "time.in_hours": {
        "es": "en {hours} horas",
        "en": "in {hours} hours",
    },

    "time.in_one_day": {
        "es": "en 1 día",
        "en": "in 1 day",
    },

    "time.in_days": {
        "es": "en {days} días",
        "en": "in {days} days",
    },

    # El español es exactamente el texto que ya se enviaba: traducir no debe
    # cambiar de paso los mensajes que los clientes españoles ya reciben.

    "abandoned.title": {
        "es": "🛒 ¿Te quedaste a medias?",
        "en": "🛒 Did you get interrupted?",
    },

    "abandoned.body": {
        "es": "Empezaste a entrar en {group} pero el pago no se completó.",
        "en": "You started joining {group} but the payment was not completed.",
    },

    "abandoned.price": {
        "es": "Sigue disponible desde {price}.",
        "en": "It is still available from {price}.",
    },

    "abandoned.footer": {
        "es": (
            "Puedes retomarlo desde donde lo dejaste: al confirmar el pago "
            "recibes tu enlace de acceso al instante."
        ),
        "en": (
            "You can pick up where you left off: as soon as the payment goes "
            "through you get your access link instantly."
        ),
    },

    "abandoned.help": {
        "es": "🛟 Si algo te dio problemas, escríbenos y lo miramos.",
        "en": "🛟 If something gave you trouble, write to us and we'll look into it.",
    },

    "button.resume_payment": {
        "es": "💳 Retomar el pago",
        "en": "💳 Resume the payment",
    },

    "button.i_had_a_problem": {
        "es": "🛟 Tuve un problema",
        "en": "🛟 I had a problem",
    },

    "button.renew": {
        "es": "💳 Renovar mi acceso",
        "en": "💳 Renew my access",
    },

    "button.renew_same_plan": {
        "es": "⚡ Renovar {plan} — {price}",
        "en": "⚡ Renew {plan} — {price}",
    },

    "button.join_again": {
        "es": "🔓 Volver a entrar",
        "en": "🔓 Join again",
    },

    "button.finish_payment": {
        "es": "💳 Terminar mi compra",
        "en": "💳 Finish my purchase",
    },

    "button.my_accesses": {
        "es": "🎟 Mis accesos",
        "en": "🎟 My accesses",
    },

    "button.i_have_a_question": {
        "es": "🛟 Tengo una duda",
        "en": "🛟 I have a question",
    },

    "button.support": {
        "es": "🛟 Contactar soporte",
        "en": "🛟 Contact support",
    },

    "help.main_title": {
        "es": "📘 Manual del bot",
        "en": "📘 Bot manual",
        "pt": "📘 Manual do bot",
        "fr": "📘 Manuel du bot",
        "it": "📘 Manuale del bot"
    },

    "help.choose_section": {
        "es": "Elige una sección:",
        "en": "Choose a section:",
        "pt": "Escolhe uma secção:",
        "fr": "Choisis une section :",
        "it": "Scegli una sezione:"
    },

    "help.commands": {
        "es": "Comandos",
        "en": "Commands",
        "pt": "Comandos",
        "fr": "Commandes",
        "it": "Comandi"
    },

    "help.buttons": {
        "es": "Botones y opciones",
        "en": "Buttons and options",
        "pt": "Botões e opções",
        "fr": "Boutons et options",
        "it": "Pulsanti e opzioni"
    },

    "help.subscriptions": {
        "es": "Suscripciones",
        "en": "Subscriptions",
        "pt": "Subscrições",
        "fr": "Abonnements",
        "it": "Abbonamenti"
    },

    "help.ai": {
        "es": "IA del bot",
        "en": "Bot AI",
        "pt": "IA do bot",
        "fr": "IA du bot",
        "it": "IA del bot"
    },

    "help.admin": {
        "es": "Administración",
        "en": "Administration",
        "pt": "Administração",
        "fr": "Administration",
        "it": "Amministrazione"
    },

    "help.language": {
        "es": "Idioma",
        "en": "Language",
        "pt": "Idioma",
        "fr": "Langue",
        "it": "Lingua"
    },

    "help.back": {
        "es": "⬅️ Volver",
        "en": "⬅️ Back",
        "pt": "⬅️ Voltar",
        "fr": "⬅️ Retour",
        "it": "⬅️ Indietro"
    },

    "help.not_available": {
        "es": "Esta sección todavía no está disponible.",
        "en": "This section is not available yet.",
        "pt": "Esta secção ainda não está disponível.",
        "fr": "Cette section n'est pas encore disponible.",
        "it": "Questa sezione non è ancora disponibile."
    }
}


# =========================
# I18N SERVICE — TRANSLATE
# =========================

def t(key, language="es", **kwargs):

    language = normalize_language(language)

    translations = TRANSLATIONS.get(key)

    if not translations:

        return key


    text = translations.get(
        language,
        translations.get(DEFAULT_LANGUAGE, key)
    )


    if kwargs:

        try:

            return text.format(**kwargs)

        except Exception:

            return text


    return text
