from typing import Dict, List

from server import util


def build_lines(form_data: Dict[str, str], metric_prefix: str, dims: Dict[str, str], timestamp_ms: int) -> List[str]:
    builder = util.MetricsBuilder(metric_prefix=metric_prefix, dims=dims, timestamp_ms=timestamp_ms)
    return builder.from_form(form_data)
