import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Input configuration
# ---------------------------------------------------------------------------


class GearConfig(BaseModel):
    target_ratio: float = Field(..., gt=0)
    reduction_margin: float = Field(default=5.0, ge=0)
    input_torque: float = Field(..., gt=0)
    max_teeth_per_gear: int = Field(default=150, ge=5)
    axis_margin: float = Field(..., ge=0)
    min_output_root_diameter: float | None = Field(default=None, ge=0)
    min_module: float | None = Field(default=None, gt=0)
    materials: list[str] | None = Field(default=None)

    @field_validator("materials")
    @classmethod
    def _validate_material_keys(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        from spurGearGenerator.materials import MATERIAL_BY_KEY

        unknown = [k for k in v if k not in MATERIAL_BY_KEY]
        if unknown:
            valid = sorted(MATERIAL_BY_KEY.keys())
            raise ValueError(
                f"Unknown material key(s): {unknown}. Valid keys: {valid}"
            )
        return v


def load_config(path: str | Path) -> GearConfig:
    with open(path) as f:
        data = json.load(f)
    return GearConfig(**data)


# ---------------------------------------------------------------------------
# Output result models
# ---------------------------------------------------------------------------


class GearResult(BaseModel):
    role: str  # "pinion" or "wheel"
    teeth: int
    module: float  # mm
    material: str  # material key
    pitch_diameter_mm: float
    addendum_diameter_mm: float
    face_width_mm: float
    lewis_stress_mpa: float
    allowable_stress_mpa: float
    weight_kg: float

    # Optional fields populated by the generate command
    profile_shift: float | None = None
    base_diameter_mm: float | None = None
    root_diameter_mm: float | None = None
    tip_diameter_corrected_mm: float | None = None
    tooth_thickness_ref_mm: float | None = None
    addendum_coeff: float | None = None
    dedendum_coeff: float | None = None


class StageGeometry(BaseModel):
    profile_shift_pinion: float
    profile_shift_wheel: float
    operating_pressure_angle_deg: float
    operating_center_distance_mm: float
    contact_ratio: float
    backlash_mm: float
    specific_sliding_tip_pinion: float
    specific_sliding_tip_wheel: float
    hertz_contact_stress_mpa: float
    tip_relief_pinion_mm: float
    tip_relief_wheel_mm: float
    root_fillet_radius_pinion_mm: float
    root_fillet_radius_wheel_mm: float


class StageResult(BaseModel):
    stage_number: int
    pinion: GearResult
    wheel: GearResult
    stage_ratio: float
    mesh_efficiency: float
    stage_torque_in_nm: float  # torque on the pinion shaft entering this stage
    geometry: StageGeometry | None = None


class SpringResult(BaseModel):
    max_torque_nm: float
    max_angle_deg: float
    outer_diameter_mm: float
    inner_diameter_mm: float
    thickness_mm: float
    spring_constant_nm_per_rad: float
    max_shear_strain: float
    rubber_weight_kg: float
    material: str
    safety_factor: float


class GearboxSolution(BaseModel):
    stages: list[StageResult]
    total_ratio: float
    ratio_error_pct: float  # (actual - target) / target * 100
    total_efficiency: float  # product of all stage efficiencies
    total_weight_kg: float  # sum of all gear weights
    ranking_tag: str = ""  # "weight", "efficiency", or "weight+efficiency"
    spring: SpringResult | None = None


# ---------------------------------------------------------------------------
# Solver statistics
# ---------------------------------------------------------------------------


@dataclass
class SolveStats:
    subtrees_searched: int = 0
    solutions_evaluated: int = 0
    elapsed_seconds: float = 0.0
    cpu_cores: int = 1
