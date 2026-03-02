"""Tests for the materials module."""

import pytest

from spurGearGenerator.materials import (
    MATERIALS,
    GearMaterial,
    get_all_materials,
    get_material,
)


def test_all_materials_have_required_fields():
    for mat in MATERIALS:
        assert isinstance(mat, GearMaterial)
        assert mat.name
        assert mat.key
        assert mat.density > 0
        assert mat.allowable_bending_stress > 0
        assert mat.friction_coefficient > 0


def test_material_keys_are_unique():
    keys = [m.key for m in MATERIALS]
    assert len(keys) == len(set(keys))


def test_material_lookup_by_key():
    mat = get_material("steel_alloy")
    assert mat.name == "Alloy Steel (AISI 4140)"
    assert mat.density == 7850
    assert mat.allowable_bending_stress == 250


def test_material_lookup_unknown_key():
    with pytest.raises(KeyError):
        get_material("unobtainium")


def test_get_all_materials_returns_tuple():
    mats = get_all_materials()
    assert isinstance(mats, tuple)
    assert len(mats) == 8


def test_material_is_frozen():
    mat = get_material("nylon")
    with pytest.raises(AttributeError):
        mat.density = 9999  # type: ignore[misc]
