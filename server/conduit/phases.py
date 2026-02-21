"""Conduit phase definitions — the finite state machine states and transitions."""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """All valid Conduit phases. The Conduit is a finite state machine
    that transitions between these phases based on concrete conditions."""

    INIT = "INIT"
    NAVIGATE = "NAVIGATE"
    ASSESS = "ASSESS"
    OBSTRUCT = "OBSTRUCT"
    AI_REASON = "AI_REASON"
    EXECUTE_PLAN = "EXECUTE_PLAN"
    EXTRACT = "EXTRACT"
    VALIDATE = "VALIDATE"
    REPAIR = "REPAIR"
    PERSIST = "PERSIST"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"


# Valid phase transitions. Each key maps to a set of phases it can transition to.
VALID_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.INIT: {Phase.NAVIGATE, Phase.FAIL},
    Phase.NAVIGATE: {Phase.ASSESS, Phase.FAIL},
    Phase.ASSESS: {Phase.EXTRACT, Phase.OBSTRUCT, Phase.FAIL},
    Phase.OBSTRUCT: {Phase.AI_REASON, Phase.NAVIGATE, Phase.FAIL},
    Phase.AI_REASON: {Phase.EXECUTE_PLAN, Phase.FAIL},
    Phase.EXECUTE_PLAN: {Phase.ASSESS, Phase.FAIL},
    Phase.EXTRACT: {Phase.VALIDATE, Phase.FAIL},
    Phase.VALIDATE: {Phase.PERSIST, Phase.REPAIR, Phase.FAIL},
    Phase.REPAIR: {Phase.VALIDATE, Phase.FAIL},
    Phase.PERSIST: {Phase.COMPLETE, Phase.FAIL},
    Phase.COMPLETE: set(),  # terminal
    Phase.FAIL: set(),  # terminal
}

TERMINAL_PHASES = {Phase.COMPLETE, Phase.FAIL}
