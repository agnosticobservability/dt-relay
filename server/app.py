import importlib
import logging
import os
import pathlib
from logging.handlers import RotatingFileHandler
from typing import Dict, List

from flask import Flask, render_template, url_for

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / "apps"
LOG_DIR = BASE_DIR / "logs"


def configure_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / "dt-relay.log"

        handler = RotatingFileHandler(log_file, maxBytes=1_048_576, backupCount=5)
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)

    except OSError as exc:
        for existing in root_logger.handlers:
            if isinstance(existing, logging.StreamHandler):
                break
        else:
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)

        root_logger.warning(
            "File logging disabled; falling back to stdout/stderr (%s)", exc,
        )
        return

    for existing in root_logger.handlers:
        if isinstance(existing, RotatingFileHandler) and getattr(existing, "baseFilename", None) == str(log_file):
            break
    else:
        root_logger.addHandler(handler)


class SubApp:
    def __init__(self, name: str, blueprint, metadata: Dict[str, str]):
        self.name = name
        self.blueprint = blueprint
        self.metadata = metadata


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__, template_folder=str(APPS_DIR / "core"))
    app.config["AUTH_PASSWORD"] = os.getenv("AUTH_PASSWORD", "")
    default_host = os.getenv("DEFAULT_DIM_HOST") or os.getenv(
        "DEFAULT_DIM_SYSTEM", "dd-system-01"
    )
    default_environment = os.getenv("DEFAULT_DIM_ENVIRONMENT") or os.getenv(
        "DEFAULT_DIM_SITE", "primary-dc"
    )
    app.config["DEFAULT_DIM_HOST"] = default_host
    app.config["DEFAULT_DIM_ENVIRONMENT"] = default_environment
    app.config["METRIC_PREFIX"] = os.getenv("METRIC_PREFIX", "custom.ddfs")

    subapps = load_subapps(app)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.route("/")
    @app.route("/dt-relay/")
    def index():
        subapp_links = [
            {**s.metadata, "url": url_for(f"{s.name}.form")}
            for s in subapps
        ]
        return render_template(
            "index.html",
            subapps=subapp_links,
        )

    @app.route("/health")
    @app.route("/dt-relay/health")
    def health():
        return ("ok", 200, {"Content-Type": "text/plain; charset=utf-8"})

    return app


def load_subapps(app: Flask) -> List[SubApp]:
    subapps: List[SubApp] = []
    for path in sorted(APPS_DIR.iterdir()):
        if not path.is_dir():
            continue
        module_name = f"apps.{path.name}.routes"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        register = getattr(module, "register", None)
        if not register:
            continue
        blueprint, metadata = register(app)
        app.register_blueprint(blueprint)
        subapps.append(SubApp(path.name, blueprint, metadata))
    app.config["SUBAPPS"] = subapps
    return subapps


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
