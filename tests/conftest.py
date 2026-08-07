"""
Entorno mínimo para los tests.

Algunos módulos del bot hacen trabajo al importarse (por ejemplo main.py crea
el objeto Bot de Telegram), así que sin estas variables la recogida de tests
falla antes de ejecutar nada. Definirlas aquí hace que la suite funcione igual
en local y en CI, sin depender de que quien la lance recuerde exportarlas.

Se usa setdefault: si el entorno ya trae un valor, se respeta.
"""

import os

os.environ.setdefault("TOKEN", "0000000000:test-token-for-tests")
os.environ.setdefault("GROUP_ID", "0")
os.environ.setdefault("ADMIN_ID", "8761243211")

# Cadena válida en forma, pero a una base de datos inexistente: la conexión es
# perezosa, así que importar módulos no intenta conectarse.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://tests:tests@127.0.0.1:5432/tests_no_conectar"
)

# Los tests no deben llamar a servicios externos.
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("STRIPE_SECRET_KEY", "")
os.environ.setdefault("REENGAGEMENT_ENABLED", "false")
