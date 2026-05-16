import os


# =========================
# WEB SERVER — FLASK RUNNER
# =========================

def run_flask_app(app):

    port = int(
        os.environ.get("PORT", 8000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
