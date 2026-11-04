"""Lossless, data-only decision options shared by promotion and handoff."""
from __future__ import annotations

import json
import math


def validate_options(options: object) -> None:
    """Check known fields; preserve JSON extensions without interpreting them."""
    if options is None:
        return
    if not isinstance(options, list):
        raise ValueError("options must be a list")
    seen: set[str] = set()
    for index, option in enumerate(options):
        field = f"options[{index}]"
        if not isinstance(option, dict):
            raise ValueError(f"{field} must be an object")
        identity = option.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError(f"{field}.id must be a unique non-empty string")
        seen.add(identity)
        if "chosen" in option and not isinstance(option["chosen"], bool):
            raise ValueError(f"{field}.chosen must be boolean")
        for key in ("rationale", "rejected_because"):
            if key in option and not isinstance(option[key], str):
                raise ValueError(f"{field}.{key} must be a string")
    # json.dumps alone coerces numeric dict keys and tuples. Do not silently
    # change extension types on a YAML -> JSON -> YAML round trip.
    def check(value: object) -> None:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("options extension keys must be strings")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif value is None or isinstance(value, (str, bool, int)):
            return
        elif isinstance(value, float) and math.isfinite(value):
            return
        else:
            raise ValueError("options extensions must contain finite JSON data")
    try:
        check(options)
        json.dumps(options, allow_nan=False)
    except (RecursionError, TypeError, OverflowError) as exc:
        raise ValueError("options must contain acyclic JSON data") from exc
