"""
Copia de seguridad de la base de datos del bot.

Contexto: este mes la base de datos de producción desapareció y el bot estuvo
parado casi un mes. Los datos se recuperaron porque el servicio de Postgres se
pudo volver a crear, pero no existía ninguna copia propia: si el volumen se
hubiese perdido, se habrían perdido usuarios, pagos, accesos y enlaces.

Esta copia no depende de Railway ni de ningún almacenamiento contratado: el
volcado se comprime y se envía al super admin como documento de Telegram, que
es gratis, queda fuera de la máquina y sobrevive a que el contenedor se
recicle.

Dos formas de volcar, en este orden:
  1. pg_dump, si está instalado en la imagen: es el formato que restaura mejor.
  2. Volcado propio en CSV por tabla con COPY, empaquetado en tar.gz. No
     necesita ninguna herramienta externa, así que siempre hay copia.
"""

import gzip
import io
import os
import shutil
import subprocess
import tarfile
import time

import requests

from db import conn, DATABASE_URL


# =========================
# CONFIGURACIÓN
# =========================

BACKUP_ENABLED = os.environ.get(
    "DB_BACKUP_ENABLED", "true"
).strip().lower() not in ("0", "false", "no")

# Una copia al día es suficiente para estos datos y no molesta con documentos.
BACKUP_INTERVAL_HOURS = float(
    os.environ.get("DB_BACKUP_INTERVAL_HOURS", "24")
)

# Telegram rechaza documentos de bot por encima de 50 MB. Se avisa antes de
# intentarlo para que el fallo no sea un error opaco de la API.
BACKUP_MAX_BYTES = int(
    os.environ.get("DB_BACKUP_MAX_BYTES", str(45 * 1024 * 1024))
)

# pg_dump puede tardar; sin tope, un volcado colgado bloquearía el job.
BACKUP_TIMEOUT_SECONDS = int(
    os.environ.get("DB_BACKUP_TIMEOUT_SECONDS", "300")
)

# Tablas que no merece la pena copiar: son registros de actividad que crecen
# mucho y no hacen falta para reconstruir el negocio (usuarios, pagos, accesos).
BACKUP_SKIP_TABLES = {
    name.strip()
    for name in os.environ.get(
        "DB_BACKUP_SKIP_TABLES",
        "bot_user_events,user_activity_log,audit_log"
    ).split(",")
    if name.strip()
}


# =========================
# QUÉ TABLAS COPIAR
# =========================

def list_backup_tables():
    """Tablas de datos del esquema public, sin las de actividad."""

    with conn.cursor() as cur:

        cur.execute("""

            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            AND table_type='BASE TABLE'
            ORDER BY table_name

        """)

        rows = cur.fetchall()


    return [
        row[0]
        for row in rows
        if row[0] not in BACKUP_SKIP_TABLES
    ]


def count_rows(table):

    try:

        with conn.cursor() as cur:

            cur.execute(f'SELECT COUNT(*) FROM "{table}"')

            return int(cur.fetchone()[0] or 0)

    except Exception:

        return 0


# =========================
# VOLCADO CON pg_dump
# =========================

def pg_dump_available():

    return bool(shutil.which("pg_dump"))


def build_pg_dump(database_url=None):
    """Devuelve (contenido_gzip, detalle) o (None, motivo del fallo)."""

    if not pg_dump_available():

        return None, "pg_dump no está instalado en la imagen"


    url = database_url or DATABASE_URL

    if not url:

        return None, "DATABASE_URL no está definida"


    try:

        result = subprocess.run(
            [
                "pg_dump",
                "--no-owner",
                "--no-privileges",
                url
            ],
            capture_output=True,
            timeout=BACKUP_TIMEOUT_SECONDS
        )

    except subprocess.TimeoutExpired:

        return None, f"pg_dump excedió {BACKUP_TIMEOUT_SECONDS}s"

    except Exception as e:

        return None, f"pg_dump falló: {type(e).__name__}: {e}"


    if result.returncode != 0:

        detail = (result.stderr or b"").decode("utf-8", "replace")[:300]

        return None, f"pg_dump devolvió {result.returncode}: {detail}"


    if not result.stdout:

        return None, "pg_dump no produjo salida"


    return gzip.compress(result.stdout), "pg_dump"


# =========================
# VOLCADO PROPIO EN CSV
# =========================

def dump_table_csv(table):
    """Contenido CSV de una tabla, con cabecera, usando COPY."""

    buffer = io.StringIO()

    with conn.cursor() as cur:

        cur.copy_expert(
            f'COPY "{table}" TO STDOUT WITH CSV HEADER',
            buffer
        )


    return buffer.getvalue()


def build_csv_backup(tables=None):
    """
    tar.gz con un CSV por tabla. No necesita herramientas externas, así que
    funciona en cualquier imagen. Devuelve (contenido, detalle).
    """

    table_names = tables if tables is not None else list_backup_tables()

    if not table_names:

        return None, "no hay tablas que copiar"


    archive = io.BytesIO()
    exported = 0
    failed = []

    with tarfile.open(fileobj=archive, mode="w:gz") as tar:

        for table in table_names:

            try:

                payload = dump_table_csv(table).encode("utf-8")

            except Exception as e:

                # Una tabla ilegible no debe tirar la copia de las demás.
                failed.append(f"{table} ({type(e).__name__})")

                continue


            info = tarfile.TarInfo(name=f"{table}.csv")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

            exported += 1


    if not exported:

        return None, "ninguna tabla se pudo exportar"


    detail = f"CSV ({exported} tablas)"

    if failed:

        detail += f", fallaron: {', '.join(failed[:5])}"


    return archive.getvalue(), detail


# =========================
# CONSTRUIR LA COPIA
# =========================

def build_backup():
    """
    Intenta pg_dump y, si no está disponible, cae al volcado CSV.
    Devuelve (contenido, nombre_de_fichero, detalle) o (None, None, motivo).
    """

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

    payload, detail = build_pg_dump()

    if payload:

        return payload, f"backup-{stamp}.sql.gz", detail


    fallback_reason = detail

    payload, detail = build_csv_backup()

    if payload:

        return (
            payload,
            f"backup-{stamp}.tar.gz",
            f"{detail} — sin pg_dump: {fallback_reason}"
        )


    return None, None, f"{fallback_reason}; {detail}"


# =========================
# ENVÍO POR TELEGRAM
# =========================

def send_backup_document(token, chat_id, payload, filename, caption):
    """Envía la copia como documento. Devuelve (ok, detalle)."""

    if len(payload) > BACKUP_MAX_BYTES:

        return False, (
            f"la copia pesa {format_size(len(payload))} y Telegram no acepta "
            f"documentos de bot tan grandes (límite usado: "
            f"{format_size(BACKUP_MAX_BYTES)})"
        )


    try:

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": caption[:1024]
            },
            files={
                "document": (filename, payload)
            },
            timeout=BACKUP_TIMEOUT_SECONDS
        ).json()

    except Exception as e:

        return False, f"{type(e).__name__}: {e}"


    if not response.get("ok"):

        return False, str(response.get("description") or response)[:300]


    return True, "enviado"


# =========================
# FORMATO
# =========================

def format_size(num_bytes):

    size = float(num_bytes or 0)

    for unit in ("B", "KB", "MB", "GB"):

        if size < 1024 or unit == "GB":

            if unit == "B":

                return f"{int(size)} {unit}"


            return f"{size:.1f} {unit}"


        size /= 1024


    return f"{int(size)} B"


def build_backup_caption(filename, payload_size, detail, tables, rows):

    return (
        "🗄️ Copia de seguridad de la base de datos\n\n"
        f"Fichero: {filename}\n"
        f"Tamaño: {format_size(payload_size)}\n"
        f"Tablas: {tables}\n"
        f"Registros: {rows}\n"
        f"Método: {detail}\n\n"
        "Guarda este fichero fuera de Telegram si quieres conservarlo a largo "
        "plazo."
    )


# =========================
# REGISTRO DE COPIAS
# =========================

def record_backup(status, method=None, filename=None, size_bytes=0,
                  table_count=0, row_count=0, detail=None):

    try:

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO database_backups
                (status, method, filename, size_bytes, table_count,
                 row_count, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s)

            """, (
                status,
                method,
                filename,
                int(size_bytes or 0),
                int(table_count or 0),
                int(row_count or 0),
                (detail or "")[:500]
            ))

        return True

    except Exception as e:

        print("No se pudo registrar la copia de seguridad:", e)

        return False


def fetch_last_backup():
    """Última copia registrada, para mostrarla en el panel."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT created_at, status, method, filename, size_bytes,
                       table_count, row_count, detail
                FROM database_backups
                ORDER BY created_at DESC
                LIMIT 1

            """)

            row = cur.fetchone()

    except Exception as e:

        print("No se pudo leer la última copia:", e)

        return None


    if not row:

        return None


    return {
        "created_at": row[0],
        "status": row[1],
        "method": row[2],
        "filename": row[3],
        "size_bytes": row[4],
        "table_count": row[5],
        "row_count": row[6],
        "detail": row[7]
    }


def hours_since_last_success():
    """Horas desde la última copia correcta, o None si no hay ninguna."""

    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 3600.0
                FROM database_backups
                WHERE status='ok'

            """)

            row = cur.fetchone()

    except Exception as e:

        print("No se pudo calcular la antigüedad de la copia:", e)

        return None


    if not row or row[0] is None:

        return None


    return float(row[0])


def backup_is_due():
    """¿Toca copia? Sin copias previas, sí."""

    if not BACKUP_ENABLED:

        return False


    hours = hours_since_last_success()

    if hours is None:

        return True


    return hours >= max(BACKUP_INTERVAL_HOURS, 1)


# =========================
# PROCESO COMPLETO
# =========================

def run_database_backup(token, chat_ids, force=False):
    """
    Crea la copia y la envía a los destinatarios indicados.
    Devuelve un resumen con lo ocurrido, sin lanzar excepciones.
    """

    summary = {
        "created": False,
        "sent": 0,
        "failed": 0,
        "skipped": False,
        "filename": None,
        "size_bytes": 0,
        "detail": None
    }


    if not BACKUP_ENABLED and not force:

        summary["skipped"] = True
        summary["detail"] = "copias desactivadas (DB_BACKUP_ENABLED)"

        return summary


    if not force and not backup_is_due():

        summary["skipped"] = True
        summary["detail"] = "todavía no toca"

        return summary


    try:

        tables = list_backup_tables()
        rows = sum(count_rows(table) for table in tables)

    except Exception as e:

        tables, rows = [], 0

        print("No se pudieron contar las tablas para la copia:", e)


    try:

        payload, filename, detail = build_backup()

    except Exception as e:

        payload, filename = None, None
        detail = f"{type(e).__name__}: {e}"


    if not payload:

        summary["detail"] = detail

        record_backup(
            "error",
            table_count=len(tables),
            row_count=rows,
            detail=detail
        )

        return summary


    summary["created"] = True
    summary["filename"] = filename
    summary["size_bytes"] = len(payload)
    summary["detail"] = detail

    caption = build_backup_caption(
        filename,
        len(payload),
        detail,
        len(tables),
        rows
    )

    send_errors = []

    for chat_id in chat_ids or []:

        ok, send_detail = send_backup_document(
            token,
            chat_id,
            payload,
            filename,
            caption
        )

        if ok:

            summary["sent"] += 1

        else:

            summary["failed"] += 1

            send_errors.append(f"{chat_id}: {send_detail}")


    if send_errors:

        summary["detail"] = f"{detail} — envíos fallidos: " + "; ".join(
            send_errors[:3]
        )


    # Una copia que se crea pero no llega a nadie no protege de nada: se
    # registra como error para que el panel no diga que todo va bien.
    record_backup(
        "ok" if summary["sent"] > 0 else "error",
        method=detail,
        filename=filename,
        size_bytes=len(payload),
        table_count=len(tables),
        row_count=rows,
        detail=summary["detail"]
    )

    return summary


def run_backup_now(force=False):
    """
    Punto de entrada único: crea la copia y la envía a los super admins.

    Vive aquí, y no en main.py, a propósito: importar main construye el objeto
    Bot de Telegram, así que el botón del panel habría dependido de que el
    token fuese válido para poder ni siquiera intentar la copia.

    Es trabajo bloqueante (volcado y subida del fichero): llámalo desde un
    hilo, no directamente dentro del bucle asíncrono del bot.
    """

    from config import ADMIN_IDS, TOKEN
    from notification_service import get_super_admin_ids

    return run_database_backup(
        TOKEN,
        get_super_admin_ids(ADMIN_IDS[0] if ADMIN_IDS else None),
        force=force
    )


def describe_last_backup():
    """Resumen legible de la última copia, para el panel de administración."""

    last = fetch_last_backup()

    if not last:

        return (
            "🗄️ Copias de seguridad\n\n"
            "Todavía no se ha hecho ninguna copia.\n"
            f"Frecuencia configurada: cada {BACKUP_INTERVAL_HOURS:g} h."
        )


    icon = "✅" if last["status"] == "ok" else "⚠️"

    created = last["created_at"]
    created_text = (
        created.strftime("%d/%m/%Y %H:%M")
        if hasattr(created, "strftime") else str(created)
    )

    lines = [
        "🗄️ Copias de seguridad",
        "",
        f"{icon} Última: {created_text}",
        f"Fichero: {last['filename'] or '—'}",
        f"Tamaño: {format_size(last['size_bytes'])}",
        f"Tablas: {last['table_count']}   Registros: {last['row_count']}",
        f"Frecuencia: cada {BACKUP_INTERVAL_HOURS:g} h"
    ]

    if last["status"] != "ok" and last["detail"]:

        lines.append("")
        lines.append(f"Motivo: {last['detail']}")


    return "\n".join(lines)
