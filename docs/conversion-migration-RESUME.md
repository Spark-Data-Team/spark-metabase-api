# REPRISE — Migration des dashboards conversions

> État live consolidé au **2026-07-16**. Ce document est le point d'entrée opérationnel.

## ⚠️ Correction 2026-07-16 (audit + fixes) — À LIRE EN PREMIER

Un audit indépendant (détecteur ré-implémenté, scan live, croisement Airtable/Supabase) a invalidé
plusieurs chiffres publiés plus bas par les runs antérieurs. **Les chiffres ci-dessous dans « Situation en
une minute » sont ceux d'AVANT correction ; se référer d'abord à ce bloc.**

**Bug corrigé (racine).** `conv_lib` masquait les littéraux SQL mais PAS les commentaires. Une apostrophe
française dans un `-- commentaire` ouvrait un faux littéral qui rendait invisible 40–66 % d'une requête. Le
MÊME masque servait au migrateur ET au vérificateur → une carte non migrée était certifiée « propre ».
Corrigé (`old_conversion_columns`/`new_conversion_columns`/`apply_substitution` → masque commentaires-aware
par type de contenu). 4 tests de régression ajoutés, **453 tests passent**.

**Vrai périmètre (clients ACTIFS uniquement, hors tout-Gaby) :**

| Vue | Corrigé (live, détecteur réparé) |
|---|---:|
| Cible actionnable (active, hors tout-Gaby) | **368** |
| Complets (true-100 **live-vérifiés**) | **111 — 30 %** |
| Résiduels | **226** |
| Jamais copiés | **31** |
| In-scope sortis — clients devenus inactifs | 46 originaux (**20 copies archivées** ce jour) |
| In-scope sortis — tout-Gaby actifs (0 slot mappé) | 15 |

**Corrections live appliquées le 2026-07-16 :**
- `26458` Komilfo **dépromu** (carte 48435 encore positionnelle, slot 0 contesté Airtable≠Supabase) →
  retour staging `14195`, snapshot `migration/depromote-snapshot-26458.json`.
- `26739` GTT carte `52242` **réparée** (branche B « All » jamais réécrite ; slot 0 = Purchases par décision
  consultant) → 0 positionnel, snapshot `migration/fix-snapshot-card-52242.json`.
- **20 copies `[conv-2026-06]` archivées** (8 clients inactifs : Virgil, Fauré Le Page, Exaprint, G-Heat,
  Merci Walter, Osée, Lutèce Cosmetics, 100% Print). Réversible, originaux intacts,
  snapshot `migration/archive-snapshot-inactive-clients.json`.

**Claims antérieurs FAUX ou trompeurs :** « 138 true-100 » (réel 111 après scan réparé + périmètre),
« 429 en scope » (368 actionnable), « 76 % au niveau tuile » (≈60 %, chiffre absent du code),
« Airtable totalement déprécié » (contient encore ~41 réponses exploitables — le garder en lecture,
voir §Mapping), « 563 blockers consultant » (dette réelle ≈113 slots, le reste = slots absents = tuiles
mortes à retirer). Le filtre clients-actifs **n'a jamais existé dans le code** : il vivait dans un JSON
gitignoré édité à la main → à mettre dans le code (`build_conversion_manifest.py`).

## Ajout 2026-07-16→17 (drop des branches CASE non mappées)

Nouvelle brique `conv_lib.drop_conversion_case_branches` (+ garde-fou `case_branch_prune_cleans`, câblée dans
`generate_card`/`generate_fallback`) : retire les branches `WHEN … THEN <slot positionnel>` d'un CASE quand le
slot est **non mappé**, sans supprimer l'item = la métrique (ce que faisait à tort `drop_conversion_selects` →
carte cassée). Cible les cartes **distribution** (bar/pie « Conversions distribution ») et **sélecteur**
(« filter choice »). **3 dashboards distribution nettoyés + vérifiés live, en STAGING (non promus)** : BYmyCAR
`26567`, EVS `27079`, Les petits culottés `27020`.

**⚠️ Leçon de sécurité (régression trouvée + corrigée)** : le drop pur (branches **+ items SELECT**) BLANCHIT
les cartes mono-métrique des clients **sans mapping** (ex. Be Radiance : « Main conversions »/« CAC » → carte
vide, « clean » Iron Law mais BLANCHE). L'Iron Law ne voit pas le blanc. Le scope a donc été **réduit au
pruning de branches CASE seul** (le CASE survit avec ses branches mappées). Tables larges, smartscalars,
sélecteurs à items CTE positionnels **restent sur l'ancien** (positionnel visible, jamais blanc).

**Vrai paysage résiduel** (scan live des 240 résiduels, 193 cartes sales) : le « motif unique = branches CASE »
était faux. Seulement **18 cartes à branches CASE** (7 nettoyables). Le reste = ~100 drop-only tables/smartscalars
(risque blanc → jugement par carte requis), 63 substituables, 14 GA4 (bloqué amont), 9 irréductibles. **Le
re-run large de `generate_fallback` n'est PAS sûr en aveugle** : petits lots + inspection valeur/rendu.

Avant toute promotion des 3 : régénérer `accounting`/`manifest` (ils marquent encore ces copies « residual »).

---

## Situation en une minute (⚠️ chiffres pré-correction — voir bloc ci-dessus)

Le balayage initial et le catch-up des dashboards prêts sont terminés. Les originaux n'ont pas été modifiés.
La promotion live est elle aussi terminée pour toutes les copies promouvables : **134 promotions uniques sont
certifiées**, sans échec et sans rollback global.

| Vue | État live |
|---|---:|
| Originaux découverts | 430 |
| Originaux dans le périmètre | 429 |
| Doublon exact hors périmètre | 1 — `21314`, doublon de `9933` |
| Roadmap — complets | 136 |
| Roadmap — résiduels | 240 |
| Roadmap — jamais copiés | 53 |
| Roadmap — inconnus / multi-copies non résolues | 0 / 0 |
| Topologies physiques multi-copies | 16 — toutes réconciliées, 17 copies superseded |
| Copies totales / dans le périmètre | 394 / 393 |
| Copies in-scope true-100 / résiduelles / inconnues | 138 / 255 / 0 |

L'accounting brut, qui inclut la copie hors périmètre, donne **73 clients, 394 copies, 138 true-100,
256 résiduelles, 0 inconnue, 563 blockers consultant et 377 cartes de couverture**.

La promotion ne change pas les statuts Iron Law : elle déplace une copie déjà certifiée, elle ne rend pas une
copie complète. Les totaux roadmap et Iron Law ci-dessus restent donc inchangés après les 134 promotions.

## Sources de vérité

À lire dans cet ordre :

1. `migration/accounting-final.json` — accounting live agrégé ;
2. `migration/accounting-copies.json` — Iron Law live au grain `copy_id` et causes ;
3. `migration/canonical-copy-decisions.json` — choix exhaustifs canonical/superseded des 16 topologies
   multi-copies ;
4. `migration/dashboard-client-attribution.json` — décisions explicites d'attribution et de scope ;
5. `migration/conversion-manifest.json` — vue canonique par original, topologie des copies et roadmap ;
6. `migration/conv-migration-tracker.json` — registre de topologie et notes d'exécution ;
7. `migration/promotion-plan-final-validation.json` — dernier préflight live de promotion ;
8. les trois `migration/promotion-snapshot-*.json` certifiés — preuve des 134 promotions ;
9. `docs/conversion-migration-PROGRESS.md` — synthèse lisible ;
10. `docs/conversion-migration-HANDOFF.md` — procédure technique et garde-fous.

`accounting-copies.json` et `conversion-manifest.json` font foi pour l'Iron Law. Le tracker ne prouve pas
qu'une copie est complète : il décrit les relations original→copie, les statuts saisis et les notes.

## Mapping conversions — règle actuelle

La source de mapping (auto-map + pipeline) est **Supabase `pipeline_manager.conversions`**. Airtable est
déprécié **comme autorité d'auto-map**, mais PAS comme oracle de lecture : `migration/conv-client-mapping.json`
contient encore ~41 réponses humaines exploitables (ex. Komilfo slot 0 = « Leads ») que Supabase a laissées
`__UNMAPPED__`. Ne pas le supprimer. Tout re-merge d'une réponse Airtable doit être **gaté par un différentiel
de valeur sur ≥2 fenêtres hors mai 2026** (Airtable = intention humaine, pas mapping row-level).

Les colonnes `type[]` et `new_type[]` sont deux **ensembles indépendants**. Elles ne sont jamais associées par
position dans les tableaux. Un slot peut être auto-mappé uniquement si :

- l'ensemble exact de ses lignes source est égal à l'ensemble exact des lignes d'une cible `new_type` ;
- cette cible est unique ;
- les valeurs live non vides de la colonne positionnelle et de la colonne nommée sont strictement égales.

Zéro cible, plusieurs cibles, une couverture partielle ou un écart de valeur = **blocage**, jamais une
approximation. `--accept-diffs` n'est pas une voie de contournement.

## Iron Law et règles de sécurité

Une copie est true-100 uniquement si aucune carte, dans le contenu principal **ou ses séries**, ne consomme
encore de colonne conversion positionnelle. Le contrôle final vérifie aussi le filtre temps, ses câblages et
le défaut `Client`.

- Travailler uniquement sur des copies ; les originaux restent intouchés.
- Ne jamais promouvoir une copie résiduelle ou inconnue.
- Ne jamais relancer `migrate_client.py` pour un original déjà copié : reprendre sa copie existante.
- Exécuter les migrations une par une ; le tracker JSON est global et n'a pas de verrou concurrent.
- Ne pas inventer un mapping et ne pas forcer un écart de valeurs.
- Une erreur de bascule ou de promotion déclenche uniquement le rollback local du dashboard ou de la copie en
  cours. Les succès antérieurs sont conservés ; aucun rollback global du lot n'est autorisé.

## Catch-up des 25 dashboards initialement prêts

Le lot est clos : **15 complets, 9 résiduels et 1 doublon exact exclu**.

Les deux derniers succès sont :

- Chilowé `9933` → copie `27797`, true-100 ;
- Chilowé `21309` → copie `27798`, true-100.

Superdiet `19890` → copie `27796` reste résiduel : les cartes générées `52448`, `52450` et `52453`
conservent les slots positionnels 1–6 et leurs valeurs ; aucun mapping sûr n'est disponible.

Chilowé `21314` est un doublon exact de `9933`. Il est hors périmètre et aucune seconde copie ne doit être
créée pour lui.

## Ce qui reste

Les **53 originaux jamais copiés** sont tous classés :

- 25 sont bloqués structurellement ;
- 28 n'ont pas de mapping exploitable.

Ils ne constituent pas une file « prête ». Il faut résoudre leur cause avant toute nouvelle copie.

La réconciliation des **16 originaux avec plusieurs copies** est close : 16 décisions exhaustives,
0 cas non résolu et 17 copies déclarées superseded. La topologie physique reste visible pour l'audit, mais
elle ne constitue plus une catégorie additive de la roadmap.

## Promotion live — terminée

Les **134 promotions uniques certifiées** sont réparties dans trois snapshots, tous `APPLIED`, en mode
`isolated`, avec `failures=[]` :

| Snapshot | Promotions vérifiées |
|---|---:|
| `migration/promotion-snapshot-20260715T203055323521Z.json` | 129 |
| `migration/promotion-snapshot-20260715T214816686551Z.json` | 1 — copie `26791` |
| `migration/promotion-snapshot-20260715T224944247792Z.json` | 4 — originaux `329`, `863`, `15865`, `22860` |

Le dernier lot a explicitement exclu l'original `18406`; il a appliqué et vérifié ses quatre autres
candidates, sans échec. Le préflight final
`migration/promotion-plan-final-validation.json`, hash
`sha256:33a2d389083eaa3620d76c1b518c0ac091ec5cf0d1fb45e9258c7810184a0d32`, contient **1 READY et
429 BLOCKED**. Son seul `READY` est `18406→27744`.

Deux exceptions restent documentées, sans action automatique sûre :

- `18406→27744` est true-100 mais non promouvable sous la règle « cards unchanged » : la Dashboard Question
  interne `52308` suit automatiquement la collection du dashboard dans Metabase. Ne pas la déplacer
  manuellement ;
- Superdiet `18768→26804` reste bloqué : la carte `50933` diverge au grain `day`, donc la bascule du filtre
  temps n'est pas équivalente en valeurs.

Les quatre bascules temps débloquées ont réussi et passé `verify_pipeline` :

| Copie | Snapshot de bascule |
|---:|---|
| `26754` | `migration/bascule-snapshot-26754-20260716-003151-520232.json` |
| `26789` | `migration/bascule-snapshot-26789-20260716-003405-211675.json` |
| `27058` | `migration/bascule-snapshot-27058-20260716-003534-824173.json` |
| `25836` | `migration/bascule-snapshot-25836-20260716-003652-531317.json` |

Leurs cartes temporal-unit partagées restent en collection technique `14115` : `50850→52626`,
`51789→52628`, `51796→52629`, `1853→52630` et `49309→52631`. La dépendance personnelle de la copie
`26791` a été remplacée par la carte partagée `14632→52594`, puis la copie a été promue et certifiée.

## Suite correcte

1. Réconciliation multi-copies : terminée, 16/16 résolues.
2. Accounting et manifeste canoniques : régénérés ; les régénérer après chaque changement live pertinent.
3. Promotion des copies éligibles : terminée, 134 promotions uniques certifiées.
4. Laisser `18406→27744` et Superdiet `18768→26804` en l'état tant que leur exception n'est pas résolue
   explicitement ; ne pas contourner les contrôles.
5. Ne pas déplacer les cartes générées/temporal-unit de la collection technique durable et partagée `14115` ;
   en maintenir la lisibilité pour les dashboards promus.
6. Laisser tous les originaux et toutes les copies superseded inchangés.
7. Faire repartager manuellement les nouveaux liens Nanga par les GM.

## Historique utile — contexte, pas procédure

- Juin 2026 : construction du pipeline copies→reuse→tables→filtre temps→fallback→polish, puis balayage du
  périmètre historique.
- Fin juin : la politique produit a été figée sur des copies destinées à devenir la nouvelle production ;
  les originaux ne doivent plus être réécrits.
- 15 juillet : intégration des décisions consultants sûres, migration du mapping vers Supabase, durcissement
  des comparaisons de valeurs, catch-up des 25 dashboards prêts et premières 130 promotions certifiées.
- 16 juillet : quatre bascules temps supplémentaires validées, quatre promotions supplémentaires certifiées,
  puis préflight final ramené à la seule exception `18406→27744`.

Les anciens chiffres et recettes mentionnés dans les journaux datés sont historiques. Pour toute décision
opérationnelle, utiliser exclusivement les artefacts live listés plus haut.
