#!/usr/bin/env python3
"""Emplacement des REGISTRES d'écriture de la migration conversions.

En série (défaut) : migration/ (les fichiers maîtres).
En PARALLÈLE : chaque subagent (1 client) exporte `CONV_REG_DIR=migration/parallel/<client>`
avant de lancer la chaîne → toutes ses écritures de registre (generated-cards, tu-generic,
tracker) vont dans SON dossier, jamais dans les maîtres. L'agent central merge ensuite les
shards dans migration/ (additif). => zéro écrasement, registres maîtres pilotés par le central.

Les ENTRÉES (conv-client-mapping.json, conv-targets.json, tu-generic-87/4854.json…) restent
lues dans migration/ : seules les ÉCRITURES sont redirigées.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MASTER = REPO / "migration"


def reg_dir():
    """Dossier des registres d'écriture (créé si absent)."""
    d = Path(os.environ["CONV_REG_DIR"]) if os.environ.get("CONV_REG_DIR") else MASTER
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_isolated():
    """True si on tourne dans un shard par-client (mode parallèle)."""
    return bool(os.environ.get("CONV_REG_DIR"))
