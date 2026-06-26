# Migration conversions — HARNAIS PARALLÈLE (orchestrateur + subagents)

> Pour l'agent CENTRAL qui déroule l'A→Z en déléguant à des subagents. Lis d'abord
> `conversion-migration-RESUME.md`. Tout est sur COPIES ; rien n'est touché sur les originaux.

## Principe (zéro contention d'état)
- **Subagent = 1 client.** Il lance la chaîne `migrate_client.py` en exportant
  `CONV_REG_DIR=migration/parallel/<slug>` → **toutes ses écritures de registre** (generated-cards,
  tu-generic, tracker) vont dans **son dossier**, jamais dans les maîtres. Il **renvoie un rapport**
  (copies, tuiles restées sur l'ancien, anomalies). Il n'écrit AUCUN fichier maître.
- **Agent central = écritures maîtres.** Après le lot, il lance `merge_client_results.py` qui fusionne
  les shards dans `migration/` en **ADDITIF** (aucun écrasement, idempotent), puis agrège les rapports.

```
parallel (cap 4-6, doux pour la prod) :
  subagent(ClientA)  CONV_REG_DIR=migration/parallel/clienta  migrate_client … → shard + rapport
  subagent(ClientB)  CONV_REG_DIR=migration/parallel/clientb  migrate_client … → shard + rapport
  …
central : merge_client_results.py  →  maîtres fusionnés + docs/conversion-migration-tracker.md re-rendu
          + agrège les rapports → PROGRESS + liste anomalies (1 fichier, jamais écrasé)
```

## Commande par client (ce que fait chaque subagent)
```bash
CONV_REG_DIR="migration/parallel/<slug>" \
  .venv/bin/python scripts/migrate_client.py \
    --client "<Nom exact Airtable>" \
    --dashboards <ids ORIGINAUX, virgule> \
    --test-collection 14016 --yes
```
- Les ids par client sont dans **`migration/worklist.json`** (100 clients / 528 dashboards).
- `<slug>` = nom client en minuscules sans espaces (ex. `cica-manuka`).
- La chaîne intégrée : copie → reuse → swap_tables → **deploy_special_cards (#87)** → bascule → generate_fallback → polish.
- Les cartes générées/copiées atterrissent en **collections ACCESSIBLES** (14115 / 13988) — pas de tuiles vides conso.

## Merge (agent central, À LA FIN du lot, SANS CONV_REG_DIR)
```bash
.venv/bin/python scripts/merge_client_results.py        # migration/parallel/* → maîtres
```

## Garde-fous (non négociables)
1. **COPIES uniquement** (jamais les originaux).
2. **Ne jamais deviner un mapping.** Slot flou/conflit/non mappé → reste sur l'ancien, listé dans
   **`migration/CONVERSIONS-A-TRANCHER.csv`** (régénérer global : `build_gaby_handoff.py <export.csv>`).
   → ce fichier part au team lead ; c'est lui qui débloque le strict-100%.
3. Concurrence **4-6 max** (la bascule `--auto-prepare` lance des requêtes lourdes sur la prod).
4. Vérif par tuile (la chaîne le fait : avant/après, fidélité cost, injection). Gros écart → flag.
5. **Le central est le SEUL à écrire les maîtres** (via merge). Les subagents n'écrivent que leur shard.

## État attendu par client après la chaîne
- **visible-100%** atteignable tout de suite (slots clairs migrés ; slots flous = colonnes restées sur
  l'ancien, souvent cachées).
- **strict-100%** (0 colonne sur l'ancien) seulement une fois le CSV tranché par le team lead.

## Validation
Au début : **valider client par client** avec l'utilisateur (cadence doc). Une fois la mécanique sûre
sur 3-4 clients, passer en lots. Mettre à jour `PROGRESS.md` + le tracker à chaque merge.
