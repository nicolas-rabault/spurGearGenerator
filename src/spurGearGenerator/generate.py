"""Orchestration for the generate command.

Loads a solution, optimizes tooth geometry, saves results, and writes solution.txt.
"""

import json
import math
from pathlib import Path

from spurGearGenerator.cli import format_solution
from spurGearGenerator.models import GearboxSolution, SpringResult
from spurGearGenerator.production import format_production
from spurGearGenerator.tooth_profile import (
    PRESSURE_ANGLE_RAD,
    base_diameter,
    optimize_stage,
    root_diameter,
    tip_diameter_corrected,
    tooth_thickness_at_reference,
)


def load_solution(
    results_path: Path,
    number: int,
) -> tuple[list[dict], GearboxSolution, int]:
    """Load a results JSON file and extract solution by 1-based number.

    Returns (raw_data_list, parsed_solution, zero_based_index).
    """
    with open(results_path) as f:
        data = json.load(f)
    if not 1 <= number <= len(data):
        raise ValueError(f"Solution {number} not found (file has {len(data)} solutions)")
    idx = number - 1
    solution = GearboxSolution(**data[idx])
    return data, solution, idx


def optimize_solution(solution: GearboxSolution) -> GearboxSolution:
    """Run tooth geometry optimization on each stage of the solution."""
    new_stages = []
    for stage in solution.stages:
        z1 = stage.pinion.teeth
        z2 = stage.wheel.teeth
        m = stage.pinion.module
        b = stage.pinion.face_width_mm
        torque = stage.stage_torque_in_nm
        mat1 = stage.pinion.material
        mat2 = stage.wheel.material

        geometry = optimize_stage(z1, z2, m, b, torque, mat1, mat2)
        alpha_w = math.radians(geometry.operating_pressure_angle_deg)

        # Update pinion with computed geometry fields
        x1 = geometry.profile_shift_pinion
        x2 = geometry.profile_shift_wheel
        d_pitch1 = stage.pinion.pitch_diameter_mm
        d_root1 = root_diameter(m, z1, x1)
        d_tip1 = tip_diameter_corrected(m, z1, x1, z2, x2, PRESSURE_ANGLE_RAD, alpha_w)
        pinion = stage.pinion.model_copy(update={
            "profile_shift": x1,
            "base_diameter_mm": round(base_diameter(m, z1), 4),
            "root_diameter_mm": round(d_root1, 4),
            "tip_diameter_corrected_mm": round(d_tip1, 4),
            "tooth_thickness_ref_mm": round(tooth_thickness_at_reference(m, x1), 4),
            "addendum_coeff": round((d_tip1 - d_pitch1) / (2.0 * m), 4),
            "dedendum_coeff": round((d_pitch1 - d_root1) / (2.0 * m), 4),
        })

        # Update wheel with computed geometry fields
        d_pitch2 = stage.wheel.pitch_diameter_mm
        d_root2 = root_diameter(m, z2, x2)
        d_tip2 = tip_diameter_corrected(m, z2, x2, z1, x1, PRESSURE_ANGLE_RAD, alpha_w)
        wheel = stage.wheel.model_copy(update={
            "profile_shift": x2,
            "base_diameter_mm": round(base_diameter(m, z2), 4),
            "root_diameter_mm": round(d_root2, 4),
            "tip_diameter_corrected_mm": round(d_tip2, 4),
            "tooth_thickness_ref_mm": round(tooth_thickness_at_reference(m, x2), 4),
            "addendum_coeff": round((d_tip2 - d_pitch2) / (2.0 * m), 4),
            "dedendum_coeff": round((d_pitch2 - d_root2) / (2.0 * m), 4),
        })

        new_stage = stage.model_copy(update={
            "pinion": pinion,
            "wheel": wheel,
            "geometry": geometry,
        })
        new_stages.append(new_stage)

    return solution.model_copy(update={"stages": new_stages})


def save_solution(
    data: list[dict],
    solution: GearboxSolution,
    idx: int,
    results_path: Path,
) -> None:
    """Replace the solution at index idx and write back to JSON."""
    data[idx] = solution.model_dump()
    with open(results_path, "w") as f:
        json.dump(data, f, indent=2)


def create_output_dir(results_path: Path, number: int) -> Path:
    """Create and return the output directory: solutions/<config_stem>/<number>/."""
    config_stem = results_path.stem.replace("_results", "")
    out_dir = results_path.parent / "solutions" / config_stem / str(number)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def compute_spring(solution: GearboxSolution, max_angle: float) -> SpringResult:
    """Compute rubber torsion spring dimensions for the gearbox output."""
    from spring_generator import compute_spring as sg_compute

    last = solution.stages[-1]
    torque_out = last.stage_torque_in_nm * last.stage_ratio * last.mesh_efficiency

    dims = sg_compute(max_torque=torque_out, max_angle=max_angle)

    return SpringResult(
        max_torque_nm=round(dims.max_torque, 4),
        max_angle_deg=round(dims.max_angle, 2),
        outer_diameter_mm=round(dims.outer_diameter * 1000, 4),
        inner_diameter_mm=round(dims.inner_diameter * 1000, 4),
        thickness_mm=round(dims.thickness * 1000, 4),
        spring_constant_nm_per_rad=round(dims.spring_constant, 4),
        max_shear_strain=round(dims.max_shear_strain, 4),
        rubber_weight_kg=round(dims.rubber_weight, 6),
        material=dims.material,
        safety_factor=dims.safety_factor,
    )


def generate(
    results_path: Path,
    number: int,
    verbose: bool = False,
    onshape_url: str | None = None,
    spring_angle: float | None = None,
) -> Path:
    """Top-level orchestration: optimize, save, and export a solution.

    Returns the output directory path.
    """
    # 1. Load
    data, solution, idx = load_solution(results_path, number)

    if verbose:
        n_stages = len(solution.stages)
        print(f"Loaded solution #{number} ({n_stages} stage(s))")

    # 2. Optimize
    if verbose:
        print("Optimizing tooth geometry...")
    optimized = optimize_solution(solution)

    # 3. Compute spring (if requested)
    if spring_angle is not None:
        if verbose:
            print(f"Computing spring dimensions for {spring_angle}° max angle...")
        spring_result = compute_spring(optimized, spring_angle)
        optimized = optimized.model_copy(update={"spring": spring_result})

    # 4. Save back to JSON
    save_solution(data, optimized, idx, results_path)
    if verbose:
        print(f"Saved optimized parameters to {results_path}")

    # 5. Create output directory
    out_dir = create_output_dir(results_path, number)

    # 6. Write text files
    text = format_solution(optimized, number)
    (out_dir / "solution.txt").write_text(text)
    if verbose:
        print("Wrote solution.txt")

    prod_text = format_production(optimized, number)
    (out_dir / "prod.txt").write_text(prod_text)
    if verbose:
        print("Wrote prod.txt")

    # 7. Push to Onshape (if URL provided)
    if onshape_url:
        from spurGearGenerator.onshape import push_to_onshape

        push_to_onshape(optimized, onshape_url, verbose=verbose)

    return out_dir
