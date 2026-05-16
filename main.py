import os
import stripe
import threading
import random
import string
import requests
import time
import asyncio

from flask import Flask, request, jsonify

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from datetime import datetime, timedelta


# =========================
# FORMATEAR TIEMPO RESTANTE
# =========================

def format_tiempo_restante(expiration):

    if expiration is None:

        return "♾️ Permanente"

    tiempo_restante = expiration - datetime.now()

    total_segundos = int(
        tiempo_restante.total_seconds()
    )

    if total_segundos <= 0:

        return "Expirado"

    dias = total_segundos // 86400

    horas = (

        total_segundos % 86400

    ) // 3600

    minutos = (

        total_segundos % 3600

    ) // 60


    # Protección contra mostrar 0m cuando aún quedan segundos

    if dias == 0 and horas == 0 and minutos == 0:

        minutos = 1


    # Mostrar SIEMPRE días, horas y minutos

    return (

        f"{dias}d "

        f"{horas}h "

        f"{minutos}m"

    )


from db import conn, create_tables
from admin_panel import build_admin_main_menu


# =========================
# CONFIG
# =========================

TOKEN = os.environ.get("TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
SERVER_URL = os.environ.get("SERVER_URL")

ADMIN_ID = 8761243211

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

bot = Bot(token=TOKEN)

telegram_app = ApplicationBuilder().token(TOKEN).build()

app = Flask(__name__)


# =========================
# HOME TEST
# =========================

@app.route("/")
def home():
    return "Bot funcionando"