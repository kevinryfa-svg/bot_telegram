import os


# =========================
# CONFIG — LEÍDA DEL ENTORNO
# =========================
# Ya NO se hardcodean secretos en el repositorio. El token del bot, el
# grupo VIP y los IDs de admin se toman de variables de entorno (las
# mismas que ya usa main.py en producción).

TOKEN = os.environ.get("TOKEN", "")

# ID DEL GRUPO VIP
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))

# IDS DE ADMIN (admite "123" o "123,456" o "123 456")
_raw_admin_ids = (
    os.environ.get("ADMIN_IDS")
    or os.environ.get("ADMIN_ID", "")
)
ADMIN_IDS = [
    int(part)
    for part in _raw_admin_ids.replace(",", " ").split()
    if part.strip().lstrip("-").isdigit()
]
