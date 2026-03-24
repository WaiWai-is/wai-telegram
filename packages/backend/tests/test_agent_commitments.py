"""Tests for Commitment Tracking — the killer feature."""

from uuid import uuid4


from app.services.agent.commitments import (
    Commitment,
    CommitmentDirection,
    CommitmentStatus,
    _commitments,
    complete_commitment,
    detect_commitments,
    format_commitments_for_display,
    get_user_commitments,
    save_commitment,
)


class TestDetectCommitmentsEnglish:
    """Test English commitment detection."""

    def test_ill_send(self):
        result = detect_commitments("I'll send you the report tomorrow")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_i_will(self):
        result = detect_commitments("I will prepare the presentation by Friday")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_let_me(self):
        result = detect_commitments("Let me check the pricing and get back to you")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_they_will_send(self):
        result = detect_commitments("Alex said he'd send the contract by Monday")
        assert len(result) >= 1
        c = result[0]
        assert c.direction == CommitmentDirection.THEY_PROMISED

    def test_she_will(self):
        result = detect_commitments("She'll handle the booking for next week")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.THEY_PROMISED

    def test_no_commitment(self):
        result = detect_commitments("The weather is nice today")
        assert len(result) == 0

    def test_deadline_by_friday(self):
        result = detect_commitments("I'll send it by Friday")
        assert len(result) >= 1
        assert result[0].deadline is not None
        assert "friday" in result[0].deadline.lower()

    def test_deadline_tomorrow(self):
        result = detect_commitments("I'll do it before tomorrow")
        assert len(result) >= 1
        assert result[0].deadline is not None

    def test_deadline_end_of_week(self):
        result = detect_commitments("I will finish it by end of week")
        assert len(result) >= 1


class TestDetectCommitmentsRussian:
    """Test Russian commitment detection."""

    def test_ya_otpravlyu(self):
        result = detect_commitments("Я отправлю тебе документ")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_ya_sdelayu(self):
        result = detect_commitments("Я сделаю это до вечера")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_napishu(self):
        result = detect_commitments("Напишу отчёт до пятницы")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.I_PROMISED

    def test_on_obeschal(self):
        result = detect_commitments("Саша обещал прислать контракт")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.THEY_PROMISED

    def test_ona_prishlyot(self):
        result = detect_commitments("Маша пришлёт бюджет завтра")
        assert len(result) >= 1
        assert result[0].direction == CommitmentDirection.THEY_PROMISED

    def test_deadline_do_pyatnitsy(self):
        result = detect_commitments("Напишу до пятницы")
        assert len(result) >= 1
        assert result[0].deadline is not None


class TestCommitmentStore:
    """Test saving and retrieving commitments."""

    def setup_method(self):
        _commitments.clear()

    def test_save_and_retrieve(self):
        user_id = uuid4()
        c = Commitment(
            who="Alex",
            what="send contract",
            direction=CommitmentDirection.THEY_PROMISED,
        )
        save_commitment(c, user_id)
        results = get_user_commitments(user_id)
        assert len(results) == 1
        assert results[0].who == "Alex"

    def test_filter_by_direction(self):
        user_id = uuid4()
        save_commitment(
            Commitment(
                who="me", what="send report", direction=CommitmentDirection.I_PROMISED
            ),
            user_id,
        )
        save_commitment(
            Commitment(
                who="Alex",
                what="review PR",
                direction=CommitmentDirection.THEY_PROMISED,
            ),
            user_id,
        )
        i_promised = get_user_commitments(
            user_id, direction=CommitmentDirection.I_PROMISED
        )
        assert len(i_promised) == 1
        assert i_promised[0].who == "me"

        they_promised = get_user_commitments(
            user_id, direction=CommitmentDirection.THEY_PROMISED
        )
        assert len(they_promised) == 1
        assert they_promised[0].who == "Alex"

    def test_complete_commitment(self):
        user_id = uuid4()
        c = Commitment(
            who="me", what="do thing", direction=CommitmentDirection.I_PROMISED
        )
        save_commitment(c, user_id)
        result = complete_commitment(c.id)
        assert result is not None
        assert result.status == CommitmentStatus.COMPLETED
        assert result.completed_at is not None

    def test_completed_not_in_open(self):
        user_id = uuid4()
        c = Commitment(
            who="me", what="do thing", direction=CommitmentDirection.I_PROMISED
        )
        save_commitment(c, user_id)
        complete_commitment(c.id)
        open_commitments = get_user_commitments(user_id, status=CommitmentStatus.OPEN)
        assert len(open_commitments) == 0

    def test_multiple_users_isolated(self):
        user1 = uuid4()
        user2 = uuid4()
        save_commitment(
            Commitment(who="A", what="task1", direction=CommitmentDirection.I_PROMISED),
            user1,
        )
        save_commitment(
            Commitment(who="B", what="task2", direction=CommitmentDirection.I_PROMISED),
            user2,
        )
        assert len(get_user_commitments(user1)) == 1
        assert len(get_user_commitments(user2)) == 1


class TestFormatCommitments:
    """Test display formatting."""

    def test_empty(self):
        result = format_commitments_for_display([])
        assert "No open commitments" in result

    def test_i_promised_format(self):
        commitments = [
            Commitment(
                who="me",
                what="send report",
                direction=CommitmentDirection.I_PROMISED,
                deadline="Friday",
            )
        ]
        result = format_commitments_for_display(commitments)
        assert "What you promised" in result
        assert "send report" in result
        assert "Friday" in result

    def test_they_promised_format(self):
        commitments = [
            Commitment(
                who="Alex",
                what="send contract",
                direction=CommitmentDirection.THEY_PROMISED,
            )
        ]
        result = format_commitments_for_display(commitments)
        assert "What others promised" in result
        assert "Alex" in result
        assert "send contract" in result

    def test_mixed_format(self):
        commitments = [
            Commitment(
                who="me", what="review code", direction=CommitmentDirection.I_PROMISED
            ),
            Commitment(
                who="Sarah",
                what="send budget",
                direction=CommitmentDirection.THEY_PROMISED,
            ),
        ]
        result = format_commitments_for_display(commitments)
        assert "What you promised" in result
        assert "What others promised" in result
