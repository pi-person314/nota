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
