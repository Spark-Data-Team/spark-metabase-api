# Spark Metabase API

Outil interne de l'équipe Tech [Spark](https://www.spark.do/) pour manipuler
notre instance Metabase. Ce n'est plus un paquet publié : il pilote une
production utilisée par 71 clients.

**Si tu es un agent, lis [`CLAUDE.md`](CLAUDE.md) avant d'écrire quoi que ce soit.**

## Installation

```bash
python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env   # puis renseigner METABASE_DOMAIN + SESSION_ID ou EMAIL/PASSWORD
```

## Usage

```python
from spark_metabase_api import connect, cards, dashboards, deps, diff

mb = connect()                                  # point d'entrée unique, lit le .env

carte = cards.get_card(mb, 32496)               # forme legacy garantie
cards.card_sql(carte)                           # le SQL, quelle que soit la forme reçue
cards.put_card(mb, 32496, {"name": "..."})      # écrit, relit, lève si ça n'a pas atterri

dashboards.put_dashboard(mb, 11917, {...})      # réinjecte tabs + parameters

deps.tables_of(mb, 32496)                       # tables réellement lues (graphe natif)
deps.broken(mb, 32496)                          # dépendances cassées
```

Les écritures lèvent `MetabaseError` en cas d'échec.

## Différentiel avant/après

La brique que rien ne remplace côté Metabase : ni l'API EE, ni le CLI `mb`.
À utiliser autour de toute modification de masse.

```python
avant = cards.card_values(mb, card_id)
# ... mutation ...
apres = cards.card_values(mb, card_id)

diff.check_values("carte 32496", avant, apres, mode="identical")
```

`identical` quand un refacto doit préserver les nombres, `monitor` quand une
migration les change volontairement.

## Tests

```bash
.venv/bin/python -m pytest -q     # 512 tests, hors-ligne, moins d'une seconde
```

La suite ne touche pas le réseau. Rien ne part en production sans qu'elle soit
au vert.

## Structure

| Chemin | Contenu |
|---|---|
| `spark_metabase_api/` | le noyau : `connect`, `http`, `cards`, `dashboards`, `deps`, `diff`, `guard` |
| `scripts/` | campagnes en cours |
| `scripts/_archive/` | campagnes closes, conservées pour la trace |
| `docs/superpowers/` | specs et plans |
| `migration/` | snapshots et rollbacks d'exécution, gitignorés sauf les décisions humaines |

## Ce qu'on laisse à Metabase

Le graphe de dépendances, le contenu obsolète, les collections officielles et
les cartes vérifiées sont natifs. Ne pas les réimplémenter. Détail dans
[`docs/superpowers/specs/2026-08-17-repo-simplification-design.md`](docs/superpowers/specs/2026-08-17-repo-simplification-design.md).

## Remerciements

- [Documentation de l'API Metabase](https://www.metabase.com/docs/latest/api-documentation)
- [Changelog de l'API](https://www.metabase.com/docs/latest/developers-guide/api-changelog)
- Inspiré de [metabase_api_python](https://github.com/vvaezian/metabase_api_python)
