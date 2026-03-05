# Spur Gear Generator

## Project Overview

A Python CLI tool (installable via `pip install -e .`) that finds optimal spur gear gearbox solutions from JSON configuration files. Supports multi-stage gear trains with stress verification, weight optimisation, and efficiency estimation. Can generate optimised tooth geometry with detailed analysis.

**Commands** (alias `sgg`):
- `sgg solve <config_file> [-s N] [-o path.json] [-v]` — find optimal gearbox solutions
- `sgg show <results_file> <number>` — display full details of a solution
- `sgg generate <results_file> <number> [-v]` — optimise tooth geometry, write solution.txt + prod.txt

## Directory Tree

```
spurGearGenerator/
├── src/spurGearGenerator/
│   ├── __init__.py          # Package version
│   ├── cli.py               # Click CLI (solve + show + generate subcommands)
│   ├── models.py            # Pydantic config + result models (GearResult, StageGeometry, etc.)
│   ├── solver.py            # Multi-stage brute-force solver with DP
│   ├── gear_math.py         # Gear geometry, Lewis stress, efficiency, weight
│   ├── materials.py         # Hardcoded material database (8 materials)
│   ├── tooth_profile.py     # Involute math, profile shift optimisation
│   ├── generate.py          # Orchestration: optimise → save → write solution.txt + prod.txt
│   └── production.py        # Production spec generator (manufacturing, tolerances, materials)
├── config/
│   └── example_config.json
├── tests/
│   ├── test_gear_math.py    # 17 tests - pure math functions
│   ├── test_materials.py    # 6 tests - material database
│   ├── test_models.py       # 7 tests - Pydantic validation
│   ├── test_solver.py       # 14 tests - solver correctness
│   ├── test_cli.py          # 8 tests - CLI integration
│   ├── test_tooth_profile.py # 24 tests - involute math
│   ├── test_generate.py     # 7 tests - orchestration
│   ├── test_production.py   # 54 tests - production spec generator
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

### Generate pipeline (generate.py)
1. Load solution from results JSON
2. Optimise tooth geometry per stage (profile shift, contact ratio, Hertz stress, etc.)
3. Save optimised parameters back to results JSON
4. Write solution.txt (technical summary) and prod.txt (production spec by part)

### Key design decisions
- Compound gear constraint enforced by DP over shafts (not per-gear materials)
- Face width computed analytically from Lewis stress (no inner loop)
- Module choice is independent across stages (no cross-stage module combinatorics)
- Stage-level caching avoids recomputing shared (ratio, torque, material) combos
- Profile shift optimised via bisection to balance specific sliding
- Axis collision constraint filters 3+ stage solutions where adjacent gears would collide

### Configuration (JSON)
```json
{
  "target_ratio": 5.0,
  "reduction_margin": 3.0,
  "input_torque": 0.5,
  "max_teeth_per_gear": 100,
  "axis_margin": 1.0
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
pytest                    # 165 tests
sgg solve config/example_config.json -s 2 -v
sgg show config/example_config_results.json 1
sgg generate config/example_config_results.json 1 -v
```
