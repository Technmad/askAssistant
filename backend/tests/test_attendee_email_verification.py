from app.agent.graph import _verified_attendee_emails


class TestVerifiedAttendeeEmails:
    def test_rejects_email_never_typed_by_the_user(self):
        # Found live: after a real contact was resolved and echoed back in an
        # assistant confirm message, a later unrelated request came back with
        # a fabricated email following the same pattern -- the user never
        # typed it anywhere.
        state = {
            "message": "schedule a meeting with Ankit tomorrow 5 pm",
            "recent_history": [
                {"role": "user", "content": "schedule a meeting with asmita tomorrow 11 am"},
                {
                    "role": "assistant",
                    "content": 'Create "Meeting with Asmita" with asmita.ria103@gmail.com -- confirm?',
                },
            ],
        }
        assert _verified_attendee_emails(state, ["ankit.ria103@gmail.com"]) == []

    def test_accepts_email_typed_in_the_current_message(self):
        state = {"message": "invite john at john@example.com", "recent_history": []}
        assert _verified_attendee_emails(state, ["john@example.com"]) == ["john@example.com"]

    def test_accepts_email_typed_in_an_earlier_user_turn(self):
        # Legitimate multi-turn slot-filling: the assistant asked for an
        # email, the user answered with it in a PRIOR turn, not this one.
        state = {
            "message": "tomorrow 6 pm",
            "recent_history": [
                {"role": "user", "content": "schedule a meeting with ritesh tomorrow"},
                {"role": "assistant", "content": "I don't have Ritesh's email yet -- what is it?"},
                {"role": "user", "content": "riteshtest123@gmail.com"},
                {"role": "assistant", "content": 'What day should "Meeting with Ritesh" be?'},
            ],
        }
        assert _verified_attendee_emails(state, ["riteshtest123@gmail.com"]) == ["riteshtest123@gmail.com"]

    def test_case_insensitive_match(self):
        state = {"message": "invite JOHN@EXAMPLE.COM", "recent_history": []}
        assert _verified_attendee_emails(state, ["john@example.com"]) == ["john@example.com"]

    def test_does_not_trust_an_email_only_seen_in_an_assistant_turn(self):
        state = {
            "message": "schedule something",
            "recent_history": [{"role": "assistant", "content": "with someone@example.com -- confirm?"}],
        }
        assert _verified_attendee_emails(state, ["someone@example.com"]) == []
