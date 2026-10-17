FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app

# LibreOffice (Writer only, no GUI) turns letters into PDF for the Canva/Figma exports.
# Carlito/Liberation are free fonts with the same sizes as Calibri/Arial/Times, so pages break as in Word.
RUN apt-get update  && apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-crosextra-carlito fonts-liberation fonts-dejavu-core  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir -e ".[dev]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
