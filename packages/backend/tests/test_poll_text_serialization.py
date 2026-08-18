"""Poll text arrives as TextWithEntities on current Telegram layers, not as str."""

import json


class _TextWithEntities:
    def __init__(self, text):
        self.text = text
        self.entities = []


class _Answer:
    def __init__(self, text):
        self.text = text


class _Poll:
    def __init__(self, question, answers):
        self.id = 7
        self.question = question
        self.answers = answers
        self.closed = False
        self.public_voters = False
        self.multiple_choice = False
        self.quiz = False


class _Media:
    def __init__(self, poll):
        self.poll = poll
        self.results = None


class _Message:
    def __init__(self, media):
        self.media = media


def _poll_of(question, answers):
    from app.services.telegram_metadata import _poll

    return _poll(_Message(_Media(_Poll(question, [_Answer(a) for a in answers]))))


def test_plain_strings_still_work():
    result = _poll_of("Когда встречаемся?", ["Утром", "Вечером"])
    assert result["question"] == "Когда встречаемся?"
    assert [a["text"] for a in result["answers"]] == ["Утром", "Вечером"]


def test_text_with_entities_is_unwrapped():
    result = _poll_of(
        _TextWithEntities("Когда встречаемся?"),
        [_TextWithEntities("Утром"), _TextWithEntities("Вечером")],
    )
    assert result["question"] == "Когда встречаемся?"
    assert [a["text"] for a in result["answers"]] == ["Утром", "Вечером"]


def test_result_is_json_serializable():
    """The unserializable object aborted the entire reconciliation batch."""
    result = _poll_of(_TextWithEntities("Вопрос"), [_TextWithEntities("Да")])
    assert json.loads(json.dumps(result))["question"] == "Вопрос"


def test_unknown_object_degrades_to_none_rather_than_breaking_the_batch():
    result = _poll_of(object(), [object()])
    assert result["question"] is None
    assert result["answers"][0]["text"] is None
