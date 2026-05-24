from pathlib import Path


ACCEPTED_DUPLICATE_CALLBACKS = {
    "admin_global_panel",
    "admin_back_main",
    "public_back_start",
    "admin_beta_monitor",
    "admin_customer_satisfaction",
    "admin_global_marketplace",
    "admin_owners_panel",
    "menu_logs"
}


ADMIN_CALLBACK_PREFIXES_FOR_AUDIT = (
    "admin_",
    "menu_",
    "owner_",
    "owner_panel_",
    "group_admin_",
    "admin_group_"
)


def load_callback_router_source():

    try:

        return Path(__file__).resolve().with_name("callback_router.py").read_text()

    except Exception:

        return ""


def get_button_rows(keyboard):

    if not keyboard:

        return []


    if hasattr(keyboard, "inline_keyboard"):

        return keyboard.inline_keyboard or []


    return keyboard or []


def flatten_keyboard_buttons(menu_name, keyboard):

    buttons = []


    for row in get_button_rows(keyboard):

        for button in row:

            callback_data = getattr(button, "callback_data", None)
            text = getattr(button, "text", None)


            if not callback_data:

                continue


            buttons.append({
                "menu": menu_name,
                "text": text or "Sin texto",
                "callback_data": callback_data
            })


    return buttons


def callback_has_handler(callback_data, handler_source):

    if not callback_data:

        return False


    if f'"{callback_data}"' in handler_source:

        return True


    parts = callback_data.split("_")


    for index in range(len(parts), 1, -1):

        prefix = "_".join(parts[:index]) + "_"


        if f'data.startswith("{prefix}")' in handler_source:

            return True


    return False


def callback_needs_admin_permission(callback_data):

    return callback_data.startswith(ADMIN_CALLBACK_PREFIXES_FOR_AUDIT)


def callback_has_admin_permission(callback_data, permission_checker):

    if not callback_needs_admin_permission(callback_data):

        return True


    try:

        return bool(permission_checker(callback_data))

    except Exception:

        return False


def classify_duplicate(callback_data):

    if callback_data in ACCEPTED_DUPLICATE_CALLBACKS:

        return "accepted"


    if callback_data.startswith("admin_help_"):

        return "accepted"


    return "suspicious"


def audit_admin_button_menus(menu_specs, permission_checker):

    router_source = load_callback_router_source()
    handler_source = router_source.split("async def button", 1)[-1]
    all_buttons = []


    for menu in menu_specs:

        all_buttons.extend(
            flatten_keyboard_buttons(
                menu.get("name"),
                menu.get("keyboard")
            )
        )


    occurrences = {}


    for button in all_buttons:

        callback_data = button.get("callback_data")
        occurrences.setdefault(callback_data, []).append(button.get("menu"))


    menu_reports = []
    detail_rows = []


    for menu in menu_specs:

        menu_name = menu.get("name")
        menu_callback = menu.get("callback_data")
        buttons = [
            button
            for button in all_buttons
            if button.get("menu") == menu_name
        ]
        menu_issues = []
        missing_handlers = 0
        missing_permissions = 0
        repeated_callbacks = 0
        suspicious_duplicates = 0
        same_menu_callbacks = 0


        has_help = any(
            button.get("callback_data", "").startswith("admin_help_")
            for button in buttons
        )
        has_navigation = any(
            "Volver" in button.get("text", "")
            or "Inicio" in button.get("text", "")
            or "Panel global" in button.get("text", "")
            for button in buttons
        )


        if menu.get("requires_help", True) and not has_help:

            menu_issues.append("Falta botón de ayuda contextual.")


        if menu.get("requires_navigation", True) and not has_navigation:

            menu_issues.append("Falta botón de volver o inicio.")


        for button in buttons:

            callback_data = button.get("callback_data")
            observations = []
            state = "✅ OK"


            if not callback_has_handler(callback_data, handler_source):

                state = "❌ Problema"
                missing_handlers += 1
                observations.append("callback sin implementación detectada")


            if not callback_has_admin_permission(callback_data, permission_checker):

                state = "❌ Problema"
                missing_permissions += 1
                observations.append("callback admin sin permiso asignado")


            if callback_data == menu_callback:

                if state == "✅ OK":

                    state = "⚠️ Revisar"


                same_menu_callbacks += 1
                observations.append("parece volver al mismo menú")


            if len(occurrences.get(callback_data, [])) > 1:

                repeated_callbacks += 1
                duplicate_kind = classify_duplicate(callback_data)


                if duplicate_kind == "accepted":

                    observations.append("duplicación aceptable como acceso rápido")

                else:

                    if state == "✅ OK":

                        state = "⚠️ Revisar"


                    suspicious_duplicates += 1
                    observations.append("callback repetido en varios menús")


            detail_rows.append({
                "menu": menu_name,
                "text": button.get("text"),
                "callback_data": callback_data,
                "state": state,
                "observation": "; ".join(observations) or "sin observaciones"
            })


        if missing_handlers or missing_permissions:

            menu_state = "❌ Problema"

        elif menu_issues or suspicious_duplicates or same_menu_callbacks:

            menu_state = "⚠️ Revisar"

        else:

            menu_state = "✅ OK"


        menu_reports.append({
            "name": menu_name,
            "state": menu_state,
            "button_count": len(buttons),
            "missing_handlers": missing_handlers,
            "missing_permissions": missing_permissions,
            "repeated_callbacks": repeated_callbacks,
            "suspicious_duplicates": suspicious_duplicates,
            "same_menu_callbacks": same_menu_callbacks,
            "issues": menu_issues
        })


    return {
        "menus": menu_reports,
        "details": detail_rows,
        "total_buttons": len(all_buttons)
    }


def format_admin_button_audit_summary(report):

    menus = report.get("menus") or []
    total_buttons = report.get("total_buttons") or 0
    problem_count = sum(1 for menu in menus if menu.get("state") == "❌ Problema")
    warning_count = sum(1 for menu in menus if menu.get("state") == "⚠️ Revisar")


    lines = [
        "🧪 Auditoría de botones",
        "",
        f"Botones revisados: {total_buttons}",
        f"Menús con problemas: {problem_count}",
        f"Menús para revisar: {warning_count}"
    ]


    for menu in menus:

        lines.extend([
            "",
            f"{menu.get('state')} {menu.get('name')}",
            f"- {menu.get('button_count')} botones revisados",
            f"- {menu.get('missing_handlers')} callbacks sin handler",
            f"- {menu.get('missing_permissions')} callbacks admin sin permiso",
            f"- {menu.get('repeated_callbacks')} callbacks repetidos"
        ])


        if menu.get("suspicious_duplicates"):

            lines.append(f"- {menu.get('suspicious_duplicates')} duplicaciones sospechosas")


        if menu.get("same_menu_callbacks"):

            lines.append(f"- {menu.get('same_menu_callbacks')} botones parecen volver al mismo menú")


        for issue in menu.get("issues") or []:

            lines.append(f"- Revisión recomendada: {issue}")


    return "\n".join(lines)[:3900]


def format_admin_button_audit_detail(report, limit=70):

    details = report.get("details") or []
    lines = [
        "📋 Detalle de auditoría de botones",
        ""
    ]


    for index, detail in enumerate(details[:limit], start=1):

        lines.extend([
            f"{index}. {detail.get('state')} {detail.get('menu')}",
            f"Botón: {detail.get('text')}",
            f"Callback: {detail.get('callback_data')}",
            f"Observación: {detail.get('observation')}",
            ""
        ])


    if len(details) > limit:

        lines.append(f"Mostrando {limit} de {len(details)} botones. Usa la revisión por menús si necesitas más detalle.")


    return "\n".join(lines)[:3900]
