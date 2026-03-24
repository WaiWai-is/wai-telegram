"""Tests for Entity Extraction — people, topics, decisions, amounts."""

from app.services.agent.entities import (
    Entity,
    EntityType,
    extract_entities_fast,
    format_entities_for_display,
)


class TestPersonExtraction:
    def test_at_mention(self):
        entities = extract_entities_fast("Ask @alex_dev about the API")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        assert len(persons) >= 1
        assert any("alex_dev" in e.name for e in persons)

    def test_name_after_with(self):
        entities = extract_entities_fast("I had a meeting with Sarah today")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        assert len(persons) >= 1
        assert any("Sarah" in e.name for e in persons)

    def test_name_after_told(self):
        entities = extract_entities_fast("I told Michael about the project")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        assert any("Michael" in e.name for e in persons)

    def test_russian_name(self):
        entities = extract_entities_fast("Встретился с Алексом вчера")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        assert len(persons) >= 1

    def test_no_false_positive_common_words(self):
        entities = extract_entities_fast("This is a simple test message")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        assert len(persons) == 0


class TestAmountExtraction:
    def test_dollar_amount(self):
        entities = extract_entities_fast("The budget is $500,000")
        amounts = [e for e in entities if e.type == EntityType.AMOUNT]
        assert len(amounts) >= 1

    def test_k_suffix(self):
        entities = extract_entities_fast("We need 50k for the project")
        amounts = [e for e in entities if e.type == EntityType.AMOUNT]
        assert len(amounts) >= 1

    def test_russian_amount(self):
        entities = extract_entities_fast("Бюджет 500 тыс руб")
        amounts = [e for e in entities if e.type == EntityType.AMOUNT]
        assert len(amounts) >= 1

    def test_euro(self):
        entities = extract_entities_fast("Price is 100 EUR")
        amounts = [e for e in entities if e.type == EntityType.AMOUNT]
        assert len(amounts) >= 1


class TestDateExtraction:
    def test_date_format(self):
        entities = extract_entities_fast("Meeting on 15/03/2026")
        dates = [e for e in entities if e.type == EntityType.DATE]
        assert len(dates) >= 1

    def test_month_name(self):
        entities = extract_entities_fast("Launch planned for March 15")
        dates = [e for e in entities if e.type == EntityType.DATE]
        assert len(dates) >= 1

    def test_russian_date(self):
        entities = extract_entities_fast("Встреча до 15 марта")
        dates = [e for e in entities if e.type == EntityType.DATE]
        assert len(dates) >= 1


class TestDecisionExtraction:
    def test_we_decided(self):
        entities = extract_entities_fast(
            "We decided to go with vendor A for the hosting"
        )
        decisions = [e for e in entities if e.type == EntityType.DECISION]
        assert len(decisions) >= 1
        assert (
            "vendor A" in decisions[0].name.lower()
            or "go with" in decisions[0].name.lower()
        )

    def test_agreed(self):
        entities = extract_entities_fast("Agreed to postpone the launch until Q2")
        decisions = [e for e in entities if e.type == EntityType.DECISION]
        assert len(decisions) >= 1

    def test_russian_decision(self):
        entities = extract_entities_fast("Решили использовать PostgreSQL для хранения")
        decisions = [e for e in entities if e.type == EntityType.DECISION]
        assert len(decisions) >= 1

    def test_dogovorilis(self):
        entities = extract_entities_fast("Договорились о бюджете в 500 тысяч")
        decisions = [e for e in entities if e.type == EntityType.DECISION]
        assert len(decisions) >= 1


class TestDeduplication:
    def test_same_person_mentioned_twice(self):
        entities = extract_entities_fast("Met with Sarah. Told Sarah about the plan.")
        persons = [e for e in entities if e.type == EntityType.PERSON]
        sarah_count = sum(1 for e in persons if "Sarah" in e.name)
        assert sarah_count == 1  # Deduplicated


class TestFormatEntities:
    def test_empty(self):
        result = format_entities_for_display([])
        assert "No entities" in result

    def test_person_format(self):
        entities = [Entity(type=EntityType.PERSON, name="Alex")]
        result = format_entities_for_display(entities)
        assert "👤" in result
        assert "Alex" in result

    def test_amount_format(self):
        entities = [Entity(type=EntityType.AMOUNT, name="$500,000")]
        result = format_entities_for_display(entities)
        assert "💰" in result
        assert "$500,000" in result

    def test_mixed_types(self):
        entities = [
            Entity(type=EntityType.PERSON, name="Sarah"),
            Entity(type=EntityType.DECISION, name="go with vendor A"),
            Entity(type=EntityType.AMOUNT, name="$10k"),
        ]
        result = format_entities_for_display(entities)
        assert "👤" in result
        assert "✅" in result
        assert "💰" in result


class TestComplexMessages:
    def test_meeting_notes(self):
        text = """Met with Sarah and Alex today. We decided to go with
        PostgreSQL. Budget is $50k. Launch date: March 30.
        Alex will handle the backend, Sarah takes frontend."""
        entities = extract_entities_fast(text)
        types = {e.type for e in entities}
        assert EntityType.PERSON in types
        assert EntityType.AMOUNT in types
        assert EntityType.DECISION in types

    def test_russian_complex(self):
        text = """Встретились с Алексом и Машей. Решили бюджет 500 тыс руб.
        Запуск до 15 марта. Маша отвечает за дизайн."""
        entities = extract_entities_fast(text)
        types = {e.type for e in entities}
        assert EntityType.PERSON in types
        assert EntityType.AMOUNT in types
        assert EntityType.DECISION in types
