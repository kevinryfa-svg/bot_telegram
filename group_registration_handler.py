import asyncio
import requests

from telegram import Update
from telegram.ext import ContextTypes

from bot_config import TOKEN, ADMIN_ID
from db import conn


# =========================
# VERIFICAR ADMIN DESPUÉS DE 30s
# =========================

async def verificar_admin_despues(group_id, group_name, bot_id, context, added_by):

    print("Esperando 30 segundos antes de verificar permisos...")

    await asyncio.sleep(30)

    try:

        print("Verificando permisos del bot...")

        r = requests.get(

            f"https://api.telegram.org/bot{TOKEN}/getChatMember",

            params={

                "chat_id": group_id,
                "user_id": bot_id

            }

        ).json()

        print("Respuesta completa getChatMember:", r)

        status = r["result"]["status"]

        print("Status del bot en grupo:", status)


        if status not in ["administrator", "creator"]:

            print("Bot NO es administrador después de 30s.")

            try:

                await context.bot.send_message(

                    chat_id=group_id,

                    text=

                    "⚠️ No tengo permisos de administrador.\n\n"

                    "Saldré del grupo en este momento."

                )

            except Exception as e:

                print("Error enviando mensaje al grupo:", e)


            try:

                await context.bot.send_message(

                    chat_id=ADMIN_ID,

                    text=

                    "⚠️ BOT SALIENDO DEL GRUPO\n\n"

                    f"Grupo: {group_name}\n"

                    f"ID: {group_id}\n\n"

                    "No fue asignado como administrador."

                )

            except Exception as e:

                print("Error enviando aviso admin:", e)


            try:

                await context.bot.leave_chat(group_id)

                print("Bot salió del grupo automáticamente.")

            except Exception as e:

                print("Error saliendo del grupo:", e)


            return

        print(f"Bot ES administrador en grupo: {group_name} ({group_id})")


        # =========================
        # GUARDAR GRUPO EN DATABASE
        # =========================

        print("Intentando guardar grupo en DB...")

        with conn.cursor() as cur:

            cur.execute("""

                SELECT id
                FROM groups
                WHERE telegram_group_id=%s

            """, (group_id,))

            existing = cur.fetchone()

            if existing:

                print("Grupo ya existe en DB — no se duplica.")

                print(f"Registro finalizado para grupo: {group_name}")

            else:

                cur.execute("""

                    INSERT INTO groups
                    (name, telegram_group_id)

                    VALUES (%s, %s)

                """, (

                    group_name,
                    group_id

                ))

                conn.commit()

                print("Grupo guardado correctamente en DB.")

                print(f"Registro finalizado para grupo: {group_name}")


        try:

            print("Enviando confirmación al ADMIN...")

            await context.bot.send_message(

                chat_id=ADMIN_ID,

                text=

                "✅ NUEVO GRUPO DETECTADO\n\n"

                f"Nombre: {group_name}\n"

                f"ID: {group_id}\n\n"

                "Grupo registrado correctamente."

            )

            print("Mensaje enviado al ADMIN.")

        except Exception as e:

            print("Error enviando confirmación:", e)


    except Exception as e:

        print("Error verificando grupo:", e)


# =========================
# DETECTAR BOT AÑADIDO A GRUPO
# =========================

async def detect_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("detect_bot_added ejecutado")

    if not update.message:
        return

    if not update.message.new_chat_members:
        return


    bot_id = context.bot.id


    for member in update.message.new_chat_members:


        # =========================
        # SI EL MIEMBRO ES EL BOT
        # =========================

        if member.id == bot_id:

            group_id = update.message.chat.id
            group_name = update.message.chat.title

            print(
                "Bot añadido a grupo:",
                group_name,
                group_id
            )


            try:

                added_by = update.message.from_user.id

            except:

                added_by = None


            print(
                "Bot añadido por usuario:",
                added_by
            )


            # =========================
            # AVISO SI NO FUE EL ADMIN
            # =========================

            if added_by and added_by != ADMIN_ID:

                try:

                    await context.bot.send_message(

                        chat_id=ADMIN_ID,

                        text=

                        "⚠️ BOT AÑADIDO POR USUARIO NO AUTORIZADO\n\n"

                        f"Grupo: {group_name}\n"

                        f"ID: {group_id}\n"

                        f"Usuario: {added_by}\n\n"

                        "El grupo será registrado igualmente."

                    )

                except Exception as e:

                    print(
                        "Error enviando aviso admin:",
                        e
                    )


            print(
                "Continuando registro del grupo..."
            )


            # =========================
            # AVISO AL GRUPO
            # =========================

            try:

                await context.bot.send_message(

                    chat_id=group_id,

                    text=

                    "⚠️ Necesito permisos de administrador.\n\n"

                    "Por favor asígnamelos en los próximos 30 segundos.\n\n"

                    "Si no, abandonaré el grupo automáticamente."

                )

            except Exception as e:

                print(
                    "Error enviando aviso al grupo:",
                    e
                )


            # =========================
            # VERIFICAR ADMIN DESPUÉS
            # =========================

            asyncio.create_task(

                verificar_admin_despues(

                    group_id,

                    group_name,

                    bot_id,

                    context,

                    added_by

                )

            )

            return
