# Design — Phase 1.5 : normalisation du nommage des cartes (collection 215)

> Date : 2026-05-21
> Phase précédente : `docs/superpowers/specs/2026-05-20-generic-questions-reorg-phase1-design.md` (faite).
> Spec d'ensemble : `docs/generic-questions-reorg.md`
> Statut : design validé — à transformer en plan d'implémentation.

---

## Contexte

La Phase 1 (restructure pure) a livré l'arborescence cible de la collection
Metabase `215 « 2. Generic Questions »`. Les noms des cartes n'ont pas été
touchés : ils restent **inconsistants** (`snake_case` vs espaces, casse, espaces
parasites), **ambigus** (22 noms en double, cartes très proches), et il est
**difficile de voir le type de viz** d'une carte quand on parcourt la bibliothèque.

## Objectif

Normaliser les noms des cartes de la collection 215 pour qu'ils soient cohérents,
non ambigus et lisibles, **sans casser aucun dashboard client**.

## Périmètre

**1 212 cartes** de la collection 215, **hors `18. Nouvelles Conversions`** — les
~1 969 cartes générées seront corrigées en Phase 2 via le générateur, pas par un
renommage en masse qui serait écrasé au prochain run.

| Opération autorisée            | Opération interdite en Phase 1.5     |
|--------------------------------|--------------------------------------|
| Renommer une carte (`name`)    | Déplacer une carte ou une collection |
|                                | Archiver / supprimer une carte       |
|                                | Modifier la requête / `dataset_query`|
|                                | Toute action sur `Nouvelles Conversions` |

## Découverte clé — visibilité côté client

Inspection live de la carte `29` (parmi les plus réutilisées, ~1 000 dashboards) :
**7 dashcards sur 8 ont un titre d'override** (`« Achats »`, `« Conversions »`,
`« leads »`…). Le nom de la carte est donc surtout un **label interne** ; le
client voit son override. Renommer une carte générique est *largement* invisible
côté client — ~12 % des dashcards héritent du nom et le verront changer.

Conséquence pour la politique de nommage : tant que le nouveau nom est une version
**plus propre** de l'ancien (snake_case nettoyé, casse correcte), sa propagation
aux ~12 % de tuiles client est neutre voire bénéfique. C'est l'ajout de suffixes
purement internes (`— Bar`) qui pose problème — d'où la règle viz ci-dessous.

## Convention de nommage (les règles)

Appliquées par un moteur déterministe :

- **Whitespace** — trim début/fin, doubles espaces collapsés.
- **Séparateur** — `_` → espace (`Add_to_cart_rate` → `Add to cart rate`).
- **Casse** — Sentence case, **liste blanche d'acronymes** préservés en
  majuscules : `CAC, CPC, CPM, CPL, CPA, CPI, CTR, CR, ROAS, COS, KPI, KPIs,
  SEO, GA4, PMax, DPA, ATC, ROI`. La liste vit dans `rename_lib.py` et peut être
  enrichie. Sans cette liste, `CAC` deviendrait `Cac`.
- **Suffixe viz** — supprimé puis **ré-ajouté en forme canonique
  ` — <Viz>`** (em-dash espace) **uniquement sur les collisions** : quand un
  ensemble de cartes partage le même nom normalisé et ne diffère que par le
  champ `display` (line/bar/table/scalar/…), on suffixe chacune. Partout
  ailleurs, on s'appuie sur l'icône native Metabase.
- **Marqueurs de statut** (`- to archive`, `| NC`, `- NC`) — **non touchés**
  par défaut ; ils relèvent d'une décision de contenu (archiver / repérer
  des cartes liées à `Nouvelles Conversions`). Signalés dans la proposition.

### Statut des règles

| Règle                | Statut       | Notes |
|----------------------|--------------|-------|
| Whitespace, snake_case | `auto`     | Mécanique, aucune ambiguïté |
| Casse + acronymes    | `auto`       | Dépend de la liste blanche — enrichissable |
| Suffixe viz (collision) | `auto`    | Détecté à partir du `display` |
| Nom irrécupérable par règles (`Cac3`, `Conv3`, `Perifit_check`) | `décision` | Les règles ne peuvent rien proposer de mieux — humain choisit un nom ou laisse |
| Doublons (22 noms ×2) | `décision`  | Comparer les requêtes ; renommer pour distinguer, ou flaguer pour archivage |

> **Note** sur `conversions_N` (`Cac_2, conversions_2 by date`, etc.) : les règles
> mécaniques s'appliquent normalement (le `_` devient un espace, la casse est
> corrigée — `Cac_2, conversions_2 by date` → `CAC 2, conversions 2 by date`).
> On ne tente **pas** de deviner le sens métier de « emplacement de conversion
> n°2 » ; c'est intentionnellement générique dans une bibliothèque template.

## Architecture

Deux fichiers Python sous `scripts/`, à côté de l'outil Phase 1 (que l'on ne
modifie pas).

| Fichier | Responsabilité |
|---|---|
| `scripts/rename_lib.py` | Logique pure : `normalize_name()`, détection de collisions, génération de la proposition, vérification d'invariant. Aucun effet de bord. |
| `scripts/rename_phase15.py` | CLI : `snapshot · propose · apply · verify · rollback`. Lit `.env`, appelle l'API Metabase. |
| `tests/test_rename_lib.py` | Tests unitaires (même convention que `tests/test_reorg_lib.py`, script autonome). |
| `migration/rename-proposal.csv` | Artefact de relecture (généré, édité par l'utilisateur, relu par `apply`). |
| `migration/rename-snapshot-<ts>.json` | Snapshot pré-vol (baseline + rollback). |

Le snapshot capture en plus de Phase 1 le champ **`display`** de chaque carte
(nécessaire pour la détection de collisions viz). Phase 1.5 ne réutilise pas
`reorg_lib.MetabaseState` pour rester isolée et tester ses propres invariants.

## Flux & artefact de relecture

1. **`snapshot`** — capture `{id, name, collection_id, dashboard_count, archived, display}`
   pour chaque carte du sous-arbre 215 hors `Nouvelles Conversions`. Écrit
   `migration/rename-snapshot-<ts>.json`.
2. **`propose`** — applique les règles au snapshot, écrit
   `migration/rename-proposal.csv` :

   | colonne          | sens |
   |------------------|------|
   | `card_id`        | id de la carte |
   | `current_name`   | nom actuel |
   | `proposed_name`  | nom après règles (ou vide pour `décision`) |
   | `rule`           | ex. `whitespace`, `snake_case`, `casing`, `viz_collision`, `cryptic`, `duplicate` |
   | `status`         | `auto` ou `décision` |
   | `notes`          | hint (ex. « collision avec card #X, #Y » ; « doublon de #Z ») |

3. **Gate de relecture** — l'utilisateur édite le CSV : valide / modifie les
   `auto`, remplit les `décision`, peut mettre `proposed_name == current_name`
   pour exclure une ligne.
4. **`apply`** — pour chaque ligne où `proposed_name ≠ current_name` :
   `PUT /api/card/{id} {name: <proposed_name>}` avec contrôle du code HTTP
   (`_check`). Après le batch : `verify`.
5. **`verify`** — re-capture l'état live et compare au snapshot.
6. **`rollback`** — restaure les noms d'origine depuis le snapshot.

## Sécurité, invariant, tests

**Invariant `verify` (différent de Phase 1)** — l'opération attendue est le
renommage, donc le nom **change**. Tout le reste doit être figé :

- même ensemble de `card_id` (aucune perdue, aucune nouvelle) ;
- `archived` toujours `False` pour les cartes de la baseline (aucune archivée) ;
- `dashboard_count` strictement identique au snapshot pour chaque carte (aucune
  référence de dashboard perdue) ;
- `collection_id` strictement identique au snapshot (aucune carte déplacée).

Toute divergence interrompt `apply`. `rollback` ré-applique les noms du snapshot.

**Idempotence** — relancer `propose` après un `apply` réussi produit **0 ligne
de renommage**. Vérifié par un test : `normalize_name(normalize_name(x)) == normalize_name(x)`.

**Tests unitaires** (`tests/test_rename_lib.py`, script autonome) :
- `normalize_name` — cas snake_case, trim, double-espaces, casse, acronymes
  préservés (CAC reste CAC), suffixe viz canonicalisé.
- Détection de collisions — groupes même-nom / displays différents → suffixés ;
  même-nom / même-display → `décision` (vrai doublon).
- Invariant — déplacement de carte = divergence, archivage = divergence, name
  change = OK.

**Garde-fous opérationnels** — comme Phase 1 : confirmation par lot (`--yes`
pour l'enchaîner), contrôle HTTP de chaque PUT, retry urllib3 hérité de la
librairie.

## Risques résiduels & limites

- **Visibilité côté client (~12 %)** — les dashcards qui héritent du nom de la
  carte verront le nom changer. Le nouveau nom étant une version plus propre
  (`Add to cart rate` au lieu de `Add_to_cart_rate`), c'est neutre/bénéfique.
  Pour les rares cas où un suffixe viz est ajouté (collisions), le client
  héritant verra `— Bar` apparaître — accepté car rare et nécessaire à la
  désambiguïsation. À communiquer si une vérification par échantillon de
  dashboards montre des cas gênants.
- **Liste d'acronymes** — toute lacune (ex. `IS` pour Impression Share, `NC`)
  produira une mise en minuscules incorrecte. Mitigation : la première
  exécution de `propose` permet d'auditer les casses obtenues avant `apply`,
  on enrichit la liste si besoin et on relance `propose`.
- **Renommages concurrents** — si un humain édite une carte entre `snapshot` et
  `apply`, son changement peut être écrasé. Mitigation : `verify` détecte un
  `dashboard_count` modifié comme signal de concurrence ; en cas de doute,
  re-`snapshot` juste avant `apply`.
- **Doublons réels (~22 paires)** — si deux cartes ont le même nom ET la même
  requête, l'une est candidate à l'archivage — décision de contenu, **hors
  Phase 1.5**. Le CSV les flagge ; le traitement reste à part.

## Hors périmètre

- Archivage / dédoublonnage / déplacement / modification de requête.
- Toute action sur `18. Nouvelles Conversions` (Phase 2).
- Description et autres champs métadonnées (peuvent être abordés en complément
  ultérieur, pas Phase 1.5).
- Marqueurs de statut dans les noms (`- to archive`, `| NC`) — signalés, pas
  modifiés automatiquement.
