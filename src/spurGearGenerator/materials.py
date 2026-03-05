from dataclasses import dataclass


@dataclass(frozen=True)
class GearMaterial:
    name: str
    key: str
    density: float  # kg/m^3
    allowable_bending_stress: float  # MPa (conservative Lewis-compatible value)
    friction_coefficient: float  # dimensionless (lubricated meshing)
    youngs_modulus: float  # MPa


MATERIALS: tuple[GearMaterial, ...] = (
    GearMaterial(
        name="Mild Steel (AISI 1020)",
        key="steel_mild",
        density=7850,
        allowable_bending_stress=140,
        friction_coefficient=0.08,
        youngs_modulus=210_000.0,
    ),
    GearMaterial(
        name="Alloy Steel (AISI 4140)",
        key="steel_alloy",
        density=7850,
        allowable_bending_stress=250,
        friction_coefficient=0.06,
        youngs_modulus=210_000.0,
    ),
    GearMaterial(
        name="Hardened Steel (case-hardened)",
        key="steel_hardened",
        density=7850,
        allowable_bending_stress=380,
        friction_coefficient=0.05,
        youngs_modulus=210_000.0,
    ),
    GearMaterial(
        name="Brass (C360)",
        key="brass",
        density=8500,
        allowable_bending_stress=80,
        friction_coefficient=0.10,
        youngs_modulus=100_000.0,
    ),
    GearMaterial(
        name="Phosphor Bronze",
        key="bronze",
        density=8800,
        allowable_bending_stress=90,
        friction_coefficient=0.08,
        youngs_modulus=110_000.0,
    ),
    GearMaterial(
        name="Aluminum (6061-T6)",
        key="aluminum",
        density=2700,
        allowable_bending_stress=75,
        friction_coefficient=0.12,
        youngs_modulus=69_000.0,
    ),
    GearMaterial(
        name="Nylon (PA6)",
        key="nylon",
        density=1140,
        allowable_bending_stress=40,
        friction_coefficient=0.25,
        youngs_modulus=3_000.0,
    ),
    GearMaterial(
        name="POM / Delrin",
        key="pom",
        density=1410,
        allowable_bending_stress=55,
        friction_coefficient=0.20,
        youngs_modulus=2_800.0,
    ),
)

MATERIAL_BY_KEY: dict[str, GearMaterial] = {m.key: m for m in MATERIALS}
