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

## Étape 3 — Reste de la collection 317 (~110 clients)

⬜ Non commencé. Prérequis (ce fichier + HANDOFF à jour = en place). Dérouler client par client avec la
chaîne d'outils rodée. Préflight global : `migration/conv-preflight.csv`.

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
