# Simplification du dépôt : un noyau étanche pour manipuler Metabase

Date : 2026-08-17
Statut : approuvé (approche A)
Branche : `chore/repo-simplification`

## 1. Objectif

Deux axes, demandés ensemble :

1. **Réduire la surface de code maison** là où Metabase fournit désormais l'équivalent natif.
2. **Rendre le dépôt anti-erreur** quand un agent LLM s'en sert pour écrire dans Metabase.

Les quatre modes d'échec visés, confirmés par l'utilisateur :

| Mode d'échec | Cause racine mesurée |
|---|---|
| Écritures fausses en prod | `put()` renvoie `res.status_code` : un 500 est truthy, donc `if mb.put(...)` réussit sur une erreur serveur |
| Batch qui casse au milieu | aucun snapshot ni reprise imposés, chaque script réinvente son garde-fou |
| Claude réinvente la roue | 118 scripts sans index, 3 idiomes de connexion concurrents, aucun `CLAUDE.md` |
| Pièges d'API Metabase | `tabs` obligatoire au PUT dashboard et forme MBQL5 en lecture, écrits nulle part |

## 2. État initial mesuré

| Périmètre | Fichiers | LOC |
|---|---|---|
| `spark_metabase_api/` | 10 | 3 464 |
| `scripts/` | 118 | 25 775 |
| `tests/` | 35 | 9 320 |

Dette structurelle :

- 58 `def connect()` distincts dans `scripts/`, 56 scripts important `_load_env` depuis
  `scripts/reorg_phase1.py` (une campagne **terminée**), 16 important `connect_resilient`
  depuis `scripts/archive_collections.py`. Aucun point d'entrée dans la bibliothèque.
- 156 `sys.path.insert` recopiés.
- 110 appels `.put(` dont 66 en mode `"raw"` : 60 % des écritures contournent la bibliothèque.
- 42 scripts et tests jamais versionnés (corrigé en vague 1).
- Aucun `CLAUDE.md`.
- Baseline de vérification : **498 tests, 0,8 s, hors-ligne, verts.**

## 3. Faits vérifiés sur l'instance live

Instance : Metabase Cloud v1.63.13, Pro/Enterprise. Sondages en GET uniquement.

**3.1 — Le validateur maison est cassé depuis MBQL5.**

```
GET /api/card/32496                    -> dataset_query = {database, lib/type, stages}  type=None
GET /api/card/32496?legacy-mbql=true   -> dataset_query = {database, native, type}      type='native'
```

`validate.check_structure` lit `dataset_query["type"]` sans le paramètre, reçoit `None`, et
conclut « unknown query type » sur **toutes** les cartes de la prod. Une couche censée
empêcher les erreurs qui en produit.

**3.2 — Le graphe de dépendances natif est strictement supérieur au nôtre.**

```
GET /api/ee/dependencies/graph?id=32496&type=card  -> 200, 9 nodes / 8 edges
```

Sur cette carte (SQL natif Snowflake, aucun `card__`), le natif résout 8 tables réelles.
Notre regex `card__(\d+)`, dupliquée dans 16 fichiers, ne voit rien.

**3.3 — L'endpoint « non référencé » n'est pas fiable aujourd'hui.**

```
GET /api/ee/dependencies/backfill-status -> {"complete": false}
```

Tant que ce drapeau est faux, `/unreferenced` remonte du vivant comme mort. Interdiction
de s'en servir pour décider d'un archivage.

**3.4 — Remote sync est licencié mais non branché.**

`remote_sync: true` dans le token, `remote-sync-enabled: false`, `remote-sync-url: null`.
Le mode `read-only` bloquerait tous nos PUT, donc il tuerait les 4 campagnes actives.
Chantier post-campagnes, hors périmètre.

**3.4bis — Le piège « PUT dashboard sans tabs » n'existe plus en v1.63.13.**

Testé le 2026-08-17 dans la condition réelle du bug (2 onglets, une tuile posée sur un
onglet) : un `PUT {"name": ...}` nu ne renvoie pas de 500 et ne perd ni onglet ni tuile.
Metabase préserve les champs omis d'un PUT partiel. `put_dashboard` reste utile pour sa
**relecture vérifiée**, pas pour sa réinjection. L'avertissement inverse a été retiré de
`CLAUDE.md` : une consigne périmée dans les instructions d'un agent est une source
d'erreur active, exactement le motif qui a fait supprimer trois scripts en vague 2.

**3.5 — Le différentiel avant/après n'a aucun équivalent natif.**

Aucun verbe `diff`, `compare` ou `baseline` dans les 139 commandes du CLI `mb`. Metabase
documente lui-même ne pas savoir détecter un changement de logique de calcul comme cassant.
C'est le cœur de valeur du dépôt : il ne bouge pas.

## 4. Architecture cible

```
spark_metabase_api/
  __init__.py      connect()          point d'entrée UNIQUE
  session.py       auth, .env, retry, plus d'impression du token
  http.py          get/post/put/delete qui LÈVENT MetabaseError
  cards.py         get_card (forme legacy garantie) / put_card (relit et vérifie)
  dashboards.py    put_dashboard (réinjecte tabs + parameters)
  deps.py          graphe de dépendances natif
  diff.py          check_values, check_differential, _signature
  guard.py         snapshot -> dry-run -> apply -> relecture -> rollback
scripts/           campagnes vivantes uniquement
scripts/_archive/  campagnes closes, conservées, hors du champ de vision
CLAUDE.md          invariants non négociables
```

### Contrats par module

**`http.py`** — une seule implémentation HTTP. Lève `MetabaseError` (avec méthode, chemin,
status, corps tronqué) sur tout non-2xx. Plafonne la sortie des listes comme le fait le CLI
natif (24 576 octets, enveloppe `{returned, total, has_more, next_offset}`) pour qu'un agent
qui liste `/api/card/` ne sature pas son contexte.

**`cards.py`** — `get_card(id)` renvoie **toujours** la forme legacy (`?legacy-mbql=true`),
ce qui supprime le piège 3.1. `put_card()` écrit, vérifie le status, relit la carte et
confirme que la modification a atterri, en lisant `dataset_query.stages[].native` et jamais
`legacy_query`.

**`dashboards.py`** — `put_dashboard()` fait GET, fusionne, réinjecte systématiquement `tabs`
et `parameters`, vérifie le status, relit. Le 500 « PUT dashboard sans tabs » devient
impossible à déclencher. Trois scripts portent ce bug aujourd'hui
(`migrate_conversions_on_dashboard.py:205`, `migrate_dashboard_full.py:183`,
`swap_card_on_dashboards.py:128`).

**`deps.py`** — enveloppe `/api/ee/dependencies/graph`. `unreferenced()` vérifie d'abord
`backfill-status` et **lève** si `complete` est faux, au lieu de rendre des résultats faux.

**`diff.py`** — `validate.py` réduit à ce qui sert : `check_values`, `check_differential`,
`_signature`. Vérifié : les scripts n'appellent qu'une seule fonction de `validate.py`,
`check_values`, dans 3 fichiers (`migrate_dashboard_reuse.py`, `deploy_special_cards.py`,
`migrate_conversions_on_dashboard.py`). Sortent : `check_structure` (cassé, remplacé par le
natif), `check_refs` (remplacé par `deps.py`), `gate`, `units_from_spec`, `unit_from_payload`,
`unit_from_card_id`, `resolve_cli_target` (couplés au bloc IaC supprimé).

**`guard.py`** — absorbe `guarded_apply`. Toute écriture de masse passe par : snapshot complet
sur disque, dry-run par défaut, apply, relecture, fichier de rollback.

### Stratégie de compatibilité

Les anciennes méthodes `mb.get` / `mb.put` / `mb.post` / `mb.delete` **restent** et gardent
leur valeur de retour historique (`False`, `status_code`), mais deviennent de fines façades
qui rattrapent `MetabaseError`. Comportement inchangé pour les 118 scripts, avec un
`DeprecationWarning`. Un shim conserve les imports `_load_env` / `connect_resilient` le temps
de la migration par lots.

Aucun script de campagne active ne casse le jour du changement.

## 5. Suppressions

| Bloc | LOC | Justification |
|---|---|---|
| `iac.py` + `chatbot.py` + `streamlit_app.py` | ~1 530 | importés par aucun script ; recouverts par le Representation Format natif ; décision utilisateur |
| `copy_methods.py` + `clone_card` | 416 | 0 appel réel ; `clone_card` porte « work in progress » |
| helpers inatteignables `_helper_methods.py:245-355` | 105 | non montés sur la classe, duplication de `get_item_id` |
| `validate.py` mort | ~140 | voir §4 `diff.py` |
| 16 scripts morts | ~1 730 | dont 3 probes cartographiant l'API de Metabase v62 alors que l'instance est en 63.13, donc **information périmée = source d'erreur active** |
| 40 scripts de campagnes closes | 6 660 | **déplacés** vers `scripts/_archive/`, pas supprimés |

Cible : bibliothèque ~2 100 LOC (−39 %), `scripts/` visibles ~60 fichiers (−49 %).

## 6. Corrections de sécurité et de logique

| Fichier | Défaut | Correction |
|---|---|---|
| `main_methods.py:98` | imprime le jeton de session à chaque auth ; 6 `redirect_stdout` dans le dépôt n'existent que pour le masquer | supprimer l'impression, les 6 contournements deviennent morts |
| `modify_methods.py:6` | `authorized_group_ids=[]` en défaut mutable = « personne » : un appel sans argument verrouille une collection | défaut `None` + refus explicite |
| `modify_methods.py:111` | le garde-fou « filtre introuvable » est branché sur `verbose`, donc en mode par défaut le PUT part quand même | lever indépendamment de `verbose` |
| `.claude/settings.local.json` | pré-autorise `generate_fallback.py:*` et `migrate_dashboard_reuse.py:*` avec n'importe quel argument, `--yes --accept-diffs` inclus, sur des scripts qui archivent en prod | retirer les `:*`, supprimer 3 chemins morts |
| `tests/test_consultant_normalization_artifact.py` | asserte des compteurs gelés sur des JSON alors versionnés depuis la vague 1 | rendre tolérant à l'ajout de réponses |

## 7. Ce qui reste maison, faute d'équivalent natif

1. Le différentiel avant/après (`diff.py`) — voir §3.5.
2. Les empreintes de requête et la détection de doublons — le modèle natif `Content` n'expose
   aucun `dataset_query`.
3. Les 6 détecteurs de collections — `:collection` est absent de l'enum natif, `/api/ee/stale`
   ne rend que `card` et `dashboard`.
4. Les garde-fous d'archivage — mesure décisive : **353 des 420 cartes « stale » natives sont
   posées sur au moins un dashboard**. Le cleanup natif ne regarde que l'activité de consultation.
5. L'archivage en masse children-first — aucune route de bulk-archive dans les 534 chemins de
   l'openapi.
6. Le graphe de permissions — `mb` n'a aucun groupe `user`, `permission`, `group`, `api-key`.
7. Toute la logique métier des campagnes : mapping Airtable/Supabase des slots de conversion,
   filtre clients actifs, trackers de reprise. `mb` est strictement objet-par-objet, aucun verbe
   n'accepte une liste d'ids.

## 8. Ordre d'exécution

```
V1  commiter les 46 fichiers non suivis        FAIT  (2 commits, survie)
V2  supprimer le code mort                     risque nul
V3  bâtir le noyau + shim de compatibilité     498 tests verts à chaque étape
V4  brancher deps.py sur le natif              corrige le validateur cassé
V5  CLAUDE.md + durcir l'allowlist
V6  archiver les campagnes closes              en dernier, imports vérifiés un par un
```

Règle : aucune vague ne démarre sans `pytest -q` vert.

## 9. Campagnes actives, intouchables

Ne rien supprimer ni déplacer sans accord explicite.

| Campagne | Preuve datée |
|---|---|
| Migration conversions | 226 résiduels au 2026-07-16 ; `migration/promotion-snapshot-20260717T133433Z.json` |
| Erreurs août 2026 | `migration/errors-2026-08-13/union-arity-fix-20260814-163932.json`, écriture prod du 14/08 |
| Descriptions top100 | volet `is_core` Supabase encore ouvert |
| Ménage collection 14115 | 64 cartes blanches restantes sur 51 dashboards |

Dépendance externe cachée à corriger : `scripts/apply_top100_descriptions.py:39` pointe en dur
vers `~/Dev/Pro/nanga-front/docs/...`, invisible pour un agent qui ne lit que ce dépôt.

## 10. Hors périmètre

- **Remote sync** : licencié mais son mode read-only tuerait les campagnes. Après.
- **`/unreferenced` natif** : attendre `backfill-status: complete = true`.
- **CLI `mb` comme backend** : 0.3.0, un process node par appel, aucun verbe multi-ids, exige
  des ids numériques donc ne remplace pas notre résolution nom→id. Adoption ciblée seulement.
- **Publication PyPI** : arrêtée (4 téléchargements/semaine, aucun consommateur externe, et le
  bloc qui justifiait la vitrine est supprimé).
