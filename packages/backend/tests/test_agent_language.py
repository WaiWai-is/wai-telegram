"""Tests for Language Detection — multi-language support."""

from app.services.agent.language import detect_language


class TestEnglish:
    def test_simple_english(self):
        assert detect_language("Hello, how are you doing today?") == "en"

    def test_technical_english(self):
        assert detect_language("Let's deploy the new version to production") == "en"

    def test_empty_string(self):
        assert detect_language("") == "en"

    def test_numbers_only(self):
        assert detect_language("12345") == "en"


class TestRussian:
    def test_simple_russian(self):
        assert detect_language("Привет, как дела?") == "ru"

    def test_business_russian(self):
        assert detect_language("Давайте обсудим бюджет проекта") == "ru"

    def test_mixed_russian_english(self):
        # Mostly Russian with some English terms
        assert detect_language("Нужно задеплоить новую версию API") == "ru"


class TestUkrainian:
    def test_simple_ukrainian(self):
        assert detect_language("Привіт, як справи?") == "uk"

    def test_ukrainian_with_i(self):
        assert detect_language("Це дуже гарний проєкт") == "uk"


class TestSpanish:
    def test_simple_spanish(self):
        assert (
            detect_language("Hola, el proyecto está listo para la presentación") == "es"
        )


class TestFrench:
    def test_simple_french(self):
        assert detect_language("Bonjour, le projet est dans une phase avancée") == "fr"


class TestGerman:
    def test_simple_german(self):
        assert detect_language("Das ist ein sehr gutes Projekt") == "de"


class TestArabic:
    def test_arabic(self):
        assert detect_language("مرحبا كيف حالك") == "ar"


class TestChinese:
    def test_chinese(self):
        assert detect_language("你好，项目进展如何？") == "zh"


class TestKorean:
    def test_korean(self):
        assert detect_language("안녕하세요 프로젝트는 어떻게 되고 있나요") == "ko"


class TestJapanese:
    def test_japanese(self):
        assert detect_language("こんにちは、プロジェクトはどうですか") == "ja"


class TestTurkish:
    def test_turkish_special_chars(self):
        assert detect_language("Günaydın, proje için bir toplantı yapalım") == "tr"


class TestEdgeCases:
    def test_url_only(self):
        assert detect_language("https://example.com/path?param=value") == "en"

    def test_emoji_only(self):
        # Emoji are not letters, should default to en
        assert detect_language("👍🎉🔥") == "en"

    def test_mixed_scripts(self):
        # When Cyrillic is clearly dominant
        result = detect_language("Привет мир как дела hello")
        assert result == "ru"
