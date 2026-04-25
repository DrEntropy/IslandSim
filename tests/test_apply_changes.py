"""Tests for islandsim.rules.apply_changes — declarative state-change engine."""

from __future__ import annotations

import pytest

from islandsim.models import (
    ActiveEffectAdd,
    ActiveEffectRemove,
    NationName,
    NationState,
    ReefMaruStatusChange,
    Relationship,
    RelationshipChange,
    ResourceChange,
    Resources,
    StraitChange,
    WorldState,
)
from islandsim.rules import apply_changes


def make_state(
    *,
    naru_resources: Resources | None = None,
    relationships: list[Relationship] | None = None,
    active_effects: list[str] | None = None,
    strait_open: bool = True,
    reef_maru_status: str = "disputed",
) -> WorldState:
    """Construct a minimal WorldState with all three nations populated."""
    default_resources = Resources(military=50, treasury=50, food=50, support=50)
    return WorldState(
        turn=1,
        max_turns=5,
        nations={
            NationName.NARU: NationState(
                name=NationName.NARU,
                resources=naru_resources or default_resources,
                traits="trade-focused",
            ),
            NationName.VELDARA: NationState(
                name=NationName.VELDARA,
                resources=default_resources.model_copy(),
                traits="militant",
            ),
            NationName.TAUMA: NationState(
                name=NationName.TAUMA,
                resources=default_resources.model_copy(),
                traits="agrarian",
            ),
        },
        relationships=relationships if relationships is not None else [],
        reef_maru_status=reef_maru_status,
        active_effects=list(active_effects) if active_effects else [],
        strait_open=strait_open,
    )


# ---------------------------------------------------------------------------
# ResourceChange
# ---------------------------------------------------------------------------


def test_resource_change_positive_delta():
    state = make_state()
    new_state, applied, warnings = apply_changes(
        state,
        [ResourceChange(nation=NationName.NARU, field="military", delta=20, reason="x")],
    )
    assert new_state.nations[NationName.NARU].resources.military == 70
    assert warnings == []
    assert len(applied) == 1
    assert "+20" in applied[0].effect


def test_resource_change_negative_delta():
    state = make_state()
    new_state, _, warnings = apply_changes(
        state,
        [ResourceChange(nation=NationName.NARU, field="treasury", delta=-15, reason="x")],
    )
    assert new_state.nations[NationName.NARU].resources.treasury == 35
    assert warnings == []


def test_resource_change_clamps_at_upper_bound():
    state = make_state(naru_resources=Resources(military=90, treasury=50, food=50, support=50))
    new_state, applied, _ = apply_changes(
        state,
        [ResourceChange(nation=NationName.NARU, field="military", delta=50, reason="x")],
    )
    assert new_state.nations[NationName.NARU].resources.military == 100
    # actual_delta is reflected in the effect string, not the requested delta
    assert "+10" in applied[0].effect


def test_resource_change_clamps_at_lower_bound():
    state = make_state(naru_resources=Resources(military=5, treasury=50, food=50, support=50))
    new_state, applied, _ = apply_changes(
        state,
        [ResourceChange(nation=NationName.NARU, field="military", delta=-30, reason="x")],
    )
    assert new_state.nations[NationName.NARU].resources.military == 0
    assert "-5" in applied[0].effect


def test_resource_change_does_not_mutate_input_state():
    state = make_state()
    apply_changes(
        state,
        [ResourceChange(nation=NationName.NARU, field="military", delta=20, reason="x")],
    )
    assert state.nations[NationName.NARU].resources.military == 50


# ---------------------------------------------------------------------------
# RelationshipChange
# ---------------------------------------------------------------------------


def test_relationship_change_clamps_high():
    rel = Relationship(nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=80)
    state = make_state(relationships=[rel])
    new_state, applied, warnings = apply_changes(
        state,
        [RelationshipChange(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, delta=50, reason="x",
        )],
    )
    new_rel = new_state.relationships[0]
    assert new_rel.sentiment == 100
    assert warnings == []
    assert len(applied) == 1


def test_relationship_change_clamps_low():
    rel = Relationship(nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=-80)
    state = make_state(relationships=[rel])
    new_state, _, _ = apply_changes(
        state,
        [RelationshipChange(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, delta=-50, reason="x",
        )],
    )
    assert new_state.relationships[0].sentiment == -100


def test_relationship_change_lookup_is_unordered():
    # Stored as (NARU, VELDARA), looked up as (VELDARA, NARU)
    rel = Relationship(nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=10)
    state = make_state(relationships=[rel])
    new_state, applied, warnings = apply_changes(
        state,
        [RelationshipChange(
            nation_a=NationName.VELDARA, nation_b=NationName.NARU, delta=5, reason="x",
        )],
    )
    assert new_state.relationships[0].sentiment == 15
    assert warnings == []
    assert len(applied) == 1


def test_relationship_change_warns_when_pair_missing():
    state = make_state(relationships=[])
    new_state, applied, warnings = apply_changes(
        state,
        [RelationshipChange(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, delta=5, reason="x",
        )],
    )
    assert applied == []
    assert len(warnings) == 1
    assert "no pair" in warnings[0]


# ---------------------------------------------------------------------------
# StraitChange
# ---------------------------------------------------------------------------


def test_strait_change_open_to_closed():
    state = make_state(strait_open=True)
    new_state, applied, _ = apply_changes(
        state, [StraitChange(open=False, reason="x")],
    )
    assert new_state.strait_open is False
    assert len(applied) == 1


def test_strait_change_closed_to_open():
    state = make_state(strait_open=False)
    new_state, _, _ = apply_changes(state, [StraitChange(open=True, reason="x")])
    assert new_state.strait_open is True


# ---------------------------------------------------------------------------
# ActiveEffectAdd / ActiveEffectRemove
# ---------------------------------------------------------------------------


def test_effect_add_appends_new():
    state = make_state(active_effects=[])
    new_state, applied, _ = apply_changes(
        state, [ActiveEffectAdd(effect="famine", reason="x")],
    )
    assert new_state.active_effects == ["famine"]
    assert len(applied) == 1


def test_effect_add_idempotent_when_present():
    state = make_state(active_effects=["famine"])
    new_state, applied, warnings = apply_changes(
        state, [ActiveEffectAdd(effect="famine", reason="x")],
    )
    # No duplicate appended
    assert new_state.active_effects == ["famine"]
    # But the change is still recorded as applied (current contract)
    assert len(applied) == 1
    assert warnings == []


def test_effect_remove_present():
    state = make_state(active_effects=["famine", "blockade"])
    new_state, applied, warnings = apply_changes(
        state, [ActiveEffectRemove(effect="famine", reason="x")],
    )
    assert new_state.active_effects == ["blockade"]
    assert len(applied) == 1
    assert warnings == []


def test_effect_remove_absent_warns_and_does_not_record_applied():
    state = make_state(active_effects=["blockade"])
    new_state, applied, warnings = apply_changes(
        state, [ActiveEffectRemove(effect="famine", reason="x")],
    )
    assert new_state.active_effects == ["blockade"]
    assert applied == []
    assert len(warnings) == 1
    assert "famine" in warnings[0]


# ---------------------------------------------------------------------------
# ReefMaruStatusChange
# ---------------------------------------------------------------------------


def test_reef_maru_status_change_replaces_string():
    state = make_state(reef_maru_status="disputed")
    new_state, applied, _ = apply_changes(
        state, [ReefMaruStatusChange(new_status="claimed by Naru", reason="x")],
    )
    assert new_state.reef_maru_status == "claimed by Naru"
    assert len(applied) == 1


# ---------------------------------------------------------------------------
# Mixed list
# ---------------------------------------------------------------------------


def test_mixed_changes_apply_in_order():
    rel = Relationship(nation_a=NationName.NARU, nation_b=NationName.VELDARA, sentiment=0)
    state = make_state(relationships=[rel], strait_open=True, active_effects=[])
    changes = [
        ResourceChange(nation=NationName.NARU, field="military", delta=10, reason="r1"),
        StraitChange(open=False, reason="r2"),
        ActiveEffectAdd(effect="tension", reason="r3"),
        RelationshipChange(
            nation_a=NationName.NARU, nation_b=NationName.VELDARA, delta=-30, reason="r4",
        ),
        ActiveEffectRemove(effect="never_existed", reason="r5"),  # warns
    ]
    new_state, applied, warnings = apply_changes(state, changes)

    assert new_state.nations[NationName.NARU].resources.military == 60
    assert new_state.strait_open is False
    assert new_state.active_effects == ["tension"]
    assert new_state.relationships[0].sentiment == -30
    # 4 applied (the absent-effect remove is dropped), 1 warning
    assert len(applied) == 4
    assert len(warnings) == 1


def test_empty_changes_list():
    state = make_state()
    new_state, applied, warnings = apply_changes(state, [])
    assert applied == []
    assert warnings == []
    # state should be a copy, equal but not the same object
    assert new_state == state
    assert new_state is not state
