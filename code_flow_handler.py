import requests
from functools import partial

from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from db import conn

from invite_link_service import (
    create_telegram_invite_link,
    revoke_telegram_invite_link
)

from telegram_group_actions import (
    ban_chat_member,
    unban_chat_member,
    kick_chat_member
)

from bot_config import TOKEN, GROUP_ID
from formatters import format_tiempo_restante
from group_service import get_latest_telegram_group_id
from rbac_helpers import (
    assign_pending_commercial_owner_for_group,
    get_admin_group_ids,
    is_super_admin
)


get_group_id = partial(
    get_latest_telegram_group_id,
    GROUP_ID
)


def is_valid_plan_duration_days(duration_days):

    return 1 <= int(duration_days) <= 3650


def get_scoped_admin_groups(context, user_id, permissions):

    if is_super_admin(user_id):

        return None


    group_ids = get_admin_group_ids(user_id, permissions)
    selected_group_id = context.user_data.get("selected_group_admin")


    if selected_group_id and selected_group_id in group_ids:

        group_ids = [selected_group_id]


    if not group_ids:

        return []


    with conn.cursor() as cur:

        cur.execute("""

            SELECT id, telegram_group_id
            FROM groups
            WHERE id = ANY(%s)

        """, (group_ids,))

        return cur.fetchall()


# =========================
# USAR CÓDIGO
# =========================

async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # =========================
    # ELIMINAR CÓDIGO
    # =========================

    if context.user_data.get("delete_code"):

        code = update.message.text.strip().upper()

        with conn.cursor() as cur:

            cur.execute("""

                DELETE FROM invite_codes
                WHERE code=%s

            """, (code,))

            conn.commit()

        await update.message.reply_text(
            f"❌ Código eliminado:\n{code}"
        )

        context.user_data["delete_code"] = False

        return


    # =========================
    # BUSCAR USUARIO
    # =========================

    if context.user_data.get("search_user"):

        user_id = update.message.text.strip()
        admin_groups = get_scoped_admin_groups(
            context,
            update.effective_user.id,
            ["can_view_users", "can_manage_users"]
        )


        if admin_groups == []:

            await update.message.reply_text(
                "⛔ No tienes permisos sobre grupos."
            )

            context.user_data["search_user"] = False

            return

        with conn.cursor() as cur:

            if admin_groups is None:

                cur.execute("""

                    SELECT u.expiration,
                           g.name
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE u.user_id=%s

                """, (user_id,))

            else:

                group_ids = [
                    group_id
                    for group_id, _telegram_group_id in admin_groups
                ]

                cur.execute("""

                    SELECT u.expiration,
                           g.name
                    FROM users u
                    LEFT JOIN groups g
                    ON u.group_id = g.id
                    WHERE u.user_id=%s
                    AND u.group_id = ANY(%s)

                """, (
                    user_id,
                    group_ids
                ))

            rows = cur.fetchall()

        if rows:

            lines = [
                f"👤 Usuario {user_id}"
            ]


            for expiration, group_name in rows:

                lines.append(
                    f"Grupo: {group_name or '-'}\nExpira: {expiration}"
                )

            await update.message.reply_text(
                "\n\n".join(lines)
            )

        else:

            await update.message.reply_text(
                "Usuario no encontrado"
            )

        context.user_data["search_user"] = False

        return


    # =========================
    # EXPULSAR USUARIO
    # =========================

    if context.user_data.get("kick_user"):

        user_id = update.message.text.strip()
        admin_groups = get_scoped_admin_groups(
            context,
            update.effective_user.id,
            ["can_manage_users"]
        )


        if admin_groups == []:

            await update.message.reply_text(
                "⛔ No tienes permisos sobre grupos."
            )

            context.user_data["kick_user"] = False

            return


        if admin_groups is not None:

            group_ids = [
                group_id
                for group_id, _telegram_group_id in admin_groups
            ]


            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link,
                           group_id
                    FROM invite_links
                    WHERE user_id=%s
                    AND group_id = ANY(%s)

                """, (
                    user_id,
                    group_ids
                ))

                links = cur.fetchall()


                for link, link_group_id in links:

                    telegram_group_id = next(
                        telegram_id
                        for current_group_id, telegram_id in admin_groups
                        if current_group_id == link_group_id
                    )

                    try:

                        revoke_telegram_invite_link(
                            TOKEN,
                            telegram_group_id,
                            link
                        )

                    except Exception as e:

                        print("Error revocando link:", e)


                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id = ANY(%s)

                """, (
                    user_id,
                    group_ids
                ))

                cur.execute("""

                    DELETE FROM users
                    WHERE user_id=%s
                    AND group_id = ANY(%s)

                """, (
                    user_id,
                    group_ids
                ))

                conn.commit()


            for _group_id, telegram_group_id in admin_groups:

                kick_chat_member(
                    TOKEN,
                    telegram_group_id,
                    user_id
                )


            await update.message.reply_text(
                f"🚫 Usuario expulsado:\n{user_id}"
            )

            context.user_data["kick_user"] = False

            return

        with conn.cursor() as cur:

            # eliminar usuario

            cur.execute("""

                DELETE FROM users
                WHERE user_id=%s

            """, (user_id,))


            # revocar links del usuario

            cur.execute("""

                SELECT invite_link
                FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            links = cur.fetchall()

            for (link,) in links:

                try:

                    revoke_telegram_invite_link(
                        TOKEN,
                        get_group_id(),
                        link
                    )

                except Exception as e:

                    print("Error revocando link:", e)


            # borrar links

            cur.execute("""

                DELETE FROM invite_links
                WHERE user_id=%s
                AND group_id=%s

            """, (

                user_id,
                get_group_id()

            ))

            conn.commit()


        kick_chat_member(
            TOKEN,
            get_group_id(),
            user_id
        )

        await update.message.reply_text(
            f"🚫 Usuario expulsado:\n{user_id}"
        )

        context.user_data["kick_user"] = False

        return


    # =========================
    # BAN PERMANENTE
    # =========================

    if context.user_data.get("ban_user"):

        user_id = update.message.text.strip()
        admin_groups = get_scoped_admin_groups(
            context,
            update.effective_user.id,
            ["can_manage_users"]
        )


        if admin_groups == []:

            await update.message.reply_text(
                "⛔ No tienes permisos sobre grupos."
            )

            context.user_data["ban_user"] = False

            return


        if admin_groups is not None:

            group_ids = [
                group_id
                for group_id, _telegram_group_id in admin_groups
            ]


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        SELECT invite_link,
                               group_id
                        FROM invite_links
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))

                    links = cur.fetchall()


                    for link, link_group_id in links:

                        telegram_group_id = next(
                            telegram_id
                            for current_group_id, telegram_id in admin_groups
                            if current_group_id == link_group_id
                        )

                        try:

                            revoke_telegram_invite_link(
                                TOKEN,
                                telegram_group_id,
                                link
                            )

                        except Exception as e:

                            print("Error revocando link:", e)


                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))


                    for group_id, _telegram_group_id in admin_groups:

                        cur.execute("""

                            INSERT INTO banned_users
                            (user_id, group_id)
                            VALUES (%s, %s)
                            ON CONFLICT (user_id, group_id)
                            DO NOTHING

                        """, (
                            user_id,
                            group_id
                        ))


                    conn.commit()


                for _group_id, telegram_group_id in admin_groups:

                    ban_chat_member(
                        TOKEN,
                        telegram_group_id,
                        user_id
                    )


                await update.message.reply_text(
                    f"⛔ Usuario baneado permanentemente:\n{user_id}"
                )

            except Exception as e:

                print("Error baneando:", e)


            context.user_data["ban_user"] = False

            return

        try:

            with conn.cursor() as cur:

                cur.execute("""

                    SELECT invite_link
                    FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    get_group_id()

                ))

                links = cur.fetchall()

                for (link,) in links:

                    try:

                        revoke_telegram_invite_link(
                            TOKEN,
                            get_group_id(),
                            link
                        )

                    except Exception as e:

                        print("Error revocando link:", e)


                # borrar avisos

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s
                    AND group_id=%s

                """, (

                    user_id,
                    get_group_id()

                ))


                # guardar en baneados

                cur.execute("""

                    INSERT INTO banned_users
                    (user_id)

                    VALUES (%s)

                    ON CONFLICT (user_id)
                    DO NOTHING

                """, (user_id,))


                # 🔴 NO ELIMINAR USUARIO
                # MANTENER USERS PARA CONSERVAR EXPIRATION

                print("Usuario marcado como baneado sin borrar users:", user_id)


                conn.commit()


            ban_chat_member(
                TOKEN,
                get_group_id(),
                user_id
            )


            await update.message.reply_text(
                f"⛔ Usuario baneado permanentemente:\n{user_id}"
            )

        except Exception as e:

            print("Error baneando:", e)


        context.user_data["ban_user"] = False

        return


    # =========================
    # DESBAN PERMANENTE
    # =========================

    if context.user_data.get("unban_user"):

        user_id = int(update.message.text.strip())
        admin_groups = get_scoped_admin_groups(
            context,
            update.effective_user.id,
            ["can_manage_users"]
        )


        if admin_groups == []:

            await update.message.reply_text(
                "⛔ No tienes permisos sobre grupos."
            )

            context.user_data["unban_user"] = False

            return


        if admin_groups is not None:

            group_ids = [
                group_id
                for group_id, _telegram_group_id in admin_groups
            ]


            try:

                with conn.cursor() as cur:

                    cur.execute("""

                        DELETE FROM banned_users
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))

                    cur.execute("""

                        DELETE FROM link_warnings
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))


                    for group_id, _telegram_group_id in admin_groups:

                        cur.execute("""

                            INSERT INTO link_warnings
                            (user_id, group_id, warnings)
                            VALUES (%s, %s, 0)
                            ON CONFLICT (user_id, group_id)
                            DO UPDATE SET warnings=0

                        """, (
                            user_id,
                            group_id
                        ))


                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))

                    cur.execute("""

                        SELECT group_id,
                               expiration
                        FROM users
                        WHERE user_id=%s
                        AND group_id = ANY(%s)

                    """, (
                        user_id,
                        group_ids
                    ))

                    expirations = {
                        group_id: expiration
                        for group_id, expiration in cur.fetchall()
                    }


                    for group_id, telegram_group_id in admin_groups:

                        unban_chat_member(
                            TOKEN,
                            telegram_group_id,
                            user_id
                        )

                        expiration = expirations.get(group_id)


                        if expiration is None or expiration > datetime.now():

                            link = create_telegram_invite_link(
                                TOKEN,
                                telegram_group_id,
                                expire_seconds=180,
                                member_limit=1
                            )


                            if link:

                                cur.execute("""

                                    INSERT INTO invite_links
                                    (user_id, group_id, invite_link)
                                    VALUES (%s, %s, %s)

                                """, (
                                    user_id,
                                    group_id,
                                    link
                                ))


                    conn.commit()


                await update.message.reply_text(
                    f"♻️ Usuario desbaneado:\n{user_id}"
                )

            except Exception as e:

                print("Error desbaneando:", e)


            context.user_data["unban_user"] = False

            return

        try:

            with conn.cursor() as cur:

                # quitar de baneados

                cur.execute("""

                    DELETE FROM banned_users
                    WHERE user_id=%s

                """, (user_id,))


                # limpiar avisos

                cur.execute("""

                    DELETE FROM link_warnings
                    WHERE user_id=%s

                """, (user_id,))


                # 🔴 RESETEAR WARNINGS A 0 (CLAVE PARA EVITAR AVISOS FALSOS)

                cur.execute("""

                    INSERT INTO link_warnings
                    (user_id, warnings)

                    VALUES (%s, 0)

                    ON CONFLICT (user_id)
                    DO UPDATE SET warnings=0

                """, (user_id,))


                # 🔴 BORRAR LINKS ANTIGUOS (ESTO ARREGLA LOS WARNINGS)

                cur.execute("""

                    DELETE FROM invite_links
                    WHERE user_id=%s

                """, (user_id,))


                # comprobar si tiene suscripción válida

                cur.execute("""

                    SELECT expiration
                    FROM users
                    WHERE user_id=%s

                """, (user_id,))

                row = cur.fetchone()

                expiration = None

                if row:

                    expiration = row[0]

                else:

                    # 🔴 SI NO EXISTE EN USERS, CREARLO TEMPORALMENTE
                    # EVITA QUE SEA DETECTADO COMO INTRUSO

                    expiration = datetime.now() + timedelta(minutes=5)

                    cur.execute("""

                        INSERT INTO users
                        (user_id, expiration)

                        VALUES (%s, %s)

                        ON CONFLICT (user_id)
                        DO NOTHING

                    """, (user_id, expiration))


                # permitir volver a entrar

                unban_chat_member(
                    TOKEN,
                    get_group_id(),
                    user_id
                )


                # =========================
                # SI TIENE SUSCRIPCIÓN ACTIVA
                # =========================

                if expiration is None or expiration > datetime.now():

                    # calcular tiempo restante

                    tiempo_texto = format_tiempo_restante(
                        expiration
                    )


                    # borrar links antiguos

                    cur.execute("""

                        DELETE FROM invite_links
                        WHERE user_id=%s

                    """, (user_id,))


                    # crear link nuevo

                    link = create_telegram_invite_link(
                        TOKEN,
                        get_group_id(),
                        expire_seconds=180,
                        member_limit=1
                    )


                    if not link:

                        await update.message.reply_text(
                            "❌ Error creando link nuevo."
                        )

                        return


                    # guardar link

                    cur.execute("""

                        INSERT INTO invite_links
                        (user_id, group_id, invite_link)

                        VALUES (%s, %s, %s)

                    """, (

                        user_id,
                        get_group_id(),
                        link

                    ))


                    conn.commit()


                    # enviar link nuevo con tiempo restante

                    requests.post(

                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",

                        json={

                            "chat_id": user_id,

                            "text":

                            "♻️ Has sido desbaneado.\n\n"

                            "Tu suscripción sigue activa.\n\n"

                            f"⏳ Tiempo restante: {tiempo_texto}\n\n"

                            "Aquí tienes tu nuevo acceso:\n\n"

                            f"{link}"

                        }

                    )


                    await update.message.reply_text(

                        f"♻️ Usuario desbaneado y link enviado:\n{user_id}"

                    )


                else:

                    conn.commit()


                    await update.message.reply_text(

                        f"♻️ Usuario desbaneado:\n{user_id}"

                    )


        except Exception as e:

            print("Error desbaneando:", e)


        context.user_data["unban_user"] = False

        return
    

    # =========================
    # CREACIÓN GRUPO — WIZARD
    # =========================

    if context.user_data.get("creating_group"):

        step = context.user_data.get("group_step")

        text = update.message.text.strip()


        # PASO 1 — NOMBRE GRUPO

        if step == 1:

            context.user_data["new_group_data"]["name"] = text

            context.user_data["group_step"] = 2

            await update.message.reply_text(

                "Paso 2️⃣\n\n"

                "Envía ahora el ID del grupo de Telegram.\n\n"

                "⚠️ El bot debe estar añadido como ADMIN."

            )

            return


        # =========================
        # PASO 2 — GROUP ID
        # =========================

        if step == 2:

            try:

                group_id = int(text)

            except:

                await update.message.reply_text(
                    "❌ ID inválido. Intenta nuevamente."
                )

                return


            context.user_data["new_group_data"]["telegram_group_id"] = group_id
            context.user_data["group_step"] = 3

            await update.message.reply_text(

                "Paso 3️⃣\n\n"

                "Verificando permisos del bot..."

            )


            # Verificar bot admin

            try:

                bot_id = int(TOKEN.split(":")[0])

                r = requests.get(

                    f"https://api.telegram.org/bot{TOKEN}/getChatMember",

                    params={

                        "chat_id": group_id,
                        "user_id": bot_id

                    }

                ).json()


                status = r["result"]["status"]

                if status not in ["administrator", "creator"]:

                    await update.message.reply_text(

                        "❌ El bot no es administrador del grupo."

                    )

                    return


            except Exception as e:

                print("Error verificando admin:", e)

                await update.message.reply_text(

                    "❌ No se pudo verificar el grupo."

                )

                return


            context.user_data["group_step"] = 4

            await update.message.reply_text(

                "Paso 4️⃣\n\n"

                "¿Cuántos planes quieres crear?\n\n"

                "Ejemplo: 1, 2, 3..."

            )

            return
    
    # =========================
    # CREACIÓN PLANES — PASO 4
    # =========================

        if step == 4:

            try:

                total_plans = int(text)

            except:

                await update.message.reply_text(
                    "❌ Número inválido."
                )

                return


            context.user_data["new_group_data"]["total_plans"] = total_plans
            context.user_data["new_group_data"]["plans"] = []

            context.user_data["current_plan"] = 1
            context.user_data["group_step"] = 5

            await update.message.reply_text(

                f"Paso 5️⃣\n\n"

                f"Introduce el NOMBRE del plan 1."

            )

            return


        # =========================
        # PASO 5 — NOMBRE PLAN
        # =========================

        if step == 5:

            context.user_data["current_plan_name"] = text
            context.user_data["group_step"] = 6

            await update.message.reply_text(

                "Paso 6️⃣\n\n"

                "Introduce el PRICE ID de Stripe."

            )

            return


        # =========================
        # PASO 6 — PRICE ID
        # =========================

        if step == 6:

            context.user_data["current_price_id"] = text
            context.user_data["group_step"] = 7

            await update.message.reply_text(

                "Paso 7️⃣\n\n"

                "Introduce duración en días."

            )

            return


        # =========================
        # PASO 7 — DURACIÓN
        # =========================

        if step == 7:

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


            context.user_data["current_duration"] = duration_days
            context.user_data["group_step"] = 8

            await update.message.reply_text(

                "Paso 8️⃣\n\n"

                "Introduce el PRECIO del plan.\n"

                "Ejemplo: 10"

            )

            return


        # =========================
        # PASO 8 — PRECIO
        # =========================

        if step == 8:

            try:

                amount = int(text)

            except:

                await update.message.reply_text(
                    "❌ Precio inválido."
                )

                return


            context.user_data["current_amount"] = amount
            context.user_data["group_step"] = 9

            await update.message.reply_text(

                "Paso 9️⃣\n\n"

                "Introduce la MONEDA.\n"

                "Ejemplo: EUR"

            )

            return


        # =========================
        # PASO 9 — MONEDA
        # =========================

        if step == 9:

            currency = text.upper()


            plans = context.user_data["new_group_data"]["plans"]

            plans.append({

                "name": context.user_data["current_plan_name"],
                "price_id": context.user_data["current_price_id"],
                "duration_days": context.user_data["current_duration"],
                "amount": context.user_data["current_amount"],
                "currency": currency

            })


            total_plans = context.user_data["new_group_data"]["total_plans"]

            current = context.user_data["current_plan"]


            if current < total_plans:

                context.user_data["current_plan"] += 1
                context.user_data["group_step"] = 5

                next_plan = context.user_data["current_plan"]

                await update.message.reply_text(

                    f"Plan {next_plan}\n\n"

                    "Introduce el NOMBRE del plan."

                )

                return


            # =========================
            # GUARDAR PLANES EN DB
            # =========================

            group_data = context.user_data["new_group_data"]

            group_name = group_data["name"]
            telegram_group_id = group_data["telegram_group_id"]


            with conn.cursor() as cur:

                cur.execute("""

                    SELECT id
                    FROM groups
                    WHERE telegram_group_id=%s

                """, (telegram_group_id,))

                row = cur.fetchone()


                if row:

                    group_id = row[0]

                else:

                    cur.execute("""

                        INSERT INTO groups
                        (name, telegram_group_id)

                        VALUES (%s, %s)

                        RETURNING id

                    """, (

                        group_name,
                        telegram_group_id

                    ))

                    group_id = cur.fetchone()[0]


                for plan in group_data["plans"]:

                    cur.execute("""

                        INSERT INTO plans
                        (
                            group_id,
                            name,
                            price_id,
                            duration_days,
                            amount,
                            currency
                        )

                        VALUES (%s, %s, %s, %s, %s, %s)

                    """, (

                        group_id,
                        plan["name"],
                        plan["price_id"],
                        plan["duration_days"],
                        plan["amount"],
                        plan["currency"]

                    ))


                assign_pending_commercial_owner_for_group(
                    group_id,
                    telegram_group_id
                )


            await update.message.reply_text(

                "✅ Grupo y planes creados correctamente.",

                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⬅️ Volver al panel",
                        callback_data="admin_back_main"
                    )],
                    [InlineKeyboardButton(
                        "📦 Gestión Grupos",
                        callback_data="menu_groups"
                    )]
                ])

            )


            context.user_data["creating_group"] = False
            context.user_data.pop("new_group_data", None)
            context.user_data.pop("group_step", None)
            context.user_data.pop("current_plan", None)
            context.user_data.pop("current_plan_name", None)
            context.user_data.pop("current_price_id", None)
            context.user_data.pop("current_duration", None)
            context.user_data.pop("current_amount", None)

            return
