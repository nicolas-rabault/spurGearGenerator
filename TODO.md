# Spur Gear Generator - Improvement Roadmap

Feedback from gear engineering experts. Items sorted by impact vs workload.

## Legend

- **Impact**: how much it improves result accuracy or usefulness
- **Workload**: estimated effort (S = days, M = 1-2 weeks, L = 3-4 weeks, XL = months)
- Status: `[ ]` todo, `[~]` in progress, `[x]` done

---

## High Impact / Low Workload

- [ ] **Fix face width cap: use b/d ratio instead of b/m** (S)
  Currently capped at `b_max = 12 * module` in `gear_math.py`. Expert points out this is wrong: a small-diameter gear at 12*m twists far more than a large-diameter gear at the same b/m. The correct limit is face width vs pitch diameter (b/d). A typical limit is b/d <= 1.0-1.5. This directly affects which solutions the solver considers valid.

- [ ] **Add allowable contact stress to materials** (S)
  Hertz stress is computed but never checked against a limit. Add `allowable_contact_stress_mpa` to each material in `materials.py` and fail solutions that exceed it. Currently the solver silently accepts any Hertz value.

- [ ] **Per-material Poisson's ratio** (S)
  Hardcoded to 0.3 in `tooth_profile.py`. Nylon is ~0.39, POM ~0.35. Affects Hertz stress calculation accuracy for plastic gears.

- [ ] **Configurable safety factor** (S)
  Currently checks `stress < allowable` with no margin. Add a configurable safety factor (default 1.5) to both bending and contact stress checks.

- [ ] **Plastic thermal derating (VDI 2736)** (M)
  Young's modulus and allowable stress for nylon/POM drop significantly with temperature and moisture. Add temperature-dependent derating per VDI 2736 for polymer gears.

## High Impact / Medium Workload

- [ ] **Replace Lewis with ISO 6336 in the solver** (M)
  Current bending stress is pure Lewis (no dynamic factor Kv, no face load factor KH-beta, no application factor KA). Expert confirms ISO 6336 equations run fast enough for the brute-force loop (tested in Matlab on thousands of candidates in seconds). This should *replace* Lewis in the solver, not just be a post-validation step.

- [ ] **Tooth root stress concentration factor (YS/Y_delta)** (M)
  Lewis Y alone underestimates root stress for low tooth counts. The root fillet radius is already computed -- use it to derive a stress correction factor per ISO 6336-3.

- [ ] **Non-standard pressure angles** (M)
  Currently locked to 20-degree reference. Opening to 22.5-25 degrees gives ~15% more bending strength and different center distance options. Requires updating the Lewis Y-factor table and Hertz formulas. Reference: *Direct Gear Design* by A. Kapelevich.

- [ ] **Hertz stress at worst-case point** (S-M)
  Currently evaluated at the pitch point only. The worst case can occur at the inner single-pair contact point (ISPCP). Evaluate along the full line of action.

## Medium Impact / Medium Workload

- [ ] **Root shape optimization** (M)
  Non-standard root fillet (full-radius or elliptical) can improve bending strength 10-25%. The fillet radius is already modeled -- allow it to be optimized beyond the standard trochoid.

- [ ] **Load-dependent tip relief** (M)
  Currently `Ca = 0.02 * m` (fixed ratio). Should be computed from tooth deflection under load for proper mesh entry/exit behavior.

- [ ] **Widthwise crowning** (M)
  Longitudinal crowning compensates for misalignment and prevents edge loading. Add crowning parameters to the geometry output. Critical for wider gears where torsional twist concentrates face load.

- [ ] **Dynamic factor (Kv)** (S-M)
  No dynamic load factor for speed effects. Add at least the ISO 6336-1 Kv approximation based on pitch-line velocity and gear accuracy grade.

## Medium Impact / High Workload

- [ ] **FEA validation step (sgg validate)** (L)
  Use SfePy + Gmsh to run 2D plane-strain FEA on the selected solution. Validate root bending stress and contact stress against the analytical results. Requires generating discrete involute profile points (~50-100 lines) then building the FEA pipeline. Not for the brute-force search -- only for the final selected solution. See notes below.

- [ ] **Asymmetric tooth profiles** (L)
  Different pressure angles on drive/coast flanks. Higher strength for unidirectional loads. Reference: Kapelevich. Less applicable when torque is bidirectional (legged robots), but worth investigating for specific use cases.

- [ ] **Logarithmic tip/root relief profiles** (M-L)
  Optimizes usable face width while preventing edge contacts. Relevant when gears are CNC ground. Reference: expert feedback on manufacturing with CNC-controlled grinders.

## Lower Priority / Nice to Have

- [ ] **Scuffing/scoring analysis** (M)
  Flash temperature or integral temperature method per ISO/TR 13989.

- [ ] **Wear/pitting life estimation** (L)
  S-N curve data per material, pitting resistance limits, fatigue life factors (ZN, YN from ISO 6336).

- [ ] **Non-solid gear weight model** (S)
  Current weight is a solid cylinder. Model gears with hub, web, and rim for more accurate weight estimation.

- [ ] **Tolerance-dependent backlash** (S)
  Currently `j_t = 0.04 * m` (fixed). Compute from ISO tolerance class and thermal expansion.

---

## Notes

### On manufacturing and non-standard profiles

Expert feedback: non-standard tooth shapes (pressure angles, root profiles, asymmetric teeth) can be manufactured at the same cost as standard profiles when using CNC-controlled grinding or injection moulding -- the tool/mould defines the shape, so any arbitrary profile is equally feasible. This removes the main objection to non-standard geometries.

### On FEA validation

Best library choice: **SfePy + Gmsh** (both pip-installable). Pipeline:
1. Generate involute + trochoid profile points from existing `tooth_profile.py` math
2. Create 2D mesh with Gmsh Python API (refine at root fillet and contact zone)
3. Solve with SfePy (plane strain, penalty contact for Hertz validation)
4. Compare FEA principal stress at root vs Lewis, and contact pressure vs Hertz

This would be a post-optimization validation step, not part of the brute-force search (too slow).

### On face width limit and torsional twist (expert warning)

The solver caps face width at 12x module, but this is the wrong metric. A gear with a small pitch diameter and b = 12*m will twist significantly more than a gear with a large pitch diameter at the same b/m. The correct limit is **b/d** (face width to pitch diameter ratio), because twist-induced misalignment depends on the gear's diameter, not its module alone. Additionally, the ISO standard's face load factor KH-beta may be too optimistic for wider gears. FEA with misalignment modeling is the proper way to evaluate this. Adding KH-beta from ISO 6336-1 is a good intermediate step.

### References

- **Direct Gear Design** -- A. Kapelevich (non-standard profiles, asymmetric gears)
- **ISO 6336** -- Calculation of load capacity of spur and helical gears (parts 1-5)
- **ISO 1328** -- Cylindrical gears, ISO system of flank tolerance classification
- **VDI 2736** -- Thermoplastic gear wheels (polymer gear design)
- **ISO/TR 13989** -- Gears -- Calculation of scuffing load capacity
- **Maag Gear Handbook** -- Profile shift, specific sliding theory
