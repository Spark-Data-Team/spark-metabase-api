"""Point d'entrée unique : `connect()`.

Il remplace les trois idiomes concurrents qui coexistaient dans scripts/ :
58 `def connect()` recopiés à la main, 56 imports de `_load_env` depuis
`scripts/reorg_phase1.py` (le CLI d'une campagne TERMINÉE), et 16 imports de
`connect_resilient` depuis `scripts/archive_collections.py`.

Un agent qui arrive dans le dépôt n'a plus qu'une seule bonne réponse à la
question « comment je me connecte ».
"""

import os
import pathlib
from typing import Optional

_FICHIER_ENV = ".env"


def load_env(racine: Optional[str] = None) -> dict:
    """Lit le .env du dépôt sans écraser les variables déjà présentes.

    Pas de dépendance à python-dotenv : le format utilisé ici est trivial et
    l'absence de la lib a déjà fait échouer des scripts.
    """
    depart = pathlib.Path(racine) if racine else pathlib.Path(__file__).resolve().parent.parent
    chemin = depart / _FICHIER_ENV
    valeurs = {}
    if not chemin.exists():
        return valeurs
    for ligne in chemin.read_text().splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        cle, valeur = cle.strip(), valeur.strip().strip('"').strip("'")
        valeurs[cle] = valeur
        os.environ.setdefault(cle, valeur)
    return valeurs


def connect(domain: Optional[str] = None, session_id: Optional[str] = None,
            email: Optional[str] = None, password: Optional[str] = None):
    """Renvoie un Metabase_API prêt à l'emploi.

    Sans argument, lit .env : METABASE_DOMAIN, puis METABASE_SESSION_ID s'il
    existe, sinon METABASE_EMAIL + METABASE_PASSWORD.
    """
    from .main_methods import Metabase_API

    load_env()
    domain = domain or os.environ.get("METABASE_DOMAIN")
    if not domain:
        raise ValueError(
            "METABASE_DOMAIN introuvable. Renseigner le .env à la racine du dépôt "
            "ou passer domain= explicitement.")

    session_id = session_id or os.environ.get("METABASE_SESSION_ID")
    if session_id:
        try:
            return Metabase_API(domain=domain, session_id=session_id)
        except Exception:
            # Jeton périmé : on retombe sur email/mot de passe plutôt que de
            # laisser un script mourir au milieu d'un lot.
            pass

    email = email or os.environ.get("METABASE_EMAIL")
    password = password or os.environ.get("METABASE_PASSWORD")
    if not (email and password):
        raise ValueError(
            "Ni METABASE_SESSION_ID valide, ni METABASE_EMAIL + METABASE_PASSWORD.")
    return Metabase_API(domain=domain, email=email, password=password)


__all__ = ["connect", "load_env"]
