from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CardUnit:
    target: str
    dataset_query: Dict[str, Any] = field(default_factory=dict)
    display: Optional[str] = None
    visualization_settings: Optional[Dict[str, Any]] = None
    live_card_id: Optional[int] = None
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
