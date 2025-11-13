import json
import os
import pathlib
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

import requests

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"


@dataclass
class Tenant:
    id: str
    label: str
    base_url: str
    metric_prefix: Optional[str]
    static_dims: Dict[str, str]


class TenantRegistry:
    """Lazy loader for tenant configuration."""

    _tenants: Optional[Dict[str, Tenant]] = None

    @classmethod
    def load(cls) -> Dict[str, Tenant]:
        if cls._tenants is not None:
            return cls._tenants

        tenants_path = CONFIG_DIR / "tenants.json"
        with tenants_path.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)

        tenants: Dict[str, Tenant] = {}
        if isinstance(raw, dict):
            iterable = raw.values()
        else:
            iterable = raw

        for entry in iterable:
            tenant = Tenant(
                id=entry["id"],
                label=entry.get("label", entry["id"]),
                base_url=entry["baseUrl"].rstrip("/"),
                metric_prefix=entry.get("metricPrefix"),
                static_dims=entry.get("staticDims", {}) or {},
            )
            tenants[tenant.id] = tenant
        cls._tenants = tenants
        return tenants


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


_KEY_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_.:-]")
_METRIC_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.:-]*$")
_DIM_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.:-]*$")


def _normalise_key(raw: Optional[str]) -> str:
    """Return a Dynatrace compatible metric or dimension key fragment."""

    if raw is None:
        return ""

    cleaned = raw.strip().replace(" ", "_")
    if not cleaned:
        return ""

    cleaned = _KEY_INVALID_CHARS.sub("_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_.:-")

    if not cleaned:
        return ""

    if not cleaned[0].isalpha():
        return ""

    return cleaned


def escape_dimension(value: str) -> str:
    replacers = {"\\": "\\\\", ",": "\\,", " ": "\\ ", "=": "\\="}
    escaped = []
    for ch in value:
        escaped.append(replacers.get(ch, ch))
    return "".join(escaped)


def normalise_dimension_key(raw_key: Optional[str]) -> str:
    key = _normalise_key(raw_key)
    if key and _DIM_KEY_PATTERN.match(key):
        return key
    return ""


def normalise_metric_key(metric_prefix: Optional[str], raw_key: Optional[str]) -> str:
    suffix = _normalise_key(raw_key)
    if not suffix:
        return ""

    prefix = _normalise_key(metric_prefix)
    if prefix:
        if suffix.startswith(prefix):
            candidate = suffix
        else:
            candidate = f"{prefix}.{suffix}"
    else:
        candidate = suffix

    if _METRIC_KEY_PATTERN.match(candidate):
        return candidate
    return ""


def sanitize_dims(values: Dict[str, str]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for raw_key, raw_value in values.items():
        if raw_value in (None, ""):
            continue
        key = normalise_dimension_key(raw_key)
        if not key:
            continue
        sanitized[key] = escape_dimension(str(raw_value))
    return sanitized


def escape_metadata_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_unit_metadata(metric_name: str, unit: Optional[str]) -> Optional[str]:
    if not unit:
        return None
    cleaned = unit.strip()
    if not cleaned:
        return None
    escaped = escape_metadata_value(cleaned)
    return f"#{metric_name} gauge dt.meta.unit=\"{escaped}\""


NUMERIC_KEYS = {
    "totalBytes": "filesystem.total.bytes",
    "usedBytes": "filesystem.used.bytes",
    "availableBytes": "filesystem.available.bytes",
    "criticalAlerts": "alerts.critical.count",
    "warningAlerts": "alerts.warning.count",
    "enclosuresNormal": "enclosures.normal.count",
    "enclosuresDegraded": "enclosures.degraded.count",
    "drivesOperational": "drives.operational.count",
    "drivesSpare": "drives.spare.count",
    "drivesFailed": "drives.failed.count",
}


class MetricsBuilder:
    def __init__(
        self,
        metric_prefix: str,
        dims: Dict[str, str],
        timestamp_ms: Optional[int],
    ):
        self.metric_prefix = metric_prefix
        self.dims = sanitize_dims(dims)
        self.timestamp_ms = timestamp_ms

    def build_line(
        self, metric_suffix: str, value: str, unit: Optional[str] = None
    ) -> List[str]:
        try:
            numeric_value = Decimal(str(value))
        except (InvalidOperation, TypeError):
            return []

        metric_name = normalise_metric_key(self.metric_prefix, metric_suffix)
        if not metric_name:
            return []

        dims = ",".join(f"{k}={v}" for k, v in self.dims.items())
        if dims:
            metric_fragment = f"{metric_name},{dims}"
        else:
            metric_fragment = metric_name

        if numeric_value == numeric_value.to_integral():
            normalized = numeric_value.quantize(Decimal("1"))
        else:
            normalized = numeric_value.normalize()
        value_fragment = format(normalized, "f")

        if self.timestamp_ms is not None:
            return [f"{metric_fragment} {value_fragment} {self.timestamp_ms}"]

        return [f"{metric_fragment} {value_fragment}"]

    def from_form(
        self, form_data: Dict[str, str], units: Optional[Dict[str, str]] = None
    ) -> List[str]:
        lines: List[str] = []
        unit_map = units or {}
        for key, suffix in NUMERIC_KEYS.items():
            unit = unit_map.get(key)
            line_entries = self.build_line(suffix, form_data.get(key), unit=unit)
            if line_entries:
                lines.extend(line_entries)
        return lines


def current_time_ms() -> int:
    return int(time.time() * 1000)


class IngestError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def post_metrics(tenant: Tenant, token: str, lines: List[str]) -> requests.Response:
    url = f"{tenant.base_url}/api/v2/metrics/ingest"
    payload = "\n".join(lines)
    headers = {
        "Authorization": f"Api-Token {token}",
        "Content-Type": "text/plain; charset=utf-8",
    }
    response = requests.post(url, data=payload.encode("utf-8"), headers=headers, timeout=10)
    return response


def merge_dimensions(*dicts: Dict[str, str]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for d in dicts:
        merged.update({k: v for k, v in (d or {}).items() if v not in (None, "")})
    return merged
