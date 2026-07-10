"""Development entrypoint: `python run.py`."""

from nota import create_app

app = create_app()

if __name__ == "__main__":
    cfg = app.config["NOTA_CONFIG"]
    app.run(port=cfg.port, debug=True)
