# Design — Migration live Phase 1 : réorganisation de la collection « 2. Generic Questions »

> Date : 2026-05-20
> Spec de réorganisation globale : [`docs/generic-questions-reorg.md`](../../generic-questions-reorg.md)
> Instance : `https://spark.metabaseapp.com/collection/215`
> Statut : design validé — à transformer en plan d'implémentation.

---

## Contexte

La collection `215` « 2. Generic Questions » regroupe **3 181 cartes dans 222
collections**, mélangeant deux axes de classement, avec des préfixes numériques
manuels, des collections vides, un fourre-tout `To sort` et 425 cartes non rangées.
Le constat complet et la structure cible figurent dans `docs/generic-questions-reorg.md`.

Deux faits établis par l'exploration de l'instance (lecture seule) cadrent la sécurité :

1. **La collection 215 est interne.** Permissions : `Administrators` / `Data` en
   écriture, `Growth` / `SEO` en lecture, groupes clients sans aucun accès.
2. **Les cartes sont référencées massivement par les dashboards clients.** Échantillon
   de 25 cartes : 24 utilisées dans ≥ 1 dashboard, certaines à très grande échelle
   (carte `29` → 1 211 dashboards, `303` → 1 101, `1453` → 435).

Conséquence : Metabase identifie une carte par son **ID** (jamais par sa collection ni
son nom). Tant qu'aucun ID ne change, aucun dashboard client ne peut casser.

## Objectif

Réorganiser **en live** la collection 215 selon la structure cible, **sans casser
aucun dashboard client**, de façon maîtrisée, vérifiable et réversible.

## Périmètre

**Phase 1 = restructure pure.**

| Opérations autorisées                        | Opérations interdites en Phase 1            |
|----------------------------------------------|---------------------------------------------|
| Créer une collection                         | Archiver ou supprimer une carte             |
| Déplacer une collection (`parent_id`)        | Renommer une carte                          |
| Renommer une collection                      | Modifier la requête / le `dataset_query`    |
| Déplacer une carte (`collection_id`)         | Toute action sur `18. Nouvelles Conversions`|
| Supprimer une collection **vide**            |                                             |

Aucune opération autorisée ne change un ID de carte → propriété de non-régression
garantie par construction, et prouvée par la vérification post-lot.

**Hors Phase 1 (phases ultérieures, dédiées) :** renommage des cartes,
dédoublonnage des 22 noms répétés, sous-découpage des tas plats (GA4, Shopify,
Adjust, Industry benchmarks), et toute la collection `18. Nouvelles Conversions`
(générée par script — traitée en corrigeant le générateur).

## Structure cible

4 familles créées sous la collection 215, profondeur 3 niveaux max :

```
2. Generic Questions
├── Cross-platform/        ex-"01. Global" (entités Account/Campaign/Ad group/Ad)
├── Ad platforms/          Google Ads, Meta, Microsoft Ads, Pinterest, Amazon Ads,
│                          Spotify, Adjust, Appsflyer
├── Web & Analytics/       Google Analytics 4, SEO, Shopify, Magento
├── Benchmarks & Strategy/ Industry benchmarks, Brand Monitoring, Client Goals,
│                          Business Plan, AI
└── 18. Nouvelles Conversions   ← inchangée, reste à la racine
```

Mapping détaillé ancien → nouveau : §4 de `docs/generic-questions-reorg.md`. Les
préfixes numériques (`00.`…`18.`) sont retirés des noms de collections ; les
collections d'entités gardent un préfixe ordinal (`1. Account`…`4. Ad`) là où un
ordre métier est nécessaire.

## Architecture de la solution

### Composant 1 — Script de migration `scripts/reorg_phase1.py`

CLI s'appuyant sur la librairie `spark_metabase_api`. Sous-commandes, chacune avec
une responsabilité unique :

| Sous-commande | Rôle | Écrit dans Metabase ? |
|---------------|------|------------------------|
| `snapshot`    | Capture l'état complet du sous-arbre 215 → JSON | Non |
| `plan`        | Calcule et imprime tous les déplacements (dry-run) | Non |
| `apply`       | Exécute un lot du plan, avec confirmation | Oui |
| `verify`      | Re-fetch et compare à un snapshot | Non |
| `rollback`    | Ré-applique les positions d'origine depuis le snapshot | Oui |

**`snapshot`** — pour chaque collection du sous-arbre 215 : `{id, name, parent_id}` ;
pour chaque carte : `{id, name, collection_id, dashboard_count, archived}`. Écrit
`migration/snapshot-<timestamp>.json`. Sert à la fois de baseline de vérification et
de fichier de rollback. `18. Nouvelles Conversions` est incluse dans le snapshot
(pour prouver qu'elle reste intacte) mais exclue du plan.

**`plan`** — lit le plan déclaratif (composant 2), résout chaque opération, imprime
le diff complet (collections créées / déplacées / renommées / supprimées, cartes
déplacées). N'effectue **aucune** écriture.

**`apply <lot>`** — exécute un lot nommé du plan (voir séquence ci-dessous). Demande
confirmation, puis applique les `PUT` / `POST` / `DELETE`, puis appelle `verify`
automatiquement. S'arrête à la première divergence.

**`verify`** — recharge l'état live et vérifie les invariants (voir section Sécurité).

**`rollback`** — relit un snapshot et ré-applique `collection_id` (cartes) et
`parent_id` (collections) d'origine. Les familles créées et vidées sont supprimées.

### Composant 2 — Plan déclaratif `migration/phase1-plan.yaml`

Source de vérité unique, **relue et validée par l'utilisateur avant tout `apply`**.
Contenu :

- `families` : les 4 collections de famille à créer (nom, description).
- `collections` : pour chacune des 18 collections numérotées — `id`, famille parente
  cible, nouveau nom (sans préfixe).
- `card_filing` : classification des **425 cartes en vrac** de `01. Global` + des
  **9 cartes** de `To sort` → `card_id: collection_cible`. Généré par analyse du nom
  et de la requête de chaque carte, **soumis à relecture utilisateur**.
- `delete_empty` : liste des collections vides à supprimer.

Le script ne déduit rien implicitement : tout ce qu'il fait est déclaré dans ce
fichier, ce qui rend le diff lisible et auditable avant exécution.

### Artefacts produits

```
scripts/reorg_phase1.py          le script CLI
migration/phase1-plan.yaml       le plan déclaratif (versionné)
migration/snapshot-<ts>.json     l'état pré-vol (versionné, = baseline + rollback)
```

## Séquence d'exécution

Chaque étape est vérifiée avant de passer à la suivante.

1. **`snapshot`** → `migration/snapshot-<ts>.json`, committé.
2. **Génération de `phase1-plan.yaml`** (classification des cartes en vrac) →
   **gate de relecture utilisateur** : l'utilisateur valide le mapping avant suite.
3. **`plan`** (dry-run) → relecture du diff complet par l'utilisateur.
4. **`apply lot-1`** : créer les 4 collections de famille (vides).
5. **`apply lot-2`** : déplacer + renommer les ~14 collections non vides sous leurs
   familles (les 4 collections plateformes vides ne sont pas déplacées, juste
   supprimées au lot-5) → `verify`.
6. **`apply lot-3`** : ranger les cartes en vrac de `01. Global` dans les entités
   → `verify`.
7. **`apply lot-4`** : dispatcher les 9 cartes de `To sort` → `verify`.
8. **`apply lot-5`** : supprimer les collections vides → `verify`.
9. **`verify` final complet** : 0 carte perdue, 0 carte archivée, tous les
   `dashboard_count` identiques au snapshot, arbre conforme au plan.
10. **Figer** : export IaC YAML de la structure finale → commit git. Toute évolution
    ultérieure passe par `plan` / `apply` du module IaC.

## Sécurité, vérification, rollback

**Invariant vérifié après chaque lot et en final** (`verify`) :

- `set(card_ids)` live == `set(card_ids)` du snapshot — aucune carte perdue/ajoutée.
- Pour chaque carte : `archived` toujours `False` — aucune carte archivée.
- Pour chaque carte : `dashboard_count` live == snapshot — aucune référence de
  dashboard perdue.
- L'arborescence live correspond à ce que le plan décrit.

Toute divergence interrompt immédiatement le script (pas de poursuite « best
effort »).

**Garde-fous opérationnels :**

- Suppression de collection : uniquement après contrôle `items == 0` au moment de
  l'exécution ; sinon la collection est ignorée et une alerte est émise.
- Le script ne touche jamais une carte ou une collection en dehors du sous-arbre 215,
  ni quoi que ce soit sous `18. Nouvelles Conversions`.
- Session HTTP avec retry urllib3 (déjà en place dans la librairie) pour absorber les
  erreurs transitoires.
- `apply` demande une confirmation explicite avant chaque lot.

**Rollback :** `rollback` ré-applique l'intégralité des positions du snapshot en une
commande. Comme la Phase 1 ne fait que déplacer (jamais archiver/supprimer une
carte), l'état d'origine est intégralement reconstructible.

## Pré-requis

- `session_id` admin valide dans `.env` (`METABASE_SESSION_ID`) — à rafraîchir s'il a
  expiré ; le groupe `Data` ou `Administrators` est requis pour les écritures.
- Support YAML : `pip install "spark-metabase-api[iac]"` (déjà nécessaire pour le
  module IaC utilisé à l'étape 10).

## Risques résiduels et limites

- **Renommage des collections visible côté outils internes** : `Growth` / `SEO`
  voient la collection 215 ; leurs raccourcis/bookmarks vers les anciennes
  collections renommées peuvent pointer ailleurs. Impact interne uniquement, pas
  client. À communiquer aux équipes.
- **Classification des cartes en vrac** : risque de mauvais classement (pas de
  casse — un déplacement est réversible). Mitigé par le gate de relecture (étape 2).
- **Expiration de session en cours de migration** : un lot interrompu laisse un état
  partiel cohérent (déplacements idempotents) ; relancer le lot après
  ré-authentification le complète. `verify` confirme l'état réel.

## Hors périmètre (rappel)

Renommage de cartes, dédoublonnage, sous-découpage des tas plats, et toute action sur
`18. Nouvelles Conversions` — traités dans des phases ultérieures dédiées.
