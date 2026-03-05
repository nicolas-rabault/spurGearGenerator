"""Tests for the materials module."""

import pytest

from spurGearGenerator.materials import (
    MATERIAL_BY_KEY,
    MATERIALS,
    GearMaterial,
)


def test_material_keys_are_unique():
    keys = [m.key for m in MATERIALS]
    assert len(keys) == len(set(keys))


def test_material_lookup_by_key():
    mat = MATERIAL_BY_KEY["steel_alloy"]
    assert mat.name == "Alloy Steel (AISI 4140)"
    assert mat.density == 7850
    assert mat.allowable_bending_stress == 250


def test_material_lookup_unknown_key():
    with pytest.raises(KeyError):
        MATERIAL_BY_KEY["unobtainium"]


def test_youngs_modulus_present():
    for mat in MATERIALS:
        assert mat.youngs_modulus > 0
