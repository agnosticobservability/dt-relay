import logging
from typing import Dict, List, Optional

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from server import util
from . import metrics, views

logger = logging.getLogger(__name__)

bp = Blueprint(
    "datadomain",
    __name__,
    url_prefix="/dt-relay/datadomain",
    template_folder="templates",
)

METADATA = {
    "slug": "datadomain",
    "name": "Datadomain",
    "description": "Ingest Data Domain storage metrics into Dynatrace.",
}


@bp.route("/", methods=["GET"])
def form():
    tenant_list = list(util.TenantRegistry.load().values())
    defaults = _form_defaults()
    error = request.args.get("error")
    selected = request.args.getlist("tenant_ids") or [t.id for t in tenant_list if request.args.get(t.id)]
    return render_template(
        views.FORM_TEMPLATE,
        tenants=tenant_list,
        error=error,
        selected_tenants=selected,
        form_defaults=defaults,
        auth_configured=bool(current_app.config.get("AUTH_PASSWORD")),
    )


@bp.route("/health", methods=["GET"])
def health():
    return ("ok", 200, {"Content-Type": "text/plain; charset=utf-8"})


@bp.route("/ingest", methods=["POST"])
def ingest():
    tenants = util.TenantRegistry.load()
    form_data = request.form

    expected_password = current_app.config.get("AUTH_PASSWORD", "")
    if not expected_password:
        return ("AUTH_PASSWORD is not configured on the server", 500)

    auth_password = form_data.get("auth_password")
    if not auth_password or auth_password != expected_password:
        return ("Unauthorized", 401)

    tenant_ids = form_data.getlist("tenant_ids")
    if not tenant_ids:
        return redirect(url_for("datadomain.form", error="Select at least one tenant."))

    dt_token = form_data.get("dt_token")
    if not dt_token:
        return redirect(url_for("datadomain.form", error="Provide a Dynatrace access token."))

    timestamp_ms = util.current_time_ms()

    tenant_results: List[Dict[str, object]] = []
    overall_success = True

    logger.info("Ingest request received for tenants: %s", ",".join(tenant_ids))

    for tenant_id in tenant_ids:
        tenant = tenants.get(tenant_id)
        if not tenant:
            tenant_results.append(
                {
                    "label": tenant_id,
                    "status": "n/a",
                    "message": "Unknown tenant",
                    "success": False,
                    "lines": "",
                }
            )
            overall_success = False
            continue

        logger.info("Preparing ingest payload for tenant %s", tenant.id)

        host_value = _first_non_empty(form_data.get("host"), form_data.get("system"))
        environment_value = _first_non_empty(
            form_data.get("environment"), form_data.get("site")
        )

        if not host_value or not environment_value:
            return redirect(
                url_for(
                    "datadomain.form",
                    error="Provide both host and environment.",
                    host=host_value,
                    environment=environment_value,
                )
            )

        dims = {
            "host": host_value,
            "environment": environment_value,
        }
        merged_dims = util.merge_dimensions(tenant.static_dims, dims)
        metric_prefix = tenant.metric_prefix or current_app.config["METRIC_PREFIX"]
        lines = metrics.build_lines(form_data, metric_prefix, merged_dims, timestamp_ms)

        if not lines:
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": "n/a",
                    "message": "No numeric values provided",
                    "success": False,
                    "lines": "",
                }
            )
            overall_success = False
            continue

        try:
            response = util.post_metrics(tenant, dt_token, lines)
            success = response.status_code in (200, 202)
            message = "Ingest accepted" if success else response.text or "Ingest failed"
            logger.info(
                "Ingest attempt for tenant %s returned status %s",
                tenant.id,
                response.status_code,
            )
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": response.status_code,
                    "message": message,
                    "success": success,
                    "lines": "\n".join(lines),
                }
            )
            if not success:
                overall_success = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ingest error for tenant %s", tenant.id)
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": "error",
                    "message": str(exc),
                    "success": False,
                    "lines": "\n".join(lines),
                }
            )
            overall_success = False

    overall_status = "SUCCESS" if overall_success else "FAILURE"

    logger.info(
        "Ingest request completed with overall status %s", overall_status
    )

    return render_template(
        views.RESULTS_TEMPLATE,
        overall_status=overall_status,
        tenant_results=tenant_results,
    )


def register(app):
    return bp, METADATA


def _first_non_empty(*candidates: Optional[str]) -> str:
    for candidate in candidates:
        if candidate is None:
            continue
        stripped = candidate.strip()
        if stripped:
            return stripped
    return ""


def _form_defaults():
    host_arg = request.args.get("host") or request.args.get("system")
    environment_arg = request.args.get("environment") or request.args.get("site")
    defaults = {
        "host": _first_non_empty(host_arg),
        "environment": _first_non_empty(environment_arg),
        "totalBytes": request.args.get("totalBytes", ""),
        "usedBytes": request.args.get("usedBytes", ""),
        "availableBytes": request.args.get("availableBytes", ""),
        "criticalAlerts": request.args.get("criticalAlerts", ""),
        "warningAlerts": request.args.get("warningAlerts", ""),
        "enclosuresNormal": request.args.get("enclosuresNormal", ""),
        "enclosuresDegraded": request.args.get("enclosuresDegraded", ""),
        "drivesOperational": request.args.get("drivesOperational", ""),
        "drivesSpare": request.args.get("drivesSpare", ""),
        "drivesFailed": request.args.get("drivesFailed", ""),
    }
    return defaults
