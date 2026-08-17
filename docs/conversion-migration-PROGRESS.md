# Avancement migration conversions

> Snapshot live final du **2026-07-16**. Les chiffres viennent de
> `migration/accounting-final.json`, `migration/accounting-copies.json` et
> `migration/conversion-manifest.json`.

## Vue roadmap canonique

La roadmap compte chaque original in-scope une seule fois, selon sa copie canonique lorsqu'elle existe.
Les topologies multi-copies sont toutes réconciliées et ne forment plus une catégorie additive.

| Statut par original | Nombre |
|---|---:|
| Complete | 136 |
| Residual | 240 |
| Never copied | 53 |
| Unknown | 0 |
| **Total in-scope** | **429** |

Le périmètre découvert contient **430 originaux** : 429 in-scope et un doublon exact hors périmètre,
Chilowé `21314`, identique à `9933`.

La topologie physique conserve **16 originaux avec plusieurs copies** : les 16 sont résolus,
0 reste non résolu et 17 copies sont explicitement superseded.

## Vue copies et Iron Law

| Mesure | Total | In-scope |
|---|---:|---:|
| Copies | 394 | 393 |
| True-100 | 138 | 138 |
| Résiduelles | 256 | 255 |
| Inconnues | 0 | 0 |

L'accounting brut couvre **73 clients, 394 copies, 138 true-100, 256 résiduelles et 0 inconnue**. Il recense
aussi **563 blockers consultant** et **377 cartes de couverture**. Ces deux paniers sont des diagnostics de
travail ; ils ne changent pas à eux seuls le statut Iron Law d'une copie.

La promotion live a certifié **134 copies uniques**. Ce nombre mesure un déplacement validé vers la
collection de destination, pas un statut Iron Law supplémentaire : les totaux de ce tableau restent donc
138/255/0 in-scope.

Une copie est true-100 seulement si le scan live ne trouve plus aucune conversion positionnelle dans les
cartes principales ou leurs séries. `accounting-copies.json` porte cette preuve ; le tracker est un registre
de topologie, pas une source Iron Law.

## Catch-up du 15 juillet

Les 25 dashboards classés READY au préflight initial ont tous été traités ou reclassés :

| Issue | Nombre | Originaux → copies |
|---|---:|---|
| Complete | 15 | `18406→27744`, `21310→27745`, `21311→27777`, `11249→27778`, `18702→27779`, `14678→27780`, `20649→27781`, `11147→27782`, `16593→27783`, `15600→27785`, `21804→27791`, `21244→27792`, `17646→27794`, `9933→27797`, `21309→27798` |
| Residual | 9 | `19659→27784`, `22266→27786`, `22233→27787`, `19956→27788`, `20484→27789`, `20880→27790`, `21243→27793`, `14676→27795`, `19890→27796` |
| Doublon exact exclu | 1 | `21314`, doublon de `9933` |

Points de clôture :

- Chilowé `9933→27797` et `21309→27798` sont complets ;
- Superdiet `19890→27796` est résiduel : les cartes `52448`, `52450` et `52453` conservent les slots
  positionnels 1–6 et aucune substitution sûre n'est disponible ;
- aucun original n'a été modifié.

## Les 53 jamais copiés

Le reliquat est entièrement expliqué :

| Cause | Nombre | Action nécessaire |
|---|---:|---|
| Blocage structurel | 25 | Corriger ou étendre l'outillage, puis refaire un préflight |
| Aucun mapping exploitable | 28 | Résoudre le mapping dans Supabase avant toute copie |
| **Total** | **53** | Aucun n'est actuellement READY |

Supabase `pipeline_manager.conversions` est l'unique source de mapping. `type[]` et `new_type[]` sont des
ensembles indépendants, jamais des listes à zipper. L'auto-mapping exige une égalité exacte des ensembles de
lignes vers une cible unique, puis une égalité stricte des valeurs live non vides.
Airtable est totalement déprécié : ne jamais le lire ni l'écrire.

## Promotion live exécutée

La promotion des copies promouvables est terminée : **134 promotions uniques certifiées** dans trois
snapshots, tous `APPLIED`, avec `failure_mode=isolated` et zéro échec.

| Snapshot | Vérifiées | Détail |
|---|---:|---|
| `migration/promotion-snapshot-20260715T203055323521Z.json` | 129 | lot principal |
| `migration/promotion-snapshot-20260715T214816686551Z.json` | 1 | copie `26791` |
| `migration/promotion-snapshot-20260715T224944247792Z.json` | 4 | originaux `329`, `863`, `15865`, `22860` |

Le dernier lot a exclu explicitement `18406`, sélectionné puis vérifié les quatre autres candidates et
conservé `failures=[]`. Une erreur éventuelle n'aurait restauré que la copie en cours : le runner ne fait
aucun rollback global et conserve tous les succès déjà certifiés.

La validation finale `migration/promotion-plan-final-validation.json`, de hash
`sha256:33a2d389083eaa3620d76c1b518c0ac091ec5cf0d1fb45e9258c7810184a0d32`, compte **1 READY et
429 BLOCKED**. Le seul READY est `18406→27744` : cette copie est true-100, mais la Dashboard Question interne
`52308` suit automatiquement la collection du dashboard. Elle reste donc volontairement non promue sous la
règle « cards unchanged » ; ne pas déplacer la carte manuellement.

Les originaux et les 17 copies superseded sont restés intacts. Les cartes générées, partagées et
temporal-unit restent dans la collection technique durable `14115`. Le repartage des nouveaux liens Nanga
reste une opération manuelle des GM.

## Dernières bascules temps certifiées

Quatre copies ont été débloquées, basculées puis validées par `verify_pipeline` avant leur promotion :

| Copie | Original | Snapshot de bascule |
|---:|---:|---|
| `26754` | `329` | `migration/bascule-snapshot-26754-20260716-003151-520232.json` |
| `26789` | `15865` | `migration/bascule-snapshot-26789-20260716-003405-211675.json` |
| `27058` | `863` | `migration/bascule-snapshot-27058-20260716-003534-824173.json` |
| `25836` | `22860` | `migration/bascule-snapshot-25836-20260716-003652-531317.json` |

Les cartes partagées créées et conservées en `14115` sont `50850→52626`, `51789→52628`,
`51796→52629`, `1853→52630` et `49309→52631`. Pour `26791`, la dépendance personnelle `14632` a été
clonée en carte partagée `52594`, la copie a été recâblée, vérifiée puis promue.

Superdiet `18768→26804` reste bloqué : la carte `50933` diverge au grain `day`. Cette différence de valeurs
interdit la bascule sûre et ne doit pas être forcée.

## Historique condensé

- **Juin 2026 — historique :** création et durcissement du pipeline de migration sur copies, support des
  onglets, cartes temporelles, tables multi-slot, fallback et contrôle des valeurs.
- **30 juin — historique :** fin du premier balayage. Les anciens totaux publiés à cette date utilisaient un
  accounting moins strict et ne doivent plus servir aux décisions.
- **15 juillet :** décisions consultants sûres intégrées, Supabase adopté comme source de mapping,
  accounting fail-closed reconstruit, catch-up clos et 130 promotions certifiées.
- **16 juillet — actuel :** quatre bascules temps et promotions supplémentaires certifiées ; préflight final
  réduit à la seule candidate `18406→27744`, maintenue en place par le garde-fou cards-unchanged.

Les détails chronologiques anciens restent utiles pour comprendre les bugs et choix techniques, mais les
statuts courants sont exclusivement ceux des trois artefacts cités en tête.
