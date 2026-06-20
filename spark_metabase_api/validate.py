from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
