from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from server import util


def extract_pairs(keys: Iterable[str], values: Iterable[str]) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for key, value in zip(keys, values):
        cleaned_key = (key or "").strip()
        if not cleaned_key:
            continue
        if value in (None, ""):
            continue
        pairs[cleaned_key] = str(value)
    return pairs


def build_lines(
    metric_items: Dict[str, str],
    metric_prefix: str,
    dims: Dict[str, str],
    timestamp_ms: int,
) -> Tuple[List[str], List[str]]:
    """Return metric lines and skipped metric keys.

    Metric names are normalised by replacing whitespace with underscores
    and prepending the metric prefix when provided.
    """

    lines: List[str] = []
    skipped: List[str] = []
    # ``dims`` is expected to be sanitized by the caller (``merge_dimensions``)
    # so avoid escaping the values a second time, which would introduce
    # additional backslashes into the payload.
    dims_fragment = ""
    if dims:
        dims_fragment = "," + ",".join(f"{k}={v}" for k, v in dims.items())

    for raw_key, raw_value in metric_items.items():
        metric_name = _format_metric_name(metric_prefix, raw_key)
        if not metric_name:
            skipped.append(raw_key)
            continue
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            skipped.append(raw_key)
            continue
        line = f"{metric_name}{dims_fragment} {numeric_value} {timestamp_ms}"
        lines.append(line)

    return lines, skipped


def _format_metric_name(metric_prefix: str, metric_key: str) -> str:
    cleaned = (metric_key or "").strip()
    if not cleaned:
        return ""
    cleaned = "_".join(cleaned.split())
    if metric_prefix:
        if cleaned.startswith(metric_prefix):
            return cleaned
        return f"{metric_prefix}.{cleaned}"
    return cleaned
