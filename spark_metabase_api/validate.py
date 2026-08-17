"""Shim de compatibilité : `validate` est devenu `diff`.

Les trois scripts de campagne active qui font `from spark_metabase_api import
validate as V` puis `V.check_values(...)` continuent de fonctionner sans
modification. Ils seront migrés vers `spark_metabase_api.diff` par lots.

Ce qui a disparu et pourquoi :
  check_structure    lisait dataset_query["type"] sans ?legacy-mbql=true, donc
                     recevait None et concluait "unknown query type" sur TOUTES
                     les cartes de la prod depuis le passage à MBQL5
  check_refs         remplacé par le graphe de dépendances natif (deps.py), qui
                     résout aussi les tables d'une carte SQL native là où notre
                     regex card__(\\d+) ne voyait rien
  gate,
  guarded_apply      reconstruits dans guard.py sur les briques correctes
  units_from_spec,
  unit_from_payload,
  unit_from_card_id,
  resolve_cli_target couplés au bloc IaC supprimé
"""

import warnings

from .diff import (  # noqa: F401
    Finding,
    Report,
    ValidationError,
    _signature,
    check_differential,
    check_values,
)

warnings.warn(
    "spark_metabase_api.validate est déprécié, utiliser spark_metabase_api.diff",
    DeprecationWarning,
    stacklevel=2,
)
