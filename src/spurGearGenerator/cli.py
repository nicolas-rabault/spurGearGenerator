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
@click.option(
    "--min-output-root-diameter",
    type=float,
    default=None,
    help="Minimum root diameter for the last output wheel in mm.",
)
def solve_cmd(
    config_file: str,
    stages: int,
    output: str | None,
    verbose: bool,
    min_output_root_diameter: float | None,
):
    """Solve gear combinations from a JSON configuration file."""
    config = load_config(config_file)
    if min_output_root_diameter is not None:
        config.min_output_root_diameter = min_output_root_diameter

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


def _mat_label(code: str) -> str:
    """Return human-readable name for a material abbreviation code."""
    return _MAT_LABEL.get(code, code)


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
    by_weight = [s for s in solutions if s.ranking_tag == "weight"]
    by_eff = [s for s in solutions if s.ranking_tag == "efficiency"]

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


def _display_stats(stats: SolveStats) -> None:
    """Print solver performance metrics."""
    click.echo()
    click.echo("\u2500" * 52)
    click.echo(
        f"Evaluated {stats.solutions_evaluated:,} feasible configurations "
        f"across {stats.subtrees_searched:,} subtrees"
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
# format_solution (shared by show and generate)
# ---------------------------------------------------------------------------


def format_solution(sol: GearboxSolution, number: int) -> str:
    """Format a solution for display. Used by both ``show`` and ``generate``."""
    lines: list[str] = []
    n_stages = len(sol.stages)

    # ── Header ──
    lines.append(f"Solution #{number} \u2014 {n_stages}-stage gearbox")
    lines.append("=" * 52)
    lines.append(
        f"Ratio: {sol.total_ratio:.4f} ({sol.ratio_error_pct:+.2f}%)   "
        f"Weight: {sol.total_weight_kg * 1000:.2f} g"
    )
    last = sol.stages[-1]
    torque_out = last.stage_torque_in_nm * last.stage_ratio * last.mesh_efficiency
    lines.append(f"Torque out: {torque_out:.3f} Nm")
    lines.append("")

    # ── Per-stage sections ──
    for stage in sol.stages:
        geom = stage.geometry
        lines.append(f"\u2500\u2500 Stage {stage.stage_number} (ratio {stage.stage_ratio:.4f}) " + "\u2500" * 30)
        lines.append("")

        # -- Parameters table --
        lines.append("Parameters")
        param_headers = [
            "Gear", "Depth (mm)", "Teeth", "Module (mm)",
            "Pressure \u00b0", "Root fillet (mm)", "Tip relief (mm)",
            "Backlash (mm)", "Dedendum", "Addendum",
        ]
        param_rows = []
        for g, label in [(stage.pinion, "Pinion"), (stage.wheel, "Wheel")]:
            pressure_deg = (
                f"{geom.operating_pressure_angle_deg:.2f}"
                if geom is not None else "20.00"
            )
            root_fillet = (
                f"{geom.root_fillet_radius_pinion_mm:.3f}" if label == "Pinion"
                else f"{geom.root_fillet_radius_wheel_mm:.3f}"
            ) if geom is not None else "\u2014"
            tip_relief_val = (
                f"{geom.tip_relief_pinion_mm:.3f}" if label == "Pinion"
                else f"{geom.tip_relief_wheel_mm:.3f}"
            ) if geom is not None else "\u2014"
            backlash_val = (
                f"{geom.backlash_mm:.3f}"
                if geom is not None else "\u2014"
            )
            dedendum_val = (
                f"{g.dedendum_coeff:.4f} (1.25)"
                if g.dedendum_coeff is not None else "\u2014"
            )
            addendum_val = (
                f"{g.addendum_coeff:.4f} (1.0)"
                if g.addendum_coeff is not None else "\u2014"
            )
            param_rows.append([
                label,
                f"{g.face_width_mm:.2f}",
                g.teeth,
                g.module,
                pressure_deg,
                root_fillet,
                tip_relief_val,
                backlash_val,
                dedendum_val,
                addendum_val,
            ])
        lines.append(tabulate(param_rows, headers=param_headers, tablefmt="simple"))
        lines.append("")

        # -- Metrics --
        lines.append("Metrics")
        mat_p = _mat_label(_mat_code(stage.pinion.material))
        mat_w = _mat_label(_mat_code(stage.wheel.material))
        lines.append(f"  Materials:        {mat_p} / {mat_w}")
        lines.append(f"  Torque in:        {stage.stage_torque_in_nm:.3f} Nm")
        lines.append(f"  Efficiency:       {stage.mesh_efficiency * 100:.2f}%")

        for g, label in [(stage.pinion, "Pinion"), (stage.wheel, "Wheel")]:
            stress_pct = g.lewis_stress_mpa / g.allowable_stress_mpa * 100
            lines.append(
                f"  Lewis stress ({label:6s}): "
                f"{g.lewis_stress_mpa:.0f} / {g.allowable_stress_mpa:.0f} MPa ({stress_pct:.0f}%)"
            )

        for g, label in [(stage.pinion, "Pinion"), (stage.wheel, "Wheel")]:
            lines.append(
                f"  Diameters ({label:6s}):  "
                f"\u00d8pitch={g.pitch_diameter_mm:.2f}  "
                f"\u00d8tip={g.addendum_diameter_mm:.2f}  "
                f"weight={g.weight_kg * 1000:.2f} g"
            )

        if geom is not None:
            lines.append(f"  Center distance:  {geom.operating_center_distance_mm:.2f} mm")
            lines.append(f"  Contact ratio:    {geom.contact_ratio:.3f}")
            lines.append(f"  Hertz stress:     {geom.hertz_contact_stress_mpa:.1f} MPa")
            lines.append(
                f"  Specific sliding: "
                f"pinion={geom.specific_sliding_tip_pinion:.3f}  "
                f"wheel={geom.specific_sliding_tip_wheel:.3f}"
            )
            lines.append(
                f"  Profile shift:    "
                f"x1={geom.profile_shift_pinion:.4f}  "
                f"x2={geom.profile_shift_wheel:.4f}"
            )

        lines.append("")

    # ── Spring section ──
    if sol.spring is not None:
        sp = sol.spring
        lines.append("\u2500\u2500 Spring " + "\u2500" * 44)
        lines.append(f"  Max torque:       {sp.max_torque_nm:.3f} Nm")
        lines.append(f"  Max angle:        {sp.max_angle_deg:.2f}\u00b0")
        lines.append(f"  Outer diameter:   {sp.outer_diameter_mm:.2f} mm")
        lines.append(f"  Inner diameter:   {sp.inner_diameter_mm:.2f} mm")
        lines.append(f"  Thickness:        {sp.thickness_mm:.2f} mm")
        lines.append(f"  Spring constant:  {sp.spring_constant_nm_per_rad:.4f} Nm/rad")
        lines.append(f"  Max shear strain: {sp.max_shear_strain:.4f}")
        lines.append(f"  Rubber weight:    {sp.rubber_weight_kg * 1000:.2f} g")
        lines.append(f"  Material:         {sp.material}")
        lines.append(f"  Safety factor:    {sp.safety_factor:.2f}")
        lines.append("")

    # ── Summary ──
    lines.append(f"Overall efficiency: {sol.total_efficiency * 100:.2f}%")

    return "\n".join(lines)


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
    click.echo(format_solution(sol, number))


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------


@main.command("generate")
@click.argument("results_file", type=click.Path(exists=True))
@click.argument("number", type=int)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.option(
    "--onshape",
    default=None,
    help="Onshape Variable Studio URL to push gear parameters to.",
)
@click.option(
    "--spring",
    type=float,
    default=None,
    help="Generate spring dimensions for given max angle (degrees).",
)
def generate_cmd(
    results_file: str,
    number: int,
    verbose: bool,
    onshape: str | None,
    spring: float | None,
):
    """Generate optimized tooth geometry and production files for a solution."""
    from spurGearGenerator.generate import generate
    from spurGearGenerator.onshape import OnshapeError, validate_onshape_env

    # Validate Onshape env vars early (before running optimization)
    if onshape:
        try:
            validate_onshape_env()
        except OnshapeError as e:
            raise click.ClickException(str(e))

    results_path = Path(results_file)
    out_dir = generate(
        results_path,
        number,
        verbose=verbose,
        onshape_url=onshape,
        spring_angle=spring,
    )
    click.echo(f"Generated files in {out_dir}")
