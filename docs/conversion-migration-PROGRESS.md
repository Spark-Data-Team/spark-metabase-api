# Avancement migration conversions — PAR CLIENT (snapshot 2026-06-24, IRON LAW)

> **Iron Law (user)** : un dashboard n'est « FINI » que si **0 tuile contenant des conversions ne reste sur
> l'ancien système** (sinon, retirer les colonnes positionnelles cassera ces tuiles). « Client complet » =
> TOUS ses dashboards finis.
>
> **Périmètre réel** : ~**98 clients ACTIFS** (≥1 `new_type` réel dans Airtable). ⚠️ le préflight (97) est
> PÉRIMÉ : **25 clients actifs en sont absents** → RE-SCANNER la collection 317 en live pour le vrai total.

---

## 🔁 A→Z PARALLÈLE — avancement orchestrateur (worklist 100 clients / 528 dash)

> Harnais : 1 subagent / client (`CONV_REG_DIR=migration/parallel/<slug>`) → shard + rapport ;
> central merge `merge_client_results.py` (additif). Tout sur COPIES (collection 14016).
> **visible-100%** = 0 tuile conv réelle sur l'ancien (slots tous mappés). **⏳ Gaby** = slots non
> mappés/conflit → restés sur l'ancien, déjà dans `migration/CONVERSIONS-A-TRANCHER.csv`.
> Détail anomalies : `docs/conversion-migration-ANOMALIES.md` (append-only).

### Lot 1 — 2026-06-26 (validation mécanique : 4 clients « frais » 1-dash)
| Client | Copie | slots | Issue | État |
|---|---|---|---|---|
| AMV Assurance | 26424 | 0→Leads | tuile CPC → fallback 49953 | **visible-100%** ✅ |
| Exaprint | 26427 | 0→Purchases, 1→Custom 1 | 4 tuiles GA4 → fallback 49954/55/56 | **visible-100%** ✅ |
| Be Radiance | 26428 | 0,1 non mappés | 14 tuiles sur l'ancien | ⏳ Gaby |
| Ecopia | 26426 | 0 conflit, 2 non mappé | tuiles sur l'ancien | ⏳ Gaby |

**Mécanique validée via 2 revues user.** 5 corrections outillage + 1 règle produit (**suite 201 verte**) :
(1) `swap_tables` crash None-dim → guard ; (2) **tuile « visualizer » vide** (sourceId `card:<old>` non
repointé) → `conv_lib.repoint_visualizer_source` (fallback + #87) ; (3) préfixe `[migré]` → nom propre ;
(4) **titre humain corrompu** (« Conversions »→« PURCHASES ») → `conv_lib.substitute_viz` préserve les
libellés ; (5) **bascule `string/=`** non détectée → `find_time_param` accepte `category|string/=`
(AMV basculé en temporal-unit, validé) ; (6) **titre tuile** : générique → conversion nommée
(« Conversions »→« Purchases »), libellés métier préservés (`relabel_conversion_title`). Copies lot 1
toutes patchées + retro-fixées. Détails : `ANOMALIES.md`.
Garde-fous tiennent : clients mappés → visible-100% ; slots flous → stop propre vers Gaby.

### Lot 2 — 2026-06-26 (5 clients, tous fixes en place)
| Client | Copies | État | Bascule |
|---|---|---|---|
| **Komilfo** | 26458, 26463 | **2/2 visible-100%** ✅ | temporal-unit ✅ |
| **Osée** | 26460, 26465 | **2/2 visible-100%** ✅ | temporal-unit ✅ |
| Toploc | 26457 | 5 migrées ; 1 résidu **34248** (table large 20 slots) | temporal-unit ✅ |
| Solarock | 26459, 26462 | résidu carte **adset** (table large, slots 1-6 non mappés) | 26459 ✅ / 26462 NA |
| CapCar | 26461, 26464, 26466 | résidu (slot 0 conflit, slot 1 « OR ») → **Gaby (au CSV)** | 26461 ✅ / 26464 bloqué / 26466 NA |

**Bascule `string/=` validée sur tout le lot.** Merge OK (tracker 33→43, +21 cartes générées).
🔎 **Nouveau patron récurrent = tables « performances by date/adset » LARGES** (déversent les 20 slots
positionnels). Les clients à peu de conversions réelles (Toploc 2, Solarock 1) laissent 15-18 colonnes
non mappées → fallback rendu KO → reste sur l'ancien. **PAS du Gaby** (slots non-réels) ni régression :
demande une STRATÉGIE de migration (ex. ne garder que les conversions nommées du client, masquer le reste).
⚠️ process : 1 subagent (Osée) a *backgroundé* la commande + rendu la main trop tôt (travail OK quand même,
état reconstruit en central) → consigne durcie « FOREGROUND, attendre, reporter » ; + `run_step` remonte
désormais le stderr (point aveugle bascule levé).

## Étape 3 — état strict (Iron Law)

| Dashboard (copie) | Client | tuiles conv sur l'ancien | FINI (Iron Law) ? |
|---|---|---|---|
| 100% Print Home (26127) | 100% Print | 0 | ✅ OUI |
| Cica Home (26197) | Cica Manuka | 0 | ✅ OUI |
| Braxton (26193) | Braxton | 3 (tables slots non mappés / 2-dim) | ❌ non |
| Absolut Cashmere (26164) | Absolut Cashmere | 1 (table 2-dim by-location) | ❌ non |
| Cica PMax (26198) | Cica Manuka | 2 (table + search terms) | ❌ non |

**Clients COMPLETS (tous dashboards finis Iron-Law) : 1 — 100% Print (1/1).**
Partiels : Cica Manuka (Home fini ; PMax + Focus + Breakdowns non), Braxton, Absolut Cashmere (résidus).
Archivés/à refaire : Cica Focus (#87), Cica Breakdowns (segment), Chilowé.

## Ce qui débloque les résidus (tooling, en cours)
- résidus 2-dim → ✅ outil corrigé (render_ok), à ré-appliquer.
- résidus slots non mappés → **Gaby** (Airtable).
- **#87 → ✅ HELPER CODÉ + PROUVÉ (2026-06-24)** : `special_cards_lib.py` + `deploy_special_cards.py`
  (swap 87→49788 + retarget metric dimension→variable + custom list dashboard, client-agnostique, vérif
  avant/après par filtre). Sweep des 141 : **133 CLEAN / 6 métrique-fixe / 2 foreign (5468/5469, sibling
  adset 5644)**. À intégrer dans `migrate_client.py` pour finir les dashboards card-87 bout-en-bout (Iron Law).
- segment / combos multi-conversion → outillage de déploiement encore à finir.
- **Re-scan live 2026-06-24** : 110 clients / 575 dash / 528 avec tuiles / 5726 tuiles (`conv-targets.json`).

## Honnête : on est au tout début
**1 client complet sur ~98.** Les 5 clients étape 1/2 (PN + Gaby) faits avant sur copies = à reprendre sous
l'Iron Law (résidus + 0 tuile GA4). Le gros du balayage A→Z reste à faire, une fois l'outillage cartes
spéciales terminé.
