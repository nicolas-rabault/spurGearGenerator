"""Tests for the CLI module."""

import json

from click.testing import CliRunner

from spurGearGenerator.cli import main


def _write_config(tmp_path, **overrides):
    data = {"target_ratio": 3.0, "input_torque": 0.5, "reduction_margin": 5.0}
    data.update(overrides)
    f = tmp_path / "config.json"
    f.write_text(json.dumps(data))
    return str(f)


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_solve_basic(tmp_path):
    cfg = _write_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["solve", cfg])
    assert result.exit_code == 0
    assert "solution" in result.output.lower()


def test_cli_solve_verbose(tmp_path):
    cfg = _write_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["solve", cfg, "--verbose"])
    assert result.exit_code == 0
    assert "target_ratio" in result.output


def test_cli_solve_two_stages(tmp_path):
    cfg = _write_config(tmp_path, target_ratio=8.0, reduction_margin=5.0, max_teeth_per_gear=60)
    runner = CliRunner()
    result = runner.invoke(main, ["solve", cfg, "--stages", "2"])
    assert result.exit_code == 0
    assert "solution" in result.output.lower()


def test_cli_output_json(tmp_path):
    cfg = _write_config(tmp_path)
    out_path = str(tmp_path / "results.json")
    runner = CliRunner()
    result = runner.invoke(main, ["solve", cfg, "--output", out_path])
    assert result.exit_code == 0
    with open(out_path) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) > 0
    assert "total_ratio" in data[0]


def test_cli_no_solutions(tmp_path):
    cfg = _write_config(tmp_path, target_ratio=50.0, max_teeth_per_gear=30, reduction_margin=0.1)
    runner = CliRunner()
    result = runner.invoke(main, ["solve", cfg])
    assert result.exit_code == 0
    assert "no solutions" in result.output.lower()


# ---- show command -----------------------------------------------------------


def test_cli_show_solution(tmp_path):
    """Solve, then show solution #1 from the results file."""
    cfg = _write_config(tmp_path)
    out_path = str(tmp_path / "results.json")
    runner = CliRunner()
    runner.invoke(main, ["solve", cfg, "--output", out_path])

    result = runner.invoke(main, ["show", out_path, "1"])
    assert result.exit_code == 0
    assert "Solution #1" in result.output
    assert "Stage 1" in result.output
    assert "Pinion" in result.output
    assert "Wheel" in result.output
    assert "stress" in result.output.lower()


def test_cli_show_invalid_number(tmp_path):
    """Show with out-of-range number should fail."""
    cfg = _write_config(tmp_path)
    out_path = str(tmp_path / "results.json")
    runner = CliRunner()
    runner.invoke(main, ["solve", cfg, "--output", out_path])

    result = runner.invoke(main, ["show", out_path, "999"])
    assert result.exit_code != 0
