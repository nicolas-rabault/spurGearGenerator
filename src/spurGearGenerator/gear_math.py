"""Gear geometry, Lewis bending stress, efficiency, and weight formulas.

All functions are pure (no side effects, no dependencies on other project modules).
Units: mm for lengths, N for forces, MPa for stress, kg for mass, Nm for torque.
"""

import math
from bisect import bisect_left, bisect_right

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESSURE_ANGLE_DEG: float = 20.0
PRESSURE_ANGLE_RAD: float = math.radians(PRESSURE_ANGLE_DEG)
MIN_TEETH: int = 12
STANDARD_MODULES: tuple[float, ...] = (
    0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25,
    1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
)
MAX_FACE_WIDTH_FACTOR: float = 12.0  # b_max = 12 * module

# ---------------------------------------------------------------------------
# Lewis form factor table (20-degree full-depth involute profile)
# ---------------------------------------------------------------------------

_LEWIS_Y_TABLE: dict[int, float] = {
    10: 0.201,
    11: 0.226,
    12: 0.245,
    13: 0.264,
    14: 0.276,
    15: 0.289,
    16: 0.295,
    17: 0.302,
    18: 0.308,
    19: 0.314,
    20: 0.320,
    22: 0.330,
    24: 0.337,
    26: 0.344,
    28: 0.352,
    30: 0.358,
    32: 0.364,
    34: 0.370,
    36: 0.377,
    38: 0.383,
    40: 0.389,
    45: 0.399,
    50: 0.408,
    55: 0.415,
    60: 0.421,
    65: 0.425,
    70: 0.429,
    75: 0.433,
    80: 0.436,
    90: 0.442,
    100: 0.446,
    150: 0.458,
    200: 0.463,
    300: 0.471,
}

_LEWIS_Y_KEYS: list[int] = sorted(_LEWIS_Y_TABLE)
_LEWIS_Y_VALUES: list[float] = [_LEWIS_Y_TABLE[k] for k in _LEWIS_Y_KEYS]


def lewis_form_factor(z: int) -> float:
    """Return the Lewis Y factor for *z* teeth via linear interpolation.

    Clamps to boundary values for z < 10 or z > 300.
    """
    if z <= _LEWIS_Y_KEYS[0]:
        return _LEWIS_Y_VALUES[0]
    if z >= _LEWIS_Y_KEYS[-1]:
        return _LEWIS_Y_VALUES[-1]

    # Exact match?
    if z in _LEWIS_Y_TABLE:
        return _LEWIS_Y_TABLE[z]

    # Linear interpolation between the two bracketing entries.
    idx = bisect_right(_LEWIS_Y_KEYS, z) - 1
    z_lo = _LEWIS_Y_KEYS[idx]
    z_hi = _LEWIS_Y_KEYS[idx + 1]
    y_lo = _LEWIS_Y_VALUES[idx]
    y_hi = _LEWIS_Y_VALUES[idx + 1]
    t = (z - z_lo) / (z_hi - z_lo)
    return y_lo + t * (y_hi - y_lo)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def pitch_diameter(module: float, z: int) -> float:
    """Pitch diameter in mm: d = m * Z."""
    return module * z


def addendum_diameter(module: float, z: int) -> float:
    """Addendum (tip) diameter in mm: da = m * (Z + 2)."""
    return module * (z + 2)


def root_diameter(module: float, z: int) -> float:
    """Root (dedendum) diameter in mm: df = m * (Z - 2.5)."""
    return module * (z - 2.5)


def max_face_width(module: float) -> float:
    """Maximum practical face width in mm: b_max = 12 * m."""
    return MAX_FACE_WIDTH_FACTOR * module


# ---------------------------------------------------------------------------
# Force and stress
# ---------------------------------------------------------------------------


def tangential_force(torque_nm: float, module: float, z: int) -> float:
    """Tangential force on the gear tooth in Newtons.

    Ft = 2 * T / d   where d is the pitch diameter in *metres*.
    """
    d_m = pitch_diameter(module, z) / 1000.0  # mm -> m
    return 2.0 * torque_nm / d_m


def lewis_bending_stress(ft_n: float, face_width_mm: float, module: float, z: int) -> float:
    """Lewis root-bending stress in MPa.

    sigma = Ft / (b * m * Y)
    With Ft in N and b, m in mm the result is N/mm^2 = MPa.
    """
    y = lewis_form_factor(z)
    return ft_n / (face_width_mm * module * y)


def minimum_face_width(
    torque_nm: float,
    module: float,
    z: int,
    allowable_stress_mpa: float,
) -> float | None:
    """Minimum face width (mm) so that Lewis bending stress <= allowable.

    Returns ``None`` when even the maximum face width (12 * module) is
    insufficient.  The result is clamped to a practical minimum of 1 * module.
    """
    ft = tangential_force(torque_nm, module, z)
    y = lewis_form_factor(z)
    # sigma = Ft / (b * m * Y) <= sigma_allow  =>  b >= Ft / (sigma_allow * m * Y)
    b_min = ft / (allowable_stress_mpa * module * y)
    b_max = max_face_width(module)
    if b_min > b_max:
        return None
    return max(b_min, module)  # practical minimum = 1 * module


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------


def mesh_efficiency(z1: int, z2: int, mu: float) -> float:
    """Approximate spur-gear mesh efficiency.

    eta = 1 - pi * mu * (1/Z1 + 1/Z2)

    *mu* is the effective friction coefficient (average of two materials when
    they differ).
    """
    return 1.0 - math.pi * mu * (1.0 / z1 + 1.0 / z2)


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------


def gear_weight(
    module: float,
    z: int,
    face_width_mm: float,
    density_kg_m3: float,
) -> float:
    """Weight of a single gear in kg (solid-cylinder approximation).

    Uses the addendum diameter as the outer diameter.
    """
    da_mm = addendum_diameter(module, z)
    r_m = (da_mm / 2.0) / 1000.0  # radius in metres
    b_m = face_width_mm / 1000.0  # face width in metres
    volume_m3 = math.pi * r_m**2 * b_m
    return density_kg_m3 * volume_m3
