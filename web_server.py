import os


# =========================
# WEB SERVER — WSGI RUNNER
# =========================

def run_flask_app(app):

    port = int(
        os.environ.get("PORT", 8000)
    )


    # Servidor WSGI de producción (waitress). Atiende los webhooks de pago
    # (Stripe, PayPal, Revolut, ChangeNOW, Guardarian) y el healthcheck, así
    # que no debe usarse el servidor de desarrollo de Flask en producción.
    # Si waitress no estuviera disponible, se cae con seguridad al servidor
    # de desarrollo para no dejar el bot sin web server.
    try:

        from waitress import serve

        print(
            f"Servidor web (waitress) escuchando en 0.0.0.0:{port}"
        )

        serve(
            app,
            host="0.0.0.0",
            port=port,
            threads=8
        )

    except ImportError:

        print(
            "waitress no disponible; usando el servidor de desarrollo de Flask."
        )

        app.run(
            host="0.0.0.0",
            port=port
        )
