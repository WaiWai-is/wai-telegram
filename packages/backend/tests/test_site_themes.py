"""Tests for site builder theme system — detection, parsing, and prompt injection."""

from app.services.agent.site_builder import (
    THEMES,
    detect_theme,
    get_theme_prompt,
    parse_theme_flag,
    resolve_theme,
)


class TestThemesDict:
    """Validate the THEMES data structure."""

    def test_default_theme_exists(self):
        assert "default" in THEMES

    def test_all_expected_themes_present(self):
        expected = [
            "default",
            "dark-corporate",
            "warm-organic",
            "neon-startup",
            "clean-minimal",
            "luxury-gold",
            "fresh-modern",
            "retro-vintage",
        ]
        for theme_key in expected:
            assert theme_key in THEMES, f"Missing theme: {theme_key}"

    def test_each_theme_has_required_keys(self):
        required_keys = {"name", "description", "prompt", "keywords_en", "keywords_ru"}
        for key, theme in THEMES.items():
            for rk in required_keys:
                assert rk in theme, f"Theme '{key}' missing key '{rk}'"

    def test_default_theme_has_empty_prompt(self):
        assert THEMES["default"]["prompt"] == ""

    def test_non_default_themes_have_prompt(self):
        for key, theme in THEMES.items():
            if key == "default":
                continue
            assert theme["prompt"], f"Theme '{key}' has empty prompt"

    def test_default_theme_has_no_keywords(self):
        assert THEMES["default"]["keywords_en"] == []
        assert THEMES["default"]["keywords_ru"] == []


class TestDetectTheme:
    """Test keyword-based theme auto-detection."""

    def test_dark_keyword_en(self):
        assert detect_theme("I want a dark landing page") == "dark-corporate"

    def test_dark_keyword_ru(self):
        assert detect_theme("Сделай тёмная тема для сайта") == "dark-corporate"

    def test_dark_keyword_ru_no_yo(self):
        assert detect_theme("Хочу темная тема") == "dark-corporate"

    def test_warm_keyword_en(self):
        assert detect_theme("Make it warm and cozy") == "warm-organic"

    def test_organic_keyword_en(self):
        assert detect_theme("Organic food store website") == "warm-organic"

    def test_neon_keyword_en(self):
        assert detect_theme("Neon-colored tech startup page") == "neon-startup"

    def test_startup_keyword_en(self):
        assert detect_theme("A startup landing page") == "neon-startup"

    def test_minimal_keyword_en(self):
        assert detect_theme("I want a minimal design") == "clean-minimal"

    def test_clean_keyword_en(self):
        assert detect_theme("Clean portfolio page") == "clean-minimal"

    def test_luxury_keyword_en(self):
        assert detect_theme("Luxury brand website") == "luxury-gold"

    def test_gold_keyword_ru(self):
        assert detect_theme("Золотая тема для ресторана") == "luxury-gold"

    def test_fresh_keyword_en(self):
        assert detect_theme("Fresh colorful design") == "fresh-modern"

    def test_vibrant_keyword_en(self):
        assert detect_theme("Vibrant app landing page") == "fresh-modern"

    def test_retro_keyword_en(self):
        assert detect_theme("Retro diner website") == "retro-vintage"

    def test_vintage_keyword_ru(self):
        assert detect_theme("Винтажная тема для магазина") == "retro-vintage"

    def test_no_match_returns_default(self):
        assert detect_theme("Landing page for a cafe with menu and prices") == "default"

    def test_empty_string_returns_default(self):
        assert detect_theme("") == "default"

    def test_case_insensitive(self):
        assert detect_theme("DARK THEME PLEASE") == "dark-corporate"

    def test_keyword_in_longer_text(self):
        assert detect_theme(
            "Build a landing page for my SaaS product. I want a neon aesthetic with gradients."
        ) == "neon-startup"


class TestParseThemeFlag:
    """Test --theme flag parsing from description text."""

    def test_valid_theme_flag(self):
        theme, desc = parse_theme_flag("--theme dark-corporate My landing page")
        assert theme == "dark-corporate"
        assert desc == "My landing page"

    def test_theme_luxury_gold(self):
        theme, desc = parse_theme_flag("--theme luxury-gold Premium brand site")
        assert theme == "luxury-gold"
        assert desc == "Premium brand site"

    def test_unknown_theme_returns_empty(self):
        theme, desc = parse_theme_flag("--theme nonexistent My landing page")
        assert theme == ""
        assert desc == "--theme nonexistent My landing page"

    def test_no_flag_returns_empty(self):
        theme, desc = parse_theme_flag("My landing page for a cafe")
        assert theme == ""
        assert desc == "My landing page for a cafe"

    def test_flag_case_insensitive(self):
        theme, desc = parse_theme_flag("--theme DARK-CORPORATE My page")
        assert theme == "dark-corporate"
        assert desc == "My page"

    def test_flag_with_extra_whitespace(self):
        theme, desc = parse_theme_flag("--theme   neon-startup   My page")
        assert theme == "neon-startup"
        assert desc == "My page"

    def test_flag_only_no_description(self):
        theme, desc = parse_theme_flag("--theme clean-minimal")
        assert theme == "clean-minimal"
        assert desc == ""

    def test_flag_default_theme(self):
        theme, desc = parse_theme_flag("--theme default My cafe site")
        assert theme == "default"
        assert desc == "My cafe site"

    def test_all_themes_parseable(self):
        for theme_key in THEMES:
            parsed, _ = parse_theme_flag(f"--theme {theme_key} test")
            assert parsed == theme_key, f"Failed to parse --theme {theme_key}"


class TestResolveTheme:
    """Test the combined resolution logic (flag > auto-detect > default)."""

    def test_flag_takes_priority_over_keywords(self):
        # Text says "dark" but flag says clean-minimal
        theme, desc = resolve_theme("--theme clean-minimal A dark corporate page")
        assert theme == "clean-minimal"
        assert desc == "A dark corporate page"

    def test_auto_detect_when_no_flag(self):
        theme, desc = resolve_theme("Make a luxury gold website for my brand")
        assert theme == "luxury-gold"
        assert desc == "Make a luxury gold website for my brand"

    def test_default_when_no_match(self):
        theme, desc = resolve_theme("Landing page for cafe with menu and prices")
        assert theme == "default"
        assert desc == "Landing page for cafe with menu and prices"

    def test_flag_with_description(self):
        theme, desc = resolve_theme("--theme retro-vintage Old school diner")
        assert theme == "retro-vintage"
        assert desc == "Old school diner"

    def test_russian_auto_detect(self):
        theme, desc = resolve_theme("Сделай минималистичная страница для портфолио")
        assert theme == "clean-minimal"
        assert desc == "Сделай минималистичная страница для портфолио"


class TestGetThemePrompt:
    """Test prompt injection for themes."""

    def test_default_returns_empty(self):
        assert get_theme_prompt("default") == ""

    def test_unknown_returns_empty(self):
        assert get_theme_prompt("nonexistent") == ""

    def test_dark_corporate_has_colors(self):
        prompt = get_theme_prompt("dark-corporate")
        assert "#0f172a" in prompt
        assert "#3b82f6" in prompt

    def test_warm_organic_has_merriweather(self):
        prompt = get_theme_prompt("warm-organic")
        assert "Merriweather" in prompt

    def test_neon_startup_has_gradient(self):
        prompt = get_theme_prompt("neon-startup")
        assert "green" in prompt.lower()
        assert "purple" in prompt.lower()

    def test_clean_minimal_has_inter(self):
        prompt = get_theme_prompt("clean-minimal")
        assert "Inter" in prompt

    def test_luxury_gold_has_gold_color(self):
        prompt = get_theme_prompt("luxury-gold")
        assert "#d4af37" in prompt

    def test_fresh_modern_has_jakarta(self):
        prompt = get_theme_prompt("fresh-modern")
        assert "Jakarta" in prompt

    def test_retro_vintage_has_baskerville(self):
        prompt = get_theme_prompt("retro-vintage")
        assert "Baskerville" in prompt

    def test_all_non_default_themes_produce_output(self):
        for key in THEMES:
            if key == "default":
                continue
            prompt = get_theme_prompt(key)
            assert len(prompt) > 50, f"Theme '{key}' prompt too short"
            assert "THEME" in prompt, f"Theme '{key}' missing THEME header"


class TestSiteGenerationPromptFormat:
    """Test that the prompt template accepts theme_instructions."""

    def test_prompt_accepts_theme_instructions(self):
        from app.services.agent.site_builder import SITE_GENERATION_PROMPT

        result = SITE_GENERATION_PROMPT.format(
            description="Test cafe", theme_instructions=""
        )
        assert "Test cafe" in result
        assert "TECH STACK" in result

    def test_prompt_with_theme_injection(self):
        from app.services.agent.site_builder import SITE_GENERATION_PROMPT

        theme_text = get_theme_prompt("dark-corporate")
        result = SITE_GENERATION_PROMPT.format(
            description="My SaaS app", theme_instructions="\n" + theme_text + "\n"
        )
        assert "My SaaS app" in result
        assert "#0f172a" in result
        assert "TECH STACK" in result

    def test_prompt_default_theme_no_extra_content(self):
        from app.services.agent.site_builder import SITE_GENERATION_PROMPT

        result = SITE_GENERATION_PROMPT.format(
            description="Test site", theme_instructions=""
        )
        # Should not contain any THEME override section
        assert "THEME (override" not in result
