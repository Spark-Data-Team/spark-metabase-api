"""Outil interne Spark pour manipuler Metabase.

Chemin normal :

    from spark_metabase_api import connect, cards, dashboards, diff
    mb = connect()                               # point d'entrée UNIQUE
    carte = cards.get_card(mb, 32496)            # forme legacy garantie
    cards.put_card(mb, 32496, {...})             # écrit, relit, vérifie
    dashboards.put_dashboard(mb, 11917, {...})   # réinjecte tabs + parameters

Les écritures lèvent en cas d'échec. Ne jamais tester `if mb.put(...)` :
l'ancienne façade rend un status_code, donc 500 est truthy.
"""

from . import cards, dashboards, deps, diff, http
from .http import MetabaseError
from .main_methods import Metabase_API
from .session import connect, load_env

__all__ = [
    "connect",
    "load_env",
    "Metabase_API",
    "MetabaseError",
    "cards",
    "dashboards",
    "deps",
    "diff",
    "http",
]
