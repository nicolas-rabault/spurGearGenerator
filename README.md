# Spur Gear Generator

A Python CLI tool that finds optimal spur gear gearbox solutions from JSON configuration files. Supports multi-stage gear trains with Lewis bending stress verification, weight optimisation, and efficiency estimation.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

A short alias `sgg` is available alongside the full `spurGearGenerator` command.

```bash
# Single-stage search
sgg solve config/example_config.json

# Multi-stage search (up to 2 stages)
sgg solve config/example_config.json -s 2

# Results are saved automatically to <config_name>_results.json
# Override with -o:
sgg solve config/example_config.json -s 2 -o results.json

# Show full details of solution #1
sgg show config/example_config_results.json 1

# Generate optimized geometry and production spec for solution #1
sgg generate config/example_config_results.json 1 -v

# Generate and push parameters to an Onshape Variable Studio
sgg generate config/example_config_results.json 1 --onshape <variable_studio_url>
```

### Generate output

The `generate` command writes two files to `config/solutions/<config>/<number>/`:

- **solution.txt** — full technical summary (diameters, stresses, efficiency)
- **prod.txt** — production specification organised by physical part (shaft), ready to send to a gear manufacturer. Includes material trade names, heat treatment, ISO 1328 quality grades, tolerances, and mesh specifications.

### Configuration

Create a JSON file describing your requirements:

```json
{
  "target_ratio": 5.0,
  "reduction_margin": 3.0,
  "input_torque": 0.5,
  "max_teeth_per_gear": 100
}
```

| Field                | Description                               | Default    |
| -------------------- | ----------------------------------------- | ---------- |
| `target_ratio`       | Desired total gear reduction ratio        | (required) |
| `reduction_margin`   | Acceptable margin around target ratio (%) | 5.0        |
| `input_torque`       | Peak input torque from the motor (Nm)     | (required) |
| `max_teeth_per_gear` | Maximum teeth on any single gear          | 150        |

### What the solver does

1. Enumerates all valid gear-tooth combinations matching the target ratio (within margin)
2. For multi-stage, finds all stage-ratio decompositions using brute force
3. Assigns materials and modules optimally using dynamic programming over shaft materials
4. Verifies Lewis bending stress on every gear
5. Optimises face width analytically (minimum that passes stress, capped at 12x module)
6. Computes total weight (solid-cylinder approximation) and mesh efficiency
7. Returns top 10 by weight + top 10 by efficiency

### Compound gear constraint

Gears sharing a shaft (wheel of stage N + pinion of stage N+1) must use the same material. This is enforced by the DP solver.

### Available materials

Steel (mild, alloy, hardened), Brass, Bronze, Aluminum, Nylon, POM/Delrin

### Onshape Integration

The `generate` command supports pushing gear parameters directly to an Onshape Variable Studio via `--onshape <url>`.

**Setup:** Create API keys at https://dev-portal.onshape.com/keys and set environment variables:

```bash
export ONSHAPE_API=https://cad.onshape.com
export ONSHAPE_ACCESS_KEY=<your-access-key>
export ONSHAPE_SECRET_KEY=<your-secret-key>
```

**Usage:** Provide the URL of a Variable Studio tab (not a Part Studio or Assembly):

```bash
sgg generate config/example_config_results.json 1 \
    --onshape "https://cad.onshape.com/documents/<did>/w/<wid>/e/<eid>"
```

This creates the following variables per stage (where `N` is the stage number):

| Variable | Description | Type |
|----------|-------------|------|
| `sN_depth` | Face width (mm) | Length |
| `sN_m` | Module (mm) | Length |
| `sN_p` | Pressure angle (deg) | Angle |
| `sN_backlash` | Backlash (mm) | Length |
| `sNp_z` | Pinion tooth count | Integer |
| `sNw_z` | Wheel tooth count | Integer |
| `sNp_dedendum` | Pinion dedendum coefficient | Real |
| `sNw_dedendum` | Wheel dedendum coefficient | Real |
| `sNp_addendum` | Pinion addendum coefficient | Real |
| `sNw_addendum` | Wheel addendum coefficient | Real |

All existing variables in the Variable Studio are replaced when pushing.

### Standard modules

0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0 mm

## Development

```bash
pip install -e ".[dev]"
pytest
```
