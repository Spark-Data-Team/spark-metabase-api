from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CardUnit:
    target: str
    dataset_query: Dict[str, Any] = field(default_factory=dict)
    display: Optional[str] = None
    visualization_settings: Optional[Dict[str, Any]] = None
    live_card_id: Optional[int] = None
    # Reserved hooks — not yet wired into guarded_apply/check_differential in v1,
    # which uses the auto metric derived from _signature. Future versions will
    # honour these fields for column-level assertions and metric overrides.
    expected_columns: Optional[List[str]] = None
    metric_override: Optional[Dict[str, Any]] = None


def units_from_spec(spec) -> List[CardUnit]:
    units: List[CardUnit] = []

    def walk(coll, path):
        for card in coll.cards:
            defn = card.definition or {}
            units.append(CardUnit(
                target=path + "/" + card.name,
                dataset_query=defn.get("dataset_query") or {},
                display=defn.get("display"),
                visualization_settings=defn.get("visualization_settings"),
            ))
        for sub in coll.collections:
            walk(sub, path + "/" + sub.name)

    walk(spec, spec.name)
    return units


def unit_from_payload(target: str, payload: Dict[str, Any]) -> CardUnit:
    return CardUnit(
        target=target,
        dataset_query=payload.get("dataset_query") or {},
        display=payload.get("display"),
        visualization_settings=payload.get("visualization_settings"),
    )


def unit_from_card_id(client, card_id: int) -> CardUnit:
    card = client.get("/api/card/{}".format(card_id))
    if not card:
        raise ValueError("card {} not found".format(card_id))
    return CardUnit(
        target="card#{}".format(card_id),
        dataset_query=card.get("dataset_query") or {},
        display=card.get("display"),
        visualization_settings=card.get("visualization_settings"),
        live_card_id=card_id,
    )


@dataclass
class Finding:
    target: str
    check: str
    level: str  # "error" | "warn" | "ok"
    message: str
    before: Any = None
    after: Any = None


def check_structure(unit: "CardUnit") -> Finding:
    dq = unit.dataset_query
    if not isinstance(dq, dict) or not dq.get("database"):
        return Finding(unit.target, "structure", "error", "dataset_query missing or invalid 'database'")
    qtype = dq.get("type")
    if qtype == "native":
        if not ((dq.get("native") or {}).get("query") or "").strip():
            return Finding(unit.target, "structure", "error", "native query is empty")
    elif qtype == "query":
        if not dq.get("query"):
            return Finding(unit.target, "structure", "error", "MBQL query is empty")
    else:
        return Finding(unit.target, "structure", "error", "unknown query type {!r}".format(qtype))
    return Finding(unit.target, "structure", "ok", "well-formed")


def _card_exists(client, card_id: int) -> bool:
    card = client.get("/api/card/{}".format(card_id))
    return bool(card) and not card.get("archived")


def check_refs(client, unit: "CardUnit") -> List[Finding]:
    findings: List[Finding] = []
    dq = unit.dataset_query
    if dq.get("type") == "query":
        src = (dq.get("query") or {}).get("source-table")
        if isinstance(src, str) and src.startswith("card__"):
            try:
                cid = int(src.split("__")[1])
            except (ValueError, IndexError):
                findings.append(Finding(unit.target, "refs", "error",
                    "malformed source-table ref {!r}".format(src)))
            else:
                if not _card_exists(client, cid):
                    findings.append(Finding(unit.target, "refs", "error",
                        "source card {} not found / archived".format(cid)))
    for tag in ((dq.get("native") or {}).get("template-tags") or {}).values():
        cid = (tag.get("values_source_config") or {}).get("card_id")
        if cid is not None and not _card_exists(client, cid):
            findings.append(Finding(unit.target, "refs", "error",
                "field-filter source card {} not found / archived".format(cid)))
    if not findings:
        findings.append(Finding(unit.target, "refs", "ok", "refs resolve"))
    return findings


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def ok(self) -> bool:
        return not self.errors()

    def summary(self) -> str:
        counts: Dict[str, int] = {}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        parts = ["{} {}".format(v, k) for k, v in sorted(counts.items())]
        return ", ".join(parts) or "no findings"

    def render(self) -> str:
        glyph = {"error": "✗", "warn": "!", "ok": "✓"}
        lines = ["  {}  {:<12} {}  [{}]".format(
            glyph.get(f.level, "?"), f.check, f.target, f.message)
            for f in self.findings]
        return "\n".join(lines) + ("\n" if lines else "") + "Report: " + self.summary()

    def exit_code(self) -> int:
        return 1 if self.errors() else 0


class ValidationError(Exception):
    def __init__(self, report: "Report"):
        self.report = report
        super().__init__("validation failed:\n" + report.render())


def _execute_unit(client, unit: "CardUnit"):
    """Run the unit's query. Returns (rows: list[dict], error: str|None)."""
    if unit.live_card_id is not None:
        try:
            rows = client.get_card_data(card_id=unit.live_card_id, data_format="json")
        except Exception as e:
            return [], str(e)
        if not isinstance(rows, list):
            err = rows.get("error") if isinstance(rows, dict) else None
            return [], err or "query failed (unexpected result shape)"
        return rows, None
    try:
        res = client.run_query(unit.dataset_query)
    except Exception as e:
        return [], str(e)
    if not isinstance(res, dict):
        return [], "query failed (non-dict response)"
    # /api/dataset returns status=="completed" on success. Anything else
    # (failed / running / missing, or a 4xx error body) is a failure, not
    # "0 rows" — otherwise an errored query slips through the gate as a warn.
    if res.get("error") or res.get("status") != "completed":
        return [], res.get("error") or "query status: {!r}".format(res.get("status"))
    data = res.get("data") or {}
    cols = [c.get("name") for c in (data.get("cols") or [])]
    rows = [dict(zip(cols, r)) for r in (data.get("rows") or [])]
    return rows, None


def check_execution(client, unit: "CardUnit") -> Finding:
    rows, error = _execute_unit(client, unit)
    if error:
        return Finding(unit.target, "execution", "error", "query failed: {}".format(error))
    if not rows:
        return Finding(unit.target, "execution", "warn", "query returned 0 rows")
    if unit.expected_columns:
        missing = [c for c in unit.expected_columns if c not in rows[0]]
        if missing:
            return Finding(unit.target, "execution", "warn",
                           "missing expected columns: {}".format(missing))
    return Finding(unit.target, "execution", "ok", "{} rows".format(len(rows)))


def _signature(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a signature of row set: row count, columns, and sums of numeric columns.
    A column is numeric only if all non-null values are int/float and not bool."""
    cols = list(rows[0].keys()) if rows else []
    sums: Dict[str, float] = {}
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            sums[c] = sum(vals)
    return {"row_count": len(rows), "columns": cols, "sums": sums}


def gate(client, units, execute=True) -> Report:
    report = Report()
    for u in units:
        s = check_structure(u)
        report.add(s)
        if s.level == "error":
            continue
        ref_findings = check_refs(client, u)
        for f in ref_findings:
            report.add(f)
        if any(f.level == "error" for f in ref_findings):
            continue
        if execute:
            report.add(check_execution(client, u))
    return report


def guarded_apply(client, units, mutate_fn, differential="monitor",
                  force=False, execute=True) -> Report:
    report = Report()
    baselines: Dict[str, List[Dict[str, Any]]] = {}
    if differential != "off":
        for u in units:
            if u.live_card_id is not None:
                rows, err = _execute_unit(client, u)
                if not err:
                    baselines[u.target] = rows
    g = gate(client, units, execute=execute)
    report.findings.extend(g.findings)
    if g.errors() and not force:
        report.add(Finding("apply", "gate", "error",
                           "aborted: pre-apply errors, nothing mutated"))
        return report
    mutate_fn()
    if differential != "off":
        mode = "identical" if differential == "identical" else "monitor"
        for u in units:
            if u.target in baselines:
                after, err = _execute_unit(client, u)
                if err:
                    report.add(Finding(u.target, "differential", "error",
                        "post-apply query failed: {}".format(err)))
                    continue
                for f in check_differential(u.target, baselines[u.target], after, mode=mode):
                    report.add(f)
    return report


def resolve_cli_target(client, target: str) -> List["CardUnit"]:
    import os
    from . import iac
    if target.lower().endswith((".yaml", ".yml", ".json")):
        if not os.path.exists(target):
            raise ValueError("spec file not found: {}".format(target))
        try:
            spec = iac.load(target)
        except Exception as e:
            raise ValueError("not a valid Metabase spec file {}: {}".format(target, e))
        if not getattr(spec, "name", None):
            raise ValueError("not a valid Metabase spec (missing 'name'): {}".format(target))
        return units_from_spec(spec)
    if target.isdigit():
        return [unit_from_card_id(client, int(target))]
    return units_from_spec(iac.export(client, target))


def check_differential(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]:
    """Compare two result sets (before/after).
    mode="identical" => deltas are errors; mode="monitor" => deltas are warns.
    tolerance: fractional threshold for numeric sums (absolute/denom > tolerance)."""
    sb, sa = _signature(before), _signature(after)
    level = "error" if mode == "identical" else "warn"
    findings: List[Finding] = []

    if sb["row_count"] != sa["row_count"]:
        findings.append(Finding(target, "differential", level,
            "row count {} -> {}".format(sb["row_count"], sa["row_count"]),
            before=sb["row_count"], after=sa["row_count"]))

    if set(sb["columns"]) != set(sa["columns"]):
        findings.append(Finding(target, "differential", level, "columns changed",
            before=sb["columns"], after=sa["columns"]))

    after_cols = set(sa["columns"])
    for c, bsum in sb["sums"].items():
        asum = sa["sums"].get(c)
        if asum is None:
            # The column was numeric before but has no numeric sum now. If it is
            # still present (same name), it regressed to all-null or a non-numeric
            # type — a real delta the row-count and column-set checks cannot see.
            if c in after_cols:
                findings.append(Finding(target, "differential", level,
                    "sum({}) numeric -> non-numeric/all-null".format(c),
                    before=bsum, after=None))
            continue
        denom = abs(bsum) or 1.0
        delta = abs(asum - bsum)
        if delta != delta or delta / denom > tolerance:  # NaN, or beyond tolerance
            findings.append(Finding(target, "differential", level,
                "sum({}) {} -> {}".format(c, bsum, asum), before=bsum, after=asum))

    if not findings:
        findings.append(Finding(target, "differential", "ok", "no significant change"))

    return findings
