"""Tests for the solver module."""

import pytest

from spurGearGenerator.models import GearConfig
from spurGearGenerator.solver import solve


def _make_config(**overrides) -> GearConfig:
    defaults = {"target_ratio": 3.0, "input_torque": 0.5, "reduction_margin": 5.0, "max_teeth_per_gear": 80, "axis_margin": 0.0}
    defaults.update(overrides)
    return GearConfig(**defaults)


# ---- Single stage -----------------------------------------------------------


def test_single_stage_finds_solutions():
    config = _make_config(target_ratio=2.0)
    solutions, _ = solve(config, max_stages=1)
    assert len(solutions) > 0


def test_single_stage_ratio_within_margin():
    config = _make_config(target_ratio=3.0, reduction_margin=5.0)
    solutions, _ = solve(config, max_stages=1)
    for s in solutions:
        assert abs(s.ratio_error_pct) <= 5.0 + 1e-6


def test_single_stage_exact_integer_ratio():
    config = _make_config(target_ratio=2.0, reduction_margin=0.1)
    solutions, _ = solve(config, max_stages=1)
    # With margin ~0.1%, exact 2:1 solutions should exist (e.g. 12/24, 13/26, ...)
    exact = [s for s in solutions if abs(s.ratio_error_pct) < 0.01]
    assert len(exact) > 0


def test_single_stage_no_solutions():
    """Ratio too large for single stage with small max teeth."""
    config = _make_config(target_ratio=20.0, max_teeth_per_gear=30, reduction_margin=1.0)
    solutions, _ = solve(config, max_stages=1)
    assert solutions == []


# ---- Multi stage ------------------------------------------------------------


def test_two_stage_finds_solutions():
    config = _make_config(target_ratio=10.0, reduction_margin=3.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    assert len(solutions) > 0
    # At least one solution should be 2-stage
    two_stage = [s for s in solutions if len(s.stages) == 2]
    assert len(two_stage) > 0


def test_two_stage_ratio_within_margin():
    config = _make_config(target_ratio=10.0, reduction_margin=3.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    for s in solutions:
        assert abs(s.ratio_error_pct) <= 3.0 + 1e-6


def test_two_stage_total_ratio_is_product_of_stages():
    config = _make_config(target_ratio=8.0, reduction_margin=5.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    for s in solutions:
        product = 1.0
        for stage in s.stages:
            product *= stage.stage_ratio
        assert s.total_ratio == pytest.approx(product, rel=1e-9)


# ---- Compound gear constraint -----------------------------------------------


def test_compound_gear_shared_material():
    """Wheel of stage N and pinion of stage N+1 must share the same material."""
    config = _make_config(target_ratio=8.0, reduction_margin=5.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    for s in solutions:
        if len(s.stages) >= 2:
            for i in range(len(s.stages) - 1):
                wheel_mat = s.stages[i].wheel.material
                next_pinion_mat = s.stages[i + 1].pinion.material
                assert wheel_mat == next_pinion_mat, (
                    f"Stage {i} wheel ({wheel_mat}) != stage {i+1} pinion ({next_pinion_mat})"
                )


# ---- Stress check -----------------------------------------------------------


def test_stress_within_allowable():
    """All gears should have stress <= allowable."""
    config = _make_config(target_ratio=3.0, input_torque=1.0)
    solutions, _ = solve(config, max_stages=1)
    for s in solutions:
        for stage in s.stages:
            assert stage.pinion.lewis_stress_mpa <= stage.pinion.allowable_stress_mpa + 1e-6
            assert stage.wheel.lewis_stress_mpa <= stage.wheel.allowable_stress_mpa + 1e-6


# ---- Torque propagation ----------------------------------------------------


def test_torque_propagation():
    """Torque at stage 2 = input_torque * stage_1_ratio."""
    config = _make_config(target_ratio=8.0, reduction_margin=5.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    for s in solutions:
        if len(s.stages) == 2:
            expected_torque_s2 = config.input_torque * s.stages[0].stage_ratio
            assert s.stages[1].stage_torque_in_nm == pytest.approx(expected_torque_s2, rel=1e-9)
            break  # one check is enough


# ---- Efficiency -------------------------------------------------------------


def test_total_efficiency_is_product_of_stages():
    config = _make_config(target_ratio=8.0, reduction_margin=5.0, max_teeth_per_gear=60)
    solutions, _ = solve(config, max_stages=2)
    for s in solutions:
        product = 1.0
        for stage in s.stages:
            product *= stage.mesh_efficiency
        assert s.total_efficiency == pytest.approx(product, rel=1e-9)


def test_efficiency_is_reasonable():
    """Efficiency should be between 0 and 1 for all solutions."""
    config = _make_config(target_ratio=3.0)
    solutions, _ = solve(config, max_stages=1)
    for s in solutions:
        assert 0.5 < s.total_efficiency <= 1.0


# ---- Ranking ----------------------------------------------------------------


def test_weight_ranking_sorted():
    config = _make_config(target_ratio=3.0)
    solutions, _ = solve(config, max_stages=1)
    weight_solutions = [s for s in solutions if "weight" in s.ranking_tag]
    weights = [s.total_weight_kg for s in weight_solutions]
    assert weights == sorted(weights)


def test_at_most_20_solutions():
    """Top 10 weight + top 10 efficiency = at most 20 unique."""
    config = _make_config(target_ratio=3.0, max_teeth_per_gear=80)
    solutions, _ = solve(config, max_stages=1)
    assert len(solutions) <= 20


# ---- Min output root diameter -----------------------------------------------


def test_min_output_root_diameter_constraint():
    """All output wheels must have root diameter >= min_output_root_diameter."""
    min_root = 15.0  # mm
    config = _make_config(target_ratio=3.0, min_output_root_diameter=min_root)
    solutions, _ = solve(config, max_stages=1)
    assert len(solutions) > 0
    for s in solutions:
        last_wheel = s.stages[-1].wheel
        root_diam = last_wheel.module * (last_wheel.teeth - 2.5)
        assert root_diam >= min_root - 1e-6, (
            f"Root diameter {root_diam:.2f} mm < {min_root} mm"
        )


def test_min_output_root_diameter_restricts_solutions():
    """A large min root diameter should reduce the number of solutions."""
    config_no_limit = _make_config(target_ratio=3.0)
    config_with_limit = _make_config(target_ratio=3.0, min_output_root_diameter=30.0)
    sols_no_limit, _ = solve(config_no_limit, max_stages=1)
    sols_with_limit, _ = solve(config_with_limit, max_stages=1)
    # The constrained set should be no larger (and likely smaller or different)
    assert len(sols_with_limit) <= len(sols_no_limit)


def test_min_output_root_diameter_too_large():
    """An impossibly large min root diameter should yield no solutions."""
    config = _make_config(target_ratio=3.0, min_output_root_diameter=1000.0)
    solutions, _ = solve(config, max_stages=1)
    assert solutions == []
