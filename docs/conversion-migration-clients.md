# Migration conversions — SUIVI PAR CLIENT (état vivant)

> Mis à jour : **2026-06-15**. Une ligne par client. Tout est sur des **COPIES** (les
> originaux + liens de partage Nanga ne sont JAMAIS touchés tant que non validé).
> Voir `conversion-migration-HANDOFF.md` pour le mode d'emploi des outils.
>
> **ÉTAT GLOBAL 2026-06-15 : les 4 clients de Gaby sont migrés sur copies** (Goodiespub, F&S, Shopinvest,
> Rivadouce — chaîne complète : reuse → swap_tables → bascule → generate_fallback → polish, via l'orchestrateur
> `scripts/migrate_client.py`). Gaby a validé l'ensemble SAUF le rendu (corrigé depuis : voir LEÇON permissions
> ci-dessous). Non-100% résiduel = GA4 (data amont), conflits de slots (Gaby), slots non mappés VISIBLES sur
> gros tableaux (Gaby doit mapper), ~3 cartes « filter choice »/edge render-KO (à déboguer).

## 🔑 LEÇON CRITIQUE — PERMISSIONS DE COLLECTION (2026-06-15)
Les cartes migrées (générées + copies temporal-unit) étaient dans **13885/13950 sous 13851 « ZZ - Migration
test »** = collection NON partagée → les consultants (Gaby) voyaient les **tuiles VIDES** (« graphes n'affichent
rien » sur Shopinvest Focus Marge ; les scalaires en 11673 s'affichaient car 11673 est partagée). Les cartes
marchent (admin les voit) — c'était purement un **accès collection**.
**FIX appliqué (user a choisi option b)** : 89 cartes déplacées → sous-collection **« Conversions migrées »**
dans CHAQUE collection client (sous /317/, accessible) : PN 13983, Goodiespub 13984, Father&Sons 13985,
Shopinvest 13986, Rivadouce 13987 ; + 7 cartes **génériques partagées** (Cost/Clicks by date, multi-clients)
→ coll **13988** sous 11673. Vérifié : 0 tuile ne pointe plus vers le sandbox.
**RÈGLE pour la suite** : les cartes migrées DOIVENT vivre dans une collection lisible par le consultant
(arbre client /317/ ou 11673), JAMAIS dans un sandbox /13851/. À intégrer dans generate_fallback /
convert_card (créer/cibler la bonne collection dès la génération). (orphelins restants dans 13885/13950 =
non utilisés, à archiver plus tard).

## ⏳ EN ATTENTE / À RELANCER (ne pas oublier)
- **🔴 purchases META sous-compte — CAUSE CONFIRMÉE par Gaby + vérifiée au compte près (2026-06-15).**
  C'est un trou de **mapping/config Airtable**, pas un bug outil ni une mauvaise migration :
  · **Rivadouce / FB −135 = EXACTEMENT** Milton-Main (old 125, new **0**) + Auriège-Main (old 10, new 0) :
    leur event meta omni_purchase a type=Main mais **new_type VIDE** → compté dans l'ancien `conversions`,
    absent du nouveau `purchases`. (Rivadouce Meta, lui, est mappé → delta 0.) → Gaby remplit new_type=Purchases.
  · **Shopinvest / social −135 ≈** 3 Suisses (−104, seul compte meta, events purchase/unique_purchase/
    onsite_web_purchase vides en type ET new_type + compte retrieve_account_data=0 non ingéré) + petits
    deltas sur Bijourama/MenCorner/Lemon Curve/Comptoir/Fitancy (−32). → corriger Airtable/config compte.
  · **F&S Pinterest (0 achats)** : la ligne checkout EST bien mappée (type=Main, new_type=Purchases — vérifié)
    → le 0 n'est PAS un trou de mapping : soit pas re-synchronisé, soit aucun volume checkout ne remonte.
    Cause AVAL (sync/volume), à creuser côté data.
  → Une fois ces fixes Airtable/sync faits par Gaby/data, les 2 clients migrent proprement (outil OK).
- **Conflits de mapping slots secondaires** (Gaby) : Goodiespub slot 2 (réglé), Father&Sons slot 1,
  Rivadouce slots 1 & 2 (+ slot 3 « Content views OR View Item » ambigu). Même type : un slot positionnel
  mélange plusieurs events/conversions nommées. Trancher par slot et par client.
- **Father and Sons** — relancer **Gaby** sur le conflit slot 1 (1ère conversion mélange tiktok `follows` /
  pinterest `page_visit` / meta `page_engagement` → conversions nommées différentes). Idem Goodiespub : quelle
  conversion nommée pour la « 1ère conversion » ? (peu de tuiles concernées ; non bloquant pour les 3 faits.)
- ✅ **ONGLETS désormais SUPPORTÉS** (codé 2026-06-13, testé sur F&S Shopify 22860→25836 : PUT OK, onglets
  intacts). Appariement par index d'onglet (les ids diffèrent entre source et copie). Gaps restants :
  carte « filter choice » (sélecteur de métrique : convert_card/reuse ne sait pas la vérifier) ;
  trou data Pinterest (purchases pinterest = 0 dans le neuf, cf. F&S Sponso) → Gaby/data.

## Statuts
- ✅ **fait** : copies migrées + basculées, vérifiées.
- 🟡 **en cours** / partiel.
- ⛔ **bloqué** (raison).
- ⬜ **à faire**.

## Étape 1 — Pilote Pro Nutrition (validé par Lucas ✅)

| Dashboard | Original | Copie | État | Notes |
|---|---|---|---|---|
| Home | 14118 | 25566 | ✅ basculé | 1/1 tuile |
| Ecommerce Sopral | 16557 | 25567 | ✅ basculé | 6/6 tuiles |
| Global perf (14016) | 14016 | 25632 | ✅ basculé | 14/14 tuiles + 3 tableaux (49098/49104/49129) |

Mapping PN : `{0:Purchases, 1:Custom 1, 3:Custom 2}`. Écart connu montré à Lucas : tableau by-network,
1 campagne FB (+2 achats) car filtre `cost!=0` (neuf) vs `impressions>0` (ancien) — validé, on garde `cost!=0`.

## 🎯 Objectif 100% (user 2026-06-15) : « génère-tout » = réutilise 11673 si la carte existe, SINON génère
une copie avec substitution de colonnes (`conversions_N`→colonne nommée), dédupliquée (1 par vieille
carte×client) dans collection **13950**. Outil : `scripts/generate_fallback.py` (à lancer APRÈS reuse+swap+
bascule). Onglets gérés, substitue aussi la viz du DASHCARD (titres/ordre/visibilité des colonnes).
**État Gaby (post-génération 2026-06-15) : les 6 dashboards prêts affichent 100% de NOUVELLES conversions
(0 colonne ancienne VISIBLE, vérifié).** Limite : 5 cartes-tableaux gardent des colonnes CACHÉES pour des
slots que le client ne mappe pas (4-7) — invisibles, pas de cible de migration ; strict-0-ancien impossible
sans que Gaby mappe ces slots OU qu'on drope les colonnes cachées. Outils de génération : `generate_fallback.py`
(génère + dédup dans 13950), `polish_generated_viz.py` (substitue la viz du dashcard : titres/ordre/visibilité),
intégrés à `migrate_client.py`. ⚠️ Les cartes générées naissent dans 13950 (sandbox) → DOIVENT être déplacées
en collection accessible après (cf. LEÇON permissions en tête).

## Étape 2 — Clients de Gaby

| # | Client | Clé mapping | Dashboards (orig → copie) | État | Reste / notes |
|---|---|---|---|---|---|
| 1 | **Goodiespub** | `Goodiespub` | 12734 Home → **25764**, 12716 Pilotage → **25765** | ✅ **100% visible** | Toutes tuiles affichent du neuf (combos + tables 2-dim générés via fallback + repolis). Reste invisible : slots 4-7 cachés non mappés. Mapping : `{0:Purchases, 1:Custom 1, 2:MQL, 3:Custom 3}`. |
| 2 | **Shopinvest** | `Shopinvest` | 10 dashboards (coll 304), copies 258xx/259xx | 🟢 **7/9 à 100% visible** (écarts meta acceptés, user: Gaby gère son mapping) | ✅ 100% : 422 (25896), 8803 (25897), 918 (25900), 6855 (25901), 8703 (25929), 23 (25902), 421 (25899). ⛔ 186 (25898) : 1 tuile #4577 «Perf by verticales with targets» rendu KO à la génération (à finir). ⛔ **863 Analytics (25930) : 5 tuiles GA4** (`analytics.*`) NON migrables — pas de colonnes nommées côté GA4 (blocage data amont) + qq globales render-KO. 8934 = 0 conv (skip). Tables : slots cachés non mappés (invisible). |
| 3 | **Father and Sons** | `Father and Sons` | 6 dashboards (coll 5404), copies 2583x | ✅ **4/6 à 100% visible** | **✅ Ecomm Home 25831, Ecomm Pilotage 25833, Noto Home 25834, Shopify 25836 (onglets)** = 100% visible (génération+repolissage). Reste invisible : slots cachés sur tables. ⛔ Annonces Meta 25832 (carte 87 « filter choice » : génération à vérifier) + Sponso 25835 (trou data Pinterest = sync aval, à finir). |
| 4 | **Rivadouce** | `Rivadouce` | 9 dashboards migrés (coll 8109), copies **25931-25939** | 🟢 **~6/9 à 100% visible** (écarts meta acceptés) | ✅ 100% : Perfs globales 25931, Perfs par levier 25932, Perfs par campagne 25933, Perf campagne 25937, Perf campagne(dup) 25938, Home 25939. ❌ tables avec slots NON mappés VISIBLES : Home Custom 25934 (slots 1-19), Perf annonces 25935, Ads&Audiences 25936 (CONVERSIONS_2). ⛔ **CONFLITS slot 1/2** (Gaby) : Home 25939 a 4 tuiles « conversion 1 » (266/1293/1307/1612 = Conversions 1 / CR / ROAS) NON substituables (slot 1 = Leads vs Custom 1) ; slot 2 (Initiate checkouts vs Sign ups) ; slot 3 « Content views OR View Item » ambigu. Écart meta −135 (Milton-Main/Auriège-Main new_type vide) accepté. ⚠️ scan a un angle mort smartscalar : 25939 « 100% » à reconfirmer (les 4 conflit-tuiles peuvent être visibles). 21210 Brand Monitoring = 0 conv (skip). |

## Étape 3 — Balayage A→Z de tous les clients (DÉMARRÉ 2026-06-22)

**Décisions de ce déroulé (user, 2026-06-22) :**
- **Ordre : alphabétique A→Z** sur tous les clients du préflight (~95 clients, `migration/conv-preflight.csv`).
- **Cibles : COPIES d'abord** (jamais l'original ; promotion = étape séparée après validation). Staging =
  collection **14016** « ZZ - Conv migration étape 3 (A→Z) » (sous le sandbox 13851). ⚠️ collision d'id :
  *collection* 14016 ≠ *dashboard* 14016 (PN Global perf) — espaces de noms distincts.
- **Cadence : client par client** au début (bilan + validation user après chaque client), puis lots une fois
  la mécanique GA4 rodée. Subagents OK pour paralléliser ensuite.
- **Mapping = Airtable, re-vérifié en LIVE par client** (via MCP Airtable, base `apptzpE1FqCMGH0dw` table
  `tbliHOIPYGJCvLvas`). Le cache `conv-client-mapping.json` (2026-06-10) sert d'indice, pas de vérité.

**🟢 GA4 DÉBLOQUÉ (user, 2026-06-22) :** les colonnes nommées existent désormais dans les tables finales
`analytics.google__analytics_metrics / _per_device / _per_landing_page / _per_location`. MAIS **aucune
question Metabase générique GA4 n'existe** (pas d'équivalent 11673 côté GA4) → **à créer à la demande**,
quand une tuile GA4 en a besoin. **Le mapping GA4 est dans la MÊME table Airtable** (lignes `platform =
google analytics 4`, mêmes slots `type`→`new_type`) → GA4 réutilise les mêmes conversions nommées que les pubs.
**237 tuiles GA4 sur 26 clients** ; 1er client GA4 en A→Z = **24S** (6 tuiles GA4) → la conception des
questions génériques GA4 doit être tranchée AVANT 24S.

**MÉCANIQUE GA4 PROUVÉE (2026-06-22) — faits de la reco read-only + carte témoin :**
- Tables GA4 = DB 144 schéma `analytics`. **Colonnes nommées IDENTIQUES aux pubs** (`PURCHASES`,
  `CUSTOM_CONVERSIONS_1..15(_VALUE)`, `LEADS`, `MARKETING_QUALIFIED_LEADS`…), peuplées de vraies données,
  dans **3 tables** : `google__analytics_metrics` (global/by date/source-medium), `_per_device`, `_per_location`.
- ⛔ `google__analytics_per_landing_page` est **TRONQUÉE** (60 cols, **aucune** colonne nommée, pas de
  `ga_campaign_id`) → les **11 tuiles GA4 « by URL »** ne sont pas migrables (besoin data amont) → laisser
  sur l'ancien `CONVERSIONS` + flag équipe data.
- **Jointure GA4 ≠ pubs** : GA4 joint par `profile = client_ad_platforms.analytics_view` (PAS `campaign_id`).
  Brand-exclusion via `ga_campaign_id` (absent sur per_landing_page). → le bloc FROM des génériques GA4
  diffère de celui des pubs (ne pas copier-coller le SQL 11673).
- **Filtre temps temporal-unit réutilisable** (field 419201 + `JOIN utils.calendar ON calendar.date=ga.date`).
- **Preuve empirique (raw SQL)** : pour un client slot Main=Purchases, ancien `conversions` == nouveau
  `purchases` AU CENTIME (PN 91 720=91 720 / 7 933 248,74 € ; 100% Print 2 162=2 162). L'écart *global*
  1,2M vs 1,1M = définitions slot-0 mélangées entre clients, pas un bug.
- **Carte témoin** : `c1842` « Main conversion (GA4) » (smartscalar/per_location/conversions) copiée via
  `generate_card` + substitution `conversions→purchases` → **carte 49623** « Purchases (GA4) — témoin »
  (sandbox coll **14049**). Avant/après au niveau carte IDENTIQUE (PN 131 564 / 100% Print 4 103). ⚠️ id 14049
  = *collection* sandbox témoin ≠ *dashboard* 14049 (PN GA4).
- **Design GA4 retenu (user GO 2026-06-22)** : questions **génériques partagées** (style 11673, 1 carte par
  conversion nommée × breakdown × type de graphe, paramétrée `clients`, réutilisée par tous), **à la demande**,
  dans une coll dédiée sous 11673, standard temporal-unit, ajoutées à l'index reuse. **Reste à faire** :
  généraliser (créer les génériques GA4 dont 24S a besoin + brancher le reuse sur GA4), puis migrer 24S.

## 🟢 CARTES PARTAGÉES SPÉCIALES — RÉSOLUES (2026-06-23)

Le 1er lot étape-3 (Absolut Cashmere, Braxton, Chilowé, Cica) a révélé que les bascules « bloquées »
venaient surtout d'un **BUG**, pas d'une limite de fond. Détail :

**🐛 BUG RACINE CORRIGÉ — `LATERAL_RE` (scripts/convert_generic_temporal.py).** La regex repérant le
`LATERAL … metabase_filters.time_periods …` était en dotall `.*?` → sur une carte à **2+ LATERAL** (presque
toutes les cartes conversion by-date ont un LATERAL *brand* avant), elle débordait du 1er LATERAL jusqu'au
time_periods et **avalait une frontière de CTE** → `Object 'FINAL' does not exist`. Corrigé en `[^()]*?`
+ `LIMIT 1` optionnel (forme de #87). → **Braxton débloqué**, by-date OK. Aussi : la CTE granularity est
passée de `/tmp/granularity_cte.sql` (volatil) à **`scripts/granularity_cte.sql`** (suivi git).

**Collection témoins** : **14082** « ZZ - témoins cartes partagées (conv-2026-06) » (sous sandbox 13851).

**#4854 « Impression share by product & date » (20 dash)** ✅ — copie temporal-unit **49755** ; avant/après
identique 4 granularités (BYmyCAR, Shopinvest). Pas une carte conversion → simple `cgt.transform`.

**#87 « Social ad metric (filter choice) by date » (141 dash) ✅ RÉSOLU SANS TABLE** — carte **49788**.
Recette (reproductible pour les cartes « sélecteur ») :
1. `cgt.transform` → filtre période temporal-unit (marche grâce au fix LATERAL ; #87 a un LATERAL
   analysis_metrics + un LATERAL time_periods *sans* LIMIT 1).
2. **Injection des conversions nommées** dans 3 zones : `get_data` (`SUM(<col>) AS <col>` + `_value` +
   `COALESCE(SUM(cost)/nullif(SUM(<col>),0)) AS cac_<col>`), `aggregated_data` (passthrough), et le grand
   `CASE WHEN metrics.name='<col>' THEN aggregated_data.<col>`. (`global.social_ad_daily_metrics` A les
   colonnes nommées : purchases/_value, 15 custom, leads, mqL, sqL, sign_ups, add_to_carts_new, etc.)
3. **Sélecteur métrique = Text variable** (pas Field Filter) : `LATERAL(SELECT name FROM analysis_metrics
   [[WHERE {{metric}}]] LIMIT 1)` remplacé par `(SELECT {{metric}} AS name) AS metrics` → la valeur passe
   DIRECT au SQL, **aucune dépendance à la table `analysis_metrics`**. Tag `metric` type=`text`.
4. **Dropdown** : param `metric` en **custom list** (`values_source_type=static-list` +
   **`values_query_type=list`** ← le réglage clé qui manquait + `isMultiSelect=False`), libellés propres
   (acronymes MAJ : CAC/CPC/CPM/CTR/ROAS ; noms InitCase : Purchases, Custom 1, Marketing Qualified Leads…).
   ⚠️ Field Filter = dropdown mais le SQL exige la valeur DANS analysis_metrics (prouvé : purchases→0). Text
   variable = pas de dropdown SAUF avec `values_query_type=list` (vérifié live par user : dropdown OK).
- Vérifié : `cost` identique à l'ancienne (17 913,25), `purchases`/`custom`/`cac_*` renvoient leur colonne.

**RESTE À FAIRE (câblage, pas encore codé) :** au swap d'un dashboard contenant #87, le script doit :
swap dashcard 87→49788, **retarget du parameter_mapping `metric` `dimension`→`variable`**, et poser la
**custom list sur le filtre Metric du DASHBOARD** (sinon le dropdown dashboard ne montre pas les nommées).
Automatisable dans le swap (0 retouche manuelle). Idem #4854 (plus simple, juste swap+bascule).

**Famille « par segment » (#10501/10502/10531/14875 + #11970)** : même patron « sélecteur » (un param
`breakdown` choisit la dimension ; user a mis #10501 en single-select). La substitution conversions→nommées
tourne (table `global.campaign_breakdown_daily_metrics` a les colonnes nommées). #11970 = vraie 2-dim (param
`dimension_2`) = niche. → appliquer la même recette qu'à #87 quand on les rencontre dans le balayage.

**Chilowé** (21310/21311) : bascule exit≠0 pour une autre raison (à creuser ; 2 mini-dash, basse priorité).

**🔑 PRINCIPE (user 2026-06-24) — FINIR chaque dashboard à 100% avant de passer au suivant ; ne JAMAIS
commencer un dashboard qu'on ne peut pas finir** (sinon on laisse 1-2 cartes incohérentes à l'agent suivant).
Conséquence : les dashboards à **cartes spéciales** (#87 filter-choice, famille segment, Chilowé) **attendent
l'outillage de déploiement** (recâblage auto du filtre Metric `dimension→variable` + custom list dashboard ;
robustesse timeout convert_card — fait ; patron segment). On ne les migre qu'une fois cet outillage prêt, comme
unités complètes. Les dashboards « propres » (sans carte spéciale) se migrent 1 par 1, bout-en-bout.
- **Nettoyage 2026-06-24** : copies à-moitié ARCHIVÉES (26194/26195 Chilowé, 26226 Cica Focus, 26199 Cica
  Breakdowns). Staging 14016 = **5 dashboards FINIS cohérents** : 26127 (100% Print), 26164 (Absolut Cashmere),
  26193 (Braxton), 26197 (Cica Home), 26198 (Cica PMax). Bascule rendue robuste (try/except convert_card).
- **Prochain pas** : coder le déploiement des cartes spéciales (helper swap #87 49788 + retarget mapping +
  custom list dashboard ; idem #4854 49755 ; patron segment) → PUIS finir les dashboards durs en unités, et
  dérouler A→Z en finissant chaque dashboard.

**🔒 IRON LAW (user 2026-06-24) — 0 tuile conv ne reste sur l'ancien.** On migre TOUT (2-dim compris), sinon
retirer les colonnes positionnelles cassera les tuiles restées dessus. Un dashboard n'est « fini » que si 0
tuile sur l'ancien. → ancienne politique « laisser les non-mappables » ANNULÉE. ⚠️ slots non mappés / conflits
Airtable = **blocage Gaby** (impossible d'inventer la cible) → « 100% client » dépend d'un Airtable complet ;
sortir la liste des slots manquants par client.

**Vrai périmètre (2026-06-24)** : ~**98 clients ACTIFS** (≥1 new_type réel), dont **25 absents du préflight**
(périmé → RE-SCANNER la coll 317 en live). Vue par client : `docs/conversion-migration-PROGRESS.md`.

**FIXES OUTILLAGE 2026-06-24 :** ✅ `LATERAL_RE` ; ✅ `bascule` robuste (timeout convert_card ≠ crash) ;
✅ **2-dim migrable** (`generate_fallback.render_ok` : « pick a value for X » = param requis non fourni, PAS
une erreur SQL → carte GARDÉE ; #11970 OK). ⬜ RESTE pour true-100% : (1) déploiement #87 (registre 49788 +
retarget mapping metric `dimension→variable` + custom list filtre Metric dashboard) ; (2) patron segment ;
(3) **combos multi-conversion** (Braxton #268 « Conversions 3 ») = pas d'outil ; (4) carte by-date lente Cica Focus.

### Suivi A→Z (1 ligne / client)

| # | Client (A→Z) | Dashboards orig | Copies | GA4 | État | Notes |
|---|---|---|---|---|---|---|
| 1 | **100% Print** | 13983 | 26127 | 0 | ✅ **migré (copie)** | 8/8 tuiles new. Avant/après IDENTIQUE fenêtre large (953,4 conv / 225 340 € / CAC 171,77 / ROAS 5,69). slot Main→Purchases. 1 carte générée 49590. **À valider par user.** |
| 2 | 24S | (17 dash) | — | 6 | ⬜ à faire | **1er client GA4** → concevoir les questions génériques GA4 d'abord |
| … | (reste A→Z) | | | | ⬜ | dérouler via `migrate_client.py` |

## ⚠️ À retenir transverse
- **GA4 / analytics.* bloqué amont** (colonnes nommées pas encore dans le pipeline data) — ~242 tuiles.
- **Conflits de mapping Airtable** = un slot positionnel qui mélange plusieurs événements → plusieurs
  conversions nommées. → demander à Gaby de trancher (ou corriger l'Airtable). NE PAS deviner.
- **Limites outils connues** (restent sur l'ancien système, sans casse) : graphes multi-conversion
  (2+ conversions sur un même graphe), tableaux à 2 dimensions (ex. produit×canal). Pas d'outil propre.
- **Rien n'est appliqué aux ORIGINAUX** : tout sur copies. L'étape « appliquer sur l'original » (ou
  basculer le partage Nanga vers la copie) reste à définir/faire APRÈS validation par le consultant.
  **MAJ 2026-06-17 : le partage Nanga n'est PAS automatisé — les GM le font à la main (responsabilisation +
  pratique). Étape prod = appliquer sur les ORIGINAUX ; le partage reste au GM.** cf. memory `dashboard-app-sharing`.

## Collections clés
- **11673** Nouvelles Conversions (cartes par conversion, PARTAGÉE) · **13884** Tables « toutes conversions »
  (mixtes 49098–49129, sous 11673 = accessible) · **317** dashboards custom clients (cibles) · **13917** copies
  de test des clients Gaby.
- **Collections de cartes migrées (post-fix permissions 2026-06-15, ACCESSIBLES) :** sous-collections
  « Conversions migrées » par client → PN **13983**, Goodiespub **13984**, Father&Sons **13985**,
  Shopinvest **13986**, Rivadouce **13987** (toutes sous /317/) ; génériques partagées **13988** (sous 11673).
- **Sandbox À NE PLUS UTILISER comme destination finale** (non lisibles par consultants) : **13851**
  « ZZ - Migration test » + ses enfants **13885** (copies temporal-unit génériques), **13950** (cartes générées).
  Les cartes utilisées ont été déplacées hors de là ; restent quelques orphelins (à archiver).
- Clés collections clients (parents sous /317/) : PN 4314 · Goodiespub 6940 · Father&Sons 5404 · Shopinvest 304
  · Rivadouce 8109.
