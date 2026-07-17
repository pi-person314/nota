"""Development entrypoint: `python run.py`."""

from pathlib import Path

from dotenv import load_dotenv

from nota import create_app

# Populate os.environ from backend/.env before the app reads configuration.
# Variables already present in the process environment take precedence.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

app = create_app()

if __name__ == "__main__":
    cfg = app.config["NOTA_CONFIG"]
    app.run(port=cfg.port, debug=True)
