import importlib
import json
import logging
import os
import pathlib
import re
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Mapping

from flask import Flask, Response, render_template, url_for

from . import util

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
    app.config["METRICS_CUSTOM_LABELS"] = _parse_custom_metric_labels(
        os.getenv("METRICS_CUSTOM_LABELS", "")
    )

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

    @app.route("/metrics/")
    def metrics():
        payload = _build_metrics_payload(subapps, app.config["METRICS_CUSTOM_LABELS"])
        return Response(payload, content_type="text/plain; charset=utf-8")

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


def _parse_custom_metric_labels(raw: str) -> Dict[str, str]:
    """Parse the METRICS_CUSTOM_LABELS environment variable.

    The value can be either a JSON object or a comma-separated list of
    ``key=value`` pairs. Invalid entries are ignored.
    """

    if not raw:
        return {}

    raw = raw.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    else:
        if isinstance(parsed, dict):
            return {str(k).strip(): str(v) for k, v in parsed.items() if str(k).strip()}

    labels: Dict[str, str] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        if "=" not in piece:
            logging.getLogger(__name__).warning(
                "Ignoring custom metrics label without '=': %s", piece
            )
            continue
        key, value = piece.split("=", 1)
        key = key.strip()
        if not key:
            logging.getLogger(__name__).warning(
                "Ignoring custom metrics label with empty key"
            )
            continue
        labels[key] = value.strip()
    return labels


def _build_metrics_payload(subapps: List[SubApp], custom_labels: Mapping[str, str]) -> str:
    sections: List[List[str]] = []

    tenant_count = len(util.TenantRegistry.load())
    sections.append(
        [
            "# HELP dt_relay_tenants Number of configured Dynatrace tenants.",
            "# TYPE dt_relay_tenants gauge",
            f"dt_relay_tenants {tenant_count}",
        ]
    )

    sections.append(
        [
            "# HELP dt_relay_subapps Number of registered dt-relay sub-applications.",
            "# TYPE dt_relay_subapps gauge",
            f"dt_relay_subapps {len(subapps)}",
        ]
    )

    if subapps:
        subapp_info: List[str] = [
            "# HELP dt_relay_subapp_info dt-relay sub-application metadata.",
            "# TYPE dt_relay_subapp_info gauge",
        ]
        for subapp in subapps:
            labels = {
                "slug": subapp.metadata.get("slug") or subapp.name,
                "name": subapp.metadata.get("name") or subapp.name,
            }
            description = subapp.metadata.get("description")
            if description:
                labels["description"] = description
            subapp_info.append(
                f"dt_relay_subapp_info{{{_format_metric_labels(labels)}}} 1"
            )
        sections.append(subapp_info)

    if custom_labels:
        sections.append(
            [
                "# HELP dt_relay_custom_labels Custom key/value metadata attached to dt-relay metrics.",
                "# TYPE dt_relay_custom_labels gauge",
                f"dt_relay_custom_labels{{{_format_metric_labels(custom_labels)}}} 1",
            ]
        )

    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def _format_metric_labels(labels: Mapping[str, str]) -> str:
    formatted = []
    for key, value in sorted(labels.items()):
        name = _sanitize_label_name(str(key))
        formatted.append(f'{name}="{_escape_label_value(str(value))}"')
    return ",".join(formatted)


_INVALID_LABEL_CHARS = re.compile(r"[^a-zA-Z0-9_]")


def _sanitize_label_name(name: str) -> str:
    sanitized = _INVALID_LABEL_CHARS.sub("_", name.strip())
    if not sanitized:
        return "_"
    if sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def _escape_label_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    )


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
