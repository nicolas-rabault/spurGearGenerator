"""Tests for the gear_math module."""

import math

import pytest

from spurGearGenerator.gear_math import (
    addendum_diameter,
    gear_weight,
    lewis_bending_stress,
    lewis_form_factor,
    mesh_efficiency,
    pitch_diameter,
    tangential_force,
)


# ---- Geometry ---------------------------------------------------------------


def test_pitch_diameter():
    assert pitch_diameter(2.0, 20) == pytest.approx(40.0)
    assert pitch_diameter(1.0, 50) == pytest.approx(50.0)
    assert pitch_diameter(0.5, 12) == pytest.approx(6.0)


def test_addendum_diameter():
    assert addendum_diameter(2.0, 20) == pytest.approx(44.0)
    assert addendum_diameter(1.0, 50) == pytest.approx(52.0)


# ---- Lewis form factor -----------------------------------------------------


def test_lewis_form_factor_known_values():
    """Check exact table entries."""
    assert lewis_form_factor(12) == pytest.approx(0.245)
    assert lewis_form_factor(20) == pytest.approx(0.320)
    assert lewis_form_factor(50) == pytest.approx(0.408)
    assert lewis_form_factor(100) == pytest.approx(0.446)


def test_lewis_form_factor_interpolation():
    """Interpolated value between Z=20 (0.320) and Z=22 (0.330)."""
    y21 = lewis_form_factor(21)
    assert 0.320 < y21 < 0.330
    assert y21 == pytest.approx(0.325, abs=0.001)


def test_lewis_form_factor_boundary_low():
    """Z below table minimum clamps to Y(10)."""
    assert lewis_form_factor(5) == pytest.approx(0.201)
    assert lewis_form_factor(10) == pytest.approx(0.201)


def test_lewis_form_factor_boundary_high():
    """Z above table maximum clamps to Y(300)."""
    assert lewis_form_factor(300) == pytest.approx(0.471)
    assert lewis_form_factor(500) == pytest.approx(0.471)


# ---- Force and stress -------------------------------------------------------


def test_tangential_force():
    """Ft = 2*T / d  where d in metres."""
    # module=2, z=20 => d=40mm=0.04m, T=1 Nm => Ft=2/0.04=50 N
    ft = tangential_force(1.0, 2.0, 20)
    assert ft == pytest.approx(50.0)


def test_lewis_bending_stress():
    """sigma = Ft / (b * m * Y)."""
    ft = 50.0  # N
    b = 20.0  # mm
    m = 2.0  # mm
    z = 20  # Y(20) = 0.320
    sigma = lewis_bending_stress(ft, b, m, z)
    expected = 50.0 / (20.0 * 2.0 * 0.320)
    assert sigma == pytest.approx(expected)


# ---- Efficiency -------------------------------------------------------------


def test_mesh_efficiency():
    """eta = 1 - pi * mu * (1/z1 + 1/z2)."""
    eta = mesh_efficiency(20, 40, 0.06)
    expected = 1.0 - math.pi * 0.06 * (1 / 20 + 1 / 40)
    assert eta == pytest.approx(expected)
    assert 0 < eta < 1


def test_mesh_efficiency_large_teeth():
    """Larger teeth -> higher efficiency."""
    eta_small = mesh_efficiency(12, 24, 0.08)
    eta_large = mesh_efficiency(50, 100, 0.08)
    assert eta_large > eta_small


# ---- Weight -----------------------------------------------------------------


def test_gear_weight():
    """Solid cylinder: W = rho * pi * r^2 * b."""
    # module=2, z=20 => da=44mm, r=22mm=0.022m, b=20mm=0.02m
    # rho=7850 => W = 7850 * pi * 0.022^2 * 0.02
    w = gear_weight(2.0, 20, 20.0, 7850.0)
    expected = 7850.0 * math.pi * 0.022**2 * 0.02
    assert w == pytest.approx(expected, rel=1e-6)


def test_gear_weight_increases_with_teeth():
    """More teeth means larger diameter, hence more weight."""
    w1 = gear_weight(2.0, 20, 20.0, 7850.0)
    w2 = gear_weight(2.0, 40, 20.0, 7850.0)
    assert w2 > w1
