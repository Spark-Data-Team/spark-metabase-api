#!/usr/bin/env python3
"""AGENT CENTRAL — merge les registres par-client (migration/parallel/<client>/) dans les
MAÎTRES (migration/), en ADDITIF (aucun écrasement) :
- generated-cards.json : union de dicts (clés cid|client, pas de collision inter-clients) ;
- conv-migration-tracker.json : conv_tracker.merge_trackers (update même clé, ajoute le reste) ;
- tu-generic-*.json : copiés dans le maître (1 fichier par carte).
Puis re-rend la vue docs/conversion-migration-tracker.md depuis le maître fusionné.
Idempotent (re-run sans doublon). Lancé SANS CONV_REG_DIR (donc écrit bien les maîtres).

Usage : python3 scripts/merge_client_results.py [migration/parallel]
"""
import json, sys, shutil
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import conv_tracker as T

MASTER = REPO / "migration"


def main():
    import os
    assert not os.environ.get("CONV_REG_DIR"), "merge doit tourner SANS CONV_REG_DIR (écrit les maîtres)"
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else MASTER / "parallel"
    shards = sorted([d for d in base.glob("*") if d.is_dir()]) if base.exists() else []
    if not shards:
        sys.exit(f"aucun shard dans {base}")

    # 1) generated-cards.json (union de dicts)
    gpath = MASTER / "generated-cards.json"
    gen = json.loads(gpath.read_text()) if gpath.exists() else {}
    g_add = 0
    for sd in shards:
        f = sd / "generated-cards.json"
        if f.exists():
            for k, v in json.loads(f.read_text()).items():
                g_add += k not in gen
                gen[k] = v
    gpath.write_text(json.dumps(gen, ensure_ascii=False, indent=0))

    # 2) tracker (merge sans perte) + re-render la vue .md
    tr = T.load(MASTER / "conv-migration-tracker.json")
    for sd in shards:
        f = sd / "conv-migration-tracker.json"
        if f.exists():
            tr = T.merge_trackers(tr, json.loads(f.read_text()))
    T.save(tr, MASTER / "conv-migration-tracker.json")
    T.render_to_file(tr)

    # 3) tu-generic-*.json (1 fichier/carte, copie dans le maître)
    tu = 0
    for sd in shards:
        for f in sd.glob("tu-generic-*.json"):
            shutil.copy2(f, MASTER / f.name); tu += 1

    print(f"MERGE OK — {len(shards)} shards | generated +{g_add} (total {len(gen)}) | "
          f"tracker {len(tr)} entrées | tu-generic {tu} copiés")


if __name__ == "__main__":
    main()
