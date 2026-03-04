"""Onshape API client for pushing gear parameters to a Variable Studio."""

import os
import re
from urllib.parse import urlparse

import requests

from spurGearGenerator.models import GearboxSolution


class OnshapeError(Exception):
    """Raised when an Onshape API operation fails."""


def validate_onshape_env() -> tuple[str, str, str]:
    """Check that required Onshape environment variables are set.

    Returns (api_url, access_key, secret_key).
    Raises OnshapeError if any variable is missing.
    """
    api_url = os.environ.get("ONSHAPE_API", "")
    access_key = os.environ.get("ONSHAPE_ACCESS_KEY", "")
    secret_key = os.environ.get("ONSHAPE_SECRET_KEY", "")

    missing = []
    if not api_url:
        missing.append("ONSHAPE_API")
    if not access_key:
        missing.append("ONSHAPE_ACCESS_KEY")
    if not secret_key:
        missing.append("ONSHAPE_SECRET_KEY")

    if missing:
        raise OnshapeError(
            f"Missing Onshape environment variable(s): {', '.join(missing)}. "
            "Get your API keys at https://dev-portal.onshape.com/keys and set:\n"
            "  export ONSHAPE_API=https://cad.onshape.com\n"
            "  export ONSHAPE_ACCESS_KEY=<your-access-key>\n"
            "  export ONSHAPE_SECRET_KEY=<your-secret-key>"
        )

    return api_url.rstrip("/"), access_key, secret_key


# Regex for Onshape document URLs:
# https://cad.onshape.com/documents/{did}/w/{wid}/e/{eid}
_URL_PATTERN = re.compile(
    r"/documents/([a-f0-9]+)/(w|v|m)/([a-f0-9]+)/e/([a-f0-9]+)"
)


def parse_onshape_url(url: str) -> tuple[str, str, str, str]:
    """Extract (did, wvm_type, wvmid, eid) from an Onshape URL.

    Supports workspace (w), version (v), and microversion (m) URLs.
    Raises OnshapeError if the URL format is invalid.
    """
    parsed = urlparse(url)
    match = _URL_PATTERN.search(parsed.path)
    if not match:
        raise OnshapeError(
            f"Invalid Onshape URL: {url}\n"
            "Expected format: https://cad.onshape.com/documents/<did>/w/<wid>/e/<eid>"
        )
    return match.group(1), match.group(2), match.group(3), match.group(4)


def _make_session(access_key: str, secret_key: str) -> requests.Session:
    """Create a requests session with Basic Auth and default headers."""
    session = requests.Session()
    session.auth = (access_key, secret_key)
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json;charset=UTF-8; qs=0.09",
    })
    return session


def _resolve_variable_studio(
    session: requests.Session,
    api_url: str,
    did: str,
    wvm: str,
    wvmid: str,
    eid: str,
    verbose: bool = False,
) -> str:
    """Resolve and validate the element as a Variable Studio.

    If the exact eid works, returns it unchanged.  If not, falls back to
    listing document elements and attempts a prefix match (handles truncated
    URLs).  Returns the resolved element ID.
    """
    # Fast path: try the variables endpoint directly
    url = f"{api_url}/api/v6/variables/d/{did}/{wvm}/{wvmid}/e/{eid}/variables"
    resp = session.get(url)
    if resp.status_code == 200:
        return eid

    # Fallback: list document elements and search
    if verbose:
        print(f"  Element {eid} not found directly, scanning document elements...")
    elems_url = f"{api_url}/api/v6/documents/d/{did}/{wvm}/{wvmid}/elements"
    elems_resp = session.get(elems_url)
    if elems_resp.status_code != 200:
        raise OnshapeError(
            f"Failed to list document elements (HTTP {elems_resp.status_code}): "
            f"{elems_resp.text[:300]}"
        )

    elements = elems_resp.json()
    var_studios = [e for e in elements if e.get("elementType") == "VARIABLESTUDIO"]

    # Try prefix match on the given eid
    prefix_matches = [e for e in var_studios if e["id"].startswith(eid)]
    if len(prefix_matches) == 1:
        resolved = prefix_matches[0]["id"]
        if verbose:
            name = prefix_matches[0].get("name", "")
            print(f"  Resolved to element {resolved} ({name})")
        return resolved

    # No match — build a helpful error
    if var_studios:
        listing = "\n".join(
            f"  - {e['id']}  ({e.get('name', 'unnamed')})" for e in var_studios
        )
        raise OnshapeError(
            f"Element {eid} is not a Variable Studio in this document.\n"
            f"Available Variable Studios:\n{listing}"
        )
    raise OnshapeError("No Variable Studios found in this document.")


def build_variables(solution: GearboxSolution) -> list[dict]:
    """Build the list of Onshape variable dicts from an optimized solution.

    Creates 10 variables per stage (depth, module, pressure angle, backlash,
    pinion/wheel teeth, pinion/wheel dedendum coeff, pinion/wheel addendum coeff).
    """
    variables: list[dict] = []

    for stage in solution.stages:
        n = stage.stage_number
        prefix = f"s{n}"
        geom = stage.geometry

        # Stage-level parameters
        variables.append({
            "name": f"{prefix}_depth",
            "type": "LENGTH",
            "expression": f"{stage.pinion.face_width_mm} mm",
            "description": f"Stage {n} face width",
        })
        variables.append({
            "name": f"{prefix}_m",
            "type": "LENGTH",
            "expression": f"{stage.pinion.module} mm",
            "description": f"Stage {n} module",
        })
        variables.append({
            "name": f"{prefix}_p",
            "type": "ANGLE",
            "expression": (
                f"{geom.operating_pressure_angle_deg} deg"
                if geom is not None else "20 deg"
            ),
            "description": f"Stage {n} pressure angle",
        })
        variables.append({
            "name": f"{prefix}_backlash",
            "type": "LENGTH",
            "expression": (
                f"{geom.backlash_mm} mm"
                if geom is not None else "0 mm"
            ),
            "description": f"Stage {n} backlash",
        })
        variables.append({
            "name": f"{prefix}_center_dist",
            "type": "LENGTH",
            "expression": (
                f"{geom.operating_center_distance_mm} mm"
                if geom is not None else "0 mm"
            ),
            "description": f"Stage {n} center distance",
        })

        # Pinion parameters
        variables.append({
            "name": f"{prefix}p_z",
            "type": "NUMBER",
            "expression": str(stage.pinion.teeth),
            "description": f"Stage {n} pinion tooth count",
        })
        variables.append({
            "name": f"{prefix}p_dedendum",
            "type": "NUMBER",
            "expression": str(stage.pinion.dedendum_coeff or 1.25),
            "description": f"Stage {n} pinion dedendum coefficient",
        })
        variables.append({
            "name": f"{prefix}p_addendum",
            "type": "NUMBER",
            "expression": str(stage.pinion.addendum_coeff or 1.0),
            "description": f"Stage {n} pinion addendum coefficient",
        })

        # Wheel parameters
        variables.append({
            "name": f"{prefix}w_z",
            "type": "NUMBER",
            "expression": str(stage.wheel.teeth),
            "description": f"Stage {n} wheel tooth count",
        })
        variables.append({
            "name": f"{prefix}w_dedendum",
            "type": "NUMBER",
            "expression": str(stage.wheel.dedendum_coeff or 1.25),
            "description": f"Stage {n} wheel dedendum coefficient",
        })
        variables.append({
            "name": f"{prefix}w_addendum",
            "type": "NUMBER",
            "expression": str(stage.wheel.addendum_coeff or 1.0),
            "description": f"Stage {n} wheel addendum coefficient",
        })

    return variables


def set_variables(
    session: requests.Session,
    api_url: str,
    did: str,
    wvm: str,
    wvmid: str,
    eid: str,
    variables: list[dict],
) -> None:
    """POST variables to the Variable Studio (full replacement).

    Raises OnshapeError on failure.
    """
    url = f"{api_url}/api/v6/variables/d/{did}/{wvm}/{wvmid}/e/{eid}/variables"
    resp = session.post(url, json=variables)
    if resp.status_code not in (200, 204):
        raise OnshapeError(
            f"Failed to set variables (HTTP {resp.status_code}): {resp.text}"
        )


def push_to_onshape(
    solution: GearboxSolution,
    onshape_url: str,
    verbose: bool = False,
) -> None:
    """Push gear parameters from a solution to an Onshape Variable Studio.

    Validates environment, parses the URL, checks the element type,
    builds variables, and sends them to the API.
    """
    # 1. Validate env
    api_url, access_key, secret_key = validate_onshape_env()

    # 2. Parse URL
    did, wvm, wvmid, eid = parse_onshape_url(onshape_url)
    if verbose:
        print(f"Onshape target: document={did}, {wvm}={wvmid}, element={eid}")

    # 3. Create session
    session = _make_session(access_key, secret_key)

    # 4. Resolve and validate element
    if verbose:
        print("Validating Variable Studio...")
    eid = _resolve_variable_studio(session, api_url, did, wvm, wvmid, eid, verbose)

    # 5. Build variables
    variables = build_variables(solution)
    if verbose:
        print(f"Pushing {len(variables)} variables to Onshape...")

    # 6. POST (full replacement — clears existing and writes new)
    set_variables(session, api_url, did, wvm, wvmid, eid, variables)

    if verbose:
        print("Variables pushed successfully.")
