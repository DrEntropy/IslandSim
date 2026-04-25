"""Tests for islandsim.rules.skill_roll — opposed stochastic check."""

from __future__ import annotations

import random

from islandsim.rules import skill_roll


def test_seeded_reproducibility():
    """Same seed → same outcome, every time."""
    out1 = skill_roll(60, 40, difficulty=10, rng=random.Random(42))
    out2 = skill_roll(60, 40, difficulty=10, rng=random.Random(42))
    assert out1.roll == out2.roll
    assert out1.margin == out2.margin
    assert out1.success == out2.success


def test_different_seeds_can_differ():
    """Sanity check: not all seeds collapse to the same output."""
    seen = {skill_roll(50, 50, rng=random.Random(s)).roll for s in range(20)}
    assert len(seen) > 1


def test_roll_within_bounds():
    """The raw random component must always lie in [-30, 30]."""
    for seed in range(200):
        out = skill_roll(50, 50, rng=random.Random(seed))
        assert -30 <= out.roll <= 30


def test_margin_formula():
    """margin == attacker_skill - defender_skill - difficulty + roll."""
    out = skill_roll(70, 40, difficulty=15, rng=random.Random(123))
    assert out.margin == 70 - 40 - 15 + out.roll
    assert out.attacker_skill == 70
    assert out.defender_skill == 40
    assert out.difficulty == 15


def test_difficulty_subtracts_from_margin():
    """With the RNG fixed, raising difficulty by N drops margin by exactly N."""
    base = skill_roll(60, 40, difficulty=0, rng=random.Random(7))
    harder = skill_roll(60, 40, difficulty=20, rng=random.Random(7))
    # Same seed → same noise, so the only delta should be the difficulty
    assert harder.roll == base.roll
    assert base.margin - harder.margin == 20


def test_success_boundary_at_zero():
    """margin == 0 must count as success (spec is `>= 0`, not `> 0`)."""
    # Construct inputs where attacker - defender - difficulty + roll == 0.
    # Easiest: equal skills, difficulty=0, and any seed; then assert
    # success iff roll >= 0.
    for seed in range(50):
        out = skill_roll(50, 50, difficulty=0, rng=random.Random(seed))
        assert out.success == (out.roll >= 0)


def test_default_rng_used_when_none_passed():
    """Smoke-test: skill_roll works without an explicit rng argument."""
    out = skill_roll(50, 50)
    assert -30 <= out.roll <= 30
    assert out.margin == out.roll
    assert out.success == (out.margin >= 0)
