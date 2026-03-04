"""Tests for the tooth_profile module."""

import math

import pytest

from spurGearGenerator.tooth_profile import (
    ADDENDUM_COEFF,
    DEDENDUM_COEFF,
    PRESSURE_ANGLE_RAD,
    backlash,
    base_diameter,
    contact_ratio,
    hertz_contact_stress,
    inv,
    inv_inverse,
    min_profile_shift,
    operating_center_distance,
    operating_pressure_angle,
    optimize_profile_shifts,
    optimize_stage,
    root_diameter,
    root_fillet_radius,
    specific_sliding,
    tip_diameter_shifted,
    tip_relief_amount,
)


# ---- Constants ---------------------------------------------------------------


def test_constants():
    """Standard 20-deg full-depth constants."""
    assert PRESSURE_ANGLE_RAD == pytest.approx(math.radians(20.0))
    assert ADDENDUM_COEFF == pytest.approx(1.0)
    assert DEDENDUM_COEFF == pytest.approx(1.25)


# ---- Involute function -------------------------------------------------------


def test_inv_zero():
    """inv(0) = tan(0) - 0 = 0."""
    assert inv(0.0) == pytest.approx(0.0)


def test_inv_at_20_degrees():
    """inv(20 deg) ~ 0.014904."""
    alpha = math.radians(20.0)
    expected = math.tan(alpha) - alpha
    assert inv(alpha) == pytest.approx(expected, rel=1e-10)
    assert inv(alpha) == pytest.approx(0.014904, rel=1e-3)


def test_inv_inverse_roundtrip():
    """inv_inverse(inv(alpha)) should recover alpha."""
    for deg in [10.0, 15.0, 20.0, 25.0, 30.0]:
        alpha = math.radians(deg)
        y = inv(alpha)
        recovered = inv_inverse(y)
        assert recovered == pytest.approx(alpha, abs=1e-10)


def test_inv_inverse_zero():
    """inv_inverse(0) = 0."""
    assert inv_inverse(0.0) == pytest.approx(0.0)


# ---- Profile shift -----------------------------------------------------------


def test_min_profile_shift_large_teeth():
    """z >= 18 should need no profile shift (x_min = 0)."""
    assert min_profile_shift(18) == pytest.approx(0.0, abs=1e-6)
    assert min_profile_shift(20) == pytest.approx(0.0, abs=1e-6)
    assert min_profile_shift(50) == pytest.approx(0.0, abs=1e-6)


def test_min_profile_shift_small_teeth():
    """z = 12: x_min = max(0, 1 - 12*sin^2(20 deg)/2) > 0."""
    sin_a = math.sin(PRESSURE_ANGLE_RAD)
    expected = max(0.0, 1.0 - 12 * sin_a * sin_a / 2.0)
    result = min_profile_shift(12)
    assert result == pytest.approx(expected)
    assert result > 0.0


def test_optimize_profile_shifts_no_shift():
    """Both z >= 17: no shift needed."""
    x1, x2 = optimize_profile_shifts(20, 40)
    assert x1 == pytest.approx(0.0)
    assert x2 == pytest.approx(0.0)


def test_optimize_profile_shifts_small_pinion():
    """Small pinion requires positive shift, both >= their minimums."""
    x1, x2 = optimize_profile_shifts(12, 40)
    assert x1 >= min_profile_shift(12) - 1e-9
    assert x2 >= min_profile_shift(40) - 1e-9
    assert x1 > 0.0  # 12 teeth needs shift


# ---- Operating geometry -------------------------------------------------------


def test_operating_pressure_angle_no_shift():
    """When x1 = x2 = 0, alpha_w equals the standard pressure angle."""
    alpha_w = operating_pressure_angle(20, 40, 0.0, 0.0)
    assert alpha_w == pytest.approx(PRESSURE_ANGLE_RAD, abs=1e-10)


def test_operating_pressure_angle_with_shift():
    """Positive sum of shifts increases the operating pressure angle."""
    alpha_w = operating_pressure_angle(12, 40, 0.3, 0.0)
    assert alpha_w > PRESSURE_ANGLE_RAD


def test_operating_center_distance_no_shift():
    """When x = 0, a = m * (z1 + z2) / 2."""
    m, z1, z2 = 2.0, 20, 40
    alpha = PRESSURE_ANGLE_RAD
    a = operating_center_distance(m, z1, z2, alpha, alpha)
    expected = m * (z1 + z2) / 2.0
    assert a == pytest.approx(expected)


# ---- Base, root, tip diameters -----------------------------------------------


def test_base_diameter():
    """d_b = m * z * cos(alpha)."""
    m, z = 2.0, 20
    expected = m * z * math.cos(PRESSURE_ANGLE_RAD)
    assert base_diameter(m, z) == pytest.approx(expected, rel=1e-10)


def test_root_diameter():
    """d_f = m * (z - 2*1.25 + 2*x)."""
    m, z, x = 2.0, 20, 0.0
    expected = m * (z - 2.0 * DEDENDUM_COEFF + 2.0 * x)
    assert root_diameter(m, z, x) == pytest.approx(expected)


def test_root_diameter_with_shift():
    """Positive shift increases root diameter."""
    assert root_diameter(2.0, 20, 0.3) > root_diameter(2.0, 20, 0.0)


def test_tip_diameter_shifted():
    """d_a = m * (z + 2 + 2*x)."""
    m, z, x = 2.0, 20, 0.0
    expected = m * (z + 2.0 * ADDENDUM_COEFF + 2.0 * x)
    assert tip_diameter_shifted(m, z, x) == pytest.approx(expected)


# ---- Contact ratio -----------------------------------------------------------


def test_contact_ratio_standard_gears():
    """Standard gears (x=0, z1=20, z2=40, m=2): contact ratio ~ 1.6-1.8."""
    m, z1, z2 = 2.0, 20, 40
    alpha = PRESSURE_ANGLE_RAD
    alpha_w = operating_pressure_angle(z1, z2, 0.0, 0.0)
    a_w = operating_center_distance(m, z1, z2, alpha, alpha_w)
    eps = contact_ratio(z1, z2, m, 0.0, 0.0, alpha_w, a_w)
    assert 1.6 <= eps <= 1.8


# ---- Specific sliding --------------------------------------------------------


def test_specific_sliding_nonzero():
    """Standard geometry (x=0): both specific sliding values are nonzero."""
    alpha_w = operating_pressure_angle(20, 40, 0.0, 0.0)
    nu1, nu2 = specific_sliding(20, 40, 0.0, 0.0, alpha_w)
    assert nu1 != 0.0
    assert nu2 != 0.0


# ---- Hertz contact stress ----------------------------------------------------


def test_hertz_contact_stress_positive():
    """Hertz stress should be positive for any loaded mesh."""
    m, z1, z2 = 2.0, 20, 40
    alpha = PRESSURE_ANGLE_RAD
    alpha_w = operating_pressure_angle(z1, z2, 0.0, 0.0)
    a_w = operating_center_distance(m, z1, z2, alpha, alpha_w)
    sigma = hertz_contact_stress(100.0, 20.0, m, z1, z2, alpha_w, a_w, "steel_alloy", "steel_alloy")
    assert sigma > 0.0


def test_hertz_contact_stress_doubles_force():
    """Doubling tangential force increases stress by sqrt(2)."""
    m, z1, z2 = 2.0, 20, 40
    alpha = PRESSURE_ANGLE_RAD
    alpha_w = operating_pressure_angle(z1, z2, 0.0, 0.0)
    a_w = operating_center_distance(m, z1, z2, alpha, alpha_w)

    sigma1 = hertz_contact_stress(100.0, 20.0, m, z1, z2, alpha_w, a_w, "steel_alloy", "steel_alloy")
    sigma2 = hertz_contact_stress(200.0, 20.0, m, z1, z2, alpha_w, a_w, "steel_alloy", "steel_alloy")
    assert sigma2 == pytest.approx(sigma1 * math.sqrt(2.0), rel=1e-6)


# ---- Tip relief, root fillet, backlash ----------------------------------------


def test_tip_relief_amount():
    """Ca = 0.02 * m."""
    assert tip_relief_amount(2.0) == pytest.approx(0.04)
    assert tip_relief_amount(1.0) == pytest.approx(0.02)


def test_root_fillet_radius_large_z():
    """For large z with no shift, fillet approaches rack tip radius (0.38*m)."""
    # z=100, x=0: should be close to 0.38*m but slightly larger (trochoid contribution)
    rho = root_fillet_radius(2.0, 100, 0.0)
    assert rho > 0.38 * 2.0
    assert rho == pytest.approx(0.38 * 2.0, abs=0.05)


def test_root_fillet_radius_small_z():
    """Smaller z gives a larger fillet (trochoid envelope effect)."""
    rho_small = root_fillet_radius(2.0, 12, 0.0)
    rho_large = root_fillet_radius(2.0, 40, 0.0)
    assert rho_small > rho_large  # smaller gear has bigger fillet at root bottom


def test_root_fillet_radius_profile_shift():
    """Positive profile shift reduces the straight rack engagement, shrinking fillet."""
    rho_no_shift = root_fillet_radius(2.0, 20, 0.0)
    rho_shifted = root_fillet_radius(2.0, 20, 0.3)
    assert rho_shifted < rho_no_shift


def test_backlash():
    """j_t = 0.04 * m."""
    assert backlash(2.0) == pytest.approx(0.08)
    assert backlash(1.0) == pytest.approx(0.04)


# ---- Top-level optimize_stage ------------------------------------------------


def test_optimize_stage_all_fields():
    """optimize_stage returns a StageGeometry with all fields populated."""
    result = optimize_stage(
        z1=20,
        z2=40,
        module=2.0,
        face_width_mm=20.0,
        torque_nm=1.0,
        mat_key_1="steel_alloy",
        mat_key_2="steel_alloy",
    )
    assert result.profile_shift_pinion == pytest.approx(0.0, abs=1e-4)
    assert result.profile_shift_wheel == pytest.approx(0.0, abs=1e-4)
    assert result.operating_pressure_angle_deg == pytest.approx(20.0, abs=0.01)
    assert result.operating_center_distance_mm == pytest.approx(60.0, abs=0.1)
    assert result.contact_ratio > 1.0
    assert result.backlash_mm > 0.0
    assert result.hertz_contact_stress_mpa > 0.0
    assert result.tip_relief_pinion_mm > 0.0
    assert result.tip_relief_wheel_mm > 0.0
    assert result.root_fillet_radius_pinion_mm > 0.0
    assert result.root_fillet_radius_wheel_mm > 0.0
