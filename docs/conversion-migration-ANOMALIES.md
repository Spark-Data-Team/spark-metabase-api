# Anomalies consolidées — migration conversions étape 3 (A→Z parallèle)

> **Fichier APPEND-ONLY (jamais écrasé).** Chaque lot ajoute ses entrées datées.
> Anomalies = bugs outillage, surprises par client, items nécessitant une décision humaine.
> Les conversions non-tranchables par client vivent dans `migration/CONVERSIONS-A-TRANCHER.csv`
> (→ team lead) ; ici on ne fait que les *référencer*.

---

## Lot 1 — 2026-06-26 · AMV Assurance, Be Radiance, Ecopia, Exaprint (validation mécanique)

### 🐛 TOOLING — corrigé
- **`swap_tables.py:62` `card_rows` — crash `AttributeError: 'NoneType'.upper()`** quand un dashcard
  table n'a **aucune colonne visible activée** (`old_dim = None` ligne 112) → `card_rows(..., None)`.
  Conséquence grave : le crash tuait **toute l'étape swap du dashboard** (et `migrate_client.py` **jette
  le stderr**, donc c'était invisible — la sortie ne montrait que la ligne d'auth).
  **FIX** : guard `if dim_col is None: return None` en tête de `card_rows` (carte non alignable →
  non vérifiable → **gardée sur l'ancien et signalée**, au lieu de crasher). Régression :
  `tests/test_swap_tables.py`. **Suite 189 verte.** Détecté sur Be Radiance, vérifié post-fix en
  dry-run (0/1 swappable, l'unique table = slots non mappés).

### ⚠️ PROCESS
- **Subagent Be Radiance a lancé `migrate_client.py` 2×** → 2 copies (26425, 26428) + 2 entrées shard.
  Corrigé par le central : shard dédoublonné (garde **26428**), copie orpheline **26425 archivée**.
  → Consigne subagent à durcir : « **UNE seule exécution** de la commande ».

### 🔎 DIAGNOSTIC — recommandation (non bloquant)
- **`migrate_client.py:run_step` jette le stderr** et ne montre que les 4 dernières lignes de stdout.
  Effet : un `bascule` exit≠0 **bénin** (« Pas de param 'Time period' — rien à basculer ») et un **vrai
  crash** (swap None-dim) sont indistinguables dans la sortie. **Reco scale-up** : capturer aussi le
  tail de stderr quand `returncode≠0`, pour que les crashes restent visibles. (Pas encore appliqué.)

### 👤 GABY — déjà dans `CONVERSIONS-A-TRANCHER.csv` (aucun mapping inventé)
- **Be Radiance** : slots 0 & 1 `__UNMAPPED__` → 14 tuiles conv restées sur l'ancien (363 CR, 58 Revenue,
  706, 382 Add-to-carts…). `NON_MAPPE_UTILISE` ×2 déjà au CSV.
- **Ecopia** : slot 0 `__CONFLICT__` (Main = « Marketing Qualified Leads **ou** Offline sales »),
  slot 2 `__UNMAPPED__` → `CONFLIT` + `PAIRING_AMBIGU` + `NON_MAPPE_UTILISE` déjà au CSV. (slot 1→Leads OK.)

### ✅ Résultat lot 1
| Client | Copie (14016) | slots mappés | Issue | État |
|---|---|---|---|---|
| AMV Assurance | 26424 | 0→Leads | tuile CPC → fallback 49953 | **visible-100%** ✅ |
| Exaprint | 26427 | 0→Purchases, 1→Custom 1 | 4 tuiles GA4 → fallback 49954/55/56 | **visible-100%** ✅ |
| Be Radiance | 26428 | 0,1 non mappés | 14 tuiles sur l'ancien | ⏳ **Gaby** |
| Ecopia | 26426 | 0 conflit, 2 non mappé | tuiles sur l'ancien | ⏳ **Gaby** |

### 🐛 TOOLING — trouvés EN REVUE USER (corrigés)
- **Tuile « visualizer » vide** (AMV, tuile « Évolution du CPC | client vs industry vs global »).
  Un dashcard *visualizer* combine des colonnes de cartes sources via
  `visualization.columnValuesMapping[*].sourceId = "card:<id>"`. Les 4 étapes qui repointent un
  dashcard (`reuse`, `swap`, `#87`, `fallback`) changeaient `card_id` mais **pas** ces `sourceId`
  → le visualizer continuait de sourcer l'ANCIENNE carte positionnelle → **tuile vide**.
  **FIX** : helper pur **`conv_lib.repoint_visualizer_source(viz, old, new)`** (réécrit le token
  exact `"card:<old>"`→`"card:<new>"`, no-op sinon) câblé dans **`generate_fallback`** (cas confirmé)
  et **`special_cards_lib.rewrite_selector_dashcard`** (#87, défensif). `reuse`/`swap` reconstruisent
  la viz (KEEP_VIZ / table.columns) donc droppent le visualizer → non concernés (note : un visualizer
  passant par reuse devient une tuile simple — perte du *combine*, à surveiller si ça se présente).
  4 tests TDD `tests/test_conv_lib.py`. **Copie 26424 patchée** (sourceId→`card:49953`, qui renvoie
  bien 3 lignes AMV/Industry/Global). **Suite 193 verte.**
- **Préfixe « [migré] » visible dans le titre des tuiles** (Exaprint « [migré] Conversions by medium
  (GA4) »). `generate_card` nommait la carte `[migré] <nom>` → la tuile l'affichait au consultant.
  **FIX** : nom propre `<nom>` (provenance = collection dédiée 14115 + registre). Aucune dépendance
  logique au préfixe (vérifié). **Cartes lot 1 renommées** (49953-62, 49954/55/56). Tuiles propres.
- **Titre humain corrompu par la substitution** (Exaprint : tuile affichait « PURCHASES » en gros).
  L'original avait `card.title = "Conversions"` ; `apply_substitution` réécrivait le **JSON viz entier**
  → le libellé « Conversions » devenait « PURCHASES » (majuscules). **FIX** : helper pur
  **`conv_lib.substitute_viz(viz, sub_map)`** (récursif : substitue les RÉFS de colonnes — graph.metrics,
  clés series/column_settings, scalar.field, table.columns[].name — mais PRÉSERVE les libellés humains :
  `card.title`, titres d'axes/séries, `column_title`). Câblé dans `generate_card` + `generate_fallback`.
  2 tests TDD. **Cartes lot 1 réparées** (viz recalculée depuis l'original ; 49954 card.title
  « PURCHASES »→« Conversions », mesure toujours `purchases`). **Suite 195 verte.**

### 🏷️ TITRE DES TUILES — générique → conversion nommée (décision user 2026-06-26)
- Demande user : une tuile de conversion migrée doit nommer la **vraie conversion** (« Purchases »),
  pas le générique « Conversions » ni le brut « PURCHASES ». **Règle retenue** (« Générique→nommée,
  garder le custom ») : si `card.title` ∈ {Conversions, Conversion, Main conversion} **et** la tuile
  mesure UNE seule conversion nommée → titre = nom d'affichage Airtable (`cmap[_slot_of(col)]`, ex.
  « Purchases », « Leads », « Custom 1 ») ; sinon **préservé** (libellés métier « Demandes de devis »,
  taux « Conversion rate »…). Helpers purs **`conv_lib.conversion_display_names` + `relabel_conversion_title`**
  (4 tests TDD), câblés dans `generate_card` (param `cmap`) + `generate_fallback` (carte ET override
  dashcard). **Lot 1 rétro-appliqué** : 49954 « Conversions »→« Purchases » ; 49955/49953/Ecopia préservés.
  **Suite 201 verte.**

---

## Lot 2 — 2026-06-26 · Toploc, Komilfo, Solarock, Osée, CapCar (1er lot avec tous les fixes)

### ✅ Résultat
- **Komilfo** (26458, 26463) & **Osée** (26460, 26465) : **visible-100%** + temporal-unit. Propres.
- **Toploc** (26457) : 5 migrées, bascule ✅ ; résidu **34248** (voir patron table-large).
- **Solarock** (26459, 26462) : résidu carte adset (table-large) ; 26459 bascule ✅, 26462 sans filtre temps.
- **CapCar** (26461, 26464, 26466) : résidu **Gaby** (slot 0 `__CONFLICT__`, slot 1 « Content views OR View
  Item ») — **déjà au CSV** (CONFLIT + INDECIS). 26461 bascule ✅, 26464 bloqué (3 GA4 dimension), 26466 sans filtre.
- **Bascule `string/=` validée** sur tout le lot (le fix lot-1 marche en série).

### 🔎 PATRON RÉCURRENT À TRANCHER — tables « performances by date/adset » LARGES
- Ex. Toploc **34248** « Performances by date » (display table, breakdown=date) référence **les 20 slots**
  positionnels (CONVERSIONS, CONVERSIONS_1..19 + CONVERSION_*_VALUE). Toploc n'a que 2 conversions réelles
  (slots 0,1) → sub_map mappe 4 colonnes, **36 restent non mappées** → fallback généré **rendu KO → archivé**
  → tuile reste sur l'ancien. Même chose pour les cartes **adset** Solarock (slots 1-6 non mappés).
- **Ce n'est PAS du Gaby** (les slots non utilisés ne sont pas de vraies conversions à trancher) ni une
  régression (chemin SQL inchangé). C'est une **décision de stratégie** : comment migrer une table qui
  déverse les 20 slots quand le client en a 2-3 ? → **décision user 2026-06-26 : « garder seulement les
  conversions réelles, masquer les colonnes positionnelles vides ».**
- 🐛 **Sous-cause révélée = faux-positif `render_ok`** : la carte large 34248 a un tag requis `bonus`
  (sans défaut). `render_ok` la testait via `/api/dataset` → « **missing required parameters: bonus** » →
  ne matchait QUE « pick a value » / « before this query can run » → la croyait erreur SQL → **archivait
  une carte saine**. **FIX** : `conv_lib.is_required_param_error` (ajoute « missing required parameter »),
  2 tests TDD, câblé dans `render_ok`. **Suite 203 verte.** (Aide tout card à param requis, pas que les
  tables larges.) ⏳ RESTE à construire (brique b) : masquer/retirer les colonnes positionnelles non
  mappées des tables larges pour atteindre true-100% + affichage propre.

### ⚠️ PROCESS — subagent qui « backgrounde »
- Le subagent **Osée** a lancé `migrate_client.py` en **arrière-plan** + armé un monitor, puis a rendu la
  main AVANT la fin → pas de rapport structuré. Le travail s'est bien terminé (shard complet, 2 copies
  100%), état **reconstruit en central**. → Consigne subagent durcie : **FOREGROUND, attendre la fin,
  PUIS reporter** (ne jamais backgrounder).

### 🔧 TOOLING — point aveugle stderr levé
- `migrate_client.py:run_step` jetait le stderr → un `bascule` exit≠0 bénin (« Pas de param Time period »)
  et un vrai crash étaient indistinguables (cf. doute du subagent CapCar 26466). **FIX** : `run_step`
  remonte désormais le tail du stderr quand `returncode≠0`. (CapCar 26466 confirmé bénin : pas de filtre temps.)

### 🧩 TABLES LARGES — le mécanisme EXISTAIT (swap_tables), 3 trous bouchés (user 2026-06-26)
- Intuition user confirmée : `swap_tables` fait DÉJÀ « garder seulement les conv réelles » (reconstruit
  `table.columns` : colonnes mappées activées, reste désactivé, ligne 181-190). Il ne s'enclenchait pas sur
  les tables larges à cause de **3 trous** (corrigés) :
  1. **`old_vis` vide** (table sans `table.columns` explicite → affiche tout) → 0 colonne à mapper. FIX :
     fallback sur `result_metadata` + flag `implicit_cols`. (34248 : 0 → **19 colonnes mappées**.)
  2. **non mappées = blocage dur** → mais pour une table implicite ce sont les slots positionnels inutilisés
     à MASQUER. FIX : `hard = unmapped AND not implicit_cols`.
  3. **`old_dim` = 1ère colonne** (faux quand implicite : 'RANK') + **param NUMBER requis `bonus`** sans
     défaut bloquait la vérif. FIX : `old_dim` = colonne mappant vers dim_new ; remplir les tags number
     requis avec 0. (suite 203 verte ; changements main() validés live, pas de régression.)
- 🚨 **CE QUE LA VÉRIF A ATTRAPÉ (Toploc 34248)** : une fois enclenchée, la vérif valeur-par-valeur montre
  **PURCHASES (slot 0) identique** (6=6, 1=1, 5=5, 3=3) mais **LEADS (slot 1) DIFFÉRENT** (18→12, 38→25,
  33→23, 36→23 ; ~30% plus bas, systématique). → swap **bloqué à juste titre** (écart réel, pas cosmétique).
  Question DATA ouverte : le mapping Toploc slot 1 = « Leads » est-il correct ? « Leads » nommé compté
  autrement (brand ? attribution ?) → à investiguer / team lead. 34248 reste sur l'ancien (correct).
  - **INVESTIGATION (user « garder + investiguer ») — verdict = question DATA, pas un bug** :
    · PAS le brand : les DEUX cartes ignorent `brand_included` (CONVERSIONS_1=36 et CURRENT_LEADS=23 constants).
    · PAS un libellé : mêmes semaines (W18-W22), slot 0 Purchases identique (3,1,5,5,6 = exact).
    · **AUCUNE colonne nommée ne vaut 36** (W22) : compteurs nommés = Purchases 3, Leads 23, Add-to-carts 234,
      MQL/SQL/Custom 1-15 = 0. Le positionnel slot 1 (36) ≠ tout nommé ; Leads (23) = le plus proche, ~35% bas.
    · → **DÉFINITION** : « Leads » nommé compte autrement que le positionnel `CONVERSIONS_1` de Toploc.
      **TEAM LEAD/DATA** : slot 1 = bien « Leads » ? écart 36→23 attendu ? 34248 reste sur l'ancien (correct).
    · Leçon : le slot→nommé n'est PAS toujours un rename iso-valeur — la vérif par-tuile est essentielle.
- ⚠️ **POLICY `--accept-diffs`** (utilisé par migrate_client) : forcerait ce swap malgré l'écart LEADS 30%.
  ✅ **TRANCHÉ + IMPLÉMENTÉ (user 2026-06-26 « on bloque et on review »)** : tout ÉCART DE VALEUR bloque
  désormais le swap → REVUE (`blocked = hard or value_diffs` ; `--accept-diffs` ne contourne plus les
  valeurs). + `conv_lib.normalize_period_label` aligne les formats de période ('2026 - W22' vs '2026_22')
  pour que la compare cellule détecte les vrais écarts (sinon masqués en « (lignes) »). Validé sur Toploc :
  swap bloqué, écart visible « CONVERSIONS_1→CURRENT_LEADS 38 vs 25 ». Suite **204 verte**. Routage revue
  (user = data) : mapping vraiment différent → consultant ; bug data → user.

### ⏳ GAP À TRANCHER — filtre « Time period » non basculé en temporal-unit (AMV, « pour info » user)
- `bascule_lib._old_time_param` ne détecte le filtre que si `type == "category"` (`bascule_lib.py:36`).
  AMV (et probablement d'autres) a un filtre « Time period » de type **`string/=`** (même filtre,
  type plus récent) → **ignoré** → pas de bascule temporal-unit. La migration **conversions** d'AMV
  reste complète (Iron Law OK), mais le filtre période reste l'ancien. **Fix candidat** : élargir la
  détection à `category` **et** `string/=` (par slug/nom `time_period` / « time period »), + re-run
  bascule. **Impact potentiellement large** (nombre de dashboards en `string/=` inconnu) → décision user.
  - ✅ **CORRIGÉ (user 2026-06-26 « corriger maintenant »)** : `bascule_lib.find_time_param` accepte
    désormais `category|string/=` (`OLD_TIME_TYPES`), 2 tests TDD. **Validé sur AMV 26424** : param
    « Time period » → **temporal-unit (month)**, 4 cartes by-date auto-préparées (49986-89), swap avec
    **valeurs week+month identiques** (vérif différentielle OK), « Anomalies résiduelles : AUCUNE ».
    Suite **197 verte**. ⚠️ effet de bord mineur : la tuile **benchmark CPC** (49953, tag `time_periods`
    pluriel ≠ temporal-unit) voit son câblage temps nettoyé → s'affiche en mensuel mais ne suit plus le
    sélecteur de granularité (rend OK). Gap benchmark/visualizer × bascule à traiter si ça gêne.

---

## Lot 3 — 2026-06-27 · Dedikazio, Dermalogica, Shining, TuneCore, Zeplug, Violette_FR

### ✅ Résultat
- **Dedikazio** (26490) & **Dermalogica** (26491) : **visible-100%** (dashboards GA4 mono-conversion ; 3 tuiles
  GA4 → fallback, bascule temporal-unit ✅). Propres.
- **Shining** (26492), **TuneCore** (26494), **Zeplug** (26493), **Violette_FR** (26495 GA4 + 26496 Global) :
  slots réels migrés + bascule TU, MAIS **résidu table-large** (voir ci-dessous). Zeplug : pas de filtre période.

### 🔎 TABLE-LARGE = PATRON DOMINANT (et un sous-cas neuf : les cartes « Synthèse des performances »)
- Lot 3 confirme : dès qu'un dashboard porte une table « Synthèse des performances » / « Performances by
  date/campaign », elle référence les **20 slots positionnels** (CONVERSIONS, CONVERSIONS_1..19,
  CONVERSION_*_VALUE). Un client à 1-3 conversions réelles laisse 15-18 colonnes non mappées → reste sur
  l'ancien (Iron Law non atteint). **Touche quasi tout client « réel »** (seuls les dashboards GA4
  mono-conversion passent visible-100% direct).
- **NOUVEAU sous-cas** : les cartes **« Synthèse des performances »** passent par **`generate_fallback`** (pas
  `swap_tables`). La carte générée substitue les slots MAPPÉS mais **GARDE les positionnels non mappés** dans le
  SQL → elle **rend OK** (donc non archivée) → le détecteur Iron-Law la flagge « sur l'ancien ». Ex : TuneCore
  5709/29059/gén.**50107** ; Violette **50099 ; 50110-50114** ; Shining **50104** (791) ; Zeplug **50087** (312).
- Le fix lot-2 (`swap_tables` 3 trous bouchés) couvre les tables **breakdown explicites**, PAS le chemin
  `generate_fallback` des « Synthèse ». → **brique b** = masquer/retirer les colonnes positionnelles non mappées
  des cartes générées (comme `swap_tables` reconstruit `table.columns`). **C'est désormais le bottleneck #1** du
  balayage. À trancher : (a) router ces cartes vers `swap_tables` (réutiliser le masquage existant) ou (b)
  ajouter le masquage dans `generate_fallback`.
- ⚠️ **Ce n'est PAS du Gaby** (le mapping client est correct) **ni une régression** (chemin SQL inchangé,
  valeurs des slots mappés vérifiées par tuile). C'est la **brique b** de la décision user 2026-06-26
  (« garder seulement les conversions réelles, masquer les colonnes positionnelles vides »), pas encore codée
  pour le chemin generate_fallback.

### ⚠️ PROCESS — backgrounding récidive (TuneCore) + interruption (Violette)
- Le subagent **TuneCore** a de nouveau **BACKGROUNDÉ** la commande + armé un monitor + rendu la main avant la
  fin (**3e occurrence** après Osée lot 2). Le travail s'est quand même terminé (copie 26494 + bascule
  `verified:true`). **Violette** interrompue par l'user **en phase RAPPORT** (la migration était déjà finie :
  2 copies + fallbacks + bascule écrits avant l'interruption).
- État reconstruit **en CENTRAL** via un détecteur Iron-Law standalone (même logique que `generate_fallback`
  lignes 156-160 : `old_conversion_columns` sur chaque carte du dashboard, hors `replacement_ids`). **Pas de
  re-run** (re-lancer `migrate_client` aurait créé des copies doublons type Be Radiance) ; vérifié : 1 copie/
  dashboard dans 14016, **zéro doublon**.
- Reco : le harnais subagent devrait **interdire le background** (wrapper « 1 commande foreground bloquante »
  plutôt que de compter sur la consigne en prose, qui a échoué 3×).

### 🧩 BRIQUE B — CODÉE (2026-06-27, après diagnostic) : retrait SQL des slots non mappés
- **Diagnostic affiné** (correction du modèle initial) : « masquer les colonnes » (affichage `table.columns`)
  **ne satisfait PAS l'Iron Law** — le détecteur teste le **SQL** ; tant que la carte `SELECT`-e les colonnes
  positionnelles, elle cassera quand on les retirera des tables source. La vraie brique b = **retirer les
  expressions SELECT des slots NON mappés du SQL** déjà substitué. Et c'est **général** (1 fix couvre social-ad,
  campaign, GA4, multi-dim — pas seulement « table large »), car purement textuel.
- **Implémentation TDD** : `conv_lib.drop_conversion_selects(sql)` (pur) + `conv_lib._select_item_alias` —
  retire par LIGNE (style cartes Spark = 1 item SELECT/ligne) toute ligne dont `old_conversion_columns` est non
  vide (inclut les dérivés mono-ligne type `cac_N` qui calculent `SUM(conversions_N)`), corrige la virgule
  pendante avant FROM/UNION. **Câblé dans `migrate_dashboard_full.generate_card`** (après `apply_substitution`).
  5 tests TDD, **suite 204→209**.
- **SELF-SAFE (zéro régression)** : si une ligne retirée expose un **alias dérivé** encore référencé par une
  ligne gardée (cartes **« KPIs evolution »** : `conversions_N` → `current_conversions_N`/`previous_…`/
  `*_evolution` sur plusieurs CTE, avec CASE **multi-lignes** que le découpage par ligne ne sait pas suivre) →
  **NO-OP** (on garde la version substituée = comportement actuel). Filet ultime en aval inchangé : `render_ok`
  archive tout SQL cassé.
- **Vérif live** : Violette 5161 (social-ad simple) → drop appliqué, **0 positionnelle**, rendu OK, **valeur
  identique** (CONVERSIONS→PURCHASES 6910.42 = 6910.42). TuneCore 5709 (KPIs-evolution) → **no-op**, rend OK,
  positionnel conservé (= aujourd'hui). 5 « solved » du lot 3 re-rendues OK via `/api/dataset` (familles
  diverses : campaign, GA4 source/medium, by ad name, creative type, 2-dim).
- **Impact mesuré (dry, sans mutation) sur le résidu du lot 3 : 5/10 tuiles deviennent Iron-Law-clean**
  (Zeplug 50087 ; Violette 50099/50111/50112/50113). **5 différées** = KPIs-evolution / réfs dérivées
  (Shining 50104 ; TuneCore 5709/29059 ; Violette 50114/50110). Les **futurs lots en bénéficient
  automatiquement** (brique b est dans `generate_card`).
- ⏳ **RESTE (follow-on)** : les cartes **KPIs-evolution** (current/previous/evolution, CASE multi-lignes,
  N niveaux de CTE) nécessitent soit un parseur d'items SELECT multi-lignes avec **cascade d'alias** (fixpoint),
  soit une **carte générique dédiée** « par X — KPIs evolution » (comme la famille mixte pour les tables simples).
  Décision user requise pour prioriser. Tant que non fait : elles restent sur l'ancien (no-op sûr).

---

## Lot 4 — 2026-06-27 · Lutèce, France Toner, Pulse Protein, My Blend, Sports d'époque, Vestiaire Collective

### ✅ Résultat (1er lot AVEC brique b dès la 1re passe)
- **7/21 dashboards visible-100% en une seule passe** (Lutèce 26523 ; France Toner 26532/26533 ; Pulse 26529 ;
  My Blend 26531 ; Sports 26527/26534). Brique b nettoie les tables simples sans intervention. Merge OK
  (tracker 50→71, +42 cartes générées, 168 total).
- Bonus : **#87 déployé + vérifié** sur Sports 26534 (cost fidèle, purchases/clicks injectés).

### 🔎 DONNÉE CLÉ — la KPIs-evolution est le RÉSIDU DOMINANT (prévalence confirmée élevée)
- Sur tous les clients à perf-tables, le résidu restant est **massivement** des cartes « **KPIs … w/ evolution** »
  (current/previous/evolution) : **Vestiaire 5/5 dashboards** (28126/28154/28157/28161, KPIs multi-dim),
  Sports (50202/50203), My Blend (50173/50176/5940/5709), France Toner (50175), Pulse (50226).
- → **Justifie le follow-on KPIs-evolution** (cf. entrée BRIQUE B « RESTE »). C'est désormais le **bottleneck #1**
  pour atteindre strict-100% sur les clients réels. À trancher : **carte(s) générique(s) dédiée(s) « par X — KPIs
  evolution »** (route via swap_tables, SQL propre garanti) **vs parseur cascade multi-lignes**. La carte
  générique est plus sûre (pas de chirurgie SQL sur 645 lignes) mais demande de créer la famille dans 11673.

### 🧩 Autres résidus (minoritaires, non KPIs-evolution)
- **Swaps bloqués sur écart-valeur → REVUE** (policy user 2026-06-26) : Pulse 26525 (écart de **lignes** :
  jeux de campagnes différents DISPLAY/FB/PMAX…), Pulse 26536 (écart **valeur** ~15-18% sur
  AVG_PURCHASES_VALUE / PURCHASES_VALUE). Routage : mapping vraiment différent → consultant ; bug data → user.
- **Fallback KO archivé** : Pulse 15402 « PMax search terms performances » (généré 50170 → rendu KO → archivé →
  reste sur l'ancien ; pas de régression).
- **Stragglers combos/2-dim** : My Blend 26537 cartes **25 « Conversions by channel »** + **55 « Revenue by
  channel »** (probables combos multi-conversion / 2-dim, tâche #4 RESUME, pas encore outillée).

### ⚠️ PROCESS — le Bash AUTO-BACKGROUNDE les commandes longues (cause racine du « backgrounding »)
- Découverte : ce n'est PAS un choix des subagents — le **Bash tool met en arrière-plan** les commandes longues
  et notifie à la fin. Les subagents qui « rendaient la main trop tôt » subissaient ça. Effet de bord : le
  subagent **My Blend** a vu son run coupé à **3/4 dashboards** (timeout d'attente côté subagent) ; le 4e
  (22167 → copie **26543**, « Campagnes | Séfia ») a été **complété en central** (même shard, `--dashboards 22167`,
  pas de doublon). Aucun process actif au moment du merge (vérifié).
- Reco : pour les clients à **≥5 dashboards** (ou run long), soit découper en sous-lots de dashboards, soit
  prévoir la **reprise en central par dashboard manquant** (ce qui a marché ici). État toujours reconstructible
  via le détecteur Iron-Law standalone + le shard.

---

## 2026-06-28 · Brique b CASCADE (KPIs-evolution) + GARDE-FOU VALEUR + règle Vestiaire/Polène

### 🧩 Brique b — CASCADE multi-lignes (follow-on KPIs-evolution CODÉ)
- `conv_lib.drop_conversion_selects` ré-écrit en **parseur SELECT-aware + cascade d'alias (fixpoint)** :
  parse les listes SELECT (entre `SELECT` et son `FROM` au même niveau de parenthèses), découpe les items
  sur les virgules de niveau 0 (items CASE **multi-lignes** gérés d'un bloc), retire tout item référençant
  un nom « tué », et **propage** : l'alias d'un item retiré rejoint l'ensemble tué → retire aussi
  `current_conversions_N` / `previous_…` / `*_evolution` / `cac_N` / `cr_N` sur tous les CTE. Helpers :
  `_mask_sql` (littéraux + commentaires), `_select_spans`, `_split_top_level`, `_refs_any`, `_select_item_alias`.
- Self-safe (pur, zéro régression) : no-op si liste vidée / positionnelle restante / **réf pendante** vers un
  alias supprimé. Filet aval inchangé (render_ok). **+3 tests TDD** (passthrough dérivé, CASE multi-lignes,
  préservation du cascade d'un slot MAPPÉ).
- Vérif live : **My Blend 5940** (KPIs-evolution) → 0 positionnelle, rendu OK, valeur exacte (114.6) ✅ ;
  cascade **value-preserving** (substitué-seul == substitué+cascade sur TuneCore : 11961.14 dans les deux).
- Limite connue : **Vestiaire** échoue au rendu sur `ambiguous column SIGN_UPS` = bug de **substitution**
  préexistant (le nommé existe dans 2 tables jointes), indépendant de la cascade (Vestiaire désormais exclu).

### 🛡️ GARDE-FOU VALEUR dans generate_fallback (policy user « écart de valeur → revue », enfin appliquée)
- **Découverte** : `generate_fallback` migrait les substitutions SANS vérifier les valeurs (≠ swap_tables).
  Quand le nommé compte AUTREMENT que le positionnel, la valeur changeait **silencieusement** (déjà le cas
  sur des cartes des lots 1-4). Ex. **TuneCore 5709** : CONVERSIONS(positionnel) 12381 vs PURCHASES(nommé)
  11961 ; CONVERSIONS_1 10085 vs SIGN_UPS 8809 — **même classe que Toploc** (définition du nommé ≠ positionnel,
  question DATA, pas un bug outil).
- **Fix** : `conv_lib.value_diffs` (pur, compare les **SOMMES** par colonne → indépendant de l'ordre ; +6 tests)
  + `generate_fallback.value_review` (lance carte originale & générée, compare). Écart → carte archivée, tuile
  **gardée sur l'ancien**, rapport **« ⚠️ À REVOIR (écart valeur …) »**. Non vérifiable (param requis) → bénéfice
  du doute (comme render_ok).
- **Subtilité corrigée** : comparer via `sub_map` (CONVERSIONS→PURCHASES) ratait les cartes KPIs-evolution
  (colonne de sortie = `current_conversions`, alias préservé). Donc on compare **toutes les colonnes communes**
  (nom préservé) **+** les renommées (sub_map). Les non-conversion (cost/clicks) ont une somme identique → 0
  faux positif. Vérifié : **TuneCore BLOQUÉ→revue** (CAC/CONV_VALUE dérivés divergent), My Blend & Violette
  **migrés (fidèles)**. **Suite 217 verte.**
- ⚠️ Effet : sur les clients où positionnel≠nommé, plus de cartes resteront « À REVOIR » (= comportement voulu,
  on ne pousse plus de valeurs douteuses). Routage : mapping vraiment différent → consultant ; bug data → user.

### 🚫 RÈGLE SPÉCIALE — Vestiaire Collective & Polène EXCLUS du balayage (user)
- Décision : on ne les balaie pas (l'user les gère à la main). Faits : worklist 100→98, tracker −5 (Vestiaire),
  generated-cards −8, shard sorti de `parallel/` → `_excluded_shards/`. **5 copies Vestiaire (lot 4) + 8 cartes
  générées ARCHIVÉES.** cf. memory `conv-migration-special-no-copy-clients`.
