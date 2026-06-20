#!/usr/bin/env python3
"""Transforme les lignes Airtable exportées (Conversions table) en mapping client résolu.
Usage: python3 scripts/export_conv_mapping.py migration/conv-airtable-rows-<ts>.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conv_lib

def main():
    rows = json.loads(Path(sys.argv[1]).read_text())
    mapping = conv_lib.build_client_mappings(rows)
    n_un = sum(1 for c in mapping.values() for v in c.values() if v == conv_lib.UNMAPPED)
    n_cf = sum(1 for c in mapping.values() for v in c.values() if v == conv_lib.CONFLICT)
    out = Path(__file__).resolve().parent.parent / "migration" / "conv-client-mapping.json"
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"{len(mapping)} clients -> {out}  (UNMAPPED slots: {n_un}, CONFLICT slots: {n_cf})")

if __name__ == "__main__":
    main()
