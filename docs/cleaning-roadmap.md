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

## Campagnes par vague

| # | Campagne | Statut | Volume | Exécuteur / note |
|---|----------|--------|--------|------------------|
| 1 | Collections vides | ✅ | 90 archivées | `archive_empty_collections.py` ; exclut template/perso/système |
| 4 | Fourre-tout (set vert) | ✅ | 5 archivées | `archive_collections.py` ; test/POC dormants |
| 5 | Cartes inutilisées périmées | ✅ | 315 archivées (≥1 an) | `archive_stale_cards.py` ; re-vérif live, exclut frozen ☠️ |
| — | Usage replié dans l'audit | ✅ | — | `last_used_at`/`view_count`/`avg_query_time` ; 433 périmées repérées, #11 rempli |
| 6 | Doublons fonctionnels | 🚧 | 156 groupes | fusion : archiver copies inutilisées d'abord, repointage dashboards ensuite (test diff.) |
| 11 | Cartes lentes | ⬜ | 213 | perf : fix-or-kill (plus lente = 224 s) |
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

## TODO outillage

- ⬜ Purge du cache deep avant un nouveau scan (les cartes archivées y figurent encore comme actives) — ajouter `audit` cache-clean ou skip-archivés.
