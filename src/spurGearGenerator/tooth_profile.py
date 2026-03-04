"""Involute gear tooth geometry, profile shift optimization, and profile generation.

All functions are pure (no side effects). Follows the same conventions as gear_math.py.
Units: mm for lengths, radians for internal angles, degrees for API boundaries,
MPa for stress, N for forces.
"""

import math

from spurGearGenerator.gear_math import PRESSURE_ANGLE_RAD, tangential_force
from spurGearGenerator.models import StageGeometry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADDENDUM_COEFF: float = 1.0  # ha*
DEDENDUM_COEFF: float = 1.25  # hf*
CLEARANCE_COEFF: float = 0.25  # c* = hf* - ha*
RACK_TIP_RADIUS_COEFF: float = 0.38  # rho_f / m for standard 20-deg full-depth
TIP_RELIEF_COEFF: float = 0.02  # Ca = 0.02 * m (conservative default)
BACKLASH_COEFF: float = 0.04  # j_t = 0.04 * m
POISSON_RATIO: float = 0.3  # Simplified: same for all materials

_YOUNGS_MODULUS: dict[str, float] = {
    "steel_mild": 210_000.0,
    "steel_alloy": 210_000.0,
    "steel_hardened": 210_000.0,
    "brass": 100_000.0,
    "bronze": 110_000.0,
    "aluminum": 69_000.0,
    "nylon": 3_000.0,
    "pom": 2_800.0,
}

# ---------------------------------------------------------------------------
# Involute function
# ---------------------------------------------------------------------------


def inv(alpha_rad: float) -> float:
    """Involute function: inv(alpha) = tan(alpha) - alpha."""
    return math.tan(alpha_rad) - alpha_rad


def inv_inverse(y: float, tol: float = 1e-12, max_iter: int = 50) -> float:
    """Numerical inversion of the involute function using Newton-Raphson.

    Given y = inv(alpha), find alpha.
    """
    if y <= 0.0:
        return 0.0
    # Starting guess: cubic approximation good for small y
    alpha = (3.0 * y) ** (1.0 / 3.0)
    for _ in range(max_iter):
        ta = math.tan(alpha)
        f = ta - alpha - y
        fp = ta * ta  # derivative: sec^2(alpha) - 1 = tan^2(alpha)
        if fp == 0.0:
            break
        delta = f / fp
        alpha -= delta
        if abs(delta) < tol:
            break
    return alpha


# ---------------------------------------------------------------------------
# Profile shift
# ---------------------------------------------------------------------------


def min_profile_shift(z: int, alpha_rad: float = PRESSURE_ANGLE_RAD) -> float:
    """Minimum profile shift coefficient to avoid undercut.

    x_min = max(0, 1 - z * sin^2(alpha) / 2)
    """
    sin_a = math.sin(alpha_rad)
    return max(0.0, 1.0 - z * sin_a * sin_a / 2.0)


def optimize_profile_shifts(
    z1: int,
    z2: int,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> tuple[float, float]:
    """Find (x1, x2) that avoid undercut and balance specific sliding.

    Strategy:
    1. Start with minimum shifts to avoid undercut
    2. Use bisection on x1 (with x_sum fixed) to equalize |specific sliding|
       at the tips of both gears
    3. x_sum is kept at sum of minimums (conservative: no extra shift beyond needed)
    """
    x1_min = min_profile_shift(z1, alpha_rad)
    x2_min = min_profile_shift(z2, alpha_rad)
    x_sum = x1_min + x2_min

    if x_sum == 0.0:
        # Both gears have enough teeth: no shift needed
        return (0.0, 0.0)

    # Bisect on x1 in [x1_min, x_sum - x2_min] to balance specific sliding
    lo = x1_min
    hi = x_sum  # x2 = x_sum - x1 >= 0 (x2_min could be 0)

    def sliding_imbalance(x1: float) -> float:
        x2 = x_sum - x1
        alpha_w = operating_pressure_angle(z1, z2, x1, x2, alpha_rad)
        nu1, nu2 = specific_sliding(z1, z2, x1, x2, alpha_w)
        return abs(nu1) - abs(nu2)

    for _ in range(60):
        mid = (lo + hi) / 2.0
        if sliding_imbalance(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-8:
            break

    x1 = (lo + hi) / 2.0
    x2 = x_sum - x1
    return (x1, x2)


# ---------------------------------------------------------------------------
# Operating geometry
# ---------------------------------------------------------------------------


def operating_pressure_angle(
    z1: int,
    z2: int,
    x1: float,
    x2: float,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> float:
    """Solve for operating pressure angle alpha_w.

    inv(alpha_w) = 2*(x1+x2)/(z1+z2) * tan(alpha) + inv(alpha)
    """
    inv_target = 2.0 * (x1 + x2) / (z1 + z2) * math.tan(alpha_rad) + inv(alpha_rad)
    return inv_inverse(inv_target)


def operating_center_distance(
    module: float,
    z1: int,
    z2: int,
    alpha_rad: float,
    alpha_w_rad: float,
) -> float:
    """Operating center distance with profile shift."""
    return module * (z1 + z2) / 2.0 * math.cos(alpha_rad) / math.cos(alpha_w_rad)


def base_diameter(module: float, z: int, alpha_rad: float = PRESSURE_ANGLE_RAD) -> float:
    """Base circle diameter: d_b = m * z * cos(alpha)."""
    return module * z * math.cos(alpha_rad)


def root_diameter(module: float, z: int, x: float) -> float:
    """Root diameter with profile shift: d_f = m * (z - 2*hf* + 2*x)."""
    return module * (z - 2.0 * DEDENDUM_COEFF + 2.0 * x)


def tip_diameter_shifted(module: float, z: int, x: float) -> float:
    """Tip diameter with profile shift (before shortening): d_a = m * (z + 2 + 2*x)."""
    return module * (z + 2.0 * ADDENDUM_COEFF + 2.0 * x)


def tip_diameter_corrected(
    module: float,
    z: int,
    x: float,
    z_mate: int,
    x_mate: float,
    alpha_rad: float,
    alpha_w_rad: float,
) -> float:
    """Tip diameter after shortening to maintain standard clearance.

    When x1+x2 > 0 the center distance increases, so tips must be shortened
    to keep clearance = c* * m.
    """
    a_ref = module * (z + z_mate) / 2.0
    a_w = operating_center_distance(module, z, z_mate, alpha_rad, alpha_w_rad)
    k = (a_w - a_ref) / module  # center distance increase coefficient
    x_sum = x + x_mate
    # Tip shortening split equally between the two gears
    shortening = (x_sum - k) * module
    da_raw = tip_diameter_shifted(module, z, x)
    return da_raw - shortening


def tooth_thickness_at_reference(
    module: float,
    x: float,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> float:
    """Tooth thickness on the reference pitch circle."""
    return module * (math.pi / 2.0 + 2.0 * x * math.tan(alpha_rad))


# ---------------------------------------------------------------------------
# Contact ratio
# ---------------------------------------------------------------------------


def contact_ratio(
    z1: int,
    z2: int,
    module: float,
    x1: float,
    x2: float,
    alpha_w_rad: float,
    a_w: float,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> float:
    """Transverse contact ratio epsilon_alpha."""
    db1 = base_diameter(module, z1, alpha_rad)
    db2 = base_diameter(module, z2, alpha_rad)
    da1 = tip_diameter_corrected(module, z1, x1, z2, x2, alpha_rad, alpha_w_rad)
    da2 = tip_diameter_corrected(module, z2, x2, z1, x1, alpha_rad, alpha_w_rad)
    p_b = math.pi * module * math.cos(alpha_rad)

    term1 = math.sqrt(max(0.0, (da1 / 2.0) ** 2 - (db1 / 2.0) ** 2))
    term2 = math.sqrt(max(0.0, (da2 / 2.0) ** 2 - (db2 / 2.0) ** 2))
    length_of_action = term1 + term2 - a_w * math.sin(alpha_w_rad)
    return length_of_action / p_b


# ---------------------------------------------------------------------------
# Specific sliding
# ---------------------------------------------------------------------------


def specific_sliding(
    z1: int,
    z2: int,
    x1: float,
    x2: float,
    alpha_w_rad: float,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> tuple[float, float]:
    """Specific sliding at the tip of each gear.

    Uses the Maag formulation with roll angles on the line of action.
    Returns (nu_tip_1, nu_tip_2).
    """
    # Addendum angles (roll angle at tip)
    cos_a = math.cos(alpha_rad)
    da1_over_db1 = (z1 + 2.0 * ADDENDUM_COEFF + 2.0 * x1) / (z1 * cos_a)
    da2_over_db2 = (z2 + 2.0 * ADDENDUM_COEFF + 2.0 * x2) / (z2 * cos_a)

    # Clamp to avoid sqrt of negative for very small gears
    xi_a1 = math.sqrt(max(0.0, da1_over_db1**2 - 1.0))
    xi_a2 = math.sqrt(max(0.0, da2_over_db2**2 - 1.0))

    tan_aw = math.tan(alpha_w_rad)

    # At tip of gear 1, the mate's roll angle:
    xi_f2 = (z1 + z2) / z2 * tan_aw - xi_a1 * z1 / z2
    # At tip of gear 2, the mate's roll angle:
    xi_f1 = (z1 + z2) / z1 * tan_aw - xi_a2 * z2 / z1

    # Specific sliding
    nu_tip_1 = 1.0 - (xi_f2 * z2) / (xi_a1 * z1) if xi_a1 * z1 != 0.0 else 0.0
    nu_tip_2 = 1.0 - (xi_f1 * z1) / (xi_a2 * z2) if xi_a2 * z2 != 0.0 else 0.0

    return (nu_tip_1, nu_tip_2)


# ---------------------------------------------------------------------------
# Hertz contact stress
# ---------------------------------------------------------------------------


def hertz_contact_stress(
    ft_n: float,
    face_width_mm: float,
    module: float,
    z1: int,
    z2: int,
    alpha_w_rad: float,
    a_w: float,
    mat_key_1: str,
    mat_key_2: str,
) -> float:
    """Hertz contact stress at the pitch point (MPa).

    Uses the cylinder-contact Hertz formula:
    sigma_H = sqrt(Fn / (b * rho_eq) * E_eq / (2*pi))
    where Fn = Ft / cos(alpha_w).
    """
    e1 = _YOUNGS_MODULUS.get(mat_key_1, 210_000.0)
    e2 = _YOUNGS_MODULUS.get(mat_key_2, 210_000.0)
    nu = POISSON_RATIO

    # Equivalent elastic modulus
    e_eq = 2.0 / ((1.0 - nu**2) / e1 + (1.0 - nu**2) / e2)

    # Operating pitch diameters
    dw1 = 2.0 * a_w * z1 / (z1 + z2)
    dw2 = 2.0 * a_w * z2 / (z1 + z2)

    # Radii of curvature at pitch point
    sin_aw = math.sin(alpha_w_rad)
    rho1 = dw1 / 2.0 * sin_aw
    rho2 = dw2 / 2.0 * sin_aw

    if rho1 <= 0.0 or rho2 <= 0.0:
        return 0.0

    rho_eq = 1.0 / (1.0 / rho1 + 1.0 / rho2)

    # Normal force
    fn = ft_n / math.cos(alpha_w_rad) if math.cos(alpha_w_rad) > 0.0 else ft_n

    sigma_h = math.sqrt(max(0.0, fn / (face_width_mm * rho_eq) * e_eq / (2.0 * math.pi)))
    return sigma_h


# ---------------------------------------------------------------------------
# Tip relief and root fillet
# ---------------------------------------------------------------------------


def tip_relief_amount(module: float) -> float:
    """Default tip relief: Ca = 0.02 * m."""
    return TIP_RELIEF_COEFF * module


def root_fillet_radius(
    module: float,
    z: int,
    x: float,
    alpha_rad: float = PRESSURE_ANGLE_RAD,
) -> float:
    """Generated root fillet radius accounting for tooth count and profile shift.

    The rack cutter tip (radius rho_a0 * m) traces a trochoid in the gear blank.
    The actual fillet is the envelope of circles of radius rho_a0*m centered on
    that trochoid.  Its minimum curvature radius at the root bottom is:

        rho_f = rho_trochoid + rho_a0 * m

    where rho_trochoid = h^2 / (h + r_pitch) and h is the straight portion of
    the rack flank above the tip radius center.
    """
    rho_a0 = RACK_TIP_RADIUS_COEFF * module
    r_pitch = module * z / 2.0
    h = max(0.0, (DEDENDUM_COEFF - x - RACK_TIP_RADIUS_COEFF * (1.0 - math.sin(alpha_rad)))) * module
    if h <= 0.0:
        return rho_a0
    rho_trochoid = h * h / (h + r_pitch)
    return rho_trochoid + rho_a0


def backlash(module: float) -> float:
    """Circumferential backlash: j_t = 0.04 * m."""
    return BACKLASH_COEFF * module


# ---------------------------------------------------------------------------
# Top-level stage optimization
# ---------------------------------------------------------------------------


def optimize_stage(
    z1: int,
    z2: int,
    module: float,
    face_width_mm: float,
    torque_nm: float,
    mat_key_1: str,
    mat_key_2: str,
) -> StageGeometry:
    """Run full tooth geometry optimization for one gear stage."""
    alpha = PRESSURE_ANGLE_RAD

    # Profile shifts
    x1, x2 = optimize_profile_shifts(z1, z2, alpha)

    # Operating geometry
    alpha_w = operating_pressure_angle(z1, z2, x1, x2, alpha)
    a_w = operating_center_distance(module, z1, z2, alpha, alpha_w)

    # Contact ratio
    eps = contact_ratio(z1, z2, module, x1, x2, alpha_w, a_w, alpha)

    # Specific sliding
    nu1, nu2 = specific_sliding(z1, z2, x1, x2, alpha_w, alpha)

    # Hertz stress
    ft = tangential_force(torque_nm, module, z1)
    sigma_h = hertz_contact_stress(ft, face_width_mm, module, z1, z2, alpha_w, a_w, mat_key_1, mat_key_2)

    # Tip relief and fillet
    ca = tip_relief_amount(module)
    rho_f1 = root_fillet_radius(module, z1, x1, alpha)
    rho_f2 = root_fillet_radius(module, z2, x2, alpha)

    # Backlash
    jt = backlash(module)

    return StageGeometry(
        profile_shift_pinion=round(x1, 6),
        profile_shift_wheel=round(x2, 6),
        operating_pressure_angle_deg=round(math.degrees(alpha_w), 4),
        operating_center_distance_mm=round(a_w, 4),
        contact_ratio=round(eps, 4),
        backlash_mm=round(jt, 4),
        specific_sliding_tip_pinion=round(nu1, 4),
        specific_sliding_tip_wheel=round(nu2, 4),
        hertz_contact_stress_mpa=round(sigma_h, 2),
        tip_relief_pinion_mm=round(ca, 4),
        tip_relief_wheel_mm=round(ca, 4),
        root_fillet_radius_pinion_mm=round(rho_f1, 4),
        root_fillet_radius_wheel_mm=round(rho_f2, 4),
    )
