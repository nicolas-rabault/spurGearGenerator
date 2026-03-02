"""CLI entry point for spurGearGenerator."""

import json
from pathlib import Path

import click
from tabulate import tabulate

from spurGearGenerator.models import GearboxSolution, SolveStats, load_config
from spurGearGenerator.solver import solve

# Short codes for materials used in compact display
_MAT_ABBREV: dict[str, str] = {
    "steel_mild": "SM",
    "steel_alloy": "SA",
    "steel_hardened": "SH",
    "brass": "BR",
    "bronze": "BZ",
    "aluminum": "AL",
    "nylon": "NY",
    "pom": "POM",
}

_MAT_LABEL: dict[str, str] = {
    "SM": "Mild Steel",
    "SA": "Alloy Steel",
    "SH": "Hardened Steel",
    "BR": "Brass",
    "BZ": "Bronze",
    "AL": "Aluminum",
    "NY": "Nylon",
    "POM": "POM/Delrin",
}


@click.group()
@click.version_option()
def main():
    """Spur Gear Generator - Find spur gear gearbox solutions."""


@main.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option(
    "--stages",
    "-s",
    type=int,
    default=1,
    show_default=True,
    help="Maximum number of gear stages to search.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Path for JSON output file (default: <config_name>_results.json).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def solve_cmd(config_file: str, stages: int, output: str | None, verbose: bool):
    """Solve gear combinations from a JSON configuration file."""
    config = load_config(config_file)

    if verbose:
        click.echo(
            f"Config: target_ratio={config.target_ratio}, "
            f"margin={config.reduction_margin}%, "
            f"input_torque={config.input_torque} Nm, "
            f"max_teeth={config.max_teeth_per_gear}"
        )
        click.echo(f"Searching up to {stages} stage(s)...")

    solutions, stats = solve(config, max_stages=stages, show_progress=True)

    if not solutions:
        click.echo("No solutions found matching the constraints.")
        _display_stats(stats)
        return

    click.echo(f"\nFound {len(solutions)} solution(s):\n")
    _display_compact(solutions)

    # Write JSON results
    if output is None:
        cfg_path = Path(config_file)
        output = str(cfg_path.parent / f"{cfg_path.stem}_results.json")
    _write_json(solutions, output)
    click.echo(f"\nResults written to {output}")
    _display_stats(stats)


def _mat_code(key: str) -> str:
    """Return short material abbreviation."""
    return _MAT_ABBREV.get(key, key)


def _stage_str(sol: GearboxSolution) -> str:
    """Build compact stage description string."""
    parts = []
    for s in sol.stages:
        mat_p = _mat_code(s.pinion.material)
        mat_w = _mat_code(s.wheel.material)
        mat = mat_p if mat_p == mat_w else f"{mat_p}/{mat_w}"
        parts.append(f"m{s.pinion.module} {s.pinion.teeth}/{s.wheel.teeth} {mat}")
    return " \u00b7 ".join(parts)


def _collect_materials(solutions: list[GearboxSolution]) -> set[str]:
    """Collect all material abbreviation codes used across solutions."""
    codes: set[str] = set()
    for sol in solutions:
        for s in sol.stages:
            codes.add(_mat_code(s.pinion.material))
            codes.add(_mat_code(s.wheel.material))
    return codes


def _display_compact(solutions: list[GearboxSolution]) -> None:
    """Print compact grouped results."""
    # Material legend
    codes = _collect_materials(solutions)
    if codes:
        legend = "  ".join(f"{c}={_MAT_LABEL.get(c, c)}" for c in sorted(codes))
        click.echo(f"Materials: {legend}\n")

    # Split by ranking group
    by_weight = [s for s in solutions if "weight" in s.ranking_tag]
    by_eff = [s for s in solutions if "efficiency" in s.ranking_tag]

    headers = ["#", "Ratio", "Err%", "Eff%", "Weight", "Stages"]
    idx = 1

    if by_weight:
        click.echo(f"\u2500\u2500 Best by weight ({len(by_weight)}) " + "\u2500" * 40)
        rows = []
        for sol in by_weight:
            rows.append([
                idx,
                f"{sol.total_ratio:.4f}",
                f"{sol.ratio_error_pct:+.2f}",
                f"{sol.total_efficiency * 100:.1f}",
                f"{sol.total_weight_kg * 1000:.1f}g",
                _stage_str(sol),
            ])
            idx += 1
        click.echo(tabulate(rows, headers=headers, tablefmt="simple"))
        click.echo()

    if by_eff:
        click.echo(f"\u2500\u2500 Best by efficiency ({len(by_eff)}) " + "\u2500" * 36)
        rows = []
        for sol in by_eff:
            rows.append([
                idx,
                f"{sol.total_ratio:.4f}",
                f"{sol.ratio_error_pct:+.2f}",
                f"{sol.total_efficiency * 100:.1f}",
                f"{sol.total_weight_kg * 1000:.1f}g",
                _stage_str(sol),
            ])
            idx += 1
        click.echo(tabulate(rows, headers=headers, tablefmt="simple"))


def _fmt_num(n: int) -> str:
    """Format a large number with comma separators."""
    return f"{n:,}"


def _display_stats(stats: SolveStats) -> None:
    """Print solver performance metrics."""
    click.echo()
    click.echo("\u2500" * 52)
    click.echo(
        f"Evaluated {_fmt_num(stats.solutions_evaluated)} feasible configurations "
        f"across {_fmt_num(stats.subtrees_searched)} subtrees"
    )
    click.echo(
        f"Completed in {stats.elapsed_seconds:.2f}s "
        f"on {stats.cpu_cores} CPU cores"
    )


def _write_json(solutions: list[GearboxSolution], path: str) -> None:
    """Write detailed JSON output."""
    data = [sol.model_dump() for sol in solutions]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# show command
# ---------------------------------------------------------------------------


@main.command()
@click.argument("results_file", type=click.Path(exists=True))
@click.argument("number", type=int)
def show(results_file: str, number: int):
    """Show full details of solution NUMBER from a results JSON file."""
    with open(results_file) as f:
        data = json.load(f)

    if not 1 <= number <= len(data):
        click.echo(f"Invalid solution number. File contains {len(data)} solution(s).")
        raise SystemExit(1)

    sol = GearboxSolution(**data[number - 1])
    n_stages = len(sol.stages)

    # Collect material codes used
    mat_codes_used: set[str] = set()
    for stage in sol.stages:
        mat_codes_used.add(_mat_code(stage.pinion.material))
        mat_codes_used.add(_mat_code(stage.wheel.material))

    # Legend block
    legend = "  ".join(f"{c}={_mat_label(c)}" for c in sorted(mat_codes_used))
    click.echo(f"Materials: {legend}")
    click.echo(
        "Z=teeth  m=module(mm)  \u00d8pitch/\u00d8tip=diameters(mm)  "
        "Face=width(mm)  Stress=Lewis actual/allowable"
    )
    click.echo()

    # Header
    click.echo(f"Solution #{number} \u2014 {n_stages}-stage gearbox")
    click.echo(
        f"Ratio: {sol.total_ratio:.4f} ({sol.ratio_error_pct:+.2f}%)   "
        f"Efficiency: {sol.total_efficiency * 100:.2f}%   "
        f"Weight: {sol.total_weight_kg * 1000:.2f}g"
    )
    click.echo()

    # Gear table
    headers = ["Stage", "Gear", "Z", "m", "Mat", "\u00d8pitch", "\u00d8tip", "Face", "Stress", "Weight"]
    rows = []
    for stage in sol.stages:
        for i, (g, label) in enumerate([(stage.pinion, "Pinion"), (stage.wheel, "Wheel")]):
            stress_pct = g.lewis_stress_mpa / g.allowable_stress_mpa * 100
            rows.append([
                stage.stage_number if i == 0 else "",
                label,
                g.teeth,
                g.module,
                _mat_code(g.material),
                f"{g.pitch_diameter_mm:.1f}",
                f"{g.addendum_diameter_mm:.1f}",
                f"{g.face_width_mm:.2f}",
                f"{g.lewis_stress_mpa:.0f}/{g.allowable_stress_mpa:.0f} ({stress_pct:.0f}%)",
                f"{g.weight_kg * 1000:.2f}g",
            ])
    click.echo(tabulate(rows, headers=headers, tablefmt="simple", colalign=(
        "right", "left", "right", "right", "left", "right", "right", "right", "right", "right",
    )))

    # Stage details
    click.echo()
    for stage in sol.stages:
        click.echo(
            f"  Stage {stage.stage_number}: "
            f"ratio {stage.stage_ratio:.4f}, "
            f"eff. {stage.mesh_efficiency * 100:.2f}%, "
            f"torque in {stage.stage_torque_in_nm:.3f} Nm"
        )

    # Output torque
    last = sol.stages[-1]
    torque_out = last.stage_torque_in_nm * last.stage_ratio * last.mesh_efficiency
    click.echo(f"\nTorque out: {torque_out:.3f} Nm")


def _mat_label(code: str) -> str:
    """Return human-readable name for a material abbreviation code."""
    return _MAT_LABEL.get(code, code)
