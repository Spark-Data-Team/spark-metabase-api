# Handoff — Suivi SEO mots-clés Manucurist (Metabase)

> État au 2026-06-15. Projet : dashboard de suivi SEO pour le client **Manucurist** (pod Nanga),
> issu de l'issue Airtable `base app8gA9M46hqIfBPO / table tblOkJO3J4H7C15au / record rec7dqswb7JefIvPf`
> (« Manucurist | Suivi des mots-clés », projet *Manucurist | Upsell GEO*).
> Demandeurs : **Geoffrey Jestin** (client Manucurist, SEO), relayé par **Thibaut de Louvencourt** (SEO Nanga) et **Geoffrey Couette / Robin Trefcon** (Spark). Dev : Louis Monier (tech).

## 0. TL;DR — où en est-on
- **V3 livrée et QA-validée dans le navigateur** (2026-06-15). Dashboard dédié opérationnel.
- Le brief a évolué V1 → V2 → V3 via un **gsheet** (onglet `V3`, le plus récent) + commentaires Thibaut.
- 2 points en attente de validation client (voir §7).
- **V3.1 (2026-06-17, retour Loom collègue → client)** : (1) toggle de pliage `+/−` par Marché rétabli sur Positions (#48634) & Saisonnalité (#49426) via `pivot.show_column_totals=True` ; (2) liens template #13489 **retirés** de la section Saisonnalité (cassaient hors embed → login Metabase ; le client ne voit que l'embed Nanga `app.nanga.tech`). Scripts : `scripts/seo_collapse_fix.py` + `seo_collapse_probe.py` (probe/backup). QA Chrome OK (pliage testé, liens absents).

## 1. Sources externes du besoin
- **Gsheet** (fait foi) : `https://docs.google.com/spreadsheets/d/1i8eoNISq4masLKAoC7Oh5Mp7MNdzwv6ynYAkN_cY5_Y`
  - Onglet **`V3`** = cible actuelle. Onglets V2/V1 = historiques.
  - Lecture des **cellules** via MCP Google Drive `read_file_content(fileId, includeComments=true)`. Les **commentaires** ne sortent PAS de l'API Drive → les lire via Chrome (panneau Commentaires).
- **Airtable** issue (ci-dessus) : description + lien gsheet dans le champ `fldH74qsETt5xSngc`.

## 2. Objets Metabase (instance https://spark.metabaseapp.com, compte louis.monier@spark.do)
DB Snowflake = **database id 144**.

| ID | Type | Nom | Rôle |
|---|---|---|---|
| **13752** | collection | **Manucurist** | foyer du livrable (créée à la racine) |
| **25137** | dashboard | Suivi mensuel des mots-clés SEO \| Manucurist | **LE livrable** (8 tuiles, 7 filtres) |
| **48633** | model | SEO Keyword Monitoring — Manucurist (model) | **modèle mots-clés V3** (cœur) |
| 48635 | card (table) | SEO — Snapshot mots-clés (mois courant) | tuile snapshot (15 col) |
| 48634 | card (pivot) | SEO — Positions mois par mois (grille) | tuile grille positions |
| 49062 | model | SEO Pages Monitoring — Manucurist (model) | modèle pages (clics/gabarit) |
| 49063 | card (pivot) | SEO — Clics par gabarit de page, mois par mois | tuile pages |
| 49064 | card (table) | SEO — Δ 6 mois par gabarit | tuile Δ pages |
| 49425 | model | SEO Saisonnalité — Manucurist (model) | modèle saisonnalité (volume kp 24 mois) |
| 49426 | card (pivot) | SEO — Saisonnalité (volume de recherche / mois) | tuile saisonnalité |
| 13489 | dashboard | SEO Historical Search Volume - Template | **template EXISTANT** (pas à nous) lié pour la saisonnalité 48 mois |
| 32496 | card (table) | Keywords average ranking by date (SERP) | ancienne carte de prod, **optimisée** (voir §6), dans collection SERP #4809, sur dashboard #17250 [IN DEV] |

**Archivés** (prototypes V1/V2 superflus, ne pas réutiliser) : 48501, 48567, 48568, 48600, 48601.

## 3. Le dashboard #25137 (V3) en détail
3 sections (titres = text cards) :
- **📊 Vision par mots-clés** : snapshot (#48635) + grille positions (#48634).
- **🗓️ Saisonnalité** : text card (descriptif seul — **liens #13489 retirés le 2026-06-17**, cassaient hors embed) + pivot saisonnalité (#49426).
- **📄 Vision par pages** : pivot pages (#49063) + table Δ gabarit (#49064).

**7 filtres** (paramètres dashboard) :
| slug | type | dropdown | mappé sur (colonne) |
|---|---|---|---|
| marche | string/= | FR/US/UK/AUTRES | tuiles kw + pages → `MARCHE` |
| gamme | string/= | Gel Polish/Nail Polish/Nailcare | tuiles kw → `GAMME` |
| categorie | string/= | Transactionnel/Générique/Clean / Engagement/Produit/Informationnel | snapshot+grille → `CATEGORIE` |
| marque | string/= | Marque/Hors Marque | tuiles pages → `MARQUE` |
| pattern_keyword | string/contains | — | tuiles kw → `KEYWORD` |
| exact_keyword | string/= | — | tuiles kw → `KEYWORD` |
| date | date/all-options (défaut `past6months`) | — | grille + saisonnalité + pages → `MONTH_DATE` (PAS le snapshot) |

**Template saisonnalité #13489** : a un filtre **Corpus Name OBLIGATOIRE**. Corpus à passer :
- US → `Corpus transactionnel US`
- FR → `Corpus transactionnel FR - Mots clés stratégiques`
Lien type : `…/dashboard/13489?client=Manucurist&corpus_name=<urlencoded>&date=past48months`.
> ⚠️ Ces liens ont été **retirés du dashboard client #25137 le 2026-06-17** : ils pointent vers `spark.metabaseapp.com`, hors du périmètre d'auth de l'embed Nanga (`app.nanga.tech`) → le client tombe sur un mur de login. Template encore dispo en interne ; ré-exposer au client = routage côté app Nanga (pas Metabase).

## 4. Modèle mots-clés #48633 (V3) — logique
Script source : **`scripts/build_seo_monitoring_v3.py`** (relancer = rebuild + PUT + validation snapshot).
Grain : (marche, gamme, categorie, keyword) × mois (13 mois). 34 kw = 16 US + 18 FR → ~476 lignes.
Colonnes produites : `MONTH_DATE, MARCHE, GAMME, CATEGORIE, KEYWORD, URL_POSITIONNEE, POSITION, POSITION_SERP, POSITION_GSC, SEARCH_VOLUME, CLICKS, IMPRESSIONS, CLICKS_FR, CLICKS_UK, CLICKS_US, CLICKS_AUTRES, POTENTIEL_TRAFIC, DELTA_M1, DELTA_M3, DELTA_CLICKS_M1`.

Sources & calculs :
- **POSITION** = `LEAST(COALESCE(<SERP DataForSEO best rank pour la zone du kw>, <GSC avg position pondérée impressions>), 100)`. **100 = non classé**. (SERP = `google_serp.serp_requests ⋈ serp_history ⋈ serp__keyword_metrics`, dédoublonné meilleure position par url/run **partition incluant client_id+corpus_name** sinon collapse cross-client ; filtre `url ILIKE '%'||client_domain||'%'`).
- **SEARCH_VOLUME** = dernier `COALESCE(adjusted_avg_searches, avg_monthly_searches)` de `google_keyword_planner.kp__keyword_monthly_metrics` (zone du kw). kp **lague ~2 mois** → on prend le dernier connu.
- **POTENTIEL_TRAFIC** = `ROUND(volume × ctr_medium)` où ctr depuis `metabase_filters.serp_ctr_scenarios` (`name='Default'`, position 0-100, on joint sur `ROUND(position)`).
- **URL_POSITIONNEE** = URL client de la meilleure position (la plus récente), query string retirée (`REGEXP_REPLACE(url,'[?].*$','')`).
- **CLICKS** = total GSC par kw/mois (tous marchés) ; **CLICKS_FR/UK/US/AUTRES** = split par marché via la **section de site** (URL) — voir §5.
- **DELTA_M1/M3** = `LAG(position,n) - position` (+ = positions gagnées) ; **DELTA_CLICKS_M1** = `clicks - LAG(clicks)`.

Mapping **Gamme/Catégorie** : hardcodé dans le script (listes `US` et `FR`). **US = repris du gsheet ; FR = proposition perso à valider.**

## 5. Modèle pages #49062 — logique
Script : **`scripts/build_seo_pages_model.py`**. Source unique : `google_search_console.gsc__page_keyword_daily_metrics` (~27M lignes, hist. 2024-02→).
Grain : (marche, gabarit, marque) × mois. Colonnes : `MONTH_DATE, MARCHE, GABARIT, MARQUE, CLICKS, IMPRESSIONS, DELTA_6M_PCT, TENDANCE`.
- **Marché** = section de site via URL : `us.manucurist.com`→US, `uk.`→UK, `www.manucurist.com/{en,es,it,de,nl,el,pt}`→AUTRES, sinon `www.`→FR.
- **Gabarit** : `/blogs/`→Blog, `/collections/`→Collections, `/products/`→Produits, sinon Autres pages.
- **Marque** : requête contient un radical de `gsc__brand_keywords` (manucuri, mancurist…) → Marque, sinon Hors Marque.
- ⚠️ granularité requête GSC = **échantillonnée** (requêtes anonymisées exclues) → totaux < clics page réels ; fiable en tendance.

## 6. Carte #32496 (optimisée, séparée du livrable V3)
Ancienne carte de prod corrigée le 2026-05-29 (scripts `apply_fixes_32496.py` + `serp_difftest.py`) :
- suppr. INNER JOIN `serp_ctr_scenarios` filtrant (perdait positions > 100), suppr. code mort, dédup déterministe `ORDER BY rank_absolute`. Backup : `migration/card-32496-backup-*.json`.

## 7. ⚠️ À VALIDER avec Thibaut/Geoffrey (bloquants métier)
1. **Mapping Gamme/Catégorie des 18 mots-clés FR** = ma proposition (le gsheet ne les renseigne pas). Voir liste `FR` dans `build_seo_monitoring_v3.py`.
2. **« led gel polish » (US)** ré-ajouté (présent onglet V3) — OK ?
3. **Liste des 34 kw figée en dur** → à terme la brancher sur un Sheet/Airtable maintenu par l'équipe SEO.
- Message de retour à Thibaut **rédigé mais pas envoyé** (dans l'historique conv).

## 8. Conventions & décisions arrêtées
- **Cadence = mensuelle** (tranché via gsheet V3).
- **Snapshot = dernier mois COMPLET** (`time-interval -1 month`), pas le mois courant partiel.
- **Marché = section du site** (le pays du chercheur GSC n'est PAS ingéré : `country='other'` partout pour Manucurist ; table `country_device` vide). Si vrai géo-chercheur voulu = chantier pipeline data.
- **100 = non classé** (hors top 100), comme le gsheet.
- **Pliage des pivots** : le toggle `+/−` par groupe (Marché) n'apparaît **que si `pivot.show_column_totals=True`** (le sous-total de groupe le porte ; cf. Pages #49063 qui l'a au défaut, vs Positions/Saiso qui l'avaient à False). Sur Positions ce sous-total = **position moyenne du marché** (compromis assumé pour avoir le pliage) ; `show_row_totals` laissé False (pas de colonne « Row totals » across-mois superflue).

## 9. Gotchas techniques (IMPORTANT pour un agent frais)
- **Lancer** : `/Users/louismonier/Dev/Pro/spark-metabase-api/.venv/bin/python scripts/<x>.py`. Connexion via `Metabase_API(domain,email,password)` lu de `.env` par `reorg_phase1._load_env`. Mettre une **boucle de retry** (instance lente/instable, timeouts fréquents).
- **Exécuter du SQL** : `mb.post("/api/dataset","raw",json={"database":144,"type":"native","native":{"query":sql}}, timeout=240+)`. **Le timeout par défaut est 30 s (trop court)** — le passer explicitement (les jointures GSC/SERP prennent 40-600 s).
- **Tout lancer en background bash + poller le fichier output** (les requêtes sont longues).
- **`legacy_query` renvoyé par GET /api/card est souvent stale/vide** → ne pas s'y fier pour vérifier le SQL stocké ; vérifier en **runnant** la carte/donnée.
- **SQL natif ≠ pivot** : une question en SQL natif **ne peut pas** utiliser la viz Pivot Table (« only supported for query builder »). → faire un **modèle** (type=model) puis une **question MBQL** par-dessus (`source-card`).
- **Redirection ad-hoc `/question#hash`** sur les questions MBQL basées sur un modèle : stocker le `dataset_query` au **format MLv2** (`{"lib/type":"mbql/query","stages":[{... "source-card": <id>, "lib/uuid": <uuid> par clause}]}`) — générer les uuid avec `uuid.uuid4()`. (Le format legacy `{type:query,query:{...}}` marche fonctionnellement mais provoque la redirection.)
- **result_metadata** : le PUT d'un `dataset_query` la **réinitialise**. Pour la peupler : run via `/api/dataset` → récupérer `data.cols` → PUT **séparé** `{"result_metadata": cols}` (sans toucher dataset_query).
- **Pivot** : `pivot_table.column_split` = colonnes par **nom** (string) ou field-ref ; désactiver les totaux parasites avec `pivot.show_row_totals=false` / `pivot.show_column_totals=false`. column_split simple `{"rows":["X"],"columns":["Y"],"values":[["aggregation",0]]}` marche pour source-card.
- **Décimales** : `column_settings` `{"number_style":"decimal","decimals":0}` (clé `["name","<COL>"]` ; pour une valeur d'agrégat pivot, clé `["name","avg"]`/`["name","sum"]`).
- **Dashboard PUT** : `{"parameters":[...], "dashcards":[...]}`. dashcards neufs = `id` négatif. Titre de tuile = `visualization_settings."card.title"`. Tuiles texte/section = `card_id:null` + `visualization_settings.text` + `virtual_card`. Filtres dropdown = `values_query_type:"list", values_source_type:"static-list", values_source_config.values:[...]`.
- **Persistance des modèles** : activée globalement + sur DB 144 (le 2026-05-29). Après un rebuild de modèle, la table persistée se re-matérialise au cycle suivant → perf redevient bonne.
- **Pas de pays/géo réel GSC** : `gsc__site_keyword`/`country_device` ont `country='other'` pour Manucurist → géo = section de site uniquement.
- **QA navigateur** : Metabase exige une **session connectée dans Chrome** (SSO Google) ; je ne saisis pas d'identifiants — demander à l'utilisateur de se connecter. Ne jamais cliquer « Se connecter avec Google » si ça demande un mot de passe.
- **Erreur transitoire « There was a problem displaying this chart »** sur la grille Positions (#48634, la + lourde : joints SERP+GSC) au **cold-load concurrent** des cartes → **recharger** la résout (vu en QA 2026-06-17). Ne pas conclure trop vite à une régression ; vérifier d'abord après reload. Renforce le besoin d'activer/fiabiliser la persistance des modèles.

## 10. Inventaire des scripts (`scripts/`)
Actuels / source de vérité V3 :
- `build_seo_monitoring_v3.py` — modèle kw #48633 (relance = rebuild+PUT).
- `build_seo_pages_model.py` — modèle pages #49062.
- `build_seo_saisonnalite.py` — modèle #49425 + pivot #49426.
- `build_seo_dashboard_v3.py` — assemble tuiles + 7 filtres + liens saisonnalité (#25137).
- `probe_v3.py` / `probe_v2.py` — découverte data (réutilisables comme gabarits de sondage).
Historiques (V1/V2, cartes archivées) : `build_seo_monitoring.py`, `build_seo_grid.py`, `build_seo_dashboard.py`, `build_seo_monitoring_v2.py`, `build_seo_dashboard_v2.py`.
#32496 : `apply_fixes_32496.py`, `serp_difftest.py`.
(NB : `scripts/` contient aussi des scripts d'AUTRES projets — find_dupes, prune_unused, reorg_*, rename_* — ne pas confondre.)

## 11. Schéma data utile (Snowflake, db 144)
- `google_serp.serp_requests` (VIEW : client_id, corpus_name, category, keyword, language, zone, domain) ⋈ `serp_history` ⋈ `serp__keyword_metrics` (keyword, url, request_date, rank_absolute, rank_group, type) → positions client.
- `google_keyword_planner.kp__keyword_monthly_metrics` (keyword, category, language, zone, month 'YYYY-MM', avg_monthly_searches, adjusted_avg_searches) → volumes (lague ~2 mois).
- `google_search_console.gsc__page_keyword_daily_metrics` (client_name, page, country['other'], keyword, date, clicks, impressions, position) → clics/impressions/position par page+kw.
- `google_search_console.gsc__brand_keywords` (client_name, keyword) → radicaux marque.
- `metabase_filters.serp_ctr_scenarios` (name, position 0-100, ctr_low/medium/high) → CTR par position.
- `utils.clients` (id, name) — Manucurist id = `recwU4Px1lyw6vq16`.
