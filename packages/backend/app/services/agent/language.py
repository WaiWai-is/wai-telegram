"""Language Detection — detect user's language from message text.

Supports: English, Russian, Ukrainian, Spanish, French, German, Portuguese,
Italian, Turkish, Arabic, Chinese, Japanese, Korean + more.

Uses character range analysis for fast detection without LLM.
"""

import re
import unicodedata
from collections import Counter


def detect_language(text: str) -> str:
    """Detect language from text using character frequency analysis.

    Returns ISO 639-1 code (e.g., 'en', 'ru', 'uk', 'es').
    Fast — no LLM call, works on any length of text.
    """
    if not text or not text.strip():
        return "en"

    # Remove URLs, mentions, numbers, punctuation for cleaner analysis
    clean = re.sub(r"https?://\S+|@\w+|#\w+|\d+", "", text)
    clean = re.sub(r"[^\w\s]", "", clean).strip()

    if not clean:
        return "en"

    # Count characters by script
    scripts: Counter[str] = Counter()
    for char in clean:
        if char.isspace():
            continue
        cat = unicodedata.category(char)
        if cat.startswith("L"):  # Letters only
            # Cyrillic
            if "\u0400" <= char <= "\u04ff":
                scripts["cyrillic"] += 1
            # Latin
            elif "\u0041" <= char <= "\u024f":
                scripts["latin"] += 1
            # Arabic
            elif "\u0600" <= char <= "\u06ff":
                scripts["arabic"] += 1
            # CJK
            elif "\u4e00" <= char <= "\u9fff":
                scripts["cjk"] += 1
            # Hangul (Korean)
            elif "\uac00" <= char <= "\ud7a3":
                scripts["hangul"] += 1
            # Hiragana/Katakana (Japanese)
            elif "\u3040" <= char <= "\u30ff":
                scripts["japanese"] += 1
            # Turkish special chars
            elif char in "ğışöüçĞİŞÖÜÇ":
                scripts["turkish"] += 1
            else:
                scripts["latin"] += 1

    total = sum(scripts.values())
    if total == 0:
        return "en"

    # Determine by dominant script
    dominant = scripts.most_common(1)[0] if scripts else ("latin", 0)
    script_name, count = dominant
    ratio = count / total

    if script_name == "cyrillic" and ratio > 0.3:
        return _detect_cyrillic_language(clean)
    elif script_name == "arabic" and ratio > 0.3:
        return "ar"
    elif script_name == "cjk" and ratio > 0.3:
        return "zh"
    elif script_name == "hangul" and ratio > 0.3:
        return "ko"
    elif script_name == "japanese" and ratio > 0.3:
        return "ja"
    elif script_name == "turkish" and ratio > 0.05:
        return "tr"

    # Latin script — detect specific language by common words
    return _detect_latin_language(clean)


def _detect_cyrillic_language(text: str) -> str:
    """Distinguish Russian from Ukrainian from other Cyrillic."""
    lower = text.lower()
    # Ukrainian-specific characters
    ua_chars = sum(1 for c in lower if c in "іїєґ")
    if ua_chars > 0:
        return "uk"
    return "ru"


def _detect_latin_language(text: str) -> str:
    """Detect language among Latin-script languages."""
    lower = text.lower()
    words = set(lower.split())

    # Spanish markers
    es_words = {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "en",
        "que",
        "por",
        "con",
        "para",
        "está",
    }
    if len(words & es_words) >= 2:
        return "es"

    # French markers
    fr_words = {
        "le",
        "la",
        "les",
        "des",
        "est",
        "une",
        "que",
        "dans",
        "pour",
        "avec",
        "pas",
    }
    if len(words & fr_words) >= 2:
        return "fr"

    # German markers
    de_words = {"der", "die", "das", "und", "ist", "ein", "eine", "nicht", "mit", "auf"}
    if len(words & de_words) >= 2:
        return "de"

    # Portuguese markers
    pt_words = {"uma", "não", "para", "com", "são", "mais", "está", "muito", "também"}
    if len(words & pt_words) >= 2:
        return "pt"

    # Italian markers
    it_words = {"il", "che", "non", "una", "sono", "per", "della", "con", "questo"}
    if len(words & it_words) >= 2:
        return "it"

    # Turkish markers (beyond special chars)
    tr_words = {"bir", "ve", "bu", "için", "ile", "var", "olan", "gibi", "daha"}
    if len(words & tr_words) >= 2:
        return "tr"

    return "en"
