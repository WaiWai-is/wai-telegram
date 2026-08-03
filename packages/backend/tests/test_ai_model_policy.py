from pathlib import Path

from app.core.config import Settings


APP_ROOT = Path(__file__).parents[1] / "app"


def test_ai_model_defaults_match_reviewed_production_policy():
    settings = Settings()

    assert settings.generation_model == "gpt-5.6-luna"
    assert settings.fast_generation_reasoning_effort == "none"
    assert settings.quality_generation_reasoning_effort == "low"
    assert settings.media_summary_model == "gpt-5.6-luna"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.deepgram_model == "nova-3"
    assert settings.deepgram_language == "multi"


def test_retired_generation_provider_is_absent_from_production_code():
    matches = []
    for path in APP_ROOT.rglob("*.py"):
        content = path.read_text().lower()
        if "anthropic" in content or "claude" in content:
            matches.append(str(path.relative_to(APP_ROOT)))

    assert matches == []


def test_retired_generation_provider_is_absent_from_dependencies():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text().lower()
    assert "anthropic" not in pyproject
