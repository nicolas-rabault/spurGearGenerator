"""Tests for the generate orchestration module."""

import json
import math

import pytest

from spurGearGenerator.generate import (
    create_output_dir,
    load_solution,
    optimize_solution,
    save_solution,
)
from spurGearGenerator.models import (
    GearboxSolution,
    GearResult,
    StageResult,
)


def _make_gear(role, teeth, module, material="steel_hardened"):
    return GearResult(
        role=role,
        teeth=teeth,
        module=module,
        material=material,
        pitch_diameter_mm=module * teeth,
        addendum_diameter_mm=module * (teeth + 2),
        face_width_mm=module * 5,
        lewis_stress_mpa=200.0,
        allowable_stress_mpa=380.0,
        weight_kg=0.01,
    )


def _make_solution():
    return GearboxSolution(
        stages=[
            StageResult(
                stage_number=1,
                pinion=_make_gear("pinion", 15, 1.0),
                wheel=_make_gear("wheel", 30, 1.0),
                stage_ratio=2.0,
                mesh_efficiency=0.98,
                stage_torque_in_nm=0.5,
            )
        ],
        total_ratio=2.0,
        ratio_error_pct=0.0,
        total_efficiency=0.98,
        total_weight_kg=0.02,
        ranking_tag="weight",
    )


def _write_results_file(tmp_path, solutions=None):
    """Write a results JSON file and return its path."""
    if solutions is None:
        solutions = [_make_solution()]
    data = [s.model_dump() for s in solutions]
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps(data, indent=2))
    return results_path


def test_load_solution_valid(tmp_path):
    results_path = _write_results_file(tmp_path)
    data, solution, idx = load_solution(results_path, 1)
    assert idx == 0
    assert len(data) == 1
    assert solution.total_ratio == pytest.approx(2.0)


def test_load_solution_invalid_number(tmp_path):
    results_path = _write_results_file(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        load_solution(results_path, 5)


def test_optimize_solution_populates_geometry():
    sol = _make_solution()
    optimized = optimize_solution(sol)
    for stage in optimized.stages:
        assert stage.geometry is not None
        assert stage.geometry.contact_ratio > 1.0
        assert stage.geometry.operating_pressure_angle_deg >= 20.0


def test_optimize_solution_populates_gear_fields():
    sol = _make_solution()
    optimized = optimize_solution(sol)
    for stage in optimized.stages:
        for gear in [stage.pinion, stage.wheel]:
            assert gear.profile_shift is not None
            assert gear.base_diameter_mm is not None
            assert gear.root_diameter_mm is not None
            assert gear.tip_diameter_corrected_mm is not None
            assert gear.tooth_thickness_ref_mm is not None


def test_optimize_solution_preserves_existing():
    sol = _make_solution()
    optimized = optimize_solution(sol)
    # Original fields should be preserved
    assert optimized.stages[0].pinion.teeth == 15
    assert optimized.stages[0].wheel.teeth == 30
    assert optimized.stages[0].pinion.module == 1.0
    assert optimized.total_ratio == pytest.approx(2.0)


def test_save_solution_roundtrip(tmp_path):
    results_path = _write_results_file(tmp_path)
    data, solution, idx = load_solution(results_path, 1)
    optimized = optimize_solution(solution)
    save_solution(data, optimized, idx, results_path)

    # Reload and verify
    data2, reloaded, _ = load_solution(results_path, 1)
    assert reloaded.stages[0].geometry is not None
    assert reloaded.stages[0].pinion.profile_shift is not None


def test_create_output_dir(tmp_path):
    results_path = tmp_path / "myconfig_results.json"
    results_path.write_text("[]")
    out_dir = create_output_dir(results_path, 3)
    assert out_dir.exists()
    assert out_dir == tmp_path / "solutions" / "myconfig" / "3"
