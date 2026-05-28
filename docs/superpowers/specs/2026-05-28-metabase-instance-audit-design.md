# Audit d'optimisation de l'instance Metabase — Design

> **Date** : 2026-05-28
> **Statut** : design validé en brainstorming, en attente de relecture
> **Topic** : audit instance-wide → backlog de campagnes de nettoyage exécutables

## 1. Contexte & objectif

L'instance Metabase a accumulé de la dette : doublons, éléments inutilisés,
collections vides, travail client logé dans des espaces personnels, structure
incohérente. Les chantiers précédents (`reorg` Phase 1, `rename` Phase 1.5,
`reorg-xplat`, `prune`, `find_dupes`) n'ont touché qu'**une seule** collection :
le template `2. Generic Questions` (215).

**Objectif** : faire ressortir, sur **toute l'instance**, les patterns
d'optimisation, de façon quantifiée et priorisée, puis livrer un **plan de
campagnes de nettoyage exécutables** — chacune suivant le workflow sûr déjà
rodé (snapshot → test différentiel → échantillon → batch → invariant).

Ce document conçoit l'**outil d'audit** et le **modèle de campagne**. Chaque
campagne retenue dans le backlog fera ensuite l'objet de son propre plan
d'exécution (à la manière des docs de Phase existants).

## 2. Périmètre

Toute l'instance. Photographie live au 2026-05-28 :

| Élément | Volume |
|---------|--------|
| Collections | **868** (533 non-perso, 335 perso) |
| Cartes actives | **5 654** (282 en collections perso, 5 372 en partagé) |
| Dashboards | **735** |
| Collections non-perso **vides** | **241 / 533** (45 %) |
| Collections "…Nanga's Personal Collection" | **191** |
| Collections perso préfixées d'un nom de client | **187** |
| Noms de collections en double | 45 noms / 189 entrées redondantes |
| ⚠️ Archivées | non comptées (l'API les masque par défaut) — à mesurer |

> Note : le template 215 représente ~1 198 cartes ; l'essentiel du désordre est
> **hors template**.

## 3. Garde-fous & contraintes

- **Toutes les actions sont autorisées** (archivage, suppression, déplacement,
  rangement du sprawl perso, renommage) **mais validation à chaque action** :
  je demande avant d'agir.
- **Réversible d'abord** : archiver avant supprimer ; suppression seulement
  après validation explicite + fenêtre de rétention.
- **Risque = barrière** : tout finding qui touche aux collections personnelles
  ou aux copies clientes passe *obligatoirement* par validation, quel que soit
  son impact.
- **Règle "hors sources"** : ne jamais prune/fusionner une carte qui sert de
  source/modèle à une autre.

## 4. Architecture

Un outil CLI `scripts/audit.py`, même squelette que les scripts existants
(connexion via `.env`, snapshots dans `migration/`). Trois commandes :

```
audit scan    →  passe LARGE (métadonnées, toute l'instance + archivées)
                 écrit migration/audit-findings-YYYYMMDD.json
audit deep    →  passe PROFONDE — fetch des requêtes du corpus complet
                 (cache disque, reprenable), enrichit le JSON
audit report  →  rend docs/audits/audit-YYYYMMDD.md (priorisé) + backlog
```

**Place dans l'existant** : l'audit ne remplace pas `find_dupes` / `prune_unused`
/ `rename_lib` / `reorg_lib`. Il **généralise leur détection à toute l'instance**
et **unifie la sortie**. Chaque campagne du backlog réutilise (ou fait évoluer)
ces scripts comme *exécuteurs*. La détection de doublons passe en **v2**
(comparaison sur requête réelle, paramètres inclus — voir #6).

### Passes

- **Passe large** (`scan`) — métadonnées uniquement (`/api/collection/`,
  `/api/card/`, `/api/dashboard/`, + variantes archivées). Détecte tous les
  patterns calculables sans ouvrir les requêtes.
- **Passe profonde** (`deep`) — **corpus complet** : fetch de la requête de
  chacune des ~5 654 cartes, **mise en cache disque et reprenable** (pas de
  re-fetch, throttlé). Permet la détection exhaustive des doublons (#6), de la
  dérive template (#8), des familles de variantes (#9) et la construction du
  **graphe de sources** (#5).

## 5. Catalogue de patterns

5 familles, 11 patterns. `[L]` = passe large, `[P]` = passe profonde.

### Famille 1 — Bruit structurel (collections)
| # | Pattern | Détection | Observé |
|---|---------|-----------|---------|
| 1 | **Collections vides** (0 carte active, 0 dashboard, aucun descendant non-vide) | `[L]` | 241/533 non-perso |
| 2 | **Sprawl perso** : travail client en collection personnelle + coquilles vides nominatives | `[L]` | 335 perso, 191 "Nanga…", 187 préfixées client |
| 3 | **Noms de collections dupliqués**, surtout **rangé-par-type-de-viz** | `[L]` | `Bar/Combo/Line/Pie/Smartscalar` ×28 |
| 4 | **Collections fourre-tout / staging** ("To sort"…) | `[L]` | "To sort" (7252) |

### Famille 2 — Gaspillage au niveau carte
| # | Pattern | Détection | Note |
|---|---------|-----------|------|
| 5 | **Cartes inutilisées** : 0 dashboard **ET** non-source d'une autre carte | `[L]`+`[P]` | template : 52 ; instance : à mesurer |
| 6 | **Doublons fonctionnels v2** : même requête normalisée (paramètres + métrique inclus) | `[P]` | corrige les faux positifs d'empreinte |
| 7 | **Backlog archivé** jamais purgé (cartes/dashboards/collections) | `[L]` | nécessite le fetch `archived=true` |

### Famille 3 — Propagation / DRY
| # | Pattern | Détection | Note |
|---|---------|-----------|------|
| 8 | **Dérive template** : copies clientes divergentes du maître 215 | `[P]` | 735 dashboards, bcp de copies |
| 9 | **Variantes paramétrables** : familles quasi-identiques → 1 carte paramétrée | `[P]` | transforme les "faux positifs" en optimisation |

### Famille 4 — Nommage / hygiène
| # | Pattern | Détection | Note |
|---|---------|-----------|------|
| 10 | **Incohérences de nommage hors template** (cryptique, suffixe viz, double espace…) | `[L]` | étend la Phase 1.5 |

### Famille 5 — Performance
| # | Pattern | Détection | Note |
|---|---------|-----------|------|
| 11 | **Cartes coûteuses / lentes / jamais consultées** | `[P]` | si l'API expose `query_executions` / vues ; sinon best-effort |

**#6 et #9 sont les deux faces d'une même pièce.** L'empreinte actuelle voit
"clics/CTR/position" comme un doublon (faux positif). En passe profonde on lit
la requête réelle : soit *vrai* doublon (→ #6, fusion), soit variantes légitimes
(→ #9, candidat à une carte paramétrée unique).

## 6. Scoring & priorisation

Chaque finding est noté **Impact / Risque / Effort** (H-M-L) :

- **Impact** — réduction de bruit / dette.
- **Risque** — dangerosité du correctif (réversibilité, dépendances). *Sert
  aussi de barrière de validation.*
- **Effort** — automatisable vs jugement manuel.

Le backlog sort ordonné en **4 vagues** (quick-wins d'abord) :

| Vague | Critère | Exemples de campagnes |
|-------|---------|------------------------|
| **0 — Quick wins** | Impact H · Risque L · réversible | Archiver les 241 collections vides · purger le backlog archivé |
| **1 — Automatisable forte valeur** | Impact H/M · Risque L/M | Doublons v2 · prune inutilisées (instance) · nommage |
| **2 — Structurel** | Impact H · Effort M/H | Aplatir le rangé-par-viz · ranger le sprawl perso *(validation)* |
| **3 — DRY / dérive** | Impact H · Effort H · jugement | Réconcilier la dérive template · paramétrer les variantes (#9) |

## 7. Format de sortie

1. **`migration/audit-findings-YYYYMMDD.json`** — machine. Par pattern : liste
   des entités touchées (id, nom, location), compteurs, preuves de la passe
   profonde. Consommé par les scripts exécuteurs.
2. **`docs/audits/audit-YYYYMMDD.md`** — humain, priorisé, **court et scannable** :
   - Résumé exécutif (chiffres-clés, top patterns par impact)
   - Une section par pattern : définition en 1 ligne, compte, **3-5 exemples**
     représentatifs (noms/id), action recommandée, I/R/E, vague
   - Le **backlog de campagnes** ordonné : scope, volume estimé, barrière de
     risque, checklist du workflow sûr

   **Principe** : le `.md` est un digest — tableaux compacts, pas de pavés,
   exemples limités. Les listes exhaustives d'entités vivent dans le JSON ;
   le rapport y renvoie plutôt que de les dérouler.

## 8. Modèle d'exécution d'une campagne

```
snapshot → plan (dry-run du diff) → test différentiel → échantillon
        → batch + invariant → verify/rollback
```

- **Test différentiel** (campagnes qui modifient une requête : #6, #8) :
  exécuter la carte avant/après, comparer — résultats identiques obligatoire.
- **Invariant post-batch** : `lost / archived / moved / dashboard_count`
  (harnais existant).
- **Validation avant chaque action** ; obligatoire sur Risque-H.
- Les **quick-wins (vague 0)** s'exécutent directement (snapshot + validation).
  Toute campagne plus lourde reçoit son **propre plan court**.

## 9. Sûreté / gestion d'erreurs

- **Archivées cachées** : forcer le fetch archivé, sinon "inutilisé" et "backlog
  archivé" sont faux.
- **Quirk `dataset_query` vide** : via l'API, le nouveau format `dataset_query`
  ressort souvent vide ; la passe profonde fetch l'objet carte complet
  (`/api/card/:id`) et se rabat sur `legacy_query` pour l'empreinte (déjà
  constaté lors de `find_dupes`). L'empreinte v2 doit normaliser à partir de la
  représentation réellement peuplée, paramètres inclus.
- **Graphe de sources** : construit en passe profonde ; protège la règle
  "hors sources".
- **Anti-faux-positif** : #6 exige une correspondance de requête réelle
  (paramètres inclus) avant toute proposition de fusion — jamais sur l'empreinte
  seule.
- **Volume** : fetch mis en cache disque, reprenable, throttlé.
- **Idempotence** : `scan`/`deep`/`report` sont en lecture seule ; les
  exécuteurs sont idempotents (gardes de suffixe comme `rename`).

## 10. Tests

- Détecteurs : tests unitaires sur fixtures (patterns connus → findings
  attendus), dans `tests/`.
- **Garde-fou régression empreinte v2** : les faux positifs connus
  (clics/CTR/position ; nuages/pluie/temp) doivent être classés **variantes
  (#9), pas doublons (#6)** — assert explicite.
- Exécuteurs : tests d'invariant (réutilise le harnais reorg/rename) + harnais
  de test différentiel.

## 11. Livrables & étapes suivantes

1. `scripts/audit.py` (commandes `scan`, `deep`, `report`) + tests.
2. `migration/audit-findings-YYYYMMDD.json` (généré).
3. `docs/audits/audit-YYYYMMDD.md` — le diagnostic priorisé + le backlog.
4. Exécution des campagnes une par une, dans l'ordre des vagues, chacune avec
   son plan court (si non-trivial) et validation à chaque action.

## 12. Hors périmètre (pour l'instant)

- L'exécution des campagnes elles-mêmes (ce design produit le backlog ; chaque
  campagne sera planifiée et exécutée séparément).
- La refonte de fond de l'arborescence cible du template (relève des chantiers
  reorg existants).
