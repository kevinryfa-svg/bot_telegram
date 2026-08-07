FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# postgresql-client-18 trae pg_dump, que es lo que usa la copia de seguridad
# para producir un volcado restaurable de una sola orden. Se instala desde el
# repositorio oficial de PostgreSQL y no desde Debian porque el de Debian trae
# la versión 15, y pg_dump se niega a volcar un servidor más nuevo que él: la
# base de datos de producción es PostgreSQL 18.
#
# El nombre de la distribución se saca de /etc/os-release en vez de escribirlo
# a mano: así, si la imagen base de Python cambia de Debian, el repositorio
# sigue siendo el correcto.
#
# Si esto no estuviera disponible, la copia sigue haciéndose en CSV por tabla
# (ver db_backup_service.py): pg_dump mejora la restauración, no la habilita.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
