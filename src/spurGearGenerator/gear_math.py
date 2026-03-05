"""Gear geometry, Lewis bending stress, efficiency, and weight formulas.

Units: mm for lengths, N for forces, MPa for stress, kg for mass, Nm for torque.
"""

import math
from bisect import bisect_right

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESSURE_ANGLE_RAD: float = math.radians(20.0)
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

    if z in _LEWIS_Y_TABLE:
        return _LEWIS_Y_TABLE[z]

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


# ---------------------------------------------------------------------------
# Force and stress
# ---------------------------------------------------------------------------


def tangential_force(torque_nm: float, module: float, z: int) -> float:
    """Tangential force on the gear tooth in Newtons.

    Ft = 2 * T / d   where d is the pitch diameter in *metres*.
    """
    return 2000.0 * torque_nm / (module * z)


def lewis_bending_stress(ft_n: float, face_width_mm: float, module: float, z: int) -> float:
    """Lewis root-bending stress in MPa.

    sigma = Ft / (b * m * Y)
    With Ft in N and b, m in mm the result is N/mm^2 = MPa.
    """
    y = lewis_form_factor(z)
    return ft_n / (face_width_mm * module * y)


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
