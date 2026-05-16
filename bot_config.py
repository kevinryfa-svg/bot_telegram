import os


# =========================
# BOT CONFIG — ENVIRONMENT
# =========================

TOKEN = os.environ.get("TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
SERVER_URL = os.environ.get("SERVER_URL")

ADMIN_ID = int(
    os.environ.get("ADMIN_ID", "8761243211")
)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")


# =========================
# BOT CONFIG — HELPERS
# =========================

def get_token():

    return TOKEN



def get_admin_id():

    return ADMIN_ID



def get_group_id(default=0):

    if GROUP_ID:

        return GROUP_ID


    return default



def get_server_url():

    return SERVER_URL
