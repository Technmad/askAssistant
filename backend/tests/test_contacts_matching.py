from app.services.contacts import _name_score


class TestNameScore:
    def test_exact_single_word_match(self):
        assert _name_score("Ankit", "Ankit Kumar") == 1.0

    def test_first_name_matches_full_contact_name(self):
        assert _name_score("Ramesh", "Ramesh Singh") == 1.0

    def test_full_name_matches_full_contact_name(self):
        assert _name_score("Ramesh Singh", "Ramesh Singh") == 1.0

    def test_shared_prefix_does_not_match_different_name(self):
        # Found live: "priyanka" scored 0.57 against "Priyadharsini" under
        # character-overlap scoring (shared "priya-" prefix) and silently
        # invited the wrong real contact. Word-based matching must reject this.
        assert _name_score("priyanka", "Priyadharsini") == 0.0

    def test_wrong_surname_does_not_match(self):
        # Only one of two words matches -- must not be treated as the same person.
        assert _name_score("Ramesh Kumar", "Ramesh Singh") < 1.0

    def test_minor_typo_still_matches(self):
        assert _name_score("Rukum", "Rukam") >= _name_score("priyanka", "Priyadharsini")
        assert _name_score("Rukum", "Rukam") == 1.0

    def test_case_insensitive(self):
        assert _name_score("ANKIT", "ankit kumar") == 1.0

    def test_unrelated_name_scores_zero(self):
        assert _name_score("Deepak", "Ankit Kumar") == 0.0
