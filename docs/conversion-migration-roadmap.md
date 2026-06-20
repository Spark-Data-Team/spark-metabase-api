# Conversion Migration — Roadmap (tracker vivant)

> **Objectif unique :** sur les dashboards **custom** des clients (sous collection **317**),
> remplacer chaque tuile branchée sur une conversion **ancien système** (colonnes positionnelles
> `CONVERSIONS`, `CONVERSIONS_1..19`, `CONVERSION_*_VALUE`) par son équivalent **nouveau système**
> (colonnes nommées `CUSTOM_CONVERSIONS_1..15`, `PURCHASES`, `LEADS`, …), en **préservant la mise en
> page et le câblage des filtres**, mapping **par client** (Airtable), réversible (snapshots).
> Design : `docs/superpowers/specs/2026-06-03-conversion-migration-design.md` ·
> Plan : `docs/superpowers/plans/2026-06-03-conversion-migration.md`.
> Légende : ✅ fait · 🚧 en cours · ⬜ à faire · ⛔ bloquant/décision · **Maj : 2026-06-03**

## Garde-fous (non négociables)
Snapshot → réconciliation Snowflake par tuile → échantillon → batch. Copy-first pour tester.
**Jamais** d'archivage de carte template partagée. Une tuile non-`ok` n'est **jamais** appliquée
automatiquement (file de revue). In-place seulement après pilote sur copie validé.

## Outillage (sur master, NON commité — décision commit en attente)
| Composant | État |
|---|---|
| `scripts/conv_lib.py` (+ `tests/test_conv_lib.py`) | ✅ **20/20**, revu + durci |
| `scripts/export_conv_mapping.py` → `migration/conv-client-mapping.json` | ✅ 173 clients |
| `scripts/build_new_conv_index.py` → `migration/conv-new-index.json` | ✅ 2422 clés (col,forme) |
| `scripts/discover_conversion_targets.py` → `migration/conv-targets.json` | 🚧 crawl en cours |
| `scripts/migrate_conversions_on_dashboard.py` | ✅ résout/valide ; dry-run OK |
| `scripts/conv_preflight.py` → `migration/conv-preflight.csv` (file de revue) | ⬜ après crawl |
| `scripts/migrate_conversions_wave.py` (runner de vague) | ⬜ |

## Taxonomie de résolution (par tuile)
`ok` (1 carte cible, garde-fous verts → applicable) · `multi` (plusieurs cibles → revue) ·
`review` (aucune forme correspondante, ou combo multi-slot → revue) · `unmapped` (slot sans
`new_type` chez ce client → revue) · `conflict` (mapping incohérent entre comptes → revue) ·
`blocked` (garde-fou échoue) · `skip` (pas de colonne ancienne).

## Mapping (Airtable `apptzpE1FqCMGH0dw / tbliHOIPYGJCvLvas`)
- 173 clients ; **214 slots UNMAPPED + 35 slots CONFLICT** (→ revue, jamais devinés).
- Clé = `brand_name` = défaut du param `Client` du dashboard. Slot ≠ numéro Custom (ex. PN `3rd→Custom 2`).
- ⛔ **Hors périmètre positionnel** : types `Add to cart` / `App install` / `runs` (colonnes déjà
  nommées `ADD_TO_CARTS`/`APP_INSTALLS`) — décision : migrer le rename `*_NEW` ou laisser ? (à trancher)

## État réel — preflight (2026-06-04, `migration/conv-preflight.csv`)
**516 dashboards · 5 557 tuiles · 97 clients.** Statuts :
| statut | tuiles | % | lecture |
|---|---:|---:|---|
| review | 2363 | 42 % | dont **tables multi-slot 1488** (qq cartes distinctes réutilisées), **source GA4/autre 364**, **forme absente 447** |
| multi | 1519 | 27 % | ambiguïté même-source (candidats surtout **2–3**) → désambiguïsation |
| ok | 603 | 11 % | applicable maintenant |
| conflict | 459 | 8 % | slot → ≠ new_types selon le compte |
| unmapped | 349 | 6 % | slot sans new_type chez ce client |
| no_client_mapping | 264 | 5 % | client absent d'Airtable (**Upway 166**, Little Worker 35, Fogal 23…) |

**⚠️ Fait structurant : le nouveau système (colonnes nommées) n'existe QUE dans les tables ads
`global.*`** (toutes ont `purchases`/`custom_conversions_*`/`leads`), **PAS dans `analytics.*` (GA4)**
(qui n'ont que `conversions`/`conversion_value`). L'arbre 11673 n'a 0 carte analytics. ⇒ la migration
est **un chantier tables-ads**. Le swap reste **table-pour-table** (granularités : campaign_daily_metrics,
geographical, url, social_ad, search_adgroup…).

Répartition par famille de source (5 557 tuiles) :
| famille | tuiles | détail |
|---|---:|---|
| **ads** `global.*` | 3 229 | multi 1476 · **ok 573** · conflict 422 · review 415 · unmapped 343 |
| **None** (source non résolue) | 2 086 | review 1723 (≈ tables perf multi-slot) · no_client_mapping 264 · … |
| **analytics** GA4 | 242 | **bloqué en amont** (pas de colonnes nommées dans `analytics.*`) — à remonter à la data |

- **Cœur ads migrable = 3 229 tuiles** ; **ok+multi = 2 049** (désambiguïsation = le levier principal).
- **Leviers** : (1) désambiguïsation multi (1476, surtout 2–3 candidats) → ~+1 400 ok ; (2) **carte table
  perf nouvelle** (clôt ~1 488 tuiles « None » via qq cartes) ; (3) compléter Airtable (conflict 422 +
  unmapped 343 + no_client 264 dont **Upway 166**) ; (4) **GA4/analytics (242) = bloqué amont** (pipeline).

## Dashboards testés (pilotes)
| Dash | Client | Tiles conv | Résultat | Notes |
|---|---|---|---|---|
| 14118 Home Pro Nutrition | Pro Nutrition | 1 | ✅ `266→42635` (copie 25302, réconcilié exact Snowflake) | slot-1→Custom 1 |
| 16557 Ecommerce Sopral | Pro Nutrition | 6 | ✅ 3 `ok` · 2 `multi` (CAC) · 1 `review` (CAC bar/date) | rename `location→campaign_location` géré |
| 673 Global \| 900.care | 900.care | 12 | 9 `multi` · 2 `review` (tables multi-slot) · 1 `blocked` | slot-0→Purchases ; cf. décision matcher |

## ⛔ Décisions ouvertes (alignement)
1. **Désambiguïsation `multi`** *(la grosse)* — l'arbre « Conversions génériques » a **plusieurs**
   cartes par (colonne × forme) (ex. 900.care « Main conversions » → 6 candidats, « CAC » → 5).
   La forme `(display, métrique, breakdown)` est trop grossière pour les conversions standard.
   Options : (a) préférer la carte dont le **nom canonique** = `new_type` ; (b) restreindre l'index
   aux cartes du **dossier** de la conversion (ancêtre 11673) ; (c) `multi` → toujours revue.
   → **décision produit nécessaire** avant un preflight massif fiable.
2. **Carte par défaut des variantes** — `with/without brand`, `- leads/- purchases`, `| social` :
   choisir la canonique vs revue.
3. **Auto-détection client** — rendre `--client` optionnel (lu du param `Client`). ⬜ petit.
4. **Tables multi-slot** (perf tables, ex. cartes 19/5940) — pas de swap 1-carte ; nécessitent une
   **nouvelle table perf** nommée. → traitement dédié (revue/manuel).
5. **Périmètre platform** — ces 3 dashboards ne sont pas scopés plateforme (`network` vide) ; le
   littéral `meta` en SQL est incident. Vérifier les dashboards réellement scopés plateforme.

## Audit bulletproof (2026-06-10, 4 agents parallèles) — corrigé dans la foulée
- ⛔→✅ **Index pollué** : 134/2095 cartes hors-11673 (dont 29 cartes d'AUTRES clients : LA Bruket,
  J.Dreyfuss…) → rebuild live restreint au sous-arbre 11673.
- ⛔→✅ **`time_period` incompatible** (dimension → temporal-unit sur les nouvelles combo/line) : le
  param « Time period » ne pilote plus la granularité → garde-fou `incompatible_wired_tags` (refus).
  ⚠️ Décision produit en attente (cf. questions).
- ⛔→✅ **PUT non vérifié** (mb.put avale l'erreur) → PUT `raw` + abort. **Onglets** refusés pour l'instant.
- ⛔→✅ **Fenêtre vide ⇒ faux « identique »** (`[]==[]`) → statut « À VÉRIFIER », jamais migré.
- ⛔→✅ Noms FR (Taux/Coût par/Valeur/Moyen) reconnus ; AVG/VALUE alignés série↔nom ; littéraux SQL
  masqués (détection + substitution) ; `conversion_source` déterministe + alias ; snippets/cartes
  sources détectés (`has_opaque_refs`) ; filtres orphelins → refus ; payload PUT whitelisté.
- 📌 **Tables 11874** : les remplaçantes des grands tableaux existent (41336–41354, custom-only) —
  substitution à contenu différent, à faire valider (pas d'égalité avant/après possible).
- Tests : **37/37**.

## Corrections déjà intégrées (durcissement via tests)
- ✅ Combos **multi-slot → review** (jamais de swap erroné). 
- ✅ Tuiles scalaires : ignore `graph.dimensions` résiduel (formes cohérentes).
- ✅ `AVG` avant `VALUE` (pas de collision « Avg…value »).
- ✅ **Rewire structurel des filtres renommés** par field-id (`location→campaign_location`).
- ✅ Migrateur écrit `migration/conv-report-<dash>.json` (sortie propre pour le runner).

## Vagues (rollout)
| # | Périmètre | Statut | Note |
|---|-----------|--------|------|
| 0 | Pilotes Pro Nutrition + 900.care (copies) | 🚧 | 14118 ✅ ; 16557/673 résolus en dry-run |
| 1 | Pro Nutrition in-place | ⬜ | après revue vague 0 + désambiguïsation |
| 2 | 5 clients échantillon (copies→revue→in-place) | ⬜ | |
| 3 | Reste (~105 clients) par lots de ~10 | ⬜ | gate : réconciliation verte par tuile |

## Artefacts de suivi (CSV)
- `migration/conv-targets.json` — **toute la charge** : (client, dashboard, tuiles). 🚧 (crawl).
- `migration/conv-preflight.csv` — worklist par tuile + statut (la file de revue). ⬜ après crawl.
- `migration/conv-report-<dash>.json` — rapport/rollback par dashboard migré.
