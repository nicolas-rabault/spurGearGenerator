"""Pydantic models for JSON configuration input and structured result output."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input configuration
# ---------------------------------------------------------------------------


class GearConfig(BaseModel):
    """Top-level JSON configuration for the gear solver."""

    target_ratio: float = Field(..., gt=0, description="Desired total gear reduction ratio")
    reduction_margin: float = Field(
        default=5.0,
        ge=0,
        le=50,
        description="Acceptable margin around target ratio in percent",
    )
    input_torque: float = Field(..., gt=0, description="Peak input torque in Nm")
    max_teeth_per_gear: int = Field(
        default=150,
        ge=20,
        le=500,
        description="Maximum number of teeth on any single gear",
    )


def load_config(path: str | Path) -> GearConfig:
    """Load and validate a JSON configuration file."""
    with open(path) as f:
        data = json.load(f)
    return GearConfig(**data)


# ---------------------------------------------------------------------------
# Output result models
# ---------------------------------------------------------------------------


class GearResult(BaseModel):
    """Description of a single gear in a solution."""

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


class StageResult(BaseModel):
    """One gear-mesh stage in a gearbox solution."""

    stage_number: int
    pinion: GearResult
    wheel: GearResult
    stage_ratio: float
    mesh_efficiency: float
    stage_torque_in_nm: float  # torque on the pinion shaft entering this stage


class GearboxSolution(BaseModel):
    """A complete multi-stage gearbox solution."""

    stages: list[StageResult]
    total_ratio: float
    ratio_error_pct: float  # (actual - target) / target * 100
    total_efficiency: float  # product of all stage efficiencies
    total_weight_kg: float  # sum of all gear weights
    ranking_tag: str = ""  # "weight", "efficiency", or "weight+efficiency"


# ---------------------------------------------------------------------------
# Solver statistics
# ---------------------------------------------------------------------------


@dataclass
class SolveStats:
    """Metrics collected during a solve run."""

    unique_ratios: int = 0
    tooth_pairs: int = 0
    material_combinations: int = 0
    subtrees_searched: int = 0
    solutions_evaluated: int = 0
    branches_pruned: int = 0
    elapsed_seconds: float = 0.0
    cpu_cores: int = 1
