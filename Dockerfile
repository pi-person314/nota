# Single-instance production image: builds the SPA, then serves it and the
# API from one Flask/gunicorn process.

# --- Stage 1: build the frontend ---------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# The shared openWakeWord feature-extraction models are third-party and
# deliberately not committed (see frontend/.gitignore), so fetch them into
# the public directory for Vite to copy into dist alongside the checked-in
# wake-word model.
ARG OPENWAKEWORD_VERSION=v0.5.1
ADD https://github.com/dscripka/openWakeWord/releases/download/${OPENWAKEWORD_VERSION}/melspectrogram.onnx public/oww/melspectrogram.onnx
ADD https://github.com/dscripka/openWakeWord/releases/download/${OPENWAKEWORD_VERSION}/embedding_model.onnx public/oww/embedding_model.onnx

# All three models have to reach dist or the wake word cannot load at
# runtime. Checking here fails the build instead of shipping an image whose
# only symptom is the browser reporting the models as missing.
RUN npm run build \
    && test -s dist/oww/hey_nota.onnx \
    && test -s dist/oww/melspectrogram.onnx \
    && test -s dist/oww/embedding_model.onnx

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
# The package's post-install script registers a desktop menu entry through
# xdg-desktop-menu, which needs a writable "applications" directory under
# one of the XDG data dirs. An image with no desktop stack has none, so
# that step aborts and dpkg fails the whole install — even though the
# application itself unpacked correctly and a headless server has no use
# for a menu entry anyway.
#
# The directories are created first so the registration can simply
# succeed where possible. Its failure is tolerated regardless, because
# nothing here depends on it: dependencies are configured before the
# package itself, so a failure at this point leaves a working install
# with only the menu entry missing. The checks afterwards are what
# actually gate the build — a genuinely missing or broken Audiveris fails
# here rather than becoming a server that quietly reports PDF import as
# unconfigured at runtime.
#
# GTK is installed alongside it because Audiveris reaches for libgtk-3
# through JNA even on a batch run, and a slim Python image carries no
# desktop libraries at all. Debian renamed this package with a "t64"
# suffix during the 64-bit time_t transition, so both names are tried.
RUN mkdir -p /usr/share/applications /usr/local/share/applications /usr/share/desktop-directories \
    && apt-get update \
    && { apt-get install -y --no-install-recommends /tmp/audiveris.deb || true; } \
    && { apt-get install -y --no-install-recommends libgtk-3-0t64 \
         || apt-get install -y --no-install-recommends libgtk-3-0; } \
    && rm /tmp/audiveris.deb \
    && rm -rf /var/lib/apt/lists/* \
    && test -x /opt/audiveris/bin/Audiveris

# No display exists here, so tell the JVM up front rather than letting AWT
# discover it by failing to load a native desktop library mid-conversion.
ENV JAVA_TOOL_OPTIONS=-Djava.awt.headless=true
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
