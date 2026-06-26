# Migration conversions Metabase — PASSATION (lis-moi en premier)

> Doc d'onboarding pour un agent frais qui reprend ce chantier.
> Lis aussi : **`conversion-migration-clients.md`** (qui est fait, où on en est, par client),
> le mémo `memory/conversion_migration.md` (log détaillé chronologique), et la spec
> `docs/superpowers/specs/2026-06-03-conversion-migration-design.md`.
> **Dernière mise à jour : 2026-06-13.**

---

## 1. L'objectif (en une phrase)
Sur les dashboards **custom** des clients (collection 317, ~110 clients), remplacer chaque tuile branchée sur
une **ancienne** conversion (colonnes positionnelles Snowflake `CONVERSIONS`, `CONVERSIONS_1..19`, valeurs,
db 144 / `global.*`) par la **nouvelle** équivalente nommée (`PURCHASES`, `CUSTOM_CONVERSIONS_1..15`, …) déjà
existante dans la collection **11673**, en préservant mise en page / filtres / valeurs ; PUIS basculer le
filtre de période du dashboard de l'ancien mécanisme (texte/category) vers le **temporal-unit** Metabase.

## 2. Règles d'or (NON négociables)
1. **TOUJOURS sur des COPIES.** Les liens de partage **Nanga** pointent sur les originaux → on ne touche
   JAMAIS un original. Copie SHALLOW : `POST /api/dashboard/<id>/copy {"is_deep_copy": false, "collection_id": <test>}`.
2. **RÉUTILISER les cartes existantes (11673 / famille mixte 13884). JAMAIS de doublon par dashboard.**
3. **Vérif avant/après par tuile.** On ne migre une tuile que si les valeurs sont identiques (tolérance
   relative ~1e-9 ; les floats Snowflake bougent au 15e chiffre), ou si la différence est **assumée+validée**
   (flag `--accept-diffs`).
4. **Airtable = source de vérité** du mapping (slot ancien → conversion nommée), par client. **Conflit** =
   un slot mélange plusieurs événements/conversions → **STOP, demander à Gaby** (ne pas deviner).
5. **En cas de doute : STOP et pose la question.** L'utilisateur préfère ça à une « décision naze ».
6. **Réponds en français, simple et visuel** (l'utilisateur pense en systèmes ; schémas/tableaux). **Pas de
   commits sans qu'il le demande.**

## 3. La chaîne d'outils (LE pipeline, par dashboard COPIE)
Tous dans `scripts/`. Connexion qui marche : `from archive_collections import connect_resilient; mb = connect_resilient()`
(NE PAS utiliser reorg_phase1.connect : session_id périmé). Dry-run d'abord (sans `--yes`).

**Raccourci (orchestrateur) :** `migrate_client.py --client "<Nom>" --dashboards <ids ORIGINAUX> [--yes]`
copie chaque dashboard puis enchaîne les **5 étapes** ci-dessous (--accept-diffs partout, --auto-prepare).
Onglets SUPPORTÉS. Sinon, étapes manuelles :

```
0. COPIER l'original (shallow) dans une collection de test.
1. migrate_dashboard_reuse.py --copy <C> --source <ORIG> --client "<Nom>" --planned-temporal-unit [--accept-diffs] [--yes]
      → migre les TUILES conversion vers 11673 (résolution unique via mapping client × colonne × breakdown ×
        KPI-set × brand × source ; masquage de séries en trop ; --accept-diffs = accepte un écart de valeurs
        connu/validé). Laisse sur l'ancien ce qu'il ne sait pas (statut « À DÉCIDER »).
2. swap_tables.py --copy <C> --client "<Nom>" [--accept-diffs] [--yes]
      → swappe les TABLEAUX multi-slot vers la famille mixte 13884 (résolveur breakdown→carte auto :
        type/channel/category/network/product/name/location/device/url/date). Mappe les colonnes visibles +
        reprend les renommages ; vérifie cellule par cellule (aligné par libellé, brand=yes inerte).
3. bascule_time_filter.py --copy <C> --client "<Nom>" --auto-prepare [--yes]
      → bascule le param 'Time period' (category) → temporal-unit (MÊME id, les câblages survivent).
        --auto-prepare : convertit le mécanisme temps de CHAQUE carte bloquante (conversion ou non : Cost,
        Clicks, Magento, charts orphelins) en copie temporal-unit (sandbox 13885, via convert_card).
        Fallback : carte non convertible AVEC filtre date séparé ET breakdown≠date (granularité vestigiale,
        ex. table 2-dim) → DÉBRANCHÉE du filtre temps. Nettoie les câblages morts.
4. generate_fallback.py --copy <C> --client "<Nom>" [--yes]   ← OBJECTIF 100%
      → pour chaque tuile ENCORE sur l'ancien (pas d'équivalent 11673), GÉNÈRE une copie de la vieille carte
        avec substitution de colonnes (substitution_map + generate_card), dédupliquée (1 par vieille carte×
        client) dans coll 13950. Slots non mappés/conflit restent vieux (colonnes cachées OK ; VISIBLES = pas
        100%, besoin Gaby). Ne vérifie que l'exécution (render KO réel = erreur SQL ; timeout = on garde).
5. polish_generated_viz.py --copy <C> --client "<Nom>" [--yes]
      → substitue la viz du DASHCARD (table.columns/column_settings/series) pour les cartes générées (13950)
        : titres/ordre/visibilité des colonnes reprennent les bons noms.
```
⚠️ **APRÈS génération : les cartes naissent dans 13950 (sandbox /13851/ = NON lisible par les consultants).
Il FAUT déplacer les cartes migrées (13950 + copies temporal-unit 13885) vers une collection accessible**
(sous-collection « Conversions migrées » dans la collection client /317/, ou collection partagée pour les
génériques) — SINON les tuiles s'affichent VIDES pour le consultant (bug vécu Shopinvest Focus Marge).
cf. `conversion-migration-clients.md` § LEÇON PERMISSIONS. À automatiser dans les outils.

## 4. Bibliothèques & helpers (testés)
- **`conv_lib.py`** (tests `tests/test_conv_lib.py`, 54/54) : logique pure. Clés : `native_and_tags`,
  `old/new_conversion_columns`, `resolve_new_card`, `series_display_map`, `map_table_columns` (gère colonnes
  `_EVOLUTION`, alias REVENUE/CONVERSION_RATE/AVG_REVENUE, dimensions nues CHANNEL/NETWORK/…),
  `fix_brand_clause`/`strip_brand_atoms`, `card_breakdown`, `kpi_signature`.
- **`bascule_lib.py`** (tests `tests/test_bascule_lib.py`, 12/12) : `bascule_plan`, `apply_bascule`,
  `build_temporal_unit_param`, `time_param_payload`.
- **`convert_generic_temporal.py`** : `convert_card(mb, cid, client, window)` — copie temporal-unit (sandbox
  13885) de N'IMPORTE QUELLE carte time-driven ; baseline INLINE fiable (`name='<g>'`) ; vérif 4 granularités ;
  registre `migration/tu-generic-<id>.json` (lu par la bascule) ; idempotent.
- Brand fix (FAIT sur 11673) : `audit_brand_clause.py`, `fix_brand_clause_cards.py`, `batch_brand_fix.py`,
  `validate_brand_batch.py`.

## 5. Faits techniques NON-OBVIES (pièges qui ont coûté du temps)
- **Le swap conversions est facile ; la BASCULE du filtre temps est le vrai goulot** : elle est atomique
  (tout-ou-rien par dashboard) et exige que CHAQUE carte time-driven ait une version temporal-unit. Chaque
  dashboard a une « longue traîne » d'oddités (Magento, tableaux 2-dim, charts orphelins) → c'est `--auto-prepare`
  qui la couvre.
- **pMBQL** : cartes récentes → `dataset_query = {database, lib/type, stages}` ; SQL+tags dans
  `stages[0].native` / `.template-tags` (PAS `dataset_query.native`). Utiliser `conv_lib.native_and_tags`.
- **Param client** : certains templates (magento) utilisent un tag `client` SINGULIER type `string/=`
  (pas `clients`/category) → toujours lire le `widget-type` du tag pour construire le param.
- **Ancien filtre time_period souvent CASSÉ** (texte) : passer une valeur → 400, non renseigné → granularité
  aléatoire. Donc pour les baselines on INLINE la granularité (`name='week'`) via /api/dataset, on ne se fie
  PAS au field-filter.
- **Recette temporal-unit** : préfixer la CTE `granularity` (sonde l'unité via le tag temporal-unit sur
  `utils.calendar.date` = field **419201**) + remplacer chaque `LATERAL(... metabase_filters.time_periods ...
  {{time_period}} ... LIMIT 1)` par `LATERAL(SELECT name FROM granularity LIMIT 1)`. `temporal_units` =
  `[day,week,month,year]` (comme l'ancien ; pas de quarter sauf besoin).
- ⚠️ **CTE granularity = fichier `scripts/granularity_cte.sql`** (suivi git). `convert_generic_temporal.py` le
  lit à l'import. **AVANT 2026-06-22 il lisait `/tmp/granularity_cte.sql`** (artefact volatil) → après vidage
  de /tmp, `bascule --auto-prepare` crashait (`FileNotFoundError`) dès qu'une carte by-date devait être
  convertie (corrigé : pointe désormais sur le fichier repo). Si la bascule crashe à l'import, vérifier ce fichier.
- 🐛 **FIX 2026-06-23 — `LATERAL_RE` débordait sur les cartes à 2+ LATERAL.** La regex repérant le
  `LATERAL (... metabase_filters.time_periods ...)` était en dotall `.*?` → si une carte avait un AUTRE LATERAL
  avant (LATERAL brand `textual_boolean`, comparison_windows…), le match partait du 1er LATERAL et avalait la
  frontière de CTE jusqu'au time_periods → un CTE aval disparaissait → `Object 'FINAL' does not exist`. Corrigé
  en `[^()]*?` (ne traverse plus de parenthèse). **C'était la cause de la plupart des bascules « bloquées » sur
  les cartes conversion by-date** (quasi toutes ont un LATERAL brand). Cartes à 1 seul LATERAL non affectées.
  Témoin : #4854 → copie 49755 (collection témoins 14082), avant/après identique 4 granularités.
- **Règle BRAND** (validée) : une campagne est « brand » si `campaign_type LIKE '%brand%'` **OU**
  `TRIM(LOWER(campaign_category)) = 'brand'` (égalité STRICTE — un LIKE attrape « Push Brand To Media » à tort).
  Appliquée à 1967 cartes de 11673 (0 régression). `conv_lib.fix_brand_clause`.
- **mb.put/mb.post** renvoient `False` sur erreur HTTP ; passer `'raw'` pour voir le corps. **PUT d'un dash à
  ONGLETS DOIT inclure `tabs`** (sinon 500) — les 3 scripts le font désormais (onglets supportés).
- **Index 11673** : `migration/conv-new-index.json` restreint au sous-arbre 11673 (le mode cache polluait).
  Régénérer : `build_new_conv_index.py --live --root 11673`. (NB : 41329 archivé, index à régénérer.)

## 6. Décisions produit DÉJÀ tranchées (ne pas re-litiger)
- Filtre temps : **tout en temporal-unit**, bascule PAR DASHBOARD (jamais 2 filtres temps en final).
- Tableaux multi-slot : **famille mixte « toutes conversions »** (option b) créée dans 13884 (cartes
  49098–49129, 10 breakdowns). Filtre de lignes : on garde **`cost != 0`** (le neuf), pas `impressions>0`.
- Conventions time series : axe X timeseries/no-label/ticks ; `temporal_units` [day,week,month,quarter,year] ;
  défaut `week` (mais contrainte défaut relâchée — pas bloquant). cf. memory `metabase-timeseries-conventions`.

## 7. Limites connues / reste à faire
- **Graphes multi-conversion** (2+ conversions sur un même graphe) et **tableaux 2-dimensions** : pas
  d'équivalent propre → restent sur l'ancien système (sans casse) ou débranchés du filtre temps.
- **Cartes « filter choice »** (sélecteur de métrique, ex. card 87) : transform OK mais convert_card/reuse ne
  savent pas les VÉRIFIER (param sélecteur requis → baseline vide) → restent sur l'ancien. À outiller.
- **ONGLETS : SUPPORTÉS** (2026-06-13). Les 3 scripts gèrent `tabs` (PUT inclut `tabs`, dashcards gardent
  `dashboard_tab_id`) ; le reuse apparie source↔copie par INDEX d'onglet (ids différents). migrate_client.py
  les passe aussi.
- **Appliquer aux ORIGINAUX** : tout est sur copies. Définir/faire l'étape finale (appliquer sur l'original
  ou repointer le partage Nanga) APRÈS validation consultant — PAS encore fait.
  **Décision 2026-06-17 : le partage / repoint Nanga reste MANUEL (fait par les GM, pas d'automatisation) —
  cf. memory `dashboard-app-sharing`. Étape finale prod = appliquer sur les ORIGINAUX ; le partage = GM.**
- **GA4 / analytics.*** : ~242 tuiles bloquées amont (pipeline data).
- **15 cartes cassées** (orphelines, 0 dashboard) repérées dans 11673 → archivage proposé, en attente GO.
- Subagents/workflows : quota hebdo (reset ~ven 21h) — sinon travailler inline.

## 8. Repères Airtable / mapping
- Mapping = `migration/conv-client-mapping.json` (régénérable). Source : base **apptzpE1FqCMGH0dw**, table
  **tbliHOIPYGJCvLvas** (champs : `client` linked, `type`=slot positionnel `fldKwKgjtULTSjX6g`,
  `new_type` `fldAOmPth76Vsd7AX`, event `fld6VHk3nAgHmRSP7`, platform `fld1VYy5IjpCPSsus`).
- `conv_lib.build_client_mappings` flague `__CONFLICT__` quand un slot a plusieurs `new_type` distincts.
  Re-vérifier en LIVE avant chaque client (Gaby corrige au fil de l'eau).

## 9. Prochaine action
**MAJ 2026-06-17.** Étapes 1+2 FAITES : PN (validé Lucas) + 4 clients Gaby (Goodiespub, Father&Sons,
Shopinvest, Rivadouce) migrés, **rétro-tagués `[conv-2026-06]`**, suivis dans
`docs/conversion-migration-tracker.md` (18 lignes). **Partage app Nanga = MANUEL (GM), pas d'automatisation**
(prototype construit puis rollback complet — cf. memory `dashboard-app-sharing`).

**ÉTAPE 3 = migrer les ~92 clients restants (ads `global.*`).** Triage préflight (`conv-preflight.csv`) :
**49 prêts** (0 conflit, mappable — démarrer par les petits propres : Toploc, 100% Print, Figaret,
France Toner, Jerome Dreyfuss), **9 à compléter Airtable** (no_client_mapping → Gaby), **34 lourds**
(conflits/unmapped → Gaby). Dérouler via `migrate_client.py` (auto-tag + écrit le registre). En parallèle :
demande groupée Gaby (9 Airtable + conflits restants des 5 faits : F&S slot 1, Rivadouce slots).

**GA4** : bloqué amont (pipeline data en cours d'ajout des colonnes nommées à `analytics.*`). Les 18 migrés
ont **0 tuile GA4**. Catch-up des déjà-migrés tracké en `ga4_pending` : PN #14049, Rivadouce #15372,
Shopinvest #863 (Goodiespub + F&S = aucun GA4). **Archivage des anciens** : `archive_superseded.py` après
validation consultant (opt-in `archive_old:true` par ligne ; dry-run ; réversible). cf. §10.

## 10. Ancre de campagne, suivi & archivage des anciens (2026-06-17)
- **Ancre `[conv-2026-06]`** = marqueur de **CAMPAGNE** (pas date de création). Ajoutée en **suffixe** au nom
  de CHAQUE copie par `migrate_client.py` (via `conv_tracker.apply_tag`). Survit à la promotion (quand on
  droppera le préfixe `[TEST conv]`). Rôle : marqueur humain + **garde-fou** anti-archivage.
- **Tracker / registre** = `migration/conv-migration-tracker.json` (vue lisible :
  `docs/conversion-migration-tracker.md`, régénérée par `conv_tracker.py --render`). 1 ligne par dashboard
  migré : `client, dashboard, copy_id, original_id, tagged, status, archive_old, old_archived, notes`.
  `migrate_client.py` y consigne chaque paire **ancien→copie** automatiquement. Lib pure testée :
  `tests/test_conv_tracker.py` (9/9). Seedé avec les copies déjà faites (PN + 4 clients Gaby).
- **Archivage des anciens = delete-by-PRESENCE (jamais par absence).** `scripts/archive_superseded.py`
  (dry-run par défaut ; `--yes` applique) archive UNIQUEMENT les originaux des lignes marquées
  **`archive_old: true`** (opt-in explicite, à poser à la main après validation), réversible
  (PUT `archived:true`), + garde-fou : refuse tout nom portant `[conv-2026-06]`. → on n'archive jamais
  « tout ce qui n'a pas le tag ».
- **Workflow** : migrer (auto-tag + registre) → consultant valide → poser `archive_old:true` sur la ligne →
  `archive_superseded.py` (dry-run puis `--yes`). Le **partage app reste MANUEL (GM)** — cf. memory
  `dashboard-app-sharing`.
