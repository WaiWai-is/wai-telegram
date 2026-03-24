"""Tests for Agent Metrics system."""

from app.services.agent.metrics import (
    AgentTimer,
    _counters,
    _histograms,
    get_metrics,
    increment,
    observe,
)


class TestMetrics:
    def setup_method(self):
        _counters.clear()
        _histograms.clear()

    def test_increment_counter(self):
        increment("test_counter")
        assert _counters["test_counter"] == 1
        increment("test_counter", 5)
        assert _counters["test_counter"] == 6

    def test_observe_histogram(self):
        observe("test_hist", 1.5)
        observe("test_hist", 2.5)
        assert len(_histograms["test_hist"]) == 2

    def test_get_metrics_structure(self):
        increment("requests", 10)
        observe("latency", 0.5)
        metrics = get_metrics()
        assert "uptime_seconds" in metrics
        assert "timestamp" in metrics
        assert "counters" in metrics
        assert "histograms" in metrics
        assert metrics["counters"]["requests"] == 10
        assert metrics["histograms"]["latency"]["count"] == 1
        assert metrics["histograms"]["latency"]["avg"] == 0.5

    def test_histogram_stats(self):
        for i in range(10):
            observe("test", float(i))
        metrics = get_metrics()
        stats = metrics["histograms"]["test"]
        assert stats["count"] == 10
        assert stats["min"] == 0.0
        assert stats["max"] == 9.0
        assert stats["p50"] == 5.0

    def test_histogram_memory_limit(self):
        for i in range(1500):
            observe("big", float(i))
        assert len(_histograms["big"]) <= 1000

    def test_agent_timer(self):
        import time

        with AgentTimer("test_op"):
            time.sleep(0.01)
        assert _counters["test_op_count"] == 1
        assert len(_histograms["test_op"]) == 1
        assert _histograms["test_op"][0] >= 0.01

    def test_empty_metrics(self):
        metrics = get_metrics()
        assert metrics["counters"] == {}
        assert metrics["histograms"] == {}
