import importlib
import os
import pathlib
from typing import Dict, List

from flask import Flask, render_template, url_for

from . import util

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / "apps"


class SubApp:
    def __init__(self, name: str, blueprint, metadata: Dict[str, str]):
        self.name = name
        self.blueprint = blueprint
        self.metadata = metadata


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "apps"))
    app.config["AUTH_PASSWORD"] = util.get_env("AUTH_PASSWORD", None)
    app.config["DEFAULT_DIM_SYSTEM"] = os.getenv("DEFAULT_DIM_SYSTEM", "dd-system-01")
    app.config["DEFAULT_DIM_SITE"] = os.getenv("DEFAULT_DIM_SITE", "primary-dc")
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
            "core/index.html",
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
