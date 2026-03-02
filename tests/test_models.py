"""Tests for the Pydantic models."""

import json

import pytest
from pydantic import ValidationError

from spurGearGenerator.models import GearConfig, load_config


def test_config_all_fields():
    cfg = GearConfig(target_ratio=5.0, reduction_margin=3.0, input_torque=0.5, max_teeth_per_gear=100)
    assert cfg.target_ratio == 5.0
    assert cfg.reduction_margin == 3.0
    assert cfg.input_torque == 0.5
    assert cfg.max_teeth_per_gear == 100


def test_config_defaults():
    cfg = GearConfig(target_ratio=3.0, input_torque=1.0)
    assert cfg.reduction_margin == 5.0
    assert cfg.max_teeth_per_gear == 150


def test_config_missing_required_field():
    with pytest.raises(ValidationError):
        GearConfig(target_ratio=3.0)  # missing input_torque


def test_config_negative_torque():
    with pytest.raises(ValidationError):
        GearConfig(target_ratio=3.0, input_torque=-1.0)


def test_config_zero_ratio():
    with pytest.raises(ValidationError):
        GearConfig(target_ratio=0.0, input_torque=1.0)


def test_config_margin_too_large():
    with pytest.raises(ValidationError):
        GearConfig(target_ratio=3.0, input_torque=1.0, reduction_margin=60.0)


def test_load_config_from_file(tmp_path):
    data = {"target_ratio": 5.0, "reduction_margin": 2.0, "input_torque": 0.3}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))
    cfg = load_config(str(f))
    assert cfg.target_ratio == 5.0
    assert cfg.input_torque == 0.3
