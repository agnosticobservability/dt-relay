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

    Metric keys are normalised to comply with Dynatrace's ingestion
    protocol before being combined with the optional prefix.
    """

    lines: List[str] = []
    skipped: List[str] = []
    sanitized_dims = util.sanitize_dims(dims)
    dims_fragment = ""
    if sanitized_dims:
        dims_fragment = "," + ",".join(f"{k}={v}" for k, v in sanitized_dims.items())

    for raw_key, raw_value in metric_items.items():
        metric_name = util.normalise_metric_key(metric_prefix, raw_key)
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

