"""Tests for the production specification generator."""

import math

import pytest

from spurGearGenerator.models import (
    GearboxSolution,
    GearResult,
    StageGeometry,
    StageResult,
)
from spurGearGenerator.production import (
    MANUFACTURING_SPECS,
    case_depth_range,
    format_production,
    iso_1328_tolerances,
    quality_grade,
    surface_finish,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gear(role, teeth, module, material="steel_hardened", profile_shift=0.1):
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
        profile_shift=profile_shift,
        base_diameter_mm=round(module * teeth * math.cos(math.radians(20)), 4),
        root_diameter_mm=round(module * (teeth - 2.5 + 2 * profile_shift), 4),
        tip_diameter_corrected_mm=round(module * (teeth + 2 * 0.99), 4),
        tooth_thickness_ref_mm=round(
            module * math.pi / 2 + 2 * profile_shift * module * math.tan(math.radians(20)),
            4,
        ),
        addendum_coeff=0.99,
        dedendum_coeff=1.15,
    )


def _make_geometry():
    return StageGeometry(
        profile_shift_pinion=0.12,
        profile_shift_wheel=0.0,
        operating_pressure_angle_deg=20.71,
        operating_center_distance_mm=7.84,
        contact_ratio=1.544,
        backlash_mm=0.012,
        specific_sliding_tip_pinion=0.14,
        specific_sliding_tip_wheel=0.95,
        hertz_contact_stress_mpa=1508.0,
        tip_relief_pinion_mm=0.006,
        tip_relief_wheel_mm=0.006,
        root_fillet_radius_pinion_mm=0.142,
        root_fillet_radius_wheel_mm=0.129,
    )


def _make_solution(material="steel_hardened", module=0.3, n_stages=1):
    stages = []
    for i in range(n_stages):
        stages.append(
            StageResult(
                stage_number=i + 1,
                pinion=_make_gear("pinion", 15, module, material),
                wheel=_make_gear("wheel", 37, module, material, profile_shift=0.0),
                stage_ratio=37.0 / 15.0,
                mesh_efficiency=0.985,
                stage_torque_in_nm=0.09,
                geometry=_make_geometry(),
            )
        )
    return GearboxSolution(
        stages=stages,
        total_ratio=(37.0 / 15.0) ** n_stages,
        ratio_error_pct=-1.94,
        total_efficiency=0.985**n_stages,
        total_weight_kg=0.02 * n_stages,
        ranking_tag="weight",
    )


# ---------------------------------------------------------------------------
# case_depth_range
# ---------------------------------------------------------------------------


class TestCaseDepthRange:
    def test_small_module(self):
        result = case_depth_range(0.3)
        assert "\u2013" in result or "-" in result.replace("\u2013", "-")
        assert "mm" in result

    def test_larger_module(self):
        result = case_depth_range(2.0)
        # Lower bound: 0.15*2 + 0.15 = 0.45, Upper: 0.2*2 + 0.3 = 0.7
        assert "0.45" in result
        assert "0.7" in result

    def test_minimum_clamp(self):
        # Very small module should not go below 0.1mm
        result = case_depth_range(0.1)
        # lo = max(0.1, 0.015 + 0.15) = 0.17 — above 0.1 so no clamp
        assert "0.1" in result


# ---------------------------------------------------------------------------
# quality_grade
# ---------------------------------------------------------------------------


class TestQualityGrade:
    def test_small_steel(self):
        grade, method = quality_grade(0.3, "steel_hardened")
        assert grade == 6
        assert "ground" in method.lower()

    def test_medium_steel(self):
        grade, method = quality_grade(2.0, "steel_alloy")
        assert grade == 7
        assert "shaved" in method.lower()

    def test_large_steel(self):
        grade, method = quality_grade(5.0, "steel_mild")
        assert grade == 8
        assert "hobbed" in method.lower()

    def test_boundary_module_1(self):
        grade, _ = quality_grade(1.0, "steel_hardened")
        assert grade == 6

    def test_polymer_small(self):
        grade, method = quality_grade(0.3, "nylon")
        assert grade == 9
        assert "moulded" in method.lower()

    def test_polymer_large(self):
        grade, method = quality_grade(1.0, "pom")
        assert grade == 10
        assert "moulded" in method.lower()

    def test_brass(self):
        grade, _ = quality_grade(0.5, "brass")
        assert grade == 6


# ---------------------------------------------------------------------------
# surface_finish
# ---------------------------------------------------------------------------


class TestSurfaceFinish:
    def test_grade_5(self):
        assert "0.8" in surface_finish(5)

    def test_grade_6(self):
        assert "0.8" in surface_finish(6)

    def test_grade_7(self):
        assert "1.6" in surface_finish(7)

    def test_grade_8(self):
        assert "3.2" in surface_finish(8)

    def test_grade_10(self):
        assert "6.3" in surface_finish(10)


# ---------------------------------------------------------------------------
# iso_1328_tolerances
# ---------------------------------------------------------------------------


class TestIso1328Tolerances:
    def test_returns_all_keys(self):
        tol = iso_1328_tolerances(0.3, 15, 4.5, 1.5, 6)
        assert set(tol.keys()) == {"fpt", "Fp", "Fa", "Fb", "Fr"}

    def test_values_positive(self):
        tol = iso_1328_tolerances(1.0, 20, 20.0, 10.0, 7)
        for v in tol.values():
            assert v > 0

    def test_higher_grade_larger_tolerances(self):
        tol_6 = iso_1328_tolerances(1.0, 20, 20.0, 10.0, 6)
        tol_8 = iso_1328_tolerances(1.0, 20, 20.0, 10.0, 8)
        for key in tol_6:
            assert tol_8[key] > tol_6[key]

    def test_grade_5_no_scaling(self):
        # At grade 5, scale factor is 1.0
        tol = iso_1328_tolerances(1.0, 20, 20.0, 10.0, 5)
        fpt_5 = 0.3 * 1.0 + 0.003 * 20.0 + 4.0
        assert tol["fpt"] == pytest.approx(fpt_5, abs=0.1)

    def test_reasonable_values_small_gear(self):
        # m=0.3, z=15, d=4.5, b=1.5, Q=6
        tol = iso_1328_tolerances(0.3, 15, 4.5, 1.5, 6)
        # fpt should be in the range 4-10 μm for small precision gears
        assert 3.0 < tol["fpt"] < 15.0
        # Fr should be reasonable
        assert 5.0 < tol["Fr"] < 20.0


# ---------------------------------------------------------------------------
# format_production
# ---------------------------------------------------------------------------


class TestFormatProduction:
    def test_contains_header(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "PRODUCTION SPECIFICATION" in text

    def test_contains_solution_number(self):
        sol = _make_solution()
        text = format_production(sol, 3)
        assert "Solution #3" in text

    def test_contains_module(self):
        sol = _make_solution(module=0.3)
        text = format_production(sol, 1)
        assert "0.3 mm" in text

    def test_contains_teeth(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Teeth:" in text
        assert "15" in text
        assert "37" in text

    def test_contains_profile_shift(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Profile shift:" in text
        assert "x = " in text

    def test_contains_material_trade_names(self):
        sol = _make_solution(material="steel_hardened")
        text = format_production(sol, 1)
        assert "16MnCr5" in text

    def test_contains_heat_treatment(self):
        sol = _make_solution(material="steel_hardened")
        text = format_production(sol, 1)
        assert "Case carburised" in text
        assert "HRC" in text

    def test_contains_case_depth(self):
        sol = _make_solution(material="steel_hardened")
        text = format_production(sol, 1)
        assert "Case depth" in text

    def test_contains_quality_grade(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "ISO 1328" in text
        assert "grade 6" in text

    def test_contains_surface_finish(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Ra" in text

    def test_contains_tolerances(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "fpt" in text
        assert "Fp" in text
        assert "\u03bcm" in text  # μm

    def test_contains_backlash(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Backlash" in text
        assert "0.012" in text

    def test_contains_cut_tooth_thickness(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Tooth thickness (cut)" in text
        assert "Backlash allowance" in text

    def test_cut_thickness_equals_ref_minus_half_backlash(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        # Pinion: tooth_thickness_ref = m*(pi/2 + 2*x*tan(20°))
        # with m=0.3, x=0.1 → ref ≈ 0.4930
        pinion = sol.stages[0].pinion
        backlash = sol.stages[0].geometry.backlash_mm  # 0.012
        expected = pinion.tooth_thickness_ref_mm - backlash / 2.0
        assert f"{expected:.4f}" in text

    def test_contains_root_fillet(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Root fillet" in text

    def test_contains_tip_relief(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Tip relief" in text

    def test_contains_centre_distance(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Centre distance" in text
        assert "7.840" in text

    def test_contains_contact_ratio(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "Contact ratio" in text
        assert "1.544" in text

    def test_multi_stage(self):
        sol = _make_solution(n_stages=3)
        text = format_production(sol, 1)
        assert "PART 1" in text
        assert "PART 2" in text
        assert "PART 3" in text
        assert "PART 4" in text
        assert "3-stage" in text
        assert "compound" in text.lower()
        assert "MESH 1" in text
        assert "MESH 2" in text
        assert "MESH 3" in text
        assert "BILL OF MATERIALS" in text

    def test_contains_notes(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "NOTES" in text
        assert "ISO 53" in text

    def test_polymer_material(self):
        sol = _make_solution(material="nylon")
        text = format_production(sol, 1)
        assert "PA6" in text
        assert "Injection moulded" in text
        assert "Case depth" not in text

    def test_no_case_depth_for_alloy_steel(self):
        sol = _make_solution(material="steel_alloy")
        text = format_production(sol, 1)
        assert "42CrMo4" in text
        assert "Case depth" not in text

    def test_iso_reference(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        assert "ISO 53" in text
        assert "ha* = 1.0" in text

    def test_total_ratio_in_header(self):
        sol = _make_solution()
        text = format_production(sol, 1)
        ratio_str = f"{sol.total_ratio:.4f}"
        assert ratio_str in text


# ---------------------------------------------------------------------------
# Part-based structure
# ---------------------------------------------------------------------------


class TestPartBasedStructure:
    def test_single_stage_has_two_parts(self):
        sol = _make_solution(n_stages=1)
        text = format_production(sol, 1)
        assert "PART 1" in text
        assert "PART 2" in text
        assert "PART 3" not in text
        assert "Input shaft" in text
        assert "Output shaft" in text

    def test_two_stage_has_compound_part(self):
        sol = _make_solution(n_stages=2)
        text = format_production(sol, 1)
        assert "PART 1" in text
        assert "PART 2" in text
        assert "PART 3" in text
        assert "compound" in text.lower()
        # Part 2 should have 2 gears
        assert "GEAR A" in text
        assert "GEAR B" in text

    def test_compound_assembly_instructions(self):
        sol = _make_solution(n_stages=2)
        text = format_production(sol, 1)
        assert "ASSEMBLY" in text
        assert "manufactured independently" in text
        assert "press" in text.lower()

    def test_single_stage_no_assembly_section(self):
        sol = _make_solution(n_stages=1)
        text = format_production(sol, 1)
        assert "manufactured independently" not in text

    def test_mesh_partner_references(self):
        sol = _make_solution(n_stages=2)
        text = format_production(sol, 1)
        # Part 1 pinion meshes with Part 2
        assert "meshes with Part 2" in text
        # Part 3 wheel meshes with Part 2
        assert "meshes with Part 2" in text

    def test_bom_lists_all_parts(self):
        sol = _make_solution(n_stages=3)
        text = format_production(sol, 1)
        assert "BILL OF MATERIALS" in text
        assert "Part 1:" in text
        assert "Part 2:" in text
        assert "Part 3:" in text
        assert "Part 4:" in text

    def test_mesh_section_present(self):
        sol = _make_solution(n_stages=2)
        text = format_production(sol, 1)
        assert "MESH SPECIFICATIONS" in text
        assert "MESH 1" in text
        assert "MESH 2" in text

    def test_mesh_contains_centre_distance(self):
        sol = _make_solution(n_stages=1)
        text = format_production(sol, 1)
        assert "7.840" in text

    def test_mesh_shows_hertz_stress(self):
        sol = _make_solution(n_stages=1)
        text = format_production(sol, 1)
        assert "1508.0 MPa" in text

    def test_parts_count_in_header(self):
        sol = _make_solution(n_stages=2)
        text = format_production(sol, 1)
        assert "Parts:            3" in text

    def test_compound_note_in_notes(self):
        sol = _make_solution(n_stages=1)
        text = format_production(sol, 1)
        assert "Compound parts" in text


class TestManufacturingSpecs:
    def test_all_materials_have_specs(self):
        from spurGearGenerator.materials import MATERIALS

        for mat in MATERIALS:
            assert mat.key in MANUFACTURING_SPECS, f"Missing spec for {mat.key}"

    def test_specs_have_required_fields(self):
        for key, spec in MANUFACTURING_SPECS.items():
            assert "trade_names" in spec, f"{key} missing trade_names"
            assert "heat_treatment" in spec, f"{key} missing heat_treatment"
            assert "case_depth" in spec, f"{key} missing case_depth"


# ---------------------------------------------------------------------------
# format_production without geometry (pre-generate)
# ---------------------------------------------------------------------------


class TestFormatProductionWithoutGeometry:
    def test_works_without_geometry(self):
        """Production spec should still render when geometry is None."""
        sol = GearboxSolution(
            stages=[
                StageResult(
                    stage_number=1,
                    pinion=GearResult(
                        role="pinion",
                        teeth=15,
                        module=0.3,
                        material="steel_hardened",
                        pitch_diameter_mm=4.5,
                        addendum_diameter_mm=5.1,
                        face_width_mm=1.5,
                        lewis_stress_mpa=200.0,
                        allowable_stress_mpa=380.0,
                        weight_kg=0.001,
                    ),
                    wheel=GearResult(
                        role="wheel",
                        teeth=37,
                        module=0.3,
                        material="steel_hardened",
                        pitch_diameter_mm=11.1,
                        addendum_diameter_mm=11.7,
                        face_width_mm=1.5,
                        lewis_stress_mpa=200.0,
                        allowable_stress_mpa=380.0,
                        weight_kg=0.005,
                    ),
                    stage_ratio=37.0 / 15.0,
                    mesh_efficiency=0.985,
                    stage_torque_in_nm=0.09,
                    geometry=None,
                )
            ],
            total_ratio=37.0 / 15.0,
            ratio_error_pct=0.0,
            total_efficiency=0.985,
            total_weight_kg=0.006,
            ranking_tag="weight",
        )
        text = format_production(sol, 1)
        assert "PRODUCTION SPECIFICATION" in text
        assert "0.3 mm" in text
        # Should show addendum diameter when corrected tip is not available
        assert "5.100" in text
