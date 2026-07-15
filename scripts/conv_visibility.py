"""Effective visibility of a result column on a dashboard tile.

A Metabase dashcard can override its card's visualization_settings. To know whether a
conversion column is actually shown to a user, the dashcard-level override must win over
the card-level setting.

effective_column_status(display, card_vs, dashcard_vs, col) -> 'visible' | 'hidden' | 'ambiguous'

Policy: only return 'hidden' when the column is PROVABLY hidden. When we cannot prove it
(no metric list, unlisted table column, unknown display type), return 'ambiguous' — never
guess 'visible'. Callers decide what to do with ambiguous vs proven-hidden.
"""

import re

_CARTESIAN = {"line", "bar", "area", "combo", "row", "scatter", "waterfall"}
_SCALAR = {"scalar", "smartscalar", "gauge", "progress"}

# A positional-conversion metric column: conversions / value / rate (CR) / CAC, for a given
# slot number, optionally prefixed for KPIs-evolution cards (current/previous/evolution).
_CONV_METRIC_RX = re.compile(
    r"^(CURRENT_|PREVIOUS_|EVOLUTION_)?(CONVERSIONS?|CONVERSION_RATE|CONV_RATE|CR|CAC)(_\d+)?(_VALUE)?$"
)


def is_conversion_metric(name):
    """True if `name` is a positional-conversion metric (count, value, rate or CAC)."""
    return bool(_CONV_METRIC_RX.match((name or "").upper()))


def slot_of(name):
    """Slot index a conversion column belongs to (0 = the base CONVERSIONS), else None."""
    up = (name or "").upper()
    if up in ("CONVERSIONS", "CONVERSION_VALUE", "CONVERSION_RATE", "CONV_RATE", "CR", "CAC"):
        return 0
    m = re.search(r"(\d+)", up)
    return int(m.group(1)) if m else None


def tile_slot_status(display, card_vs, dashcard_vs, result_cols, slot):
    """Effective visibility of a conversion *slot* on one tile, considering every conversion
    column tied to that slot (base + derived cr/cac/value, incl. current/previous variants).

    Returns 'visible' | 'ambiguous' | 'hidden' | 'absent' (slot has no conversion column here).
    A slot is 'visible' as soon as ANY of its columns is shown, so a hidden `conversions_n`
    that still feeds a visible `cr_n`/`cac_n` correctly counts as visible.
    """
    candidates = [c for c in result_cols if is_conversion_metric(c) and slot_of(c) == slot]
    if not candidates:
        return "absent"
    statuses = [effective_column_status(display, card_vs, dashcard_vs, c) for c in candidates]
    if "visible" in statuses:
        return "visible"
    if "ambiguous" in statuses:
        return "ambiguous"
    return "hidden"


def _pick(card_vs, dashcard_vs, key):
    """Dashcard override wins over the card for a given viz key."""
    dashcard_vs = dashcard_vs or {}
    if key in dashcard_vs and dashcard_vs[key] is not None:
        return dashcard_vs[key]
    return (card_vs or {}).get(key)


def effective_column_status(display, card_vs, dashcard_vs, col):
    up = col.upper()

    if display == "table":
        cols = _pick(card_vs, dashcard_vs, "table.columns")
        if not cols:
            return "visible"  # no explicit list -> all query columns are shown
        by_name = {(c.get("name") or "").upper(): c.get("enabled", True) for c in cols}
        if up in by_name:
            return "visible" if by_name[up] else "hidden"
        return "ambiguous"  # listed table but this column absent -> version-dependent, can't prove

    if display in _CARTESIAN:
        metrics = _pick(card_vs, dashcard_vs, "graph.metrics")
        if not metrics:
            return "ambiguous"
        return "visible" if up in {m.upper() for m in metrics if m} else "hidden"

    if display in _SCALAR:
        field = _pick(card_vs, dashcard_vs, "scalar.field")
        if not field:
            return "ambiguous"
        return "visible" if field.upper() == up else "hidden"

    return "ambiguous"
