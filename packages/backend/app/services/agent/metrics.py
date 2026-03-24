"""Agent Metrics — track usage, performance, costs.

Simple in-memory counters for now. Can be replaced with Prometheus later.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Global counters (thread-safe enough for single-worker uvicorn)
_counters: dict[str, int] = defaultdict(int)
_histograms: dict[str, list[float]] = defaultdict(list)
_start_time = time.monotonic()


def increment(metric: str, value: int = 1) -> None:
    """Increment a counter metric."""
    _counters[metric] += value


def observe(metric: str, value: float) -> None:
    """Record a value in a histogram metric."""
    _histograms[metric].append(value)
    # Keep only last 1000 observations to prevent memory leak
    if len(_histograms[metric]) > 1000:
        _histograms[metric] = _histograms[metric][-500:]


def get_metrics() -> dict:
    """Return all metrics as a dict."""
    uptime = time.monotonic() - _start_time
    result = {
        "uptime_seconds": round(uptime, 1),
        "timestamp": datetime.now(UTC).isoformat(),
        "counters": dict(_counters),
        "histograms": {},
    }

    for name, values in _histograms.items():
        if values:
            result["histograms"][name] = {
                "count": len(values),
                "avg": round(sum(values) / len(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "p50": round(sorted(values)[len(values) // 2], 3),
            }

    return result


@dataclass
class AgentTimer:
    """Context manager to time agent operations."""

    metric_name: str
    _start: float = field(default=0, init=False)

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *args):
        elapsed = time.monotonic() - self._start
        observe(self.metric_name, elapsed)
        increment(f"{self.metric_name}_count")
