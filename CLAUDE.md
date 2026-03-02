# Spur Gear Generator

## Project Overview

A Python CLI tool (installable via `pip install -e .`) that finds optimal spur gear gearbox solutions from JSON configuration files. Supports multi-stage gear trains with stress verification, weight optimisation, and efficiency estimation.

**Commands** (alias `sgg`):
- `sgg solve <config_file> [-s N] [-o path.json] [-v]` — find optimal gearbox solutions
- `sgg show <results_file> <number>` — display full details of a solution

## Directory Tree

```
spurGearGenerator/
├── src/spurGearGenerator/
│   ├── __init__.py          # Package version
│   ├── cli.py               # Click CLI (solve + show subcommands)
│   ├── models.py            # Pydantic config + result models
│   ├── solver.py            # Multi-stage brute-force solver with DP
│   ├── gear_math.py         # Gear geometry, Lewis stress, efficiency, weight
│   └── materials.py         # Hardcoded material database (8 materials)
├── config/
│   └── example_config.json
├── tests/
│   ├── test_gear_math.py    # 17 tests - pure math functions
│   ├── test_materials.py    # 6 tests - material database
│   ├── test_models.py       # 7 tests - Pydantic validation
│   ├── test_solver.py       # 14 tests - solver correctness
│   ├── test_cli.py          # 8 tests - CLI integration
│   └── fixtures/sample_configs/
├── pyproject.toml
├── README.md
├── .gitignore
└── CLAUDE.md
```

## Architecture

### Solver algorithm (solver.py)
1. **Phase 1**: Build unique-ratio index from all (z1, z2) tooth pairs
2. **Phase 2**: Recursive ratio combination search with binary search + non-decreasing constraint to prune permutations
3. **Phase 3**: For each ratio combo, DP over shaft materials (enforces compound gear constraint), finds best module per stage analytically
4. **Phase 4**: Rank top-10 by weight + top-10 by efficiency

### Key design decisions
- Compound gear constraint enforced by DP over shafts (not per-gear materials)
- Face width computed analytically from Lewis stress (no inner loop)
- Module choice is independent across stages (no cross-stage module combinatorics)
- Stage-level caching avoids recomputing shared (ratio, torque, material) combos

### Configuration (JSON)
```json
{
  "target_ratio": 5.0,
  "reduction_margin": 3.0,
  "input_torque": 0.5,
  "max_teeth_per_gear": 100
}
```

## Dependencies
- **click** (>=8.0.0): CLI framework
- **pydantic** (>=2.0.0): Data validation
- **tabulate** (>=0.9.0): Terminal table output

## Performance notes
- Single-stage: instant (< 1 second)
- Two-stage: minutes depending on max_teeth and margin (brute force by design)
- Three-stage: may take significant time with large max_teeth

## Running
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 52 tests
sgg solve config/example_config.json -s 1 -v
sgg show config/example_config_results.json 1
```
