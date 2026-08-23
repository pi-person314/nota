"""Production entrypoint: `gunicorn -c gunicorn.conf.py wsgi:app`."""

from pathlib import Path

from dotenv import load_dotenv

from nota import create_app

# Populate os.environ from backend/.env before the app reads configuration.
# Harmless in a deployment where the platform injects real environment
# variables directly (no .env file present, or variables already set take
# precedence over it).
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

app = create_app()
