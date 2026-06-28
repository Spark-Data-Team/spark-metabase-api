# REPRISE — Migration conversions étape 3 (handoff 2026-06-24)

> Point d'entrée pour un **agent frais** qui reprend le chantier. Lis ce fichier EN ENTIER d'abord.

## 0. À lire (dans l'ordre)
1. **Ce fichier.**
2. `docs/conversion-migration-PROGRESS.md` — où on en est, par client + lots parallèles (Iron Law).
3. `docs/conversion-migration-ANOMALIES.md` — journal append-only des bugs trouvés + décisions user (lots 1 & 2).
4. `docs/conversion-migration-PARALLEL.md` — recette du harnais orchestrateur + subagents.
5. `docs/conversion-migration-clients.md` — détail vivant (§Étape 3 + « cartes partagées spéciales » + Iron Law).
6. `docs/conversion-migration-HANDOFF.md` — chaîne d'outils, pièges techniques.
7. `memory/conv_migration_etape3.md` (+ `memory/conversion_migration.md` = log long).

## 1. Objectif + LA RÈGLE
Migrer A→Z **tous les clients actifs (~98)** : remplacer les conversions **positionnelles** (`CONVERSIONS`,
`CONVERSIONS_1..19`, `CONVERSION_*_VALUE`, `CAC_*`) par les **nommées** (`PURCHASES`, `CUSTOM_CONVERSIONS_1..15`,
`LEADS`, `MARKETING_QUALIFIED_LEADS`…) déjà dispo dans les tables `global.*` (et `analytics.*` pour GA4), via les
cartes génériques (collection 11673 + famille mixte 13884), puis basculer le filtre période en **temporal-unit**.

🔒 **IRON LAW (non négociable, user 2026-06-24)** : **AUCUNE tuile contenant des conversions ne reste sur
l'ancien système.** Un dashboard n'est « fini » que si **0 tuile conv sur l'ancien** (sinon retirer les colonnes
positionnelles cassera tout). **Finir chaque dashboard à 100% avant le suivant ; ne JAMAIS commencer un
dashboard qu'on ne peut pas finir.**

Autres règles d'or : **COPIES d'abord** (jamais les originaux — les liens Nanga pointent dessus ; copie
SHALLOW `is_deep_copy:false`). **Ancre `[conv-2026-06]`** en suffixe du nom. **Mapping = Airtable, re-vérifié
LIVE par client.** **Slots non mappés / conflits = STOP → Gaby** (on n'invente jamais la cible). Réponds au
user en **français, simple et visuel** ; pas de commit sans demande.

## 2bis. MAJ 2026-06-26 — HARNAIS PARALLÈLE LANCÉ + OUTILLAGE DURCI (lire en premier)
**Outillage commité** (branche `feat/conv-migration-tooling-hardening`, suite **204 tests verts**).
2 lots de validation passés sur COPIES (collection **14016**) via subagents → merge central :
- **Lot 1** : AMV Assurance (26424), Exaprint (26427) = **visible-100%** ; Be Radiance (26428),
  Ecopia (26426) = ⏳ Gaby (slots non mappés/conflit, au CSV).
- **Lot 2** : **Komilfo** (26458/26463) & **Osée** (26460/26465) = **visible-100%** ; Toploc (26457) &
  Solarock (26459/26462) = résidu **table large** ; CapCar (26461/64/66) = ⏳ Gaby.
- **8 bugs outillage corrigés** (cf. ANOMALIES) : swap None-dim, visualizer vide, préfixe [migré], titre
  corrompu MAJ (`substitute_viz`), bascule `string/=`, titre générique→nommé, `render_ok` faux-positif,
  **tables larges** (swap s'enclenche : old_vis vide → result_metadata, non-mappées masquées, bonus rempli).
- **2 décisions user TRANCHÉES** : (1) tout **écart de valeur bloque → REVUE** (`--accept-diffs` ne force
  plus ; la revue montre la colonne+chiffres, ex. Toploc « CONVERSIONS_1→CURRENT_LEADS 38 vs 25 »).
  Routage : mapping vraiment différent → consultant ; bug data → user (= équipe data). (2) titre tuile
  migrée = conversion nommée si titre générique, libellé métier préservé.
- **Lot 3 (2026-06-27)** : Dedikazio (26490), Dermalogica (26491), Shining (26492), TuneCore (26494),
  Zeplug (26493), Violette_FR (26495 GA4 + 26496 Global). Merge OK (tracker 43→50).
- **🧩 BRIQUE B CODÉE + RÉ-APPLIQUÉE (2026-06-27)** : `conv_lib.drop_conversion_selects` (pur, 5 tests TDD,
  suite **209**) retire du SQL généré les slots NON mappés (Iron Law = niveau **SQL**, pas affichage ; « masquer »
  ne suffisait pas). Câblée dans `migrate_dashboard_full.generate_card` → **les futurs lots passent en 1 passe**.
  **Self-safe** : no-op sur les cartes **KPIs-evolution** (réfs dérivées multi-CTE / CASE multi-lignes) → zéro
  régression. Lot 3 : dashboards visible-100% **2 → 4** (+Zeplug, +Violette GA4) ; résidu restant = **5 tuiles,
  uniquement KPIs-evolution / 2-dim** = le **follow-on** (parseur cascade OU carte générique « par X — KPIs
  evolution »). Détails : ANOMALIES « BRIQUE B » + PROGRESS lot 3.
- **Lot 4 (2026-06-27/28)** : Lutèce Cosmetics, France Toner, Pulse Protein, My Blend, Sports d'époque
  (Vestiaire = exclu, voir ci-dessous). **7/21 dashboards visible-100% en 1 passe** (brique b active). Résidu
  dominant = **KPIs-evolution** (prévalence confirmée).
- **🧩 BRIQUE B CASCADE + 🛡️ GARDE-FOU VALEUR codés (2026-06-28, suite 217)** — détails ANOMALIES « 2026-06-28 » :
  · `conv_lib.drop_conversion_selects` = parseur SELECT-aware + cascade d'alias (gère KPIs-evolution multi-CTE /
    CASE multi-lignes / multi-dim). Self-safe (no-op si réf pendante). Vérifié : My Blend 5940 KPIs-evo → clean.
  · `generate_fallback.value_review` + `conv_lib.value_diffs` = **garde-fou valeur** (policy user) : écart
    nommé≠positionnel → carte gardée sur l'ancien + « ⚠️ À REVOIR ». Vérifié : TuneCore bloqué, My Blend/Violette migrés.
- **🚫 EXCLUS du balayage (user 2026-06-28)** : **Vestiaire Collective** + **Polène** (worklist 100→98 ;
  copies Vestiaire lot 4 archivées). memory `conv-migration-special-no-copy-clients`.
- **À FAIRE ENSUITE** : prochain lot (4-6 clients NON faits) dans `migration/worklist.json` (déjà faits :
  AMV, Exaprint, Be Radiance, Ecopia, Komilfo, Osée, Toploc, Solarock, CapCar, Dedikazio, Dermalogica, Shining,
  TuneCore, Zeplug, Lutèce, France Toner, Pulse Protein, My Blend, Sports d'époque). Recette PARALLEL, valider
  lot par lot. ⚠️ le **Bash auto-backgroundé** les runs longs → pour ≥5 dash, découper ou reprendre en central
  le dashboard manquant. Toploc/TuneCore (slot nommé≠positionnel) = arbitrage data. **Re-appliquer cascade +
  garde-fou aux lots 1-4 déjà faits** = optionnel (les nouveaux lots en profitent en 1 passe).

## 2. État au 2026-06-24 (avant le harnais — historique)
- **1 client complet** (Iron Law) : 100% Print. **2 dashboards true-100%** : copies 26127 (100% Print), 26197 (Cica Home).
- Partiels (résidus conv sur l'ancien, à finir) : Braxton (26193), Absolut Cashmere (26164), Cica PMax (26198).
- Archivés / à refaire en unités complètes : Cica Focus 6846 (#87), Cica Breakdowns 11249 (segment), Chilowé 21310/21311.
- **Staging copies** : collection **14016**. **Témoins cartes spéciales** : collection **14082**.
- **Cartes spéciales PRÊTES** (prouvées, sans table) :
  - **#87** « Social ad metric (filter choice) by date » → **49788** : Text variable + menu nommé (custom list,
    `values_query_type=list`, single-select) + filtre temporal-unit. (141 dashboards concernés.)
  - **#4854** « Impression share by product & date » → **49755** : temporal-unit (non-conversion).
  - GA4 témoin → **49623** (preuve mécanique GA4).
- **Registre** : `migration/tu-generic-87.json` (→49788) + `tu-generic-4854.json` (→49755) écrits (la bascule les prend).

## 3. Fixes outillage DÉJÀ faits (ne pas refaire)
- `scripts/convert_generic_temporal.py` : **`LATERAL_RE`** → `[^()]*?` + `LIMIT 1` optionnel (corrige le
  débordement sur cartes à 2+ LATERAL = cause des bascules bloquées). CTE granularity = **`scripts/granularity_cte.sql`** (repo, plus /tmp).
- `scripts/bascule_time_filter.py` : **try/except** autour de `convert_card` (un timeout/crash ne tue plus la bascule).
- `scripts/generate_fallback.py` : **`render_ok`** garde les cartes à param requis sans défaut (erreur
  « pick a value for X » = param requis ≠ erreur SQL) et vérifie via `/api/dataset`. → **2-dim migrable** (#11970 OK).
- Tests libs verts (conv_lib 54, bascule_lib 12). Aucun commit fait (working tree).
- **(2026-06-24) NOUVEAU : `scripts/special_cards_lib.py`** (pur, 28 tests `tests/test_special_cards_lib.py`)
  **+ `scripts/deploy_special_cards.py`** (driver live #87) **+ `scripts/sweep_card87.py`** (balayage 141 →
  `migration/sweep-card87.json`). Suite complète 179 tests verts. cf. memory `conv-migration-etape3`.

## 4. TÂCHES, dans l'ordre
1. ✅ **RE-SCAN live FAIT (2026-06-24)** : `discover_conversion_targets.py --root 317` → `migration/conv-targets.json`
   régénéré = **110 clients / 575 dash / 528 avec tuiles / 5726 tuiles**. Le préflight stale ne ratait que **3
   noms** (Lutèce Cosmetics, Mavala, Mavala France), pas 25. (Régénérer le préflight per-tile = optionnel ;
   `conv_preflight.py` lit conv-targets.json frais.) ✅ **MAPPING GLOBAL RAFRAÎCHI 2026-06-25** via export CSV
   Airtable (`flatten_airtable_csv.py` gère le multi-select → `export_conv_mapping.py`) : 173 clients, **33 ont
   gagné des slots** que le cache ratait (bug multi-select). Liste Gaby complète = `migration/airtable-ambiguous.json`
   (125 : 111 cardinalités ≠ + 14 « … OR … »). Backup : `conv-client-mapping.PRE-CSV.json`.
2. ✅ **HELPER #87 CODÉ + PROUVÉ (2026-06-24)** : `special_cards_lib.py` (pur, 28 tests) + `deploy_special_cards.py`
   (driver). Swap 87→49788 des tuiles **sélecteur**, retarget `metric` dimension→variable, custom list sur le(s)
   filtre(s) Metric du dashboard. CLIENT-AGNOSTIQUE. Prouvé sur copies 26292 (Cica Focus) + 26293 (Helloprêt
   multi-filtres). Revue adverse passée. **Sweep des 141** (`sweep_card87.py`→`migration/sweep-card87.json`) :
   **133 CLEAN**, 6 NO_METRIC_PARAM (métrique fixe→passe client), 2 BLOCKED_FOREIGN (5468/5469, sibling adset
   **5644** à migrer à part). 14/141 ont un défaut hors-liste → repli cost. **⚠️ le helper ne FINIT pas un
   dashboard seul** (Iron Law). ✅ **INTÉGRÉ dans `migrate_client.py`** (après swap_tables, avant bascule). Test
   bout-en-bout 6846→copie **26325** : chaîne OK ; `generate_fallback` GÈRE les perf-tables sélecteur (1427/5161/
   5163) par substitution → **pas de nouvel outil « segment » nécessaire**. **2 blocages restants pour true-100%** :
   (a) 🔴 **mapping cache PÉRIMÉ** (Cica live≠cache : slot 3→Custom 2 manquant) → régénérer LIVE (MCP export des
   lignes Airtable → `export_conv_mapping.py`) ; (b) 🐛 `generate_fallback` faux-positive sur cartes spéciales déjà
   migrées (49788/49755 : leur SQL référence CONVERSIONS) → ajouter une skip-list (+ dans le détecteur Iron-Law).
3. **Patron segment** (#10501/10502/10531/14875) : sélecteur `breakdown` single-select ; substitution OK
   (table `global.campaign_breakdown_daily_metrics` a les colonnes nommées) ; #11970 = vraie 2-dim (param
   `dimension_2`). Intégrer via generate_fallback (render_ok corrigé les garde).
4. **Combos multi-conversion** (⚠️ NEUF, pas d'outil) : 2+ conversions sur un même graphe (ex. Braxton #268
   « Conversions 3 », Cica #267/#268). À concevoir (graphe par conversion nommée, masquage de séries, ou
   carte mixte). C'est le morceau le plus nouveau.
5. **Carte by-date lente de Cica Focus** : `convert_card` timeout (300s) → augmenter le timeout ou la convertir hors-bande.
6. **Re-finir Braxton / Absolut / Cica à true-100%** (résidus 2-dim désormais migrables via le render_ok corrigé).
7. **Dérouler A→Z** : finir CHAQUE dashboard à 100% (Iron Law), re-vérif Airtable LIVE par client, mettre à
   jour `PROGRESS.md` + le tracker `migration/conv-migration-tracker.json` à chaque client.

## 5. Décisions tranchées (ne pas re-litiger)
- Iron Law (migrer TOUT, 0 tuile conv sur l'ancien). Copies d'abord. Validation user client par client au début.
- **#87 = Text variable** (PAS Field Filter) → la valeur passe direct au SQL, **aucune table à modifier**
  (`analysis_metrics` est HEVO-synced ; un Field Filter exigerait d'y ajouter les noms). Dropdown via custom
  list + `values_query_type=list`. (Vérifié live par le user : le dropdown s'affiche.)
- 2-dim : on les MIGRE (générer + substituer). Slots non mappés / conflits → Gaby (bloquant, pas de contournement).

## 6. Connexion, scripts, pièges
- Connexion : `import sys; sys.path.insert(0,'scripts'); from archive_collections import connect_resilient; mb=connect_resilient()`.
- Orchestrateur : `scripts/migrate_client.py --client "<Nom>" --dashboards <ids ORIG> --test-collection 14016 --yes`
  (copy shallow + tag → reuse → swap_tables → bascule --auto-prepare → generate_fallback → polish).
- Voir les erreurs SQL : `mb.post('/api/dataset','raw',json={**dataset_query,"parameters":[...]})` puis `.json()`.
- **Airtable** (MCP) : base `apptzpE1FqCMGH0dw`, table `tbliHOIPYGJCvLvas`. Champs : brand_name
  `fldlzNF2KPPRh2Wdj`, type(slot) `fldKwKgjtULTSjX6g`, new_type `fldAOmPth76Vsd7AX`. **Client ACTIF = ≥1
  new_type réel.** Mapping cache : `migration/conv-client-mapping.json` (indice ; re-vérifier live).
- **PIÈGES** :
  · mapping cache JSON = clés STRING ("0") ; `conv_lib._slot_of` renvoie INT → faire `{int(k):v for k,v in ...}`.
  · pMBQL : SQL/tags dans `dataset_query.stages[0].native/.template-tags` (pas `dataset_query.native`) → `conv_lib.native_and_tags`.
  · PUT d'un dashboard à ONGLETS doit inclure `tabs`.
  · `mb.put/mb.post` renvoient False sur erreur HTTP → passer `'raw'` pour voir le corps.
  · floats Snowflake bougent au 15e chiffre → comparer avec tolérance ~1e-9.
  · cartes migrées doivent vivre dans une collection lisible par le consultant (arbre /317/ ou 11673), JAMAIS
    le sandbox 13851 — sinon tuiles vides côté consultant. (À automatiser ; pour la validation admin c'est OK.)
- Étape finale prod (après validation) = appliquer sur les ORIGINAUX ; le **partage Nanga reste MANUEL (GM)**.
