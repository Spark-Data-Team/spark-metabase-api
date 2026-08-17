# Manipuler Metabase depuis ce dépôt

Outil interne Spark. Il pilote **une instance de production** utilisée par 71 clients.
Toute écriture est visible immédiatement par eux. Lis cette page en entier avant
d'écrire quoi que ce soit.

## Le chemin normal

```python
from spark_metabase_api import connect, cards, dashboards, deps, diff

mb = connect()                                  # point d'entrée UNIQUE
carte = cards.get_card(mb, 32496)               # forme legacy garantie
cards.put_card(mb, 32496, {"name": "..."})      # écrit, relit, vérifie
dashboards.put_dashboard(mb, 11917, {...})      # réinjecte tabs + parameters
deps.tables_of(mb, 32496)                       # dépendances réelles
```

Ne construis pas ta propre connexion. Le dépôt a longtemps porté trois idiomes
concurrents (58 `def connect()` recopiés, des imports de `_load_env` depuis un
script de campagne terminée). `connect()` les remplace tous.

## Les six invariants

**1. Ne teste jamais `if mb.put(...)`.**
L'ancienne façade rend un `status_code`, donc **500 est truthy**. Une écriture
ratée passe pour une réussite. Utilise `spark_metabase_api.http`, qui lève
`MetabaseError`, ou `cards.put_card` / `dashboards.put_dashboard`.

**2. Lis une carte avec `cards.get_card`, jamais `mb.get("/api/card/{id}")`.**
Depuis MBQL5, `GET /api/card/{id}` rend `dataset_query = {database, lib/type, stages}`
avec `type = None`. Il faut `?legacy-mbql=true` pour retrouver `{database, native, type}`.
Tout le code du dépôt lit `type` et `native`. `get_card` ajoute le paramètre pour toi.
Pour extraire le SQL quelle que soit la forme reçue : `cards.card_sql(carte)`.

**3. Un PUT dashboard sans `tabs` renvoie un 500.**
Et omettre `parameters` efface les filtres **sans lever d'erreur**. Passe toujours par
`dashboards.put_dashboard`, qui relit l'état, réinjecte, écrit, puis vérifie qu'aucun
onglet, filtre ou tuile n'a disparu.

**4. Ne te sers pas de `/unreferenced` pour archiver.**
`backfill-status` vaut `complete: false` sur l'instance. Dans cet état le graphe natif
remonte du vivant comme mort : une sonde `type=card` a rendu le dashboard 673, vu
6 547 fois. `deps.unreferenced()` lève tant que le backfill n'est pas terminé, c'est
volontaire. Ne contourne pas avec `force=True` pour décider d'un archivage.

**5. `Metabase_API` n'est pas thread-safe.**
Le client peut se ré-authentifier en vol et remplacer son header. Ne le partage pas
entre threads. Un script du dépôt fait tourner 5 pools de 8 threads sur un client
partagé : c'est un bug, pas un modèle à copier.

**6. Toute écriture de masse : snapshot, puis échantillon, puis lot.**
Sauvegarde l'état complet sur disque avant de toucher quoi que ce soit, applique sur
2 ou 3 objets, vérifie le différentiel, et seulement ensuite lance le lot. Le rollback
n'existe que si tu l'as écrit avant.

## Vérifier son travail

```bash
.venv/bin/python -m pytest -q        # 504 tests, hors-ligne, < 1 s
```

Aucune modification ne part sans cette suite au vert. Elle ne touche pas le réseau,
donc tu peux la lancer autant que tu veux.

Pour un différentiel avant/après sur des données réelles :

```python
avant = cards.card_values(mb, card_id)
# ... mutation ...
apres = cards.card_values(mb, card_id)
diff.check_values("carte 32496", avant, apres, mode="identical")
```

`mode="identical"` quand un refacto doit préserver les nombres, `mode="monitor"`
quand une migration les change exprès. C'est la seule brique du dépôt qu'aucune
fonctionnalité native de Metabase ne remplace.

## Ce qui est natif et ne doit pas être réécrit

| Besoin | À utiliser |
|---|---|
| dépendances d'une carte, tables lues, casse potentielle | `deps.py` (API EE native) |
| contenu obsolète | `/api/ee/stale`, mais voir l'invariant 4 |
| collections officielles, cartes vérifiées | `authority_level`, `moderated_status` |

N'écris pas de regex `card__(\d+)` pour trouver des dépendances. Elle ne voit rien
sur une carte SQL native. Le graphe natif résout les vraies tables.

## Structure

```
spark_metabase_api/   le noyau. Peu de fichiers, chacun avec un contrat clair.
scripts/              campagnes en cours. Un script = une campagne.
scripts/_archive/     campagnes closes. Ne pas y toucher, ne pas s'en inspirer.
docs/superpowers/     specs et plans.
migration/            artefacts d'exécution (snapshots, rollbacks). Gitignoré sauf
                      les décisions humaines.
```

Avant d'écrire un nouveau script, cherche s'il existe déjà. Le dépôt a compté
jusqu'à 118 scripts, dont beaucoup faisaient la même chose deux fois.

## Campagnes actives

Ne supprime, ne déplace et ne refactore aucun script de campagne active sans accord
explicite. Elles écrivent en production cette semaine.

- migration des conversions
- réparation des questions en erreur (août 2026)
- descriptions top100
- ménage de la collection 14115

## Interdits

- Créer une clé API, changer les permissions ou toucher au graphe de collections
  sans demande explicite.
- Archiver ou supprimer du contenu Metabase sur la foi d'un seul signal.
- Lancer un lot complet sans avoir validé un échantillon.
- Publier le paquet sur PyPI. C'est un outil interne.
