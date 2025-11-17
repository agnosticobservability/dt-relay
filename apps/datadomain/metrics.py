from typing import Dict, List

from server import util


METRIC_GROUPS = (
    (
        "# Filesystem capacity (bytes)",
        (
            ("filesystem.used.bytes", "usedBytes"),
            ("filesystem.available.bytes", "availableBytes"),
            ("filesystem.total.bytes", "totalBytes"),
        ),
    ),
    (
        "# Alerts",
        (
            ("alerts.critical.count", "criticalAlerts"),
            ("alerts.warning.count", "warningAlerts"),
        ),
    ),
    (
        "# Enclosures",
        (
            ("enclosures.normal.count", "enclosuresNormal"),
            ("enclosures.degraded.count", "enclosuresDegraded"),
        ),
    ),
    (
        "# Drives",
        (
            ("drives.operational.count", "drivesOperational"),
            ("drives.spare.count", "drivesSpare"),
            ("drives.failed.count", "drivesFailed"),
        ),
    ),
)


def build_lines(
    form_data: Dict[str, str],
    metric_prefix: str,
    dims: Dict[str, str],
    timestamp_ms: int,
) -> List[str]:
    builder = util.MetricsBuilder(
        metric_prefix=metric_prefix,
        dims=dims,
        timestamp_ms=None,
    )

    lines: List[str] = []
    for heading, metrics in METRIC_GROUPS:
        group_lines: List[str] = []
        for suffix, form_key in metrics:
            group_lines.extend(
                builder.build_line(suffix, form_data.get(form_key))
            )
        if group_lines:
            lines.extend(group_lines)

    return lines
