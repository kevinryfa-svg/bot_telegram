"""
Los mensajes que recibe un cliente al pagar, en un solo sitio.

Existen dos caminos de cobro en el bot: el webhook de Stripe
(stripe_handler.py) y el camino compartido de los demás proveedores —PayPal,
Revolut, ChangeNOW y Guardarian— en payment_access_service.py. Cada uno tenía su
propio mensaje al comprador, y los dos habían quedado en la misma línea pelada:

    🔗 Tu acceso VIP:
    https://t.me/...

Sin confirmar el cobro, sin decir qué había comprado, cuánto duraba, ni a quién
preguntar. Y cuando el enlace no se podía crear, ninguno de los dos le decía
nada: el cliente pagaba y recibía silencio.

Estos textos viven aquí porque tener el mensaje más importante del bot duplicado
en dos ficheros es exactamente lo que hizo que uno se arreglara y el otro no.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n_service import DEFAULT_LANGUAGE, t
from invite_link_service import format_access_link_validity


def format_purchase_amount(amount, currency):
    """
    Importe tal y como se le muestra al cliente.

    Los proveedores mandan el importe en la unidad mínima (1500 = 15,00 EUR).
    """

    if amount is None:

        return "-"


    try:

        return f"{int(amount) / 100:.2f} {(currency or '').upper()}".strip()

    except Exception:

        return f"{amount} {(currency or '').upper()}".strip()


# =========================
# COMPRA COMPLETADA
# =========================

def build_purchase_confirmation_text(group_name, plan_name, amount_total,
                                     currency, expiration, expire_seconds,
                                     link, language=DEFAULT_LANGUAGE):
    """
    Mensaje de compra confirmada: lo lee alguien que acaba de pagar.

    Confirma el cobro, dice qué ha comprado y hasta cuándo, da el enlace con su
    validez real, y avisa de que es personal y de un solo uso.
    """

    lines = [
        t("purchase.title", language),
        "",
        t("purchase.community", language, group=group_name)
    ]


    if plan_name:

        lines.append(t("purchase.plan", language, plan=plan_name))


    if amount_total is not None:

        lines.append(
            t(
                "purchase.amount",
                language,
                amount=format_purchase_amount(amount_total, currency)
            )
        )


    lines.append("")

    if expiration is None:

        lines.append(t("purchase.permanent", language))

    else:

        try:

            fecha = expiration.strftime("%d/%m/%Y")

        except Exception:

            fecha = str(expiration)


        lines.append(t("purchase.until", language, date=fecha))


    lines.extend([
        "",
        t("purchase.link_title", language),
        str(link or ""),
        "",
        t(
            "purchase.link_validity",
            language,
            validity=format_access_link_validity(expire_seconds, language)
        ),
        "",
        t("purchase.keep_this", language)
    ])

    return "\n".join(lines)


def build_purchase_confirmation_keyboard(telegram_group_id, language=DEFAULT_LANGUAGE,
                                         group_id=None):
    """
    Botones del mensaje de compra: su acceso, invitar a alguien y soporte.

    Sin esto, alguien cuyo enlace fallara no tenía a dónde ir desde el propio
    mensaje del pago.

    EL BOTÓN DE INVITAR VA AQUÍ POR UN MOTIVO. El sistema de referidos existe
    desde hace tiempo —el que invita y el invitado se llevan días gratis cuando
    el segundo paga— pero vivía enterrado dentro de «Mis accesos», donde hay que
    ir a buscarlo. El único momento en que a alguien le apetece recomendar una
    comunidad es el minuto en que acaba de entrar, y ese minuto es este.
    """

    filas = [[InlineKeyboardButton(
        t("button.my_access_now", language),
        callback_data=f"mysub_{telegram_group_id}"
    )]]

    if group_id and telegram_group_id and _referidos_activos(group_id):

        # La MISMA pantalla que ya existe en «Mis accesos» (mysub_invite_...):
        # tiene su texto, sus estadísticas y su comprobación de que el
        # propietario no ha apagado el programa. Inventar aquí otro camino
        # habría sido una segunda pantalla que mantener y que se separaría.
        filas.append([InlineKeyboardButton(
            "🎁 Invitar y ganar días gratis",
            callback_data=f"mysub_invite_{telegram_group_id}"
        )])

    filas.append([InlineKeyboardButton(
        t("button.support", language),
        callback_data="public_support"
    )])

    return InlineKeyboardMarkup(filas)


def _referidos_activos(group_id):
    """¿Esta comunidad tiene los referidos encendidos? Nunca lanza.

    Un fallo mirando esto no puede impedir que alguien reciba el mensaje con su
    enlace de entrada: sin botón se vive, sin acceso no.
    """

    try:

        from referral_service import referrals_enabled_for_group

        return bool(referrals_enabled_for_group(group_id))

    except Exception as e:

        print("Compra: no se pudo mirar si hay referidos:", str(e)[:160])

        return False


# =========================
# COBRADO PERO SIN ENLACE
# =========================

def build_link_pending_text(group_name, plan_name, amount_total, currency,
                            language=DEFAULT_LANGUAGE):
    """
    Mensaje para cuando el cobro salió bien pero el enlace no se pudo crear.

    Antes este caso no enviaba nada al cliente: solo se avisaba a los
    administradores. Alguien que acababa de pagar se quedaba en silencio, que es
    exactamente cuando piensa que le han estafado.
    """

    lines = [
        t("purchase.link_pending_title", language),
        "",
        t("purchase.link_pending_body", language, group=group_name)
    ]


    if plan_name:

        lines.append("")
        lines.append(t("purchase.plan", language, plan=plan_name))


    if amount_total is not None:

        lines.append(
            t(
                "purchase.amount",
                language,
                amount=format_purchase_amount(amount_total, currency)
            )
        )


    lines.extend([
        "",
        t("purchase.link_pending_what_now", language)
    ])

    return "\n".join(lines)


def build_link_pending_keyboard(telegram_group_id, language=DEFAULT_LANGUAGE):
    """
    Pedir el enlace y soporte.

    El botón de pedir el enlace funciona porque el acceso se guarda aunque falle
    la entrega: es lo único que necesita el cliente para desbloquearse solo.
    """

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("button.get_my_link", language),
            callback_data=f"mysub_{telegram_group_id}"
        )],
        [InlineKeyboardButton(
            t("button.support", language),
            callback_data="public_support"
        )]
    ])


# =========================
# ELEGIR EL MENSAJE
# =========================

def build_buyer_message(group_name, plan_name, amount_total, currency,
                        expiration, expire_seconds, link,
                        telegram_group_id, language=DEFAULT_LANGUAGE,
                        group_id=None):
    """
    Devuelve (texto, teclado) según haya enlace o no.

    Los dos caminos de cobro llaman aquí, así que el cliente recibe lo mismo
    pague con Stripe o con cualquier otro proveedor.
    """

    if link:

        return (
            build_purchase_confirmation_text(
                group_name=group_name,
                plan_name=plan_name,
                amount_total=amount_total,
                currency=currency,
                expiration=expiration,
                expire_seconds=expire_seconds,
                link=link,
                language=language
            ),
            build_purchase_confirmation_keyboard(
                telegram_group_id,
                language=language,
                group_id=group_id
            )
        )


    return (
        build_link_pending_text(
            group_name=group_name,
            plan_name=plan_name,
            amount_total=amount_total,
            currency=currency,
            language=language
        ),
        build_link_pending_keyboard(
            telegram_group_id,
            language=language
        )
    )
