"""Tests for the Onshape API client module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from spurGearGenerator.models import (
    GearboxSolution,
    GearResult,
    StageGeometry,
    StageResult,
)
from spurGearGenerator.onshape import (
    OnshapeError,
    _resolve_variable_studio,
    build_variables,
    parse_onshape_url,
    push_to_onshape,
    set_variables,
    validate_onshape_env,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gear(role, teeth, module, dedendum_coeff=1.25, addendum_coeff=1.0):
    return GearResult(
        role=role,
        teeth=teeth,
        module=module,
        material="steel_hardened",
        pitch_diameter_mm=module * teeth,
        addendum_diameter_mm=module * (teeth + 2),
        face_width_mm=module * 5,
        lewis_stress_mpa=200.0,
        allowable_stress_mpa=380.0,
        weight_kg=0.01,
        dedendum_coeff=dedendum_coeff,
        addendum_coeff=addendum_coeff,
    )


def _make_geometry():
    return StageGeometry(
        profile_shift_pinion=0.12,
        profile_shift_wheel=0.0,
        operating_pressure_angle_deg=20.71,
        operating_center_distance_mm=22.5,
        contact_ratio=1.55,
        backlash_mm=0.04,
        specific_sliding_tip_pinion=0.14,
        specific_sliding_tip_wheel=0.95,
        hertz_contact_stress_mpa=1500.0,
        tip_relief_pinion_mm=0.006,
        tip_relief_wheel_mm=0.006,
        root_fillet_radius_pinion_mm=0.14,
        root_fillet_radius_wheel_mm=0.13,
    )


def _make_solution(n_stages=1):
    stages = []
    for i in range(1, n_stages + 1):
        stages.append(
            StageResult(
                stage_number=i,
                pinion=_make_gear("pinion", 15, 1.0, dedendum_coeff=1.1273, addendum_coeff=1.1216),
                wheel=_make_gear("wheel", 30, 1.0, dedendum_coeff=1.25, addendum_coeff=0.999),
                stage_ratio=2.0,
                mesh_efficiency=0.98,
                stage_torque_in_nm=0.5,
                geometry=_make_geometry(),
            )
        )
    return GearboxSolution(
        stages=stages,
        total_ratio=2.0 ** n_stages,
        ratio_error_pct=0.0,
        total_efficiency=0.98 ** n_stages,
        total_weight_kg=0.02 * n_stages,
        ranking_tag="weight",
    )


# ---------------------------------------------------------------------------
# validate_onshape_env
# ---------------------------------------------------------------------------


class TestValidateOnshapeEnv:
    def test_all_set(self, monkeypatch):
        monkeypatch.setenv("ONSHAPE_API", "https://cad.onshape.com")
        monkeypatch.setenv("ONSHAPE_ACCESS_KEY", "key123")
        monkeypatch.setenv("ONSHAPE_SECRET_KEY", "secret456")
        api, key, secret = validate_onshape_env()
        assert api == "https://cad.onshape.com"
        assert key == "key123"
        assert secret == "secret456"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("ONSHAPE_API", "https://cad.onshape.com/")
        monkeypatch.setenv("ONSHAPE_ACCESS_KEY", "k")
        monkeypatch.setenv("ONSHAPE_SECRET_KEY", "s")
        api, _, _ = validate_onshape_env()
        assert api == "https://cad.onshape.com"

    def test_missing_all(self, monkeypatch):
        monkeypatch.delenv("ONSHAPE_API", raising=False)
        monkeypatch.delenv("ONSHAPE_ACCESS_KEY", raising=False)
        monkeypatch.delenv("ONSHAPE_SECRET_KEY", raising=False)
        with pytest.raises(OnshapeError, match="ONSHAPE_API"):
            validate_onshape_env()

    def test_missing_secret(self, monkeypatch):
        monkeypatch.setenv("ONSHAPE_API", "https://cad.onshape.com")
        monkeypatch.setenv("ONSHAPE_ACCESS_KEY", "k")
        monkeypatch.delenv("ONSHAPE_SECRET_KEY", raising=False)
        with pytest.raises(OnshapeError, match="ONSHAPE_SECRET_KEY"):
            validate_onshape_env()


# ---------------------------------------------------------------------------
# parse_onshape_url
# ---------------------------------------------------------------------------


class TestParseOnshapeUrl:
    def test_valid_workspace_url(self):
        url = "https://cad.onshape.com/documents/abcdef1234567890abcdef12/w/fedcba0987654321fedcba09/e/112233445566778899aabbcc"
        did, wvm, wvmid, eid = parse_onshape_url(url)
        assert did == "abcdef1234567890abcdef12"
        assert wvm == "w"
        assert wvmid == "fedcba0987654321fedcba09"
        assert eid == "112233445566778899aabbcc"

    def test_valid_version_url(self):
        url = "https://cad.onshape.com/documents/aabb/v/ccdd/e/eeff"
        did, wvm, wvmid, eid = parse_onshape_url(url)
        assert wvm == "v"

    def test_valid_microversion_url(self):
        url = "https://cad.onshape.com/documents/aabb/m/ccdd/e/eeff"
        did, wvm, wvmid, eid = parse_onshape_url(url)
        assert wvm == "m"

    def test_url_with_query_params(self):
        url = "https://cad.onshape.com/documents/aabb/w/ccdd/e/eeff?configuration=default"
        did, wvm, wvmid, eid = parse_onshape_url(url)
        assert did == "aabb"
        assert eid == "eeff"

    def test_invalid_url(self):
        with pytest.raises(OnshapeError, match="Invalid Onshape URL"):
            parse_onshape_url("https://google.com")

    def test_missing_element(self):
        with pytest.raises(OnshapeError, match="Invalid Onshape URL"):
            parse_onshape_url("https://cad.onshape.com/documents/aabb/w/ccdd")


# ---------------------------------------------------------------------------
# build_variables
# ---------------------------------------------------------------------------


class TestBuildVariables:
    def test_single_stage_count(self):
        sol = _make_solution(1)
        variables = build_variables(sol)
        assert len(variables) == 10

    def test_multi_stage_count(self):
        sol = _make_solution(3)
        variables = build_variables(sol)
        assert len(variables) == 30

    def test_variable_names(self):
        sol = _make_solution(1)
        variables = build_variables(sol)
        names = [v["name"] for v in variables]
        expected = [
            "s1_depth", "s1_m", "s1_p", "s1_backlash",
            "s1p_z", "s1p_dedendum", "s1p_addendum",
            "s1w_z", "s1w_dedendum", "s1w_addendum",
        ]
        assert names == expected

    def test_multi_stage_prefixes(self):
        sol = _make_solution(2)
        variables = build_variables(sol)
        names = [v["name"] for v in variables]
        assert "s1_depth" in names
        assert "s2_depth" in names
        assert "s1p_z" in names
        assert "s2w_z" in names

    def test_variable_types(self):
        sol = _make_solution(1)
        variables = build_variables(sol)
        by_name = {v["name"]: v for v in variables}
        assert by_name["s1_depth"]["type"] == "LENGTH"
        assert by_name["s1_m"]["type"] == "LENGTH"
        assert by_name["s1_p"]["type"] == "ANGLE"
        assert by_name["s1_backlash"]["type"] == "LENGTH"
        assert by_name["s1p_z"]["type"] == "NUMBER"
        assert by_name["s1w_z"]["type"] == "NUMBER"
        assert by_name["s1p_dedendum"]["type"] == "NUMBER"
        assert by_name["s1w_addendum"]["type"] == "NUMBER"

    def test_variable_expressions(self):
        sol = _make_solution(1)
        variables = build_variables(sol)
        by_name = {v["name"]: v for v in variables}
        assert by_name["s1_depth"]["expression"] == "5.0 mm"  # face_width = module * 5 = 1.0 * 5
        assert by_name["s1_m"]["expression"] == "1.0 mm"
        assert by_name["s1_p"]["expression"] == "20.71 deg"
        assert by_name["s1_backlash"]["expression"] == "0.04 mm"
        assert by_name["s1p_z"]["expression"] == "15"
        assert by_name["s1w_z"]["expression"] == "30"
        assert by_name["s1p_dedendum"]["expression"] == "1.1273"
        assert by_name["s1w_addendum"]["expression"] == "0.999"

    def test_no_geometry_defaults(self):
        """When geometry is None, use default pressure angle and zero backlash."""
        sol = _make_solution(1)
        sol.stages[0] = sol.stages[0].model_copy(update={"geometry": None})
        variables = build_variables(sol)
        by_name = {v["name"]: v for v in variables}
        assert by_name["s1_p"]["expression"] == "20 deg"
        assert by_name["s1_backlash"]["expression"] == "0 mm"


# ---------------------------------------------------------------------------
# check_variable_studio
# ---------------------------------------------------------------------------


class TestResolveVariableStudio:
    def test_exact_match(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        resolved = _resolve_variable_studio(session, "https://api", "d", "w", "wid", "eid2")
        assert resolved == "eid2"

    def test_prefix_match_fallback(self):
        """Truncated element ID is resolved via prefix match on elements list."""
        session = MagicMock()
        # First call (direct variables GET) returns 404
        # Second call (elements list) returns the full element
        session.get.side_effect = [
            MagicMock(status_code=404),
            MagicMock(status_code=200, json=lambda: [
                {"id": "aabb1122", "elementType": "PARTSTUDIO", "name": "Part"},
                {"id": "aabb3344cc", "elementType": "VARIABLESTUDIO", "name": "Vars"},
            ]),
        ]
        resolved = _resolve_variable_studio(session, "https://api", "d", "w", "wid", "aabb3344")
        assert resolved == "aabb3344cc"

    def test_no_variable_studios(self):
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(status_code=404),
            MagicMock(status_code=200, json=lambda: [
                {"id": "aabb", "elementType": "PARTSTUDIO", "name": "Part"},
            ]),
        ]
        with pytest.raises(OnshapeError, match="No Variable Studios"):
            _resolve_variable_studio(session, "https://api", "d", "w", "wid", "bad")

    def test_no_prefix_match_lists_studios(self):
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(status_code=404),
            MagicMock(status_code=200, json=lambda: [
                {"id": "xxxx1111", "elementType": "VARIABLESTUDIO", "name": "MyVars"},
            ]),
        ]
        with pytest.raises(OnshapeError, match="MyVars"):
            _resolve_variable_studio(session, "https://api", "d", "w", "wid", "bad")


# ---------------------------------------------------------------------------
# set_variables
# ---------------------------------------------------------------------------


class TestSetVariables:
    def test_success_200(self):
        session = MagicMock()
        session.post.return_value = MagicMock(status_code=200)
        variables = [{"name": "x", "type": "LENGTH", "expression": "1 mm"}]
        set_variables(session, "https://api", "d", "w", "wid", "eid", variables)
        session.post.assert_called_once()

    def test_success_204(self):
        session = MagicMock()
        session.post.return_value = MagicMock(status_code=204)
        set_variables(session, "https://api", "d", "w", "wid", "eid", [])
        session.post.assert_called_once()

    def test_failure(self):
        session = MagicMock()
        session.post.return_value = MagicMock(status_code=500, text="Server Error")
        with pytest.raises(OnshapeError, match="500"):
            set_variables(session, "https://api", "d", "w", "wid", "eid", [])


# ---------------------------------------------------------------------------
# push_to_onshape (integration with mocks)
# ---------------------------------------------------------------------------


class TestPushToOnshape:
    @patch("spurGearGenerator.onshape.set_variables")
    @patch("spurGearGenerator.onshape._resolve_variable_studio")
    @patch("spurGearGenerator.onshape._make_session")
    @patch("spurGearGenerator.onshape.validate_onshape_env")
    def test_full_flow(self, mock_env, mock_session, mock_resolve, mock_set):
        mock_env.return_value = ("https://cad.onshape.com", "key", "secret")
        mock_session.return_value = MagicMock()
        mock_resolve.return_value = "eeff"

        sol = _make_solution(2)
        url = "https://cad.onshape.com/documents/aabb/w/ccdd/e/eeff"
        push_to_onshape(sol, url, verbose=False)

        mock_env.assert_called_once()
        mock_session.assert_called_once_with("key", "secret")
        mock_resolve.assert_called_once()
        mock_set.assert_called_once()

        # Verify correct number of variables
        posted_vars = mock_set.call_args[0][-1]  # last positional arg
        assert len(posted_vars) == 20  # 2 stages * 10 vars

    @patch("spurGearGenerator.onshape.validate_onshape_env")
    def test_env_validation_failure(self, mock_env):
        mock_env.side_effect = OnshapeError("Missing ONSHAPE_API")
        sol = _make_solution(1)
        with pytest.raises(OnshapeError, match="Missing"):
            push_to_onshape(sol, "https://cad.onshape.com/documents/a/w/b/e/c")
