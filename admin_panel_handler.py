from telegram import (
    Update
)
from telegram.ext import ContextTypes

from admin_menu_catalog import build_admin_menu_button_rows
from rbac_helpers import is_super_admin
from ui_menu_helpers import make_keyboard_from_specs


# =========================
# PANEL ADMIN PRINCIPAL
# =========================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id


    if not is_super_admin(user_id):

        # DECIR LA VERDAD Y LLEVARLE DONDE SÍ PUEDE TRABAJAR. A un admin
        # delegado —alguien a quien el propietario dio permisos sobre una
        # comunidad— este panel le contestaba «no tienes permisos», que es
        # falso: tiene los suyos, solo que este panel es el de plataforma.
        # Quedaba sin saber que existe el panel de su grupo.
        from rbac_helpers import ALLOWED_PERMISSIONS, has_any_permission_any_group

        try:
            delegado = has_any_permission_any_group(user_id, ALLOWED_PERMISSIONS)
        except Exception as e:
            print("Panel admin: no se pudo mirar si es delegado:", str(e)[:160])
            delegado = False

        if delegado:

            await update.message.reply_text(
                "👮 Este es el panel de la plataforma y ese es del "
                "propietario principal.\n\n"
                "Tú tienes permisos sobre comunidades concretas: entra por el "
                "panel de grupo.",
                reply_markup=make_keyboard_from_specs([
                    [{
                        "text": "👮 Panel admin de grupo",
                        "callback_data": "admin_edit_group",
                    }],
                ])
            )

            return


        await update.message.reply_text(
            "⛔ No tienes permisos para acceder al panel."
        )

        return


    keyboard = build_admin_menu_button_rows(
        is_super_admin=True
    )

    await update.message.reply_text(

        "🔐 PANEL ADMIN",

        reply_markup=make_keyboard_from_specs(keyboard)

    )
