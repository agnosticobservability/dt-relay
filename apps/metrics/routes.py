from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from flask import Blueprint, current_app, redirect, request, url_for

from server import util

from . import metrics

logger = logging.getLogger(__name__)

bp = Blueprint(
    "metrics",
    __name__,
    url_prefix="/dt-relay/metrics",
    template_folder="templates",
)

METADATA = {
    "slug": "metrics",
    "name": "Generic Metrics",
    "description": "Submit arbitrary metrics with custom dimensions to Dynatrace.",
}


@bp.route("/", methods=["GET"])
def form():
    tenant_list = list(util.TenantRegistry.load().values())
    error = request.args.get("error")
    selected = request.args.getlist("tenant_ids") or [
        t.id for t in tenant_list if request.args.get(t.id)
    ]
    defaults = _form_defaults()

    return bp.render_template(
        "form.html",
        tenants=tenant_list,
        error=error,
        selected_tenants=selected,
        require_global_token=False,
        auth_configured=bool(current_app.config.get("AUTH_PASSWORD")),
        form_defaults=defaults,
        initial_dimensions=_initial_pairs("dim"),
        initial_metrics=_initial_pairs("metric"),
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
        return redirect(url_for("metrics.form", error="Select at least one tenant."))

    global_token = form_data.get("dt_token")
    timestamp_ms = _parse_timestamp(form_data.get("ts"))
    metric_prefix = form_data.get("metric_prefix") or current_app.config["METRIC_PREFIX"]
    metric_unit = form_data.get("metric_unit")

    dimension_pairs = metrics.extract_pairs(
        form_data.getlist("dim_keys"), form_data.getlist("dim_values")
    )
    metric_pairs = metrics.extract_pairs(
        form_data.getlist("metric_keys"), form_data.getlist("metric_values")
    )

    if not metric_pairs:
        return redirect(url_for("metrics.form", error="Add at least one metric."))

    tenant_results: List[Dict[str, object]] = []
    overall_success = True

    logger.info("Generic metrics ingest request received for tenants: %s", ",".join(tenant_ids))

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
                    "warnings": [],
                }
            )
            overall_success = False
            continue

        token_override = form_data.get(f"dt_token__{tenant.id}")
        token_to_use = token_override or global_token
        if not token_to_use:
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": "n/a",
                    "message": "Missing token",
                    "success": False,
                    "lines": "",
                    "warnings": [],
                }
            )
            overall_success = False
            continue

        merged_dims = util.merge_dimensions(tenant.static_dims, dimension_pairs)

        lines, skipped = metrics.build_lines(
            metric_pairs,
            metric_prefix=metric_prefix,
            dims=merged_dims,
            timestamp_ms=timestamp_ms,
            unit=metric_unit,
        )

        if not lines:
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": "n/a",
                    "message": "No numeric metric values provided",
                    "success": False,
                    "lines": "",
                    "warnings": skipped,
                }
            )
            overall_success = False
            continue

        try:
            response = util.post_metrics(tenant, token_to_use, lines)
            success = response.status_code in (200, 202)
            message = "Ingest accepted" if success else response.text or "Ingest failed"
            logger.info(
                "Generic metrics ingest for tenant %s returned status %s",
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
                    "warnings": skipped,
                }
            )
            if not success:
                overall_success = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("Generic metrics ingest error for tenant %s", tenant.id)
            tenant_results.append(
                {
                    "label": tenant.label,
                    "status": "error",
                    "message": str(exc),
                    "success": False,
                    "lines": "\n".join(lines),
                    "warnings": skipped,
                }
            )
            overall_success = False

    overall_status = "SUCCESS" if overall_success else "FAILURE"

    logger.info("Generic metrics ingest completed with overall status %s", overall_status)

    return bp.render_template(
        "results.html",
        overall_status=overall_status,
        tenant_results=tenant_results,
    )


def register(app):
    return bp, METADATA


def _form_defaults() -> Dict[str, str]:
    return {
        "metric_prefix": request.args.get("metric_prefix")
        or current_app.config["METRIC_PREFIX"],
        "metric_unit": request.args.get("metric_unit", ""),
        "ts": request.args.get("ts", ""),
    }


def _parse_timestamp(ts_value: str) -> int:
    if ts_value:
        try:
            return int(float(ts_value))
        except ValueError:
            pass
    return util.current_time_ms()


def _initial_pairs(param_prefix: str) -> List[Tuple[str, str]]:
    keys_param = f"{param_prefix}_key"
    values_param = f"{param_prefix}_value"
    keys = request.args.getlist(keys_param)
    values = request.args.getlist(values_param)
    if not keys and param_prefix == "dim":
        return [
            ("host", current_app.config["DEFAULT_DIM_HOST"]),
            ("environment", current_app.config["DEFAULT_DIM_ENVIRONMENT"]),
        ]
    pairs: List[Tuple[str, str]] = []
    for key, value in zip(keys, values):
        if not key and not value:
            continue
        pairs.append((key, value))
    return pairs or [("", "")]
