from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from db import conn
from audit_log_service import log_event
from bot_config import TOKEN
from code_flow_handler import (
    receive_code,
    get_group_id,
    format_tiempo_restante
)
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    revoke_telegram_invite_link
)
from publicity_invite_link_service import (
    authorize_existing_publicity_invite_link,
    normalize_telegram_invite_url
)
from rbac_helpers import (
    get_admin_group_ids,
    get_group_owner_user_id,
    has_group_permission,
    is_super_admin
)
from plan_payment_provider_helpers import (
    PLAN_PAYMENT_PROVIDER_PAYPAL,
    PLAN_PAYMENT_PROVIDER_STRIPE,
    format_plan_payment_provider,
    get_plan_provider_id_prompt,
    normalize_plan_payment_provider
)
from wizard_state_helpers import clear_plan_wizard_state
from stripe_catalog import create_stripe_product_and_price


GROUP_ADMIN_PERMISSION_OPTIONS = [
    ("view_users", "Ver usuarios", "can_view_users"),
    ("manage_users", "Gestionar usuarios", "can_manage_users"),
    ("kick_users", "Expulsar usuarios", "can_kick_users"),
    ("ban_users", "Banear usuarios", "can_ban_users"),
    ("unban_users", "Desbanear usuarios", "can_unban_users"),
    ("warn_users", "Dar warnings", "can_warn_users"),
    ("reset_warnings", "Resetear warnings", "can_reset_warnings"),
    ("manage_links", "Gestionar enlaces", "can_resend_links"),
    ("view_stats", "Ver estadísticas", "can_view_stats"),
    ("manage_plans", "Gestionar planes", "can_manage_plans"),
    ("edit_texts", "Editar textos del grupo", "can_edit_group_texts"),
    ("edit_preview", "Editar preview marketplace", "can_edit_marketplace_preview"),
    ("support", "Responder soporte del grupo", "can_respond_group_support"),
    ("view_logs", "Ver logs del grupo", "can_view_logs")
]


def revoke_link(chat_id, link):

    try:

        revoke_telegram_invite_link(
            TOKEN,
            chat_id,
            link
        )

    except Exception as e:

        print(
            "Error revoke_link:",
            e
        )


def fetch_publicity_input_group(group_id):

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id,
                   name,
                   telegram_group_id
            FROM groups
            WHERE id=%s
            LIMIT 1

        """, (group_id,))

        return cur.fetchone()


def user_can_authorize_publicity_invite_link(user_id, group_id):

    if is_super_admin(user_id) or get_group_owner_user_id(group_id) == user_id:

        return True


    return has_group_permission(user_id, group_id, "can_manage_groups")


def build_publicity_authorize_existing_back_keyboard(group_id):

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Volver al grupo de publicidad", callback_data=f"owner_publicity_group_{group_id}")],
        [InlineKeyboardButton("🏠 Inicio", callback_data="public_back_start")]
    ])


def is_public_t_me_username_link(invite_link):

    if not invite_link:

        return False


    suffix = invite_link.replace("https://t.me/", "", 1)

    return bool(suffix and not suffix.startswith("+") and not suffix.startswith("joinchat/"))


def lookup_group_admin_target_user(raw_text):

    raw_text = (raw_text or "").strip()


    if not raw_text:

        return None


    with conn.cursor() as cur:

        if raw_text.startswith("@"):

            username = raw_text[1:]

            cur.execute("""

                SELECT user_id,
                       username,
                       first_name
                FROM (
                    SELECT user_id, username, first_name
                    FROM users
                    WHERE username IS NOT NULL
                    UNION
                    SELECT user_id, username, first_name
                    FROM commercial_requests
                    WHERE username IS NOT NULL
                ) known_users
                WHERE LOWER(username)=LOWER(%s)
                LIMIT 1

            """, (username,))

        else:

            try:

                target_user_id = int(raw_text)

            except Exception:

                return None


            if target_user_id <= 0:

                return None


            cur.execute("""

                SELECT user_id,
                       username,
                       first_name
                FROM (
                    SELECT user_id, username, first_name
                    FROM users
                    WHERE user_id=%s
                    UNION
                    SELECT user_id, username, first_name
                    FROM commercial_requests
                    WHERE user_id=%s
                    UNION
                    SELECT user_id, NULL AS username, NULL AS first_name
                    FROM admins
                    WHERE user_id=%s
                ) known_users
                LIMIT 1

            """, (
                target_user_id,
                target_user_id,
                target_user_id
            ))


        row = cur.fetchone()


        if row:

            return row


        if not raw_text.startswith("@"):

            return target_user_id, None, None


        return None


def build_group_admin_back_keyboard():

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Volver",
            callback_data="group_admin_panel"
        )],
        [InlineKeyboardButton(
            "🏠 Inicio",
            callback_data="public_back_start"
        )]
    ])


def is_valid_plan_duration_days(duration_days):

    return 1 <= int(duration_days) <= 3650


def fetch_manageable_admin_groups(user_id):

    group_ids = get_admin_group_ids(
        user_id,
        ["can_manage_admins"]
    )


    with conn.cursor() as cur:

        if group_ids is None:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id
                FROM groups
                WHERE telegram_group_id != 0
                ORDER BY id ASC

            """)

        elif not group_ids:

            return []

        else:

            cur.execute("""

                SELECT id,
                       name,
                       telegram_group_id
                FROM groups
                WHERE telegram_group_id != 0
                AND id = ANY(%s)
                ORDER BY id ASC

            """, (group_ids,))


        return cur.fetchall()


def fetch_context_manageable_admin_groups(context, user_id):

    groups = fetch_manageable_admin_groups(user_id)
    selected_owner_group = context.user_data.get("selected_owner_group")


    if selected_owner_group:

        for group in groups:

            if int(group[0]) == int(selected_owner_group):

                return [group]


    return groups


def format_pending_group_admin_permissions(selected_permissions):

    lines = []


    for _key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        marker = "✅" if selected_permissions.get(permission) is True else "▫️"
        lines.append(f"{marker} {label}")


    return "\n".join(lines)


def build_pending_group_admin_permissions_keyboard(group_id, target_user_id, permissions):

    keyboard = []


    for key, label, permission in GROUP_ADMIN_PERMISSION_OPTIONS:

        marker = "✅" if permissions.get(permission) is True else "▫️"
        keyboard.append([InlineKeyboardButton(
            f"{marker} {label}",
            callback_data=f"gga_t_{group_id}_{target_user_id}_{key}"
        )])


    keyboard.append([InlineKeyboardButton(
        "💾 Guardar admin",
        callback_data=f"add_group_admin_save_{group_id}"
    )])
    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


def build_group_admin_add_group_keyboard(groups):

    keyboard = []


    for group_id, name, _telegram_group_id in groups:

        keyboard.append([InlineKeyboardButton(
            name or f"Grupo {group_id}",
            callback_data=f"add_group_admin_select_group_{group_id}"
        )])


    keyboard.append([InlineKeyboardButton(
        "⬅️ Volver",
        callback_data="group_admin_panel"
    )])

    return InlineKeyboardMarkup(keyboard)


async def receive_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("publicity_authorize_existing_group_id"):

        group_id = context.user_data.get("publicity_authorize_existing_group_id")
        user_id = update.effective_user.id
        raw_link = (update.message.text or "").strip()
        invite_link = normalize_telegram_invite_url(raw_link)


        if not user_can_authorize_publicity_invite_link(user_id, group_id):

            context.user_data.pop("publicity_authorize_existing_group_id", None)

            await update.message.reply_text(
                "⛔ No tienes permiso para autorizar links públicos de esta comunidad.",
                reply_markup=build_publicity_authorize_existing_back_keyboard(group_id)
            )

            return


        if not invite_link:

            log_event(
                "publicity_invite_existing_link_invalid",
                category="access",
                severity="warning",
                scope="group",
                group_id=group_id,
                actor_user_id=user_id,
                message="Intento de autorizar un link público de publicidad con formato inválido.",
                metadata={}
            )

            await update.message.reply_text(
                "⚠️ Ese texto no parece un link válido de Telegram. Pega un enlace que empiece por https://t.me/ o t.me/.",
                reply_markup=build_publicity_authorize_existing_back_keyboard(group_id)
            )

            return


        group = fetch_publicity_input_group(group_id)
        telegram_group_id = group[2] if group else None


        if not telegram_group_id:

            context.user_data.pop("publicity_authorize_existing_group_id", None)

            await update.message.reply_text(
                "⚠️ Esta comunidad no tiene telegram_group_id configurado.",
                reply_markup=build_publicity_authorize_existing_back_keyboard(group_id)
            )

            return


        saved = authorize_existing_publicity_invite_link(
            group_id,
            telegram_group_id,
            invite_link,
            user_id,
            label="Autorizado manualmente"
        )
        context.user_data.pop("publicity_authorize_existing_group_id", None)
        warning = (
            "\n\n⚠️ Si Telegram no informa este link en el evento de entrada, puede que el bot no pueda detectarlo. "
            "Para mayor fiabilidad se recomiendan enlaces tipo https://t.me/+... o https://t.me/joinchat/..."
        ) if is_public_t_me_username_link(invite_link) else ""


        if not saved:

            await update.message.reply_text(
                "❌ No he podido autorizar ese link ahora mismo.",
                reply_markup=build_publicity_authorize_existing_back_keyboard(group_id)
            )

            return


        await update.message.reply_text(
            (
                "✅ Link existente autorizado para publicidad.\n\n"
                "A partir de ahora, si Telegram informa ese link en la entrada al grupo, "
                "el bot no expulsará a los usuarios que entren por él."
                f"{warning}"
            ),
            reply_markup=build_publicity_authorize_existing_back_keyboard(group_id)
        )

        return


    # =========================
    # PRECIO DE PUBLICAR COMUNIDAD
    # =========================
    # Se pide EN EUROS a propósito. commercial_plans.amount va en céntimos, pero
    # nadie teclea «2900» pensando en 29 euros: pedir céntimos aquí es cómo se
    # publica un precio cien veces más bajo del que se quería. Y ojo, porque en
    # este mismo producto plans.amount SÍ va en unidades mayores: las dos
    # convenciones conviven, así que la conversión se hace donde se lee el texto.

    if context.user_data.get("setting_platform_plan_price_id"):

        plan_id = context.user_data.get("setting_platform_plan_price_id")

        from platform_plan_service import set_platform_plan_amount

        try:

            euros = float(str(text).strip().replace(",", "."))

        except (TypeError, ValueError):

            await update.message.reply_text(
                "❌ Eso no es un número. Escribe el precio en euros, por "
                "ejemplo 29 o 29,50."
            )

            return


        if euros <= 0:

            await update.message.reply_text(
                "❌ El precio tiene que ser mayor que cero. Si quieres que sea "
                "gratis, desactiva el plan en vez de ponerle 0."
            )

            return


        if euros > 10000:

            # Un tope alto pero tope: un dedazo de más ceros publicaría un
            # precio absurdo, y el primero que lo vea se va.
            await update.message.reply_text(
                "❌ Ese precio parece un error de tecleo (más de 10.000 EUR). "
                "Escríbelo otra vez si es correcto... o mejor revísalo."
            )

            return


        context.user_data["setting_platform_plan_price_id"] = None

        guardado = set_platform_plan_amount(plan_id, round(euros * 100))

        if not guardado:

            await update.message.reply_text(
                "❌ No he podido guardar ese precio. Vuelve a intentarlo."
            )

            return


        await update.message.reply_text(
            f"✅ Precio guardado: {euros:.2f}".replace(".", ",")
            + " EUR.\n\n"
            "Ya se puede pagar por publicar una comunidad con esa duración: el "
            "precio de Stripe se crea solo en la primera compra.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "💰 Ver los precios",
                callback_data="admin_platform_plan_prices"
            )]])
        )

        return


    if (
        context.user_data.get("configuring_owner_payment_provider")
        or context.user_data.get("configuring_platform_payment_provider")
    ):

        return


    if context.user_data.get("adding_group_admin"):

        text = update.message.text.strip()
        target = lookup_group_admin_target_user(text)


        if not target:

            await update.message.reply_text(
                "❌ Usuario no encontrado en la base de datos.\n\n"
                "Puedes enviar un user_id numérico válido o un @username que ya exista en la base.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        target_user_id, username, first_name = target


        if int(target_user_id) == int(update.effective_user.id):

            await update.message.reply_text(
                "❌ No puedes añadirte a ti mismo como admin.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        groups = fetch_context_manageable_admin_groups(
            context,
            update.effective_user.id
        )


        if not groups:

            context.user_data["adding_group_admin"] = False

            await update.message.reply_text(
                "⛔ No tienes permiso para realizar esta acción en esta comunidad.",
                reply_markup=build_group_admin_back_keyboard()
            )

            return


        context.user_data["group_admin_target_user_id"] = target_user_id
        context.user_data["group_admin_target_display"] = (
            f"@{username}" if username else first_name or str(target_user_id)
        )
        context.user_data["adding_group_admin"] = False


        if len(groups) > 1:

            await update.message.reply_text(
                "Selecciona la comunidad donde quieres añadir este admin.",
                reply_markup=build_group_admin_add_group_keyboard(groups)
            )

            return


        group_id = groups[0][0]
        context.user_data["group_admin_selected_group_id"] = group_id
        context.user_data["group_admin_permissions"] = {
            permission: False
            for _key, _label, permission in GROUP_ADMIN_PERMISSION_OPTIONS
        }

        await update.message.reply_text(
            "Permisos del nuevo admin:\n\n"
            + format_pending_group_admin_permissions(
                context.user_data["group_admin_permissions"]
            ),
            reply_markup=build_pending_group_admin_permissions_keyboard(
                group_id,
                target_user_id,
                context.user_data["group_admin_permissions"]
            )
        )

        return

    # =========================
    # RECIBIR PREVIEW MEDIA
    # =========================

    if context.user_data.get("editing_preview"):

        file_id = None
        file_type = None

        if update.message.photo:

            file_id = update.message.photo[-1].file_id
            file_type = "image"

        elif update.message.video:

            file_id = update.message.video.file_id
            file_type = "video"

        else:

            await update.message.reply_text(
                "❌ Debes enviar imagen o video."
            )

            return


        context.user_data["new_preview_file"] = file_id
        context.user_data["new_preview_file_type"] = file_type


        keyboard = [

            [InlineKeyboardButton(
                "💾 Guardar cambios",
                callback_data="save_preview"
            )],

            [InlineKeyboardButton(
                "❌ Descartar",
                callback_data="cancel_preview"
            )]

        ]


        await update.message.reply_text(

            "Preview recibido.\n\n"

            "¿Deseas guardar cambios?",

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return


    if context.user_data.get("editing_plan"):

        step = context.user_data.get("edit_plan_step")

        text = update.message.text.strip()


        # =========================
        # PASO 1 — NUEVO NOMBRE
        # =========================

        if step == 1:

            context.user_data["edit_plan_name"] = text
            context.user_data["edit_plan_step"] = 2
            provider = normalize_plan_payment_provider(
                context.user_data.get("edit_plan_provider")
            )

            await update.message.reply_text(

                get_plan_provider_id_prompt(provider, editing=True)
                + "\n\nPara cambiar método de pago, crea un nuevo plan. "
                "Puedes actualizar la referencia del proveedor actual."

            )

            return


        # =========================
        # PASO 2 — NUEVO PRICE ID
        # =========================

        if step == 2:

            from plan_price_service import (
                parece_plan_de_paypal,
                parece_precio_de_stripe,
                parece_referencia_interna,
                pide_precio_automatico,
            )

            provider = normalize_plan_payment_provider(
                context.user_data.get("edit_plan_provider")
            )

            # Lo que se escriba aquí es lo que el cobro usará para cobrar. Si no
            # puede ser un identificador, no entra: guardarlo deja el plan
            # anunciándose y sin poder cobrar, y eso no se ve hasta que alguien
            # lo intenta y se va.
            if provider == PLAN_PAYMENT_PROVIDER_STRIPE:

                if pide_precio_automatico(text):

                    # El paso lo ofrecía por escrito y al editar no existía: se
                    # guardaba la palabra «auto» como identificador de precio.
                    context.user_data["edit_plan_stripe_autocreate"] = True
                    context.user_data["edit_plan_price"] = None
                    context.user_data["edit_plan_stripe_price_id"] = None
                    context.user_data["edit_plan_provider_price_id"] = None
                    context.user_data["edit_plan_step"] = 3

                    await update.message.reply_text(

                        "Paso 3️⃣\n\n"
                        "Vale: al terminar creo yo el precio en Stripe con el "
                        "importe que me digas.\n\n"
                        "Introduce la nueva duración en días."

                    )

                    return

                if not parece_precio_de_stripe(text):

                    await update.message.reply_text(

                        "❌ Eso no es un Stripe Price ID.\n\n"
                        "Tiene la forma price_1ABCxyz... y se copia del panel "
                        "de Stripe, en el precio del producto.\n\n"
                        "O escribe *auto* y lo creo yo con el importe que me "
                        "digas al terminar."

                    )

                    return

            elif provider == PLAN_PAYMENT_PROVIDER_PAYPAL:

                if not parece_plan_de_paypal(text):

                    await update.message.reply_text(

                        "❌ Eso no es un PayPal Plan ID.\n\n"
                        "Empieza por P- (por ejemplo P-5ML4271244454362W) y se "
                        "copia del panel de PayPal, en el plan de "
                        "suscripción."

                    )

                    return

            elif not parece_referencia_interna(text):

                await update.message.reply_text(

                    "❌ Eso no vale como referencia: tiene que ser una sola "
                    "palabra, sin espacios (por ejemplo mensual_vip)."

                )

                return

            context.user_data["edit_plan_stripe_autocreate"] = False
            context.user_data["edit_plan_provider_price_id"] = text

            if provider == PLAN_PAYMENT_PROVIDER_PAYPAL:

                context.user_data["edit_plan_price"] = None
                context.user_data["edit_plan_paypal_plan_id"] = text

            elif provider == PLAN_PAYMENT_PROVIDER_STRIPE:

                context.user_data["edit_plan_price"] = text
                context.user_data["edit_plan_stripe_price_id"] = text

            else:

                context.user_data["edit_plan_price"] = None

            context.user_data["edit_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"

                "Introduce la nueva duración en días."

            )

            return


        # =========================
        # PASO 3 — NUEVA DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            if not is_valid_plan_duration_days(duration_days):

                await update.message.reply_text(
                    "⚠️ La duración debe estar entre 1 y 3650 días."
                )

                return


            context.user_data["edit_plan_duration"] = duration_days
            context.user_data["edit_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"

                "Introduce el nuevo PRECIO."

            )

            return


        # =========================
        # PASO 4 — NUEVO PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["edit_plan_amount"] = amount
            context.user_data["edit_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"

                "Introduce la nueva MONEDA."

            )

            return


        # =========================
        # PASO 5 — NUEVA MONEDA
        # =========================

        if step == 5:

            from plan_price_service import moneda_valida_para_stripe

            # En producción hay planes con la moneda escrita «EURO», «€», «$» y
            # hasta «1». Con Stripe el descuadre tarda en verse (el precio lleva
            # su propia moneda), pero los demás proveedores mandan este código
            # tal cual y lo rechazan: el plan se anuncia y no cobra.
            try:

                currency = moneda_valida_para_stripe(text)

            except ValueError:

                await update.message.reply_text(

                    "❌ Esa moneda no vale.\n\n"
                    "Escribe el código de tres letras: EUR, USD, GBP..."

                )

                return

            plan_id = context.user_data.get("editing_plan_id")
            group_id = context.user_data.get("selected_group_admin")

            name = context.user_data.get("edit_plan_name")

            price_id = context.user_data.get("edit_plan_price")
            provider = normalize_plan_payment_provider(
                context.user_data.get("edit_plan_provider")
            )
            provider_price_id = context.user_data.get("edit_plan_provider_price_id")
            stripe_price_id = context.user_data.get("edit_plan_stripe_price_id")
            paypal_plan_id = context.user_data.get("edit_plan_paypal_plan_id")

            duration_days = context.user_data.get("edit_plan_duration")

            amount = context.user_data.get("edit_plan_amount")


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        UPDATE plans

                        SET
                            name=%s,
                            price_id=%s,
                            payment_provider=%s,
                            stripe_price_id=%s,
                            paypal_plan_id=%s,
                            provider_price_id=%s,
                            duration_days=%s,
                            amount=%s,
                            currency=%s

                        WHERE id=%s
                        AND group_id=%s

                    """, (

                        name,
                        price_id,
                        provider,
                        stripe_price_id,
                        paypal_plan_id,
                        provider_price_id,
                        duration_days,
                        amount,
                        currency,
                        plan_id,
                        group_id

                    ))

                    conn.commit()

            except Exception as e:

                print("Error editando plan:", e)

                await update.message.reply_text(
                    "❌ Error editando plan."
                )

                return


            aviso_precio = ""

            if context.user_data.get("edit_plan_stripe_autocreate"):

                # Se pidió «auto»: el precio se crea AHORA, con el importe y el
                # nombre que se acaban de guardar, para que la página de pago
                # diga exactamente lo mismo que el bot.
                from plan_price_service import set_group_plan_price

                ok_precio, detalle_precio = set_group_plan_price(plan_id, amount)

                aviso_precio = (
                    "\nPrecio de Stripe: creado con el importe que has puesto."
                    if ok_precio else
                    f"\n⚠️ No he podido crear el precio en Stripe "
                    f"({detalle_precio}). El plan no podrá cobrar hasta que se "
                    "arregle."
                )

            clear_plan_wizard_state(
                context,
                user_id=update.effective_user.id,
                action="edit_plan_completed"
            )

            await update.message.reply_text(

                "✅ Plan actualizado correctamente.\n\n"
                f"Método: {format_plan_payment_provider(provider)}\n"
                f"{aviso_precio}\n"
                "Para cambiar método de pago, crea un nuevo plan. "
                "Puedes actualizar la referencia del proveedor actual."

            )

            return


    # =========================
    # CUPÓN DE DESCUENTO — WIZARD
    # =========================

    if context.user_data.get("creating_stripe_coupon"):

        from stripe_coupon_service import create_group_coupon, normalizar_codigo

        estado = context.user_data["creating_stripe_coupon"]
        texto = update.message.text.strip()

        if estado.get("step") == 1:

            codigo = normalizar_codigo(texto)

            if not codigo:

                await update.message.reply_text(
                    "❌ Código inválido. 3-30 caracteres: letras, números, "
                    "guiones. Prueba otra vez (p. ej. VERANO20)."
                )

                return

            estado["code"] = codigo
            estado["step"] = 2

            await update.message.reply_text(
                f"Paso 2️⃣ — ¿Qué DESCUENTO aplica {codigo}?\n\n"
                "Escribe el porcentaje (1-100). Se descuenta el primer "
                "cobro; en suscripciones, el primer ciclo."
            )

            return


        if estado.get("step") == 2:

            resultado = create_group_coupon(
                estado["group_id"],
                estado.get("code"),
                texto,
                created_by=update.effective_user.id,
            )

            if not resultado.get("ok"):

                errores = {
                    "porcentaje_invalido": "❌ Porcentaje inválido: escribe un número del 1 al 100.",
                    "codigo_repetido": "❌ Ya existe un cupón activo con ese código. Empieza de nuevo desde «Cupones de descuento».",
                    "sin_planes_stripe": "❌ Esta comunidad no tiene planes de Stripe activos: el cupón no tendría dónde aplicarse.",
                    "stripe": "❌ Stripe no aceptó el cupón. Inténtalo de nuevo en un momento.",
                }

                await update.message.reply_text(
                    errores.get(resultado.get("error"), "❌ No se pudo crear el cupón.")
                )

                # El porcentaje inválido se reintenta; el resto termina aquí.
                if resultado.get("error") != "porcentaje_invalido":

                    context.user_data.pop("creating_stripe_coupon", None)

                return


            context.user_data.pop("creating_stripe_coupon", None)

            await update.message.reply_text(
                f"✅ Cupón {resultado['code']} creado: {resultado['percent_off']}% "
                "de descuento en el primer cobro.\n\n"
                "El comprador solo tiene que teclearlo en el checkout de "
                "Stripe. Solo vale para los planes de Stripe de esta "
                "comunidad, y puedes desactivarlo cuando quieras desde "
                "«Cupones de descuento»."
            )

            return


        return


    # =========================
    # AÑADIR PLAN — WIZARD
    # =========================

    if context.user_data.get("adding_plan"):

        step = context.user_data.get("add_plan_step")

        text = update.message.text.strip()

        group_id = context.user_data.get("selected_group_admin")


        # =========================
        # PASO 1 — NOMBRE
        # =========================

        if step == 1:

            context.user_data.setdefault("new_plan", {})

            context.user_data["new_plan"]["name"] = text
            context.user_data["add_plan_step"] = 2
            provider = normalize_plan_payment_provider(
                context.user_data["new_plan"].get("payment_provider")
            )

            await update.message.reply_text(

                get_plan_provider_id_prompt(provider)

            )

            return


        # =========================
        # PASO 2 — PRICE ID
        # =========================

        if step == 2:

            provider = normalize_plan_payment_provider(
                context.user_data["new_plan"].get("payment_provider")
            )

            context.user_data["new_plan"]["payment_provider"] = provider

            from plan_price_service import (
                parece_plan_de_paypal,
                parece_precio_de_stripe,
                parece_referencia_interna,
                pide_precio_automatico,
            )

            # La misma puerta que al editar: lo que no puede ser un
            # identificador no entra. Un plan nuevo con la referencia mal
            # copiada se anuncia igual y no cobra.
            if (
                provider == PLAN_PAYMENT_PROVIDER_STRIPE
                and not pide_precio_automatico(text)
                and not parece_precio_de_stripe(text)
            ):

                await update.message.reply_text(

                    "❌ Eso no es un Stripe Price ID.\n\n"
                    "Tiene la forma price_1ABCxyz... y se copia del panel de "
                    "Stripe, en el precio del producto.\n\n"
                    "O escribe *auto* y lo creo yo con el importe que me digas."

                )

                return

            if (
                provider == PLAN_PAYMENT_PROVIDER_PAYPAL
                and not parece_plan_de_paypal(text)
            ):

                await update.message.reply_text(

                    "❌ Eso no es un PayPal Plan ID.\n\n"
                    "Empieza por P- (por ejemplo P-5ML4271244454362W) y se "
                    "copia del panel de PayPal, en el plan de suscripción."

                )

                return

            if (
                provider not in (
                    PLAN_PAYMENT_PROVIDER_STRIPE, PLAN_PAYMENT_PROVIDER_PAYPAL
                )
                and not parece_referencia_interna(text)
            ):

                await update.message.reply_text(

                    "❌ Eso no vale como referencia: tiene que ser una sola "
                    "palabra, sin espacios (por ejemplo mensual_vip)."

                )

                return

            if provider == PLAN_PAYMENT_PROVIDER_PAYPAL:

                context.user_data["new_plan"]["provider_price_id"] = text
                context.user_data["new_plan"]["paypal_plan_id"] = text
                context.user_data["new_plan"]["price_id"] = None

            elif provider == PLAN_PAYMENT_PROVIDER_STRIPE:

                if pide_precio_automatico(text):

                    # El bot creará el Producto + Precio en Stripe al terminar.
                    context.user_data["new_plan"]["stripe_autocreate"] = True
                    context.user_data["new_plan"]["stripe_price_id"] = None
                    context.user_data["new_plan"]["price_id"] = None
                    context.user_data["new_plan"]["provider_price_id"] = None

                else:

                    context.user_data["new_plan"]["stripe_autocreate"] = False
                    context.user_data["new_plan"]["stripe_price_id"] = text
                    context.user_data["new_plan"]["price_id"] = text
                    context.user_data["new_plan"]["provider_price_id"] = text

            else:

                context.user_data["new_plan"]["provider_price_id"] = text
                context.user_data["new_plan"]["price_id"] = None

            context.user_data["add_plan_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"
                "Introduce duración en días."

            )

            return


        # =========================
        # PASO 3 — DURACIÓN
        # =========================

        if step == 3:

            try:

                duration_days = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            if not is_valid_plan_duration_days(duration_days):

                await update.message.reply_text(
                    "⚠️ La duración debe estar entre 1 y 3650 días."
                )

                return


            context.user_data["new_plan"]["duration_days"] = duration_days
            context.user_data["add_plan_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"
                "Introduce el PRECIO."

            )

            return


        # =========================
        # PASO 4 — PRECIO
        # =========================

        if step == 4:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["new_plan"]["amount"] = amount
            context.user_data["add_plan_step"] = 5

            await update.message.reply_text(

                "Paso 5️⃣\n\n"
                "Introduce la MONEDA (EUR, USD...)."

            )

            return


        # =========================
        # PASO 5 — MONEDA (Y GUARDAR, SALVO STRIPE AUTOCREADO)
        # =========================

        if step == 5:

            from plan_price_service import moneda_valida_para_stripe

            # La misma puerta que al editar: un código que el cobro no reconoce
            # deja el plan anunciado y sin poder cobrar.
            try:

                currency = moneda_valida_para_stripe(text)

            except ValueError:

                await update.message.reply_text(

                    "❌ Esa moneda no vale.\n\n"
                    "Escribe el código de tres letras: EUR, USD, GBP..."

                )

                return

            context.user_data["new_plan"]["currency"] = currency

            plan = context.user_data["new_plan"]
            provider = normalize_plan_payment_provider(
                plan.get("payment_provider")
            )

            # Para Stripe autocreado queda UNA decisión más: ¿pago único o
            # renovación automática? Se pregunta en un paso 6. El resto de
            # proveedores guarda aquí, como siempre.
            if (
                provider == PLAN_PAYMENT_PROVIDER_STRIPE
                and plan.get("stripe_autocreate")
                and not plan.get("stripe_price_id")
            ):

                context.user_data["add_plan_step"] = 6

                await update.message.reply_text(

                    "Paso 6️⃣\n\n"
                    "¿RENOVACIÓN AUTOMÁTICA?\n\n"
                    "SÍ — suscripción: se cobra sola cada periodo hasta que "
                    "el cliente la cancele. Quien ya esté suscrito conserva "
                    "su precio aunque luego lo cambies.\n\n"
                    "NO — pago único: el acceso caduca y el cliente decide "
                    "si vuelve a pagar.\n\n"
                    "Responde SÍ o NO."

                )

                return


        # =========================
        # PASO 5 (RESTO) / PASO 6-7 (STRIPE) — GUARDAR
        # =========================

        # El paso 6 decide la renovación automática. Con SÍ queda UNA pregunta
        # más: los días de prueba gratis (paso 7) — la prueba solo existe en
        # suscripciones, que es como la modela Stripe (trial_period_days, con
        # tarjeta por delante: cancela durante la prueba y el cobro es cero).
        if step == 6:

            respuesta = text.strip().lower()

            if respuesta in ("sí", "si", "s", "yes", "y"):

                context.user_data["new_plan"]["is_recurring"] = True
                context.user_data["add_plan_step"] = 7

                await update.message.reply_text(

                    "Paso 7️⃣\n\n"
                    "¿DÍAS DE PRUEBA GRATIS?\n\n"
                    "El cliente pone la tarjeta al suscribirse, prueba gratis "
                    "esos días y el primer cobro sale al terminar. Si cancela "
                    "durante la prueba, no paga nada.\n\n"
                    "Escribe un número de 1 a 30, o 0 si no hay prueba."

                )

                return

            elif respuesta in ("no", "n"):

                context.user_data["new_plan"]["is_recurring"] = False

            else:

                await update.message.reply_text(
                    "Responde SÍ o NO."
                )

                return


        if step == 7:

            try:

                trial_days = int(text.strip())

            except Exception:

                trial_days = -1


            if not 0 <= trial_days <= 30:

                await update.message.reply_text(
                    "Escribe un número de 0 a 30 (0 = sin prueba)."
                )

                return

            context.user_data["new_plan"]["trial_days"] = trial_days


        if step in (5, 6, 7):

            plan = context.user_data["new_plan"]
            provider = normalize_plan_payment_provider(
                plan.get("payment_provider")
            )
            currency = plan.get("currency") or text.upper()

            is_recurring = bool(plan.get("is_recurring"))
            trial_days = int(plan.get("trial_days") or 0)

            provider_price_id = plan.get("provider_price_id")
            stripe_price_id = plan.get("stripe_price_id")
            stripe_product_id = plan.get("stripe_product_id")
            paypal_plan_id = plan.get("paypal_plan_id")


            # =========================
            # CREAR PRODUCTO + PRECIO EN STRIPE (modo "auto")
            # =========================

            if (
                provider == PLAN_PAYMENT_PROVIDER_STRIPE
                and plan.get("stripe_autocreate")
                and not stripe_price_id
            ):

                try:

                    stripe_product_id, stripe_price_id = create_stripe_product_and_price(
                        plan.get("name") or "Plan",
                        plan.get("amount"),
                        currency,
                        metadata={
                            "group_id": group_id,
                            "plan_name": plan.get("name"),
                            "duration_days": plan.get("duration_days"),
                            "is_recurring": is_recurring
                        },
                        recurring_interval_days=(
                            plan.get("duration_days") if is_recurring else None
                        )
                    )

                except Exception as e:

                    print("Error creando producto/precio en Stripe:", e)

                    await update.message.reply_text(
                        "❌ No se pudo crear el precio en Stripe.\n"
                        "Revisa la clave de Stripe y reenvía la moneda "
                        "para reintentarlo."
                    )

                    return


                provider_price_id = stripe_price_id
                plan["stripe_price_id"] = stripe_price_id
                plan["price_id"] = stripe_price_id
                plan["provider_price_id"] = stripe_price_id
                plan["stripe_product_id"] = stripe_product_id


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        INSERT INTO plans
                        (
                            group_id,
                            name,
                            price_id,
                            payment_provider,
                            stripe_price_id,
                            stripe_product_id,
                            paypal_plan_id,
                            provider_price_id,
                            duration_days,
                            amount,
                            currency,
                            is_recurring,
                            trial_days
                        )

                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id

                    """, (

                        group_id,
                        plan["name"],
                        plan.get("price_id"),
                        provider,
                        stripe_price_id,
                        stripe_product_id,
                        paypal_plan_id,
                        provider_price_id,
                        plan["duration_days"],
                        plan["amount"],
                        currency,
                        is_recurring,
                        trial_days

                    ))

                    plan_id = cur.fetchone()[0]
                    conn.commit()

                log_event(
                    "plan_created_for_provider",
                    category="payment",
                    severity="info",
                    scope="group",
                    group_id=group_id,
                    actor_user_id=update.effective_user.id,
                    target_user_id=update.effective_user.id,
                    message="Plan creado para proveedor de pago.",
                    metadata={
                        "group_id": group_id,
                        "user_id": update.effective_user.id,
                        "provider": provider,
                        "plan_id": plan_id
                    }
                )

            except Exception as e:

                print("Error guardando plan:", e)

                await update.message.reply_text(
                    "❌ Error guardando plan."
                )

                return


            clear_plan_wizard_state(
                context,
                user_id=update.effective_user.id,
                action="add_plan_completed"
            )

            success_message = (
                "✅ Plan creado correctamente.\n\n"
                f"Método: {format_plan_payment_provider(provider)}"
            )

            if provider == PLAN_PAYMENT_PROVIDER_STRIPE and stripe_price_id:

                success_message += (
                    f"\nPrecio Stripe: {stripe_price_id}"
                )

                if plan.get("stripe_autocreate"):

                    if is_recurring:

                        success_message += (
                            "\n\n🔁 Renovación automática ACTIVADA: el bot ha "
                            "creado el precio como suscripción. Se cobrará "
                            "solo cada periodo hasta que el cliente cancele, "
                            "y quien se suscriba conserva su precio aunque "
                            "luego lo cambies."
                        )

                        if trial_days:

                            success_message += (
                                f"\n\n🎁 Prueba gratis de {trial_days} días: "
                                "el cliente pone la tarjeta al suscribirse y "
                                "el primer cobro sale al acabar la prueba. Si "
                                "cancela antes, no paga nada."
                            )

                    else:

                        success_message += (
                            "\n\nEl bot ha creado el producto y el precio en "
                            "Stripe automáticamente. Cada usuario recibirá su "
                            "enlace de pago único al comprar este plan."
                        )

            await update.message.reply_text(success_message)

            return


    # =========================
    # USO NORMAL DE CÓDIGO
    # =========================

    if context.user_data.get("waiting_code"):

        await receive_code(update, context)

        return

    # ⚠️ IMPORTANTE:
    # Si no estamos esperando código → NO procesar

    if not context.user_data.get("waiting_code"):
        return

    user_code = update.message.text.strip().upper()

    with conn.cursor() as cur:

        cur.execute("""

            SELECT user_id
            FROM banned_users
            WHERE user_id=%s

        """, (update.effective_user.id,))

        banned = cur.fetchone()

        if banned:

            await update.message.reply_text(
                "⛔ Estás baneado permanentemente."
            )

            return


        cur.execute("""

        SELECT duration, used
        FROM invite_codes
        WHERE code=%s

        """, (user_code,))

        row = cur.fetchone()

        if not row:

            await update.message.reply_text(
                "❌ Código inválido"
            )
            return

        duration, used = row

        if used:

            await update.message.reply_text(
                "❌ Código ya usado"
            )
            return


        if duration == 0:

            expiration = None

        else:

            expiration = datetime.now() + timedelta(minutes=duration)


        cur.execute("""

            INSERT INTO users
            (user_id, username, first_name, expiration)

            VALUES (%s, %s, %s, %s)

            ON CONFLICT (user_id)
            DO UPDATE SET

                username=%s,
                first_name=%s,
                expiration=%s

        """, (

            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration,
            update.effective_user.username,
            update.effective_user.first_name,
            expiration

        ))

        cur.execute("""

            UPDATE invite_codes
            SET used=TRUE
            WHERE code=%s

        """, (user_code,))


        cur.execute("""

            SELECT invite_link
            FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))


        old_links = cur.fetchall()

        for (old_link,) in old_links:

            try:

                revoke_link(
                    get_group_id(),
                    old_link
                )

                cur.execute("""

                    UPDATE invite_links

                    SET is_active=FALSE,
                        revoked_at=NOW()

                    WHERE invite_link=%s

                """, (old_link,))

            except Exception as e:

                print("Error revocando link:", e)


        # borrar antiguos

        cur.execute("""

            DELETE FROM invite_links
            WHERE user_id=%s
            AND group_id=%s

        """, (

            update.effective_user.id,
            get_group_id()

        ))

        conn.commit()


    link = create_telegram_invite_link(
        TOKEN,
        get_group_id(),
        expire_seconds=ACCESS_LINK_EXPIRE_SECONDS,
        member_limit=1
    )


    if not link:

        await update.message.reply_text(
            "❌ Error creando link de acceso."
        )

        return


    try:

        with conn.cursor() as cur:

            cur.execute("""

    INSERT INTO invite_links
    (user_id, group_id, invite_link)

    VALUES (%s, %s, %s)

""", (

    update.effective_user.id,
    get_group_id(),
    link

))

            conn.commit()

    except Exception as e:

        print("Error guardando invite link:", e)


    # =========================
    # CALCULAR TIEMPO RESTANTE
    # =========================

    tiempo_texto = format_tiempo_restante(
        expiration
    )


    await update.message.reply_text(

        "🔗 Acceso concedido\n\n"

        f"⏳ Tiempo restante: {tiempo_texto}\n\n"

        f"{link}"

    )


    context.user_data["waiting_code"] = False
