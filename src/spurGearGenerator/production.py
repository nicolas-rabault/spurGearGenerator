"""Production specification generator for spur gear manufacturing.

Generates a human-readable prod.txt with all information needed to manufacture
the gears: dimensions, tolerances, material grades, heat treatment, and
quality specifications.
"""

import math

from dataclasses import dataclass, field

from spurGearGenerator.materials import MATERIAL_BY_KEY
from spurGearGenerator.models import (
    GearboxSolution,
    GearResult,
    StageGeometry,
    StageResult,
)

# ---------------------------------------------------------------------------
# Manufacturing specifications per material key
# ---------------------------------------------------------------------------

MANUFACTURING_SPECS: dict[str, dict] = {
    "steel_hardened": {
        "trade_names": "16MnCr5, 20MnCr5, or equivalent",
        "heat_treatment": "Case carburised, 58–62 HRC",
        "case_depth": True,
    },
    "steel_alloy": {
        "trade_names": "42CrMo4 (AISI 4140) or equivalent",
        "heat_treatment": "Quench & temper, 28–32 HRC",
        "case_depth": False,
    },
    "steel_mild": {
        "trade_names": "C45 / S45C (AISI 1045) or equivalent",
        "heat_treatment": "Normalised, no hardening",
        "case_depth": False,
    },
    "brass": {
        "trade_names": "CuZn39Pb3 (CW614N / C360)",
        "heat_treatment": "None required",
        "case_depth": False,
    },
    "bronze": {
        "trade_names": "CuSn8P (CC483K / C52100)",
        "heat_treatment": "None required",
        "case_depth": False,
    },
    "aluminum": {
        "trade_names": "EN AW-6061-T6 (AA 6061-T6)",
        "heat_treatment": "T6 precipitation hardened",
        "case_depth": False,
    },
    "nylon": {
        "trade_names": "PA6 or PA66",
        "heat_treatment": "N/A",
        "case_depth": False,
    },
    "pom": {
        "trade_names": "POM-C (Delrin / Hostaform C)",
        "heat_treatment": "N/A",
        "case_depth": False,
    },
}


# ---------------------------------------------------------------------------
# Manufacturing derivation functions
# ---------------------------------------------------------------------------


def case_depth_range(module: float) -> str:
    """Recommended effective case depth range derived from module (mm).

    Rule of thumb for case-carburised small gears:
    lower bound ≈ 0.15*m + 0.15 mm, upper bound ≈ 0.2*m + 0.3 mm.
    """
    lo = round(0.15 * module + 0.15, 2)
    hi = round(0.2 * module + 0.3, 2)
    lo = max(0.1, lo)
    hi = max(lo + 0.1, hi)
    return f"{lo}–{hi} mm (effective)"


def quality_grade(module: float, material_key: str) -> tuple[int, str]:
    """Derive ISO 1328 quality grade and manufacturing method.

    Returns (grade, method_description).
    """
    is_polymer = material_key in ("nylon", "pom")
    if is_polymer:
        if module <= 0.5:
            return 9, "Injection moulded"
        return 10, "Injection moulded"
    # Metals
    if module <= 1.0:
        return 6, "Hobbed + ground"
    elif module <= 3.0:
        return 7, "Hobbed + shaved"
    else:
        return 8, "Hobbed"


def surface_finish(grade: int) -> str:
    """Recommended flank surface roughness for a given quality grade."""
    if grade <= 6:
        return "Ra \u2264 0.8 \u03bcm (flanks)"
    elif grade <= 7:
        return "Ra \u2264 1.6 \u03bcm (flanks)"
    elif grade <= 8:
        return "Ra \u2264 3.2 \u03bcm (flanks)"
    else:
        return "Ra \u2264 6.3 \u03bcm"


def iso_1328_tolerances(
    module: float,
    teeth: int,
    d_ref: float,
    face_width: float,
    grade: int,
) -> dict[str, float]:
    """Approximate ISO 1328-1 tolerances in micrometres.

    Uses simplified formulas derived from ISO 1328-1:2013 tables.
    Each quality step from the base grade (5) scales by sqrt(2).

    Parameters
    ----------
    module : mm
    teeth : number of teeth
    d_ref : reference (pitch) diameter in mm
    face_width : face width in mm
    grade : ISO 1328-1 quality grade (typically 5–12)

    Returns dict with keys: fpt, Fp, Fa, Fb, Fr (all in micrometres).
    """
    # Base tolerances for quality grade 5
    fpt_5 = 0.3 * module + 0.003 * d_ref + 4.0
    fa_5 = 2.5 + 0.7 * math.sqrt(module)
    fb_5 = 3.0 + 0.6 * math.sqrt(face_width)
    fr_5 = 5.0 + 0.7 * math.sqrt(d_ref)

    # Scale factor: each grade step multiplies by sqrt(2)
    scale = math.sqrt(2) ** (grade - 5)

    fpt = fpt_5 * scale
    fp = fpt * 0.7 * math.sqrt(teeth)
    fa = fa_5 * scale
    fb = fb_5 * scale
    fr = fr_5 * scale

    return {
        "fpt": round(fpt, 1),
        "Fp": round(fp, 1),
        "Fa": round(fa, 1),
        "Fb": round(fb, 1),
        "Fr": round(fr, 1),
    }


# ---------------------------------------------------------------------------
# Part-based structure: group gears by physical shaft
# ---------------------------------------------------------------------------


@dataclass
class _GearOnShaft:
    """A single gear mounted on a shaft, with its stage context."""

    gear: GearResult
    stage: StageResult
    role: str  # "pinion" or "wheel"
    mesh_partner_part: int = 0  # 1-based part number of the meshing partner


@dataclass
class _Part:
    """A physical shaft carrying one or two gears."""

    part_number: int
    label: str  # e.g. "Input shaft", "Shaft 2", "Output shaft"
    gears: list[_GearOnShaft] = field(default_factory=list)
    is_compound: bool = False


def _collect_parts(solution: GearboxSolution) -> list[_Part]:
    """Group gears by physical shaft.

    For N stages the gearbox has N+1 shafts:
      - Part 1  (input):  Stage 1 pinion
      - Part 2..N:        Stage i wheel + Stage i+1 pinion  (compound)
      - Part N+1 (output): Stage N wheel
    """
    stages = solution.stages
    n = len(stages)
    parts: list[_Part] = []

    # Part 1 — input shaft
    parts.append(_Part(
        part_number=1,
        label="Input shaft",
        gears=[_GearOnShaft(stages[0].pinion, stages[0], "pinion", mesh_partner_part=2)],
    ))

    # Intermediate shafts (compound)
    for i in range(n - 1):
        parts.append(_Part(
            part_number=i + 2,
            label=f"Shaft {i + 2}",
            is_compound=True,
            gears=[
                _GearOnShaft(stages[i].wheel, stages[i], "wheel", mesh_partner_part=i + 1),
                _GearOnShaft(stages[i + 1].pinion, stages[i + 1], "pinion", mesh_partner_part=i + 3),
            ],
        ))

    # Last part — output shaft
    parts.append(_Part(
        part_number=n + 1,
        label="Output shaft",
        gears=[_GearOnShaft(stages[-1].wheel, stages[-1], "wheel", mesh_partner_part=n)],
    ))

    return parts


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_gear_spec(
    gear: GearResult,
    geom: StageGeometry | None,
    role: str,
    stage_num: int,
    mesh_partner_part: int,
    gear_letter: str,
    lines: list[str],
) -> None:
    """Append a single gear's specification lines."""
    m = gear.module
    x = gear.profile_shift if gear.profile_shift is not None else 0.0

    # Pick the correct geometry fields based on role
    if geom and role == "pinion":
        root_fillet = geom.root_fillet_radius_pinion_mm
        tip_relief = geom.tip_relief_pinion_mm
    elif geom and role == "wheel":
        root_fillet = geom.root_fillet_radius_wheel_mm
        tip_relief = geom.tip_relief_wheel_mm
    else:
        root_fillet = None
        tip_relief = None

    tip_d = gear.tip_diameter_corrected_mm if gear.tip_diameter_corrected_mm is not None else gear.addendum_diameter_mm

    lines.append(
        f"    GEAR {gear_letter} \u2014 Stage {stage_num} {role}"
        f"  (meshes with Part {mesh_partner_part})"
    )
    lines.append(f"      Module:                   {m} mm")
    lines.append(f"      Teeth:                    {gear.teeth}")
    lines.append(f"      Profile shift:            x = {x:+.4f}")
    lines.append("")
    lines.append(f"      Diameters")
    lines.append(f"        Reference (pitch) \u00d8:    {gear.pitch_diameter_mm:.3f} mm")
    lines.append(f"        Tip \u00d8:                  {tip_d:.3f} mm")
    if gear.root_diameter_mm is not None:
        lines.append(f"        Root \u00d8:                 {gear.root_diameter_mm:.3f} mm")
    if gear.base_diameter_mm is not None:
        lines.append(f"        Base \u00d8:                 {gear.base_diameter_mm:.3f} mm")
    lines.append("")
    lines.append(f"      Face width:               {gear.face_width_mm:.3f} mm")
    lines.append("")
    lines.append(f"      Tooth profile")
    if gear.tooth_thickness_ref_mm is not None:
        lines.append(f"        Tooth thickness (ref):  {gear.tooth_thickness_ref_mm:.4f} mm")
        if geom is not None:
            half_backlash = geom.backlash_mm / 2.0
            actual_thickness = gear.tooth_thickness_ref_mm - half_backlash
            lines.append(f"        Tooth thickness (cut):  {actual_thickness:.4f} mm")
            lines.append(f"        Backlash allowance:     {half_backlash:.4f} mm (per gear, symmetric)")
    if root_fillet is not None:
        lines.append(f"        Root fillet radius:     \u03c1 = {root_fillet:.3f} mm")
    if tip_relief is not None:
        lines.append(f"        Tip relief:             {tip_relief:.3f} mm")
    if gear.addendum_coeff is not None:
        lines.append(f"        Addendum coefficient:   {gear.addendum_coeff:.4f}")
    if gear.dedendum_coeff is not None:
        lines.append(f"        Dedendum coefficient:   {gear.dedendum_coeff:.4f}")
    lines.append("")

    # Tolerances
    q, _ = quality_grade(m, gear.material)
    tol = iso_1328_tolerances(
        m, gear.teeth, gear.pitch_diameter_mm, gear.face_width_mm, q,
    )
    lines.append(f"      Tolerances (ISO 1328-1, grade {q} \u2014 indicative)")
    lines.append(f"        Single pitch deviation: fpt \u2264 {tol['fpt']:.1f} \u03bcm")
    lines.append(f"        Total pitch deviation:  Fp  \u2264 {tol['Fp']:.1f} \u03bcm")
    lines.append(f"        Profile total:          F\u03b1  \u2264 {tol['Fa']:.1f} \u03bcm")
    lines.append(f"        Helix total:            F\u03b2  \u2264 {tol['Fb']:.1f} \u03bcm")
    lines.append(f"        Radial runout:          Fr  \u2264 {tol['Fr']:.1f} \u03bcm")
    lines.append("")


def _format_part(part: _Part) -> str:
    """Format one physical part (shaft) with all its gears."""
    lines: list[str] = []
    sep = "\u2500" * 80

    n_gears = len(part.gears)
    compound_note = " (compound)" if part.is_compound else ""
    gear_count = f"{n_gears} gear{'s' if n_gears > 1 else ''}"

    lines.append(sep)
    lines.append(
        f"  PART {part.part_number} \u2014 {part.label}"
        f"  ({gear_count}{compound_note})"
    )
    lines.append(sep)
    lines.append("")

    # Material & treatment (shared across all gears on the shaft)
    ref_gear = part.gears[0].gear
    ref_module = ref_gear.module
    # For compound parts with different modules, use the larger one for case depth
    if part.is_compound:
        ref_module = max(g.gear.module for g in part.gears)

    spec = MANUFACTURING_SPECS.get(ref_gear.material, {})
    mat = MATERIAL_BY_KEY[ref_gear.material]
    q, method = quality_grade(ref_module, ref_gear.material)
    finish = surface_finish(q)

    lines.append("  MATERIAL & TREATMENT")
    lines.append(f"    Material:                   {spec.get('trade_names', mat.name)}")
    lines.append(f"    Heat treatment:             {spec.get('heat_treatment', 'N/A')}")
    if spec.get("case_depth"):
        lines.append(f"    Case depth:                 {case_depth_range(ref_module)}")
    lines.append("")

    lines.append("  MANUFACTURING")
    lines.append(f"    Quality grade:              ISO 1328 grade {q} (DIN {q})")
    lines.append(f"    Method:                     {method}")
    lines.append(f"    Surface finish:             {finish}")
    lines.append("")

    # Each gear on this shaft
    letters = "ABCDEFGH"
    for i, gos in enumerate(part.gears):
        _format_gear_spec(
            gear=gos.gear,
            geom=gos.stage.geometry,
            role=gos.role,
            stage_num=gos.stage.stage_number,
            mesh_partner_part=gos.mesh_partner_part,
            gear_letter=letters[i],
            lines=lines,
        )

    # Assembly instructions for compound parts
    if part.is_compound:
        lines.append("  ASSEMBLY")
        lines.append("    Each gear is manufactured independently")
        lines.append("    Assembled by interference (press) fit onto shared shaft")
        lines.append("")

    return "\n".join(lines)


def _format_mesh(stage: StageResult, pinion_part: int, wheel_part: int) -> str:
    """Format the mesh specification for one gear pair."""
    geom = stage.geometry
    lines: list[str] = []

    lines.append(
        f"  MESH {stage.stage_number} \u2014 Stage {stage.stage_number}"
        f"  (Part {pinion_part} \u2194 Part {wheel_part},"
        f" ratio {stage.stage_ratio:.4f}:1)"
    )

    if geom:
        lines.append(f"    Centre distance:            {geom.operating_center_distance_mm:.3f} mm")
        lines.append(f"    Operating pressure angle:   {geom.operating_pressure_angle_deg:.2f}\u00b0")
        lines.append(f"    Contact ratio:              {geom.contact_ratio:.3f}")
        lines.append(f"    Backlash (tooth thinning):  {geom.backlash_mm:.3f} mm")
        lines.append(f"    Hertz contact stress:       {geom.hertz_contact_stress_mpa:.1f} MPa")
        lines.append(
            f"    Specific sliding:           "
            f"pinion = {geom.specific_sliding_tip_pinion:.3f}, "
            f"wheel = {geom.specific_sliding_tip_wheel:.3f}"
        )
    else:
        lines.append(f"    (geometry not yet optimised \u2014 run generate first)")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_production(solution: GearboxSolution, number: int) -> str:
    """Generate the full production specification document.

    The document is organised by physical parts (shafts) rather than
    stages, so that each manufactured piece is fully described in one
    section.  Compound gears (two gears on the same shaft) are grouped
    together.  A separate MESH SPECIFICATIONS section describes the
    gear-pair interactions (centre distance, backlash, contact ratio).

    Parameters
    ----------
    solution : fully optimised GearboxSolution (after generate pipeline)
    number : 1-based solution number
    """
    n_stages = len(solution.stages)
    parts = _collect_parts(solution)
    n_parts = len(parts)

    lines: list[str] = []
    header = "=" * 80
    sep = "\u2500" * 80

    # --- Title ---
    lines.append(header)
    lines.append("PRODUCTION SPECIFICATION \u2014 SPUR GEARS".center(80))
    lines.append(f"Solution #{number} \u2014 {n_stages}-stage gearbox".center(80))
    lines.append(header)
    lines.append("")
    lines.append(f"  Total ratio:      {solution.total_ratio:.4f}:1 (error {solution.ratio_error_pct:+.2f}%)")
    lines.append(f"  Stages:           {n_stages}")
    lines.append(f"  Parts:            {n_parts}")
    lines.append(f"  Gear system:      ISO 53 (standard basic rack, ha* = 1.0, hf* = 1.25)")
    lines.append(f"  Pressure angle:   20\u00b0 (reference)")
    lines.append("")

    # --- Bill of materials ---
    lines.append(sep)
    lines.append("  BILL OF MATERIALS")
    lines.append(sep)
    for part in parts:
        descs = []
        for gos in part.gears:
            descs.append(f"z={gos.gear.teeth} m={gos.gear.module}")
        compound_tag = " [compound]" if part.is_compound else ""
        lines.append(
            f"    Part {part.part_number}: {part.label}"
            f" \u2014 {' + '.join(descs)}{compound_tag}"
        )
    lines.append("")

    # --- Parts ---
    for part in parts:
        lines.append(_format_part(part))

    # --- Mesh specifications ---
    lines.append(sep)
    lines.append("  MESH SPECIFICATIONS")
    lines.append(sep)
    lines.append("")
    for stage in solution.stages:
        pinion_part = stage.stage_number  # Part N has the pinion of stage N
        wheel_part = stage.stage_number + 1
        lines.append(_format_mesh(stage, pinion_part, wheel_part))

    # --- Notes ---
    lines.append(sep)
    lines.append("  NOTES")
    lines.append(sep)
    lines.append("  - All dimensions in millimetres unless stated otherwise")
    lines.append("  - Tolerances are indicative (ISO 1328-1:2013); verify against full standard")
    lines.append("  - Gear tooth system: ISO 53 standard basic rack profile")
    lines.append("  - Rack tip radius coefficient: \u03c1_a0* = 0.38")
    lines.append("  - Backlash achieved by symmetric tooth thinning")
    lines.append("  - Profile shift optimised to balance specific sliding between pinion and wheel")
    lines.append("  - Tip relief applied to reduce mesh impact at entry/exit")
    lines.append("  - Compound parts: both gears share the same shaft and material")
    lines.append("")
    lines.append("  Generated by spurGearGenerator")
    lines.append("")

    return "\n".join(lines)
