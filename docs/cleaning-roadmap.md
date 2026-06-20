# Metabase Cleaning — Roadmap

> Tracker vivant du nettoyage instance-wide. Design : `docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md`.
> Légende : ✅ fait · 🚧 en cours · ⬜ à faire · ⏸️ tenu de côté
> **Maj : 2026-05-29**

## Progression globale (réversible — tout en archivage)

| | Départ (2026-05-29) | Actuel |
|---|---|---|
| Collections actives | 868 | **773** (−95) |
| Cartes actives | 5654 | **5329** (−325) |

## Outillage (sur master, testé)

- `scripts/audit.py` — `scan` → `deep` (cache reprenable) → `report`. Usage-aware (`last_used_at`/`view_count`/`average_query_time`).
- `scripts/audit_lib.py` / `audit_report.py` — détecteurs, empreinte v2, scoring, rendu. 18 tests (`tests/test_audit_lib.py`, `test_audit_report.py`).
- Exécuteurs (dry-run, re-vérif live, CSV de relecture, rollback) : `archive_empty_collections.py`, `archive_collections.py`, `archive_stale_cards.py`.
- `swap_card_on_dashboards.py` + `swap_lib.py` (8 tests) : remplace une carte par sa canonique sur ses dashboards en recâblant les filtres, puis archive. Dry-run, `--difftest`, snapshot rollback, garde-fou tuile-en-double. **Dashboard-safe.**

## Campagnes par vague

| # | Campagne | Statut | Volume | Exécuteur / note |
|---|----------|--------|--------|------------------|
| 1 | Collections vides | ✅ | 90 archivées | `archive_empty_collections.py` ; exclut template/perso/système |
| 4 | Fourre-tout (set vert) | ✅ | 5 archivées | `archive_collections.py` ; test/POC dormants |
| 5 | Cartes inutilisées périmées | ✅ | 315 archivées (≥1 an) | `archive_stale_cards.py` ; re-vérif live, exclut frozen ☠️ |
| — | Usage replié dans l'audit | ✅ | — | `last_used_at`/`view_count`/`avg_query_time` ; 433 périmées repérées, #11 rempli |
| 6 | Doublons fonctionnels | 🚧 | 156 groupes | **reframé** : 3 vrais doublons isolés (entangled), 39 en zone sensible, 111 cross-location = structure de propagation → relève de #8. Outil de swap prêt (dashboard-safe). Appliquer = décisions par-paire + cas tuile-en-double |
| 11 | Cartes lentes | 🔎 triagé | 212 actives | **toutes sur dashboard → optimiser en place (pas d'archivage)**. ROI réel = famille **benchmark "client vs industry vs global"** (~14 s × 20-33k vues : #2116/2187/2115/2097/2240-2243). Les GSC 224 s sont lentes mais peu vues (faible ROI). Optimisation = matérialiser/pré-agréger les benchmarks industrie+global (requête Snowflake multi-CTE) + test différentiel. Discipline distincte → session dédiée. Alerte #2510 (99 s × 2496 vues) à part. |
| 10 | Nommage hors template | ⬜ | 1919 | normalisation (étend Phase 1.5) |
| 2 | Sprawl perso | ⬜ | 162 clients | sensible : sortir le travail client de l'espace perso |
| 3 | Noms de collections dupliqués | ⬜ | 45 | |
| 8 | Dérive template | ⬜ | 279 | copies clientes divergentes du maître 215 |
| 9 | Familles de variantes | ⬜ | 20 | paramétrer en 1 carte (ex. `breakdown`) |
| 7 | Backlog archivé | ⏸️ | 1803 collections | suppression DÉFINITIVE — prudence, ou laisser |

## Tenu de côté (ne pas archiver sans décision)

- `Old audit questions` (#3918) — 1 carte encore active (les 164 dormantes archivées).
- `[WIP] Presento | Questions` (#10980) — 1904 vues.
- `Quitoque-Dashboards-Temp` (#1461) — dashboards clients vus récemment.
- Collections `DO NOT MODIFY ☠️` (Presento) — marqueur humain explicite.
- `#17584 Fields` — `can_write=False` (permissions).
- 5 collections vides nichées en perso — relèvent de la campagne sprawl (#2).

## Garde-fous

Toutes actions autorisées **mais validation avant chaque action** ; réversible d'abord (archivage, jamais suppression sans accord). Snapshot → (test différentiel) → échantillon → batch → invariant.

**Invariant dashboard** : une carte sur ≥1 dashboard n'est JAMAIS archivée sans (a) la remplacer sur chaque dashboard par la canonique à la même place, (b) re-câbler les filtres (`parameter_mappings`), (c) test différentiel. Sinon, on ne touche que `dashboard_count == 0`. (→ `swap_card_on_dashboards.py`.)

## TODO outillage

- ⬜ Purge du cache deep avant un nouveau scan (les cartes archivées y figurent encore comme actives) — ajouter `audit` cache-clean ou skip-archivés.
