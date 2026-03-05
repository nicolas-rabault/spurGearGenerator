"""Multi-stage spur gear gearbox solver.

Fused tree search over ratio combinations with integrated DP-based
material assignment, analytical module selection, and branch-and-bound
pruning.

Key optimisations:
- Precomputed per-(z1, z2, material-pair) coefficients avoid repeated
  Lewis Y lookups, stress calculations, and weight formulas.
- Analytical minimum-module selection replaces the 17-module brute-force
  loop (proven that smallest feasible module minimises weight).
- Efficiency is module-independent — best (z1, z2) pair is picked
  directly, with a single feasibility check.
- Tree search shares DP work across combos with common prefixes
  (stage 0 evaluated once per unique r0, not once per combo).
- Branch-and-bound pruning skips subtrees that cannot beat the best
  known weight.
- Parallelised at the stage-0 level across CPU cores.
"""

from __future__ import annotations

import heapq
import math
import os
import time
from bisect import bisect_left, bisect_right
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from tqdm import tqdm

from spurGearGenerator.gear_math import (
    MIN_TEETH,
    STANDARD_MODULES,
    addendum_diameter,
    gear_weight,
    lewis_bending_stress,
    lewis_form_factor,
    mesh_efficiency,
    pitch_diameter,
    tangential_force,
)
from spurGearGenerator.materials import GearMaterial, get_all_materials, get_material
from spurGearGenerator.models import (
    GearboxSolution,
    GearConfig,
    GearResult,
    SolveStats,
    StageResult,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum (z1, z2) pairs kept per unique ratio (5 smallest + 5 largest z1).
_MAX_PAIRS_PER_RATIO = 5

# Maximum Pareto frontier size per material in the DP.
_MAX_PARETO_PER_MAT = 5

# Minimum work items before spawning a process pool.
_PARALLEL_THRESHOLD = 50

# Number of top solutions to track per objective during search.
_TOP_K = 20

# Pruning margin: prune weight branches that exceed best * (1 + margin).
_PRUNE_MARGIN = 0.05


# ---------------------------------------------------------------------------
# Phase 1: Build unique-ratio index  (unchanged)
# ---------------------------------------------------------------------------


def _build_ratio_data(
    max_teeth: int,
) -> tuple[list[float], dict[float, list[tuple[int, int]]]]:
    """Build a sorted list of unique ratios and ratio -> [(z1, z2)] mapping."""
    ratio_map: dict[float, list[tuple[int, int]]] = {}
    for z1 in range(MIN_TEETH, max_teeth + 1):
        for z2 in range(z1, max_teeth + 1):
            r = z2 / z1
            ratio_map.setdefault(r, []).append((z1, z2))

    k = _MAX_PAIRS_PER_RATIO
    for r in ratio_map:
        pairs = ratio_map[r]
        if len(pairs) > 2 * k:
            head = pairs[:k]
            tail = pairs[-k:]
            seen = set()
            merged: list[tuple[int, int]] = []
            for p in head + tail:
                if p not in seen:
                    seen.add(p)
                    merged.append(p)
            ratio_map[r] = merged

    unique_ratios = sorted(ratio_map)
    return unique_ratios, ratio_map


# ---------------------------------------------------------------------------
# Precomputation infrastructure
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PairCoeffs:
    """Precomputed coefficients for one (z1, z2, mat_p, mat_w) combination.

    Derived once from gear_math formulas:
      Ft = 2000*T / (m*z1)
      b  = max(k_b * T / m^2, m)
      feasibility: m >= (c_feas * T)^(1/3)
      weight: k_w * m^2 * b
      eta: module-independent mesh efficiency
    """

    z1: int
    z2: int
    c_feas: float  # m_min = (c_feas * T)^(1/3)
    k_b: float  # face_width = max(k_b * T / m^2, m)
    k_w: float  # total_weight = k_w * m^2 * face_width
    eta: float  # mesh efficiency (precomputed)


@dataclass
class _Precomputed:
    """All precomputed data for the tree search."""

    unique_ratios: list[float]
    std_modules: tuple[float, ...]
    materials: tuple[GearMaterial, ...]
    n_mats: int
    # ratio -> (mat_p_idx, mat_w_idx) -> list[_PairCoeffs] sorted by z1 asc
    pair_data: dict[float, dict[tuple[int, int], list[_PairCoeffs]]]
    # Lower bound on weight per unit torque (across all ratios/materials)
    global_min_weight_per_torque: float
    # Minimum clearance between adjacent-stage axes (mm)
    axis_margin: float
    # Minimum root diameter for the last output wheel (mm); 0.0 = no constraint
    min_output_root_diameter: float


def _precompute(
    unique_ratios: list[float],
    ratio_map: dict[float, list[tuple[int, int]]],
    materials: tuple[GearMaterial, ...],
    max_teeth: int,
    axis_margin: float = 0.0,
    min_output_root_diameter: float = 0.0,
    std_modules: tuple[float, ...] = STANDARD_MODULES,
) -> _Precomputed:
    """Build all precomputed coefficients.  Called once per solve()."""
    # Precompute Lewis Y factors for all tooth counts
    y_factors = [0.0] * (max_teeth + 3)  # +3 for z2+2 in weight
    for z in range(MIN_TEETH, max_teeth + 1):
        y_factors[z] = lewis_form_factor(z)

    n_mats = len(materials)
    pair_data: dict[float, dict[tuple[int, int], list[_PairCoeffs]]] = {}
    global_min_w_per_t = float("inf")

    for ratio in unique_ratios:
        tooth_pairs = ratio_map[ratio]
        mat_pair_dict: dict[tuple[int, int], list[_PairCoeffs]] = {}

        for mp_idx in range(n_mats):
            mat_p = materials[mp_idx]
            sigma_p = mat_p.allowable_bending_stress
            rho_p = mat_p.density
            for mw_idx in range(n_mats):
                mat_w = materials[mw_idx]
                sigma_w = mat_w.allowable_bending_stress
                rho_w = mat_w.density
                mu_eff = (
                    mat_p.friction_coefficient + mat_w.friction_coefficient
                ) / 2.0

                pairs: list[_PairCoeffs] = []
                for z1, z2 in tooth_pairs:
                    y1 = y_factors[z1]
                    y2 = y_factors[z2]
                    if y1 <= 0 or y2 <= 0:
                        continue

                    # Face-width coefficients: b = k_b * T / m^2
                    k_b_p = 2000.0 / (z1 * sigma_p * y1)
                    k_b_w = 2000.0 / (z1 * sigma_w * y2)
                    k_b = max(k_b_p, k_b_w)

                    # Feasibility: m >= (c_feas * T)^(1/3)
                    c_feas = k_b / 12.0

                    # Weight: total_weight = k_w * m^2 * b
                    k_w = (rho_p * (z1 + 2) ** 2 + rho_w * (z2 + 2) ** 2) * (
                        math.pi / 4e9
                    )

                    # Efficiency (module-independent)
                    eta = 1.0 - math.pi * mu_eff * (1.0 / z1 + 1.0 / z2)

                    pairs.append(_PairCoeffs(z1, z2, c_feas, k_b, k_w, eta))

                    # Track global min weight per unit torque
                    # (weight = k_w * k_b * T when stress-limited)
                    w_per_t = k_w * k_b
                    if w_per_t < global_min_w_per_t:
                        global_min_w_per_t = w_per_t

                if pairs:
                    pairs.sort(key=lambda p: p.z1)
                    mat_pair_dict[(mp_idx, mw_idx)] = pairs

        pair_data[ratio] = mat_pair_dict

    return _Precomputed(
        unique_ratios=unique_ratios,
        std_modules=std_modules,
        materials=materials,
        n_mats=n_mats,
        pair_data=pair_data,
        global_min_weight_per_torque=global_min_w_per_t,
        axis_margin=axis_margin,
        min_output_root_diameter=min_output_root_diameter,
    )


# ---------------------------------------------------------------------------
# Fast stage evaluation (replaces _find_best_for_stage)
# ---------------------------------------------------------------------------


def _fast_find_best_weight(
    ratio: float,
    torque: float,
    mat_p_idx: int,
    mat_w_idx: int,
    min_module: float,
    precomp: _Precomputed,
    min_output_root_diam: float = 0.0,
) -> tuple[float, float, int, int, float, float] | None:
    """Find lightest feasible stage config: (module, face_width, z1, z2, weight, eta).

    Uses analytical minimum-module selection (proven optimal for weight).
    Returns None if nothing is feasible.
    """
    mat_pairs = precomp.pair_data.get(ratio)
    if mat_pairs is None:
        return None
    pair_list = mat_pairs.get((mat_p_idx, mat_w_idx))
    if pair_list is None:
        return None

    std_mods = precomp.std_modules
    n_mods = len(std_mods)
    best_weight = float("inf")
    best_result = None

    for pc in pair_list:
        # Analytical minimum feasible module
        m_required = max((pc.c_feas * torque) ** (1.0 / 3.0), min_module)
        # Minimum module for output root diameter constraint: m >= d_root_min / (z2 - 2.5)
        if min_output_root_diam > 0:
            m_required = max(m_required, min_output_root_diam / (pc.z2 - 2.5))

        idx = bisect_left(std_mods, m_required)
        if idx >= n_mods:
            continue
        m = std_mods[idx]

        # Face width at chosen module
        b = pc.k_b * torque / (m * m)
        b = max(b, m)  # practical minimum = 1 * module

        # Safety check (handles float rounding near boundary)
        if b > 12.0 * m:
            idx += 1
            if idx >= n_mods:
                continue
            m = std_mods[idx]
            b = pc.k_b * torque / (m * m)
            b = max(b, m)
            if b > 12.0 * m:
                continue

        w = pc.k_w * m * m * b
        if w < best_weight:
            best_weight = w
            best_result = (m, b, pc.z1, pc.z2, w, pc.eta)

    return best_result


def _fast_find_best_efficiency(
    ratio: float,
    torque: float,
    mat_p_idx: int,
    mat_w_idx: int,
    min_module: float,
    precomp: _Precomputed,
    min_output_root_diam: float = 0.0,
) -> tuple[float, float, int, int, float, float] | None:
    """Find highest-efficiency feasible stage config.

    Efficiency is module-independent (eta = 1 - pi*mu*(1/z1 + 1/z2)),
    and increases with z1 for a given ratio.  Iterates pairs largest-z1
    first, returning the first with a valid module.
    """
    mat_pairs = precomp.pair_data.get(ratio)
    if mat_pairs is None:
        return None
    pair_list = mat_pairs.get((mat_p_idx, mat_w_idx))
    if pair_list is None:
        return None

    std_mods = precomp.std_modules
    n_mods = len(std_mods)

    # Iterate largest z1 first (highest efficiency)
    for pc in reversed(pair_list):
        m_required = max((pc.c_feas * torque) ** (1.0 / 3.0), min_module)
        # Minimum module for output root diameter constraint: m >= d_root_min / (z2 - 2.5)
        if min_output_root_diam > 0:
            m_required = max(m_required, min_output_root_diam / (pc.z2 - 2.5))

        idx = bisect_left(std_mods, m_required)
        if idx >= n_mods:
            continue
        m = std_mods[idx]

        b = pc.k_b * torque / (m * m)
        b = max(b, m)

        if b > 12.0 * m:
            idx += 1
            if idx >= n_mods:
                continue
            m = std_mods[idx]
            b = pc.k_b * torque / (m * m)
            b = max(b, m)
            if b > 12.0 * m:
                continue

        w = pc.k_w * m * m * b
        return (m, b, pc.z1, pc.z2, w, pc.eta)

    return None


# ---------------------------------------------------------------------------
# Lightweight DP state for tree search
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _LightDPState:
    """Compact DP state carried through the tree search."""

    total_weight: float
    total_efficiency: float
    last_module: float  # module at most recent stage (0.0 = none yet)
    # Compact path for reconstruction:
    # tuple of (ratio, mat_p_idx, mat_w_idx, module, z1, z2, face_width)
    path: tuple


@dataclass
class _TreeResults:
    """Top-K results collected during tree search."""

    # Max-heap (negated weight): [(-weight, counter, efficiency, path), ...]
    top_weight: list
    # Min-heap: [(efficiency, counter, weight, path), ...]
    top_eff: list
    best_weight: float  # best (smallest) weight seen — used for pruning
    counter: int  # tie-breaker for heap comparisons
    evaluations: int = 0  # total feasible configurations scored
    branches_pruned: int = 0  # B&B pruned subtrees


def _update_results(
    results: _TreeResults,
    total_weight: float,
    total_eff: float,
    path: tuple,
) -> None:
    """Insert a complete solution into the top-K heaps."""
    results.evaluations += 1
    c = results.counter
    results.counter += 1

    # Weight top-K (want smallest weights -> max-heap with negation)
    if len(results.top_weight) < _TOP_K:
        heapq.heappush(results.top_weight, (-total_weight, c, total_eff, path))
        if total_weight < results.best_weight:
            results.best_weight = total_weight
    elif total_weight < -results.top_weight[0][0]:
        heapq.heapreplace(results.top_weight, (-total_weight, c, total_eff, path))
        if total_weight < results.best_weight:
            results.best_weight = total_weight

    # Efficiency top-K (want largest -> min-heap)
    if len(results.top_eff) < _TOP_K:
        heapq.heappush(results.top_eff, (total_eff, c, total_weight, path))
    elif total_eff > results.top_eff[0][0]:
        heapq.heapreplace(results.top_eff, (total_eff, c, total_weight, path))


def _merge_results(main: _TreeResults, worker: _TreeResults) -> None:
    """Merge a worker's top-K results into the main results."""
    main.evaluations += worker.evaluations
    main.branches_pruned += worker.branches_pruned
    for neg_w, _, eff, path in worker.top_weight:
        _update_results(main, -neg_w, eff, path)
    for eff, _, w, path in worker.top_eff:
        _update_results(main, w, eff, path)


# ---------------------------------------------------------------------------
# Pareto insert for lightweight DP
# ---------------------------------------------------------------------------


def _pareto_insert_light(
    frontier: list[_LightDPState],
    candidate: _LightDPState,
    objective: str,
) -> None:
    """Insert *candidate* into Pareto frontier, removing dominated states.

    Dominance is on (objective_value, last_module).  A state dominates
    another if it is at least as good on both dimensions with at least
    one strict improvement.
    """
    # Check if candidate is dominated
    for s in frontier:
        if objective == "weight":
            obj_dom = s.total_weight <= candidate.total_weight
            obj_strict = s.total_weight < candidate.total_weight
        else:
            obj_dom = s.total_efficiency >= candidate.total_efficiency
            obj_strict = s.total_efficiency > candidate.total_efficiency
        mod_dom = s.last_module <= candidate.last_module
        mod_strict = s.last_module < candidate.last_module
        if obj_dom and mod_dom and (obj_strict or mod_strict):
            return  # dominated

    # Remove states dominated by candidate
    kept: list[_LightDPState] = []
    for s in frontier:
        if objective == "weight":
            obj_dom = candidate.total_weight <= s.total_weight
            obj_strict = candidate.total_weight < s.total_weight
        else:
            obj_dom = candidate.total_efficiency >= s.total_efficiency
            obj_strict = candidate.total_efficiency > s.total_efficiency
        mod_dom = candidate.last_module <= s.last_module
        mod_strict = candidate.last_module < s.last_module
        if obj_dom and mod_dom and (obj_strict or mod_strict):
            continue  # dominated by candidate
        kept.append(s)
    kept.append(candidate)

    # Cap frontier size
    if len(kept) > _MAX_PARETO_PER_MAT:
        if objective == "weight":
            kept.sort(key=lambda s: s.total_weight)
        else:
            kept.sort(key=lambda s: -s.total_efficiency)
        min_mod_state = min(kept, key=lambda s: s.last_module)
        kept = kept[:_MAX_PARETO_PER_MAT]
        if min_mod_state not in kept:
            kept[-1] = min_mod_state

    frontier[:] = kept


# ---------------------------------------------------------------------------
# Axis collision constraint
# ---------------------------------------------------------------------------


def _check_axis_constraint(path: tuple, axis_margin: float) -> bool:
    """Check that the most recently added stage doesn't cause axis collision.

    For stage N (0-indexed), verifies:
      center_dist(N-1) > (tip_diam_wheel(N-2) + tip_diam_pinion(N)) / 2 + axis_margin
    Only applies when the path has >= 3 stages.
    """
    n = len(path)
    if n < 3:
        return True
    # path entries: (ratio, mat_p_idx, mat_w_idx, module, z1, z2, face_width)
    _, _, _, m_prev, _, z2_prev, _ = path[-3]  # stage N-2
    _, _, _, m_mid, z1_mid, z2_mid, _ = path[-2]  # stage N-1
    _, _, _, m_next, z1_next, _, _ = path[-1]  # stage N
    center_dist = m_mid * (z1_mid + z2_mid) / 2.0
    tip_wheel_prev = m_prev * (z2_prev + 2) / 2.0
    tip_pinion_next = m_next * (z1_next + 2) / 2.0
    return center_dist > tip_wheel_prev + tip_pinion_next + axis_margin


# ---------------------------------------------------------------------------
# DP extension helper
# ---------------------------------------------------------------------------


def _extend_dp(
    ratio: float,
    torque: float,
    dp: dict[int, list[_LightDPState]],
    objective: str,
    precomp: _Precomputed,
) -> dict[int, list[_LightDPState]]:
    """Extend DP frontiers by one stage at the given ratio.

    Returns new DP frontiers keyed by next-shaft material index.
    """
    if not dp:
        return {}

    find_best = (
        _fast_find_best_weight if objective == "weight" else _fast_find_best_efficiency
    )
    n_mats = precomp.n_mats
    dp_next: dict[int, list[_LightDPState]] = {}

    for mat_idx, frontier in dp.items():
        for state in frontier:
            for next_mat in range(n_mats):
                result = find_best(
                    ratio, torque, mat_idx, next_mat, state.last_module, precomp
                )
                if result is None:
                    continue
                m, b, z1, z2, w, eta = result

                new_path = state.path + ((ratio, mat_idx, next_mat, m, z1, z2, b),)
                if not _check_axis_constraint(new_path, precomp.axis_margin):
                    continue

                candidate = _LightDPState(
                    total_weight=state.total_weight + w,
                    total_efficiency=state.total_efficiency * eta,
                    last_module=m,
                    path=new_path,
                )

                if next_mat not in dp_next:
                    dp_next[next_mat] = []
                _pareto_insert_light(dp_next[next_mat], candidate, objective)

    return dp_next


# ---------------------------------------------------------------------------
# Lower bound for branch-and-bound pruning
# ---------------------------------------------------------------------------


def _lower_bound_remaining_weight(
    n_remaining: int,
    torque: float,
    sub_r_low: float,
    precomp: _Precomputed,
) -> float:
    """Lower bound on total weight of *n_remaining* more stages.

    Uses the global minimum weight-per-unit-torque and a geometric-mean
    estimate for torque growth across remaining stages.
    """
    if n_remaining <= 0:
        return 0.0
    min_w = precomp.global_min_weight_per_torque
    if n_remaining == 1:
        return min_w * torque
    # Geometric mean ratio for remaining stages
    g = max(sub_r_low ** (1.0 / n_remaining), 1.0)
    if g <= 1.0 + 1e-12:
        return n_remaining * min_w * torque
    # Sum of geometric series: T * (1 + g + g^2 + ... + g^(n-1))
    geo_sum = (g**n_remaining - 1.0) / (g - 1.0)
    return min_w * torque * geo_sum


# ---------------------------------------------------------------------------
# Leaf evaluation (last stage of the tree)
# ---------------------------------------------------------------------------


def _evaluate_leaf(
    ratio: float,
    torque: float,
    dp_w: dict[int, list[_LightDPState]],
    dp_e: dict[int, list[_LightDPState]],
    precomp: _Precomputed,
    results: _TreeResults,
) -> None:
    """Evaluate the last stage and update top-K results."""
    n_mats = precomp.n_mats
    min_root = precomp.min_output_root_diameter

    for mat_idx, frontier in dp_w.items():
        for state in frontier:
            for next_mat in range(n_mats):
                result = _fast_find_best_weight(
                    ratio, torque, mat_idx, next_mat, state.last_module, precomp,
                    min_output_root_diam=min_root,
                )
                if result is None:
                    continue
                m, b, z1, z2, w, eta = result
                path = state.path + ((ratio, mat_idx, next_mat, m, z1, z2, b),)
                if not _check_axis_constraint(path, precomp.axis_margin):
                    continue
                _update_results(results, state.total_weight + w, state.total_efficiency * eta, path)

    for mat_idx, frontier in dp_e.items():
        for state in frontier:
            for next_mat in range(n_mats):
                result = _fast_find_best_efficiency(
                    ratio, torque, mat_idx, next_mat, state.last_module, precomp,
                    min_output_root_diam=min_root,
                )
                if result is None:
                    continue
                m, b, z1, z2, w, eta = result
                path = state.path + ((ratio, mat_idx, next_mat, m, z1, z2, b),)
                if not _check_axis_constraint(path, precomp.axis_margin):
                    continue
                _update_results(results, state.total_weight + w, state.total_efficiency * eta, path)


# ---------------------------------------------------------------------------
# Recursive tree search with branch-and-bound
# ---------------------------------------------------------------------------


def _tree_search(
    stage_idx: int,
    n_stages: int,
    r_low: float,
    r_high: float,
    min_ratio: float,
    torque: float,
    dp_w: dict[int, list[_LightDPState]],
    dp_e: dict[int, list[_LightDPState]],
    precomp: _Precomputed,
    results: _TreeResults,
) -> None:
    """Recursive tree search over ratio combinations with integrated DP."""
    n_remaining = n_stages - stage_idx
    unique_ratios = precomp.unique_ratios

    if n_remaining == 1:
        # Last stage: ratio must be in [r_low, r_high] and >= min_ratio
        search_low = max(r_low, min_ratio)
        if search_low > r_high:
            return
        lo = bisect_left(unique_ratios, search_low)
        hi = bisect_right(unique_ratios, r_high)
        for ri in range(lo, hi):
            _evaluate_leaf(unique_ratios[ri], torque, dp_w, dp_e, precomp, results)
        return

    # Multi-stage: enumerate ratio for this stage, extend DP, recurse
    stage_low = min_ratio
    stage_high = r_high  # upper bound on any single stage ratio

    lo = bisect_left(unique_ratios, stage_low)
    hi = bisect_right(unique_ratios, stage_high)

    for ri in range(lo, hi):
        r = unique_ratios[ri]
        sub_r_low = r_low / r
        sub_r_high = r_high / r
        if sub_r_high < 1.0:
            continue
        sub_r_low = max(sub_r_low, 1.0)

        next_torque = torque * r

        # Extend DP for both objectives
        dp_w_next = _extend_dp(r, torque, dp_w, "weight", precomp)
        dp_e_next = _extend_dp(r, torque, dp_e, "efficiency", precomp)

        if not dp_w_next and not dp_e_next:
            continue

        # Branch-and-bound: prune weight branch if it can't beat best known
        if dp_w_next and results.best_weight < float("inf"):
            min_partial = min(
                s.total_weight
                for frontier in dp_w_next.values()
                for s in frontier
            )
            lb = _lower_bound_remaining_weight(
                n_remaining - 1, next_torque, sub_r_low, precomp
            )
            if min_partial + lb > results.best_weight * (1.0 + _PRUNE_MARGIN):
                dp_w_next = {}  # prune weight branch
                results.branches_pruned += 1

        if not dp_w_next and not dp_e_next:
            continue

        _tree_search(
            stage_idx + 1,
            n_stages,
            sub_r_low,
            sub_r_high,
            min_ratio=r,
            torque=next_torque,
            dp_w=dp_w_next,
            dp_e=dp_e_next,
            precomp=precomp,
            results=results,
        )


# ---------------------------------------------------------------------------
# Solution reconstruction from compact path
# ---------------------------------------------------------------------------


def _reconstruct_solution(
    path: tuple,
    input_torque: float,
    precomp: _Precomputed,
) -> GearboxSolution:
    """Rebuild a full GearboxSolution from a compact path tuple."""
    stages: list[StageResult] = []
    torque = input_torque
    total_ratio = 1.0
    total_weight = 0.0
    total_eff = 1.0

    for i, step in enumerate(path):
        ratio, mat_p_idx, mat_w_idx, m, z1, z2, b = step
        mat_p = precomp.materials[mat_p_idx]
        mat_w = precomp.materials[mat_w_idx]

        ft = tangential_force(torque, m, z1)
        sigma_p = lewis_bending_stress(ft, b, m, z1)
        sigma_w = lewis_bending_stress(ft, b, m, z2)
        w1 = gear_weight(m, z1, b, mat_p.density)
        w2 = gear_weight(m, z2, b, mat_w.density)
        mu_eff = (mat_p.friction_coefficient + mat_w.friction_coefficient) / 2.0
        eta = mesh_efficiency(z1, z2, mu_eff)

        total_ratio *= ratio
        total_weight += w1 + w2
        total_eff *= eta

        pinion = GearResult(
            role="pinion",
            teeth=z1,
            module=m,
            material=mat_p.key,
            pitch_diameter_mm=pitch_diameter(m, z1),
            addendum_diameter_mm=addendum_diameter(m, z1),
            face_width_mm=b,
            lewis_stress_mpa=sigma_p,
            allowable_stress_mpa=mat_p.allowable_bending_stress,
            weight_kg=w1,
        )
        wheel = GearResult(
            role="wheel",
            teeth=z2,
            module=m,
            material=mat_w.key,
            pitch_diameter_mm=pitch_diameter(m, z2),
            addendum_diameter_mm=addendum_diameter(m, z2),
            face_width_mm=b,
            lewis_stress_mpa=sigma_w,
            allowable_stress_mpa=mat_w.allowable_bending_stress,
            weight_kg=w2,
        )
        stages.append(
            StageResult(
                stage_number=i + 1,
                pinion=pinion,
                wheel=wheel,
                stage_ratio=ratio,
                mesh_efficiency=eta,
                stage_torque_in_nm=torque,
            )
        )
        torque *= ratio

    return GearboxSolution(
        stages=stages,
        total_ratio=total_ratio,
        ratio_error_pct=0.0,  # filled in by ranking
        total_efficiency=total_eff,
        total_weight_kg=total_weight,
    )


# ---------------------------------------------------------------------------
# Ranking  (unchanged)
# ---------------------------------------------------------------------------


def _select_top_results(
    solutions: list[GearboxSolution],
    target_ratio: float,
) -> list[GearboxSolution]:
    """Keep top-10 by weight and top-10 by efficiency (unique union)."""
    if not solutions:
        return []

    for s in solutions:
        s.ratio_error_pct = (s.total_ratio - target_ratio) / target_ratio * 100.0

    by_weight = sorted(solutions, key=lambda s: s.total_weight_kg)[:10]
    by_efficiency = sorted(solutions, key=lambda s: s.total_efficiency, reverse=True)[
        :10
    ]

    weight_set = set(id(s) for s in by_weight)
    efficiency_set = set(id(s) for s in by_efficiency)

    for s in by_weight:
        if id(s) in efficiency_set:
            s.ranking_tag = "weight+efficiency"
        else:
            s.ranking_tag = "weight"

    for s in by_efficiency:
        if id(s) not in weight_set:
            s.ranking_tag = "efficiency"

    seen: set[int] = set()
    result: list[GearboxSolution] = []
    for s in by_weight + by_efficiency:
        sid = id(s)
        if sid not in seen:
            seen.add(sid)
            result.append(s)

    return result


# ---------------------------------------------------------------------------
# Worker process functions
# ---------------------------------------------------------------------------

# Module-level global set by _tree_worker_init in each worker process.
_w_precomp: _Precomputed | None = None


def _tree_worker_init(precomp: _Precomputed) -> None:
    """Initialise worker-process global (called once per worker)."""
    global _w_precomp
    _w_precomp = precomp


def _worker_tree_search(
    args: tuple[int, int, float, float, float],
) -> _TreeResults:
    """Search one stage-0 subtree in a worker process."""
    r0_idx, n_stages, r_low, r_high, input_torque = args
    precomp = _w_precomp
    assert precomp is not None

    r0 = precomp.unique_ratios[r0_idx]
    n_mats = precomp.n_mats

    # Initial DP: one state per material (all materials as input shaft)
    dp_w_init: dict[int, list[_LightDPState]] = {
        mi: [_LightDPState(0.0, 1.0, 0.0, ())] for mi in range(n_mats)
    }
    dp_e_init: dict[int, list[_LightDPState]] = {
        mi: [_LightDPState(0.0, 1.0, 0.0, ())] for mi in range(n_mats)
    }

    results = _TreeResults(
        top_weight=[], top_eff=[], best_weight=float("inf"), counter=0
    )

    if n_stages == 1:
        # Single stage: ratio r0 must be in [r_low, r_high]
        if r_low <= r0 <= r_high:
            _evaluate_leaf(r0, input_torque, dp_w_init, dp_e_init, precomp, results)
    else:
        # Extend DP for stage 0, then recurse for remaining stages
        dp_w_0 = _extend_dp(r0, input_torque, dp_w_init, "weight", precomp)
        dp_e_0 = _extend_dp(r0, input_torque, dp_e_init, "efficiency", precomp)

        if dp_w_0 or dp_e_0:
            sub_r_low = r_low / r0
            sub_r_high = r_high / r0
            if sub_r_high >= 1.0:
                sub_r_low = max(sub_r_low, 1.0)
                _tree_search(
                    stage_idx=1,
                    n_stages=n_stages,
                    r_low=sub_r_low,
                    r_high=sub_r_high,
                    min_ratio=r0,
                    torque=input_torque * r0,
                    dp_w=dp_w_0,
                    dp_e=dp_e_0,
                    precomp=precomp,
                    results=results,
                )

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve(
    config: GearConfig,
    max_stages: int = 1,
    show_progress: bool = False,
) -> tuple[list[GearboxSolution], SolveStats]:
    """Find the best spur gear gearbox solutions for the given configuration.

    Searches from 1 up to *max_stages* stages and returns the top results
    ranked by weight and efficiency, along with solver statistics.

    Enforces non-decreasing module ordering across stages.
    When *show_progress* is True, tqdm progress bars are displayed.
    """
    t0 = time.perf_counter()
    target = config.target_ratio
    margin = config.reduction_margin / 100.0
    r_low = target * (1.0 - margin)
    r_high = target * (1.0 + margin)
    max_teeth = config.max_teeth_per_gear

    if config.materials is not None:
        materials = tuple(get_material(k) for k in config.materials)
    else:
        materials = get_all_materials()

    if config.min_module is not None:
        std_modules = tuple(m for m in STANDARD_MODULES if m >= config.min_module)
    else:
        std_modules = STANDARD_MODULES

    num_cores = os.cpu_count() or 1

    # Phase 1: build unique-ratio index
    unique_ratios, ratio_map = _build_ratio_data(max_teeth)

    total_tooth_pairs = sum(len(v) for v in ratio_map.values())

    if not unique_ratios or not std_modules:
        stats = SolveStats(elapsed_seconds=time.perf_counter() - t0)
        return [], stats

    # Phase 1.5: precompute coefficients
    precomp = _precompute(
        unique_ratios, ratio_map, materials, max_teeth, config.axis_margin,
        min_output_root_diameter=config.min_output_root_diameter or 0.0,
        std_modules=std_modules,
    )

    # Phase 2+3: fused tree search per stage count
    all_results = _TreeResults(
        top_weight=[], top_eff=[], best_weight=float("inf"), counter=0
    )
    total_subtrees = 0

    for n in range(1, max_stages + 1):
        # Determine viable r0 range for n stages
        if n == 1:
            r0_low = r_low
            r0_high = r_high
        else:
            r0_low = 1.0
            r0_high = r_high

        lo_idx = bisect_left(unique_ratios, r0_low)
        hi_idx = bisect_right(unique_ratios, r0_high)

        work_items = [
            (ri, n, r_low, r_high, config.input_torque) for ri in range(lo_idx, hi_idx)
        ]

        if not work_items:
            continue

        total_subtrees += len(work_items)

        if show_progress:
            tqdm.write(f"Searching {n}-stage solutions...")

        if len(work_items) >= _PARALLEL_THRESHOLD:
            with ProcessPoolExecutor(
                max_workers=num_cores,
                initializer=_tree_worker_init,
                initargs=(precomp,),
            ) as executor:
                for worker_results in tqdm(
                    executor.map(_worker_tree_search, work_items, chunksize=1),
                    total=len(work_items),
                    desc=f"Stage-count {n}",
                    disable=not show_progress,
                ):
                    _merge_results(all_results, worker_results)
        else:
            # Sequential: set module-level global for _worker_tree_search
            global _w_precomp
            _w_precomp = precomp
            for item in tqdm(
                work_items,
                desc=f"Stage-count {n}",
                disable=not show_progress,
            ):
                worker_results = _worker_tree_search(item)
                _merge_results(all_results, worker_results)

    # Phase 4: reconstruct solutions and rank
    solutions: list[GearboxSolution] = []
    seen_paths: set[tuple] = set()
    for _, _, _, path in all_results.top_weight:
        if path not in seen_paths:
            seen_paths.add(path)
            solutions.append(
                _reconstruct_solution(path, config.input_torque, precomp)
            )
    for _, _, _, path in all_results.top_eff:
        if path not in seen_paths:
            seen_paths.add(path)
            solutions.append(
                _reconstruct_solution(path, config.input_torque, precomp)
            )

    elapsed = time.perf_counter() - t0

    stats = SolveStats(
        unique_ratios=len(unique_ratios),
        tooth_pairs=total_tooth_pairs,
        material_combinations=len(materials) ** 2,
        subtrees_searched=total_subtrees,
        solutions_evaluated=all_results.evaluations,
        branches_pruned=all_results.branches_pruned,
        elapsed_seconds=elapsed,
        cpu_cores=num_cores,
    )

    return _select_top_results(solutions, target), stats
