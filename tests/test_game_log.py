"""Tests for islandsim.models — GameLog and friends.

Covers schema validation, JSON round-trip, and the JSON-string coercion
validator on TurnResolution.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from islandsim.models import (
    Action,
    ActionVisibility,
    GameLog,
    GameSummary,
    NationName,
    NationState,
    Relationship,
    ResourceChange,
    Resources,
    TurnActions,
    TurnRecord,
    TurnResolution,
    WorldState,
)


def _make_world_state() -> WorldState:
    res = Resources(military=50, treasury=50, food=50, support=50)
    return WorldState(
        turn=1,
        max_turns=3,
        nations={
            NationName.NARU: NationState(name=NationName.NARU, resources=res, traits="t"),
            NationName.VELDARA: NationState(
                name=NationName.VELDARA, resources=res.model_copy(), traits="t",
            ),
            NationName.TAUMA: NationState(
                name=NationName.TAUMA, resources=res.model_copy(), traits="t",
            ),
        },
        relationships=[],
        reef_maru_status="disputed",
    )


def _make_game_log() -> GameLog:
    state = _make_world_state()
    action = Action(
        description="patrol the strait",
        visibility=ActionVisibility.PUBLIC,
        category="military",
    )
    turn_actions = {
        n: TurnActions(nation=n, actions=[action], reasoning="r")
        for n in NationName
    }
    resolution = TurnResolution(
        narrative="quiet turn",
        changes=[
            ResourceChange(
                nation=NationName.NARU, field="military", delta=5, reason="patrol",
            ),
        ],
    )
    turn_record = TurnRecord(
        turn=1, actions=turn_actions, resolution=resolution, final_state=state,
    )
    summary = GameSummary(
        narrative="game played",
        nation_assessments={n: "ok" for n in NationName},
        reef_maru_outcome="still disputed",
    )
    return GameLog(
        timestamp="2026-04-25T12:00:00Z",
        num_turns=1,
        initial_state=state,
        turns=[turn_record],
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_game_log_round_trip():
    log = _make_game_log()
    raw = log.model_dump_json()
    restored = GameLog.model_validate_json(raw)
    assert restored == log


def test_game_log_metadata_optional_for_back_compat():
    """Logs written before schema_version 1 had no metadata field."""
    log = _make_game_log()
    assert log.metadata is None
    restored = GameLog.model_validate_json(log.model_dump_json())
    assert restored.metadata is None


# ---------------------------------------------------------------------------
# TurnResolution JSON-string coercion (the _parse_json_string validator)
# ---------------------------------------------------------------------------


def test_turn_resolution_changes_accepts_json_string():
    """LLMs sometimes emit list fields as a JSON-encoded string; validator coerces."""
    changes_payload = [
        {
            "kind": "resource",
            "nation": "naru",
            "field": "military",
            "delta": 5,
            "reason": "x",
        },
    ]
    resolution = TurnResolution.model_validate({
        "narrative": "n",
        "changes": json.dumps(changes_payload),
    })
    assert len(resolution.changes) == 1
    assert isinstance(resolution.changes[0], ResourceChange)
    assert resolution.changes[0].delta == 5


def test_turn_resolution_action_results_accepts_json_string():
    payload = [
        {
            "nation": "naru",
            "action_description": "patrol",
            "outcome": "no contact",
        },
    ]
    resolution = TurnResolution.model_validate({
        "narrative": "n",
        "action_results": json.dumps(payload),
    })
    assert len(resolution.action_results) == 1
    assert resolution.action_results[0].nation == NationName.NARU


def test_turn_resolution_skill_rolls_accepts_json_string():
    payload = [
        {
            "attacker": "naru",
            "defender": "veldara",
            "difficulty": 0,
            "attacker_skill": 60,
            "defender_skill": 50,
            "roll": 5,
            "margin": 15,
            "success": True,
            "context": "espionage",
        },
    ]
    resolution = TurnResolution.model_validate({
        "narrative": "n",
        "skill_rolls": json.dumps(payload),
    })
    assert len(resolution.skill_rolls) == 1
    assert resolution.skill_rolls[0].success is True


def test_turn_resolution_accepts_real_lists_too():
    """The validator must not break the normal list path."""
    resolution = TurnResolution(narrative="n", changes=[])
    assert resolution.changes == []


# ---------------------------------------------------------------------------
# Field constraints
# ---------------------------------------------------------------------------


def test_resource_constraint_rejects_above_100():
    with pytest.raises(ValidationError):
        Resources(military=150, treasury=50, food=50, support=50)


def test_resource_constraint_rejects_below_zero():
    with pytest.raises(ValidationError):
        Resources(military=-1, treasury=50, food=50, support=50)


def test_relationship_sentiment_rejects_above_100():
    with pytest.raises(ValidationError):
        Relationship(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=200,
        )


def test_relationship_sentiment_rejects_below_minus_100():
    with pytest.raises(ValidationError):
        Relationship(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=-200,
        )
