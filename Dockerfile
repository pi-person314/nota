# Single-instance production image: builds the SPA, then serves it and the
# API from one Flask/gunicorn process.

# --- Stage 1: build the frontend ---------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend runtime -------------------------------------------
FROM python:3.13-slim AS backend

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/nota ./nota
COPY backend/wsgi.py backend/gunicorn.conf.py ./

# Built SPA from stage 1, served by Flask (see nota/__init__.py's
# FRONTEND_DIST_DIR handling).
COPY --from=frontend-build /app/frontend/dist /app/frontend-dist

ENV FRONTEND_DIST_DIR=/app/frontend-dist
ENV APP_ENV=production
ENV PORT=5001

# --- Optional OMR: Audiveris (PDF -> MusicXML) --------------------------
# The official .deb bundles its own Java runtime, so no separate JRE is
# installed. The ubuntu22.04 build is chosen for its older glibc floor,
# which keeps it installable on current Debian-based python images.
# `apt install ./file.deb` resolves the package's system dependencies.
ARG AUDIVERIS_VERSION=5.11.0
ADD https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu22.04-x86_64.deb /tmp/audiveris.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends /tmp/audiveris.deb \
    && rm /tmp/audiveris.deb \
    && rm -rf /var/lib/apt/lists/*
ENV AUDIVERIS_PATH=/opt/audiveris/bin/Audiveris

# Audiveris ships no OCR language data; interactively it offers a download
# dialog, which a headless batch run can never show. Baking in the English
# tessdata lets its text recognition (titles, directions, lyrics) work.
ADD https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata /opt/tessdata/eng.traineddata
ENV TESSDATA_PREFIX=/opt/tessdata

# Persistent data (the SQLite database and uploaded/converted score files)
# should live on a mounted volume, not in the image, e.g.:
#   DATABASE_URL=sqlite:////data/nota.db
#   SCORE_STORAGE_DIR=/data/scores
# with /data mounted as a volume at deploy time. SECRET_KEY, CLAUDE_MODEL,
# and any OAuth/API credentials also need to be supplied as environment
# variables at deploy time (see backend/.env.example) — none of that is
# baked into this image.

EXPOSE 5001

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
