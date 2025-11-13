import json
import os
import pathlib
import re
import time
from dataclasses import dataclass
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


NUMERIC_KEYS = {
    "totalSpace": "total_space",
    "usedSpace": "used_space",
    "availableSpace": "available_space",
    "preComp": "pre_compressed_bytes",
    "postComp": "post_compressed_bytes",
    "totalCompFactor": "compression_factor",
}


class MetricsBuilder:
    def __init__(self, metric_prefix: str, dims: Dict[str, str], timestamp_ms: int):
        self.metric_prefix = metric_prefix
        self.dims = sanitize_dims(dims)
        self.timestamp_ms = timestamp_ms

    def build_line(self, metric_suffix: str, value: str) -> Optional[str]:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None

        metric_name = normalise_metric_key(self.metric_prefix, metric_suffix)
        if not metric_name:
            return None

        dims = ",".join(f"{k}={v}" for k, v in self.dims.items())
        if dims:
            metric_fragment = f"{metric_name},{dims}"
        else:
            metric_fragment = metric_name
        return f"{metric_fragment} {numeric_value} {self.timestamp_ms}"

    def from_form(self, form_data: Dict[str, str]) -> List[str]:
        lines: List[str] = []
        for key, suffix in NUMERIC_KEYS.items():
            line = self.build_line(suffix, form_data.get(key))
            if line:
                lines.append(line)
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
