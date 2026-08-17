# Migration conversions Metabase — passation opérationnelle

> Procédure actuelle, alignée sur l'état live du **2026-07-16**.

## Objectif et état

Les dashboards custom doivent abandonner les colonnes de conversion positionnelles au profit des colonnes
nommées, sans changer les valeurs, les filtres ni le rendu. Tout le travail se fait sur des copies ; les
originaux restent intouchés.

État canonique : **429 originaux in-scope**, dont 136 complets, 240 résiduels, 53 jamais copiés et
0 inconnu. La topologie physique comprend 16 originaux avec plusieurs copies, tous réconciliés
(0 non résolu, 17 copies superseded). Il existe **393 copies in-scope : 138 true-100, 255 résiduelles,
0 inconnue**.

La promotion live des copies éligibles est terminée : **134 promotions uniques certifiées**. Les originaux,
les copies superseded et les statuts Iron Law n'ont pas été modifiés par cette opération.

## Les sources à ne pas confondre

| Source | Rôle |
|---|---|
| Supabase `pipeline_manager.conversions` | Mapping des conversions |
| `migration/accounting-copies.json` | État Iron Law live et causes au grain `copy_id` |
| `migration/canonical-copy-decisions.json` | Choix exhaustifs canonical/superseded des multi-copies |
| `migration/dashboard-client-attribution.json` | Décisions explicites d'attribution et de scope |
| `migration/conversion-manifest.json` | Vue canonique par original, scope, topologie et copie canonique |
| `migration/conv-migration-tracker.json` | Registre original→copie, notes et statut déclaré |
| `migration/promotion-plan-final-validation.json` | Dernier préflight live de promotion |
| `migration/promotion-snapshot-*.json` | Preuves d'application et de vérification des promotions |

`migration/accounting-final.json` est la synthèse agrégée de l'accounting live. Le tracker est utile pour la
topologie, mais son champ `status` ne remplace jamais un scan Iron Law. Accounting + manifeste font foi.

## Mapping Supabase : sémantique obligatoire

Airtable est totalement déprécié. Ne pas le lire, ne pas l'écrire et ne pas réintroduire ses exports dans le
pipeline.

Dans `pipeline_manager.conversions`, `type[]` et `new_type[]` représentent deux ensembles indépendants. Les
éléments de même index ne forment pas une paire. Pour un slot donné :

1. construire son ensemble exact de lignes source ;
2. chercher une cible `new_type` possédant exactement le même ensemble de lignes ;
3. accepter seulement si cette cible est unique ;
4. comparer les valeurs live non vides de l'ancien et du nouveau champ ;
5. écrire uniquement si elles sont strictement égales.

Une intersection partielle, une cardinalité ambiguë, plusieurs cibles, du count-only face à une valeur, une
comparaison impossible ou une différence de valeur bloque la tuile. Ne jamais zipper les tableaux, compléter
un mapping par intuition ou utiliser `--accept-diffs` pour forcer un résultat.

Deux slots ne peuvent partager une cible que si leurs ensembles exacts de lignes sont eux-mêmes identiques.
SQL `NULL` et tableau vide restent deux états distincts dans le snapshot.

Le snapshot local se régénère en lecture seule :

```bash
.venv/bin/python scripts/export_supabase_conversion_mapping.py \
  --env-file ../pipeline-manager/.env --write
```

Cette commande écrit uniquement le snapshot local ; elle n'écrit rien dans Supabase.

## Iron Law

Une copie n'est complète que si le contrôle live prouve simultanément :

- zéro colonne conversion positionnelle dans toutes les cartes principales ;
- zéro colonne conversion positionnelle dans toutes les séries associées ;
- filtre temps canonique et câblages cohérents ;
- défaut `Client` égal au propriétaire attendu ;
- aucune erreur de rendu introduite.

Une carte masquée, un SQL conservant les vieux slots ou une différence de valeur suffit à rendre la copie
résiduelle. Le statut fail-closed est volontaire.

## Pipeline pour un original jamais copié et réellement READY

Exécuter un seul original à la fois :

```bash
.venv/bin/python scripts/migrate_client.py \
  --client "<Client>" --dashboards <ORIGINAL_ID> --yes
```

L'orchestrateur :

1. crée une copie de staging et pose l'ancre de campagne ;
2. corrige et vérifie le défaut `Client` ;
3. réutilise les cartes canoniques compatibles ;
4. swappe les tables multi-slot sûres ;
5. bascule le filtre temps et prépare les cartes temporelles ;
6. génère les fallbacks nécessaires ;
7. polit les visualisations générées ;
8. exécute le contrôle final primary + series.

Les copies de travail vivent dans la collection de staging **14016**. Les cartes générées et temporal-unit
vivent dans la collection technique durable et partagée **14115**. Elles peuvent alimenter plusieurs
dashboards, y compris de clients différents : elles ne doivent jamais être déplacées par dashboard. La
promotion vérifie que leurs dépendances restent lisibles.

Garde-fous :

- ne jamais lancer deux migrations en parallèle : le tracker global n'a pas de verrou ;
- ne jamais passer plusieurs originaux dans la même invocation ;
- si l'orchestrateur échoue après création, reprendre **la même copie** avec les étapes ciblées ;
- ne jamais relancer l'orchestrateur pour le même original, au risque de créer une copie concurrente ;
- ne jamais travailler sur l'original ;
- en cas d'échec, restaurer uniquement le dashboard ou la copie en cours depuis son snapshot. Ne jamais
  annuler les succès antérieurs du lot.

Pour une copie existante résiduelle, commencer par lire ses causes dans `accounting-copies.json` et les notes
du tracker. N'appliquer que l'étape ciblée qui résout cette cause, puis refaire le contrôle live complet.

## Régénérer les preuves

Après une modification live :

```bash
.venv/bin/python scripts/final_accounting.py
.venv/bin/python scripts/build_conversion_manifest.py \
  --worklist migration/worklist.json \
  --tracker migration/conv-migration-tracker.json \
  --iron-state migration/accounting-copies.json \
  --client-attribution migration/dashboard-client-attribution.json \
  --copy-decisions migration/canonical-copy-decisions.json \
  --output migration/conversion-manifest.json
```

Vérifier ensuite :

```bash
jq '.summary' migration/conversion-manifest.json
jq '{clients,dashboards,visible_100,residu,unknown,blockers_consultant,coverage_cards}' \
  migration/accounting-final.json
```

Le snapshot attendu au 2026-07-16 est :

- roadmap : 136 complete, 240 residual, 53 never-copied, 0 unknown ;
- topologie : 16 multiple-copies, 16 réconciliées, 0 non résolue, 17 copies superseded ;
- copies in-scope : 138 complete, 255 residual, 0 unknown ;
- accounting brut : 73 clients, 394 copies, 138 true-100, 256 résiduelles, 0 inconnue, 563 blockers,
  377 coverage.

Ces chiffres ne varient pas du seul fait d'une promotion : l'Iron Law décrit le contenu de la copie, pas sa
collection Metabase.

## Catch-up clos

Le lot des 25 READY initiaux est terminé : **15 complete, 9 residual, 1 doublon exact exclu**.

- Chilowé `9933→27797` et `21309→27798` sont complete.
- Superdiet `19890→27796` est residual : les cartes `52448`, `52450`, `52453` gardent les slots 1–6.
- Chilowé `21314` est le doublon exact hors scope de `9933` ; ne pas lui créer une copie.
- Les 53 jamais copiés restants sont 25 blocages structurels + 28 absences de mapping exploitable.

## Réconciliation multi-copies close

Les 16 topologies multi-copies sont réconciliées : une copie canonique et toutes les copies superseded sont
enregistrées explicitement pour chacune. La liste auditable est dans le manifeste :

```bash
jq -r '.dashboards[]
  | select(.copy_status == "multiple_copies")
  | [.original_id, .client, .copy_reconciliation_status, .canonical_copy_id,
     (.superseded_copy_ids | join(",")), .iron_law_status]
  | @tsv' migration/conversion-manifest.json
```

Le fichier `migration/canonical-copy-decisions.json` contient 16 décisions exhaustives. Une copie reste
promouvable uniquement si son état canonique est true-100 et si le préflight live complet réussit.

## Promotion — état live certifié

Les **134 promotions uniques** sont prouvées par trois snapshots, tous `APPLIED`, en mode `isolated`, sans
échec :

| Snapshot | Promotions certifiées |
|---|---:|
| `migration/promotion-snapshot-20260715T203055323521Z.json` | 129 |
| `migration/promotion-snapshot-20260715T214816686551Z.json` | 1 — copie `26791` |
| `migration/promotion-snapshot-20260715T224944247792Z.json` | 4 — originaux `329`, `863`, `15865`, `22860` |

Le dernier snapshot porte `selected_original_ids=[329,863,15865,22860]`,
`excluded_original_ids=[18406]`, quatre succès `VERIFIED` et `failures=[]`. Le mode isolé est une exigence :
si une copie échoue, elle seule est restaurée et mise de côté ; toutes les promotions déjà vérifiées sont
conservées. Il n'existe pas de rollback global du lot.

Le dernier plan live, `migration/promotion-plan-final-validation.json`, a le hash
`sha256:33a2d389083eaa3620d76c1b518c0ac091ec5cf0d1fb45e9258c7810184a0d32` et contient **1 READY pour
429 BLOCKED**. Le seul READY est `18406→27744`, mais il ne doit pas être promu avec le contrat actuel : sa
Dashboard Question interne `52308` (`can_delete=false`) suit automatiquement la collection du dashboard dans
Metabase. Cela viole la règle « cards unchanged ». Ne pas déplacer cette carte manuellement et ne pas
contourner le fingerprint.

Règles permanentes pour toute reprise ultérieure :

1. figer un accounting et un manifeste à jour ;
2. promouvoir uniquement une copie canonique true-100 dont le préflight live est intégralement vert ;
3. laisser toute candidate bloquée en place et la revoir séparément en fin de lot ;
4. laisser les dépendances partagées dans `14115` et en maintenir la lisibilité ;
5. laisser les originaux et les copies superseded intouchés ;
6. faire repartager manuellement les nouveaux liens Nanga par les GM.

Les résiduelles, les inconnues et les copies non canoniques ne sont jamais promues.

## Bascule temps et cartes partagées — dernières preuves

Quatre bascules temps ont réussi leur application, leurs postconditions et `verify_pipeline` :

| Copie | Snapshot |
|---:|---|
| `26754` | `migration/bascule-snapshot-26754-20260716-003151-520232.json` |
| `26789` | `migration/bascule-snapshot-26789-20260716-003405-211675.json` |
| `27058` | `migration/bascule-snapshot-27058-20260716-003534-824173.json` |
| `25836` | `migration/bascule-snapshot-25836-20260716-003652-531317.json` |

Les cartes temporal-unit partagées correspondantes sont toutes en collection technique durable `14115` :

- `50850→52626` ;
- `51789→52628` ;
- `51796→52629` ;
- `1853→52630` ;
- `49309→52631`.

La copie `26791` utilisait la dépendance personnelle `14632`. Elle a été clonée vers la carte partagée
`52594` en `14115`, puis le dashboard a été recâblé, vérifié et promu.

Une exception temps reste volontairement bloquée : Superdiet `18768→26804`. La carte `50933` diverge au
grain `day`; l'équivalence des valeurs n'est donc pas prouvée. Ne pas forcer la bascule.

## Historique utile — non opérationnel

- Juin 2026 : le pipeline a acquis le support des onglets, des tables multi-slot, des cartes temporelles, du
  fallback généré et des comparaisons de valeurs.
- Le premier balayage a produit plusieurs générations de copies ; c'est la raison des 16 topologies multiples.
- La décision produit finale est de promouvoir les copies validées et de conserver les originaux inchangés.
- Le 15 juillet, le mapping a été basculé vers Supabase, l'accounting a été rendu fail-closed, le catch-up a
  été clos et 130 promotions ont été certifiées.
- Le 16 juillet, quatre bascules temps supplémentaires et leurs promotions ont été certifiées ; le préflight
  final ne laisse que `18406→27744` READY, maintenu non promu par la règle cards-unchanged.

Les anciennes recettes, anciens totaux et statuts saisis dans les journaux datés sont des éléments de contexte,
pas des instructions. Toujours repartir des artefacts live.
