"""Tests for Conduit phase definitions and transition validation."""


from server.conduit.phases import TERMINAL_PHASES, VALID_TRANSITIONS, Phase


class TestPhaseDefinitions:
    """Test that all phases are properly defined."""

    def test_all_phases_exist(self):
        expected = {
            "INIT", "NAVIGATE", "ASSESS", "OBSTRUCT", "AI_REASON",
            "EXECUTE_PLAN", "EXTRACT", "VALIDATE", "REPAIR",
            "PERSIST", "COMPLETE", "FAIL",
        }
        assert {p.value for p in Phase} == expected

    def test_terminal_phases(self):
        assert Phase.COMPLETE in TERMINAL_PHASES
        assert Phase.FAIL in TERMINAL_PHASES
        assert len(TERMINAL_PHASES) == 2

    def test_terminal_phases_have_no_transitions(self):
        for phase in TERMINAL_PHASES:
            assert VALID_TRANSITIONS[phase] == set()

    def test_every_phase_has_transition_entry(self):
        for phase in Phase:
            assert phase in VALID_TRANSITIONS

    def test_init_transitions(self):
        assert VALID_TRANSITIONS[Phase.INIT] == {Phase.NAVIGATE, Phase.FAIL}

    def test_navigate_transitions(self):
        assert VALID_TRANSITIONS[Phase.NAVIGATE] == {Phase.ASSESS, Phase.FAIL}

    def test_assess_transitions(self):
        assert VALID_TRANSITIONS[Phase.ASSESS] == {Phase.EXTRACT, Phase.OBSTRUCT, Phase.FAIL}

    def test_extract_transitions(self):
        assert VALID_TRANSITIONS[Phase.EXTRACT] == {Phase.VALIDATE, Phase.FAIL}

    def test_validate_transitions(self):
        assert VALID_TRANSITIONS[Phase.VALIDATE] == {Phase.PERSIST, Phase.REPAIR, Phase.FAIL}

    def test_persist_transitions(self):
        assert VALID_TRANSITIONS[Phase.PERSIST] == {Phase.COMPLETE, Phase.FAIL}

    def test_non_terminal_phases_can_fail(self):
        """Every non-terminal phase must be able to transition to FAIL."""
        for phase in Phase:
            if phase not in TERMINAL_PHASES:
                assert Phase.FAIL in VALID_TRANSITIONS[phase], (
                    f"Phase {phase.value} cannot transition to FAIL"
                )

    def test_no_transitions_to_init(self):
        """No phase should transition back to INIT."""
        for phase in Phase:
            targets = VALID_TRANSITIONS[phase]
            assert Phase.INIT not in targets, (
                f"Phase {phase.value} can transition to INIT, which is not allowed"
            )
