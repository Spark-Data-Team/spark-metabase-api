"""Écritures de masse : snapshot, échantillon, lot, rollback.

Le mode d'échec visé : un lot qui casse au milieu et laisse la production dans
un état incohérent, sans moyen de revenir en arrière.

La règle imposée ici est celle qu'on appliquait à la main : sauvegarder l'état
complet AVANT de toucher quoi que ce soit, valider sur un échantillon, puis
seulement lancer le reste. Le rollback n'existe que s'il a été écrit avant.

    from spark_metabase_api import connect, cards, guard

    mb = connect()
    rapport = guard.batch(
        mb, [32496, 32497, 32498],
        muter=lambda mb, cid: cards.put_card(mb, cid, {"description": "..."}),
        mesurer=cards.card_values,      # optionnel : active le différentiel
        mode="identical",               # les nombres ne doivent pas bouger
        dry_run=True,                   # défaut : on ne touche à rien
    )
    print(rapport.render())
"""

import datetime
import json
import pathlib
from typing import Any, Callable, List, Optional

from . import cards as _cards
from . import dashboards as _dashboards
from . import http
from .diff import Finding, Report, check_values

# Résolu contre la racine du paquet, pas contre le cwd : un script lancé depuis
# scripts/ écrivait sinon ses snapshots dans scripts/migration/, c'est-à-dire
# ailleurs que là où l'opérateur va les chercher.
_RACINE = pathlib.Path(__file__).resolve().parent.parent
_DOSSIER_DEFAUT = str(_RACINE / "migration")

_KINDS = ("card", "dashboard", "collection")


def _horodatage() -> str:
    # Microsecondes, pas secondes : deux snapshots lancés dans la même seconde
    # sont un usage légitime, ils ne doivent pas se marcher dessus.
    return datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")


def snapshot(client, kind: str, ids: List[int], dossier: str = _DOSSIER_DEFAUT,
             etiquette: str = "snapshot") -> str:
    """Sauvegarde l'état complet des objets sur disque. Renvoie le chemin.

    À appeler AVANT toute mutation. Sans ça, il n'y a pas de rollback possible.

    Le nom porte un horodatage et n'écrase JAMAIS un fichier existant : sans ça,
    relancer un lot après un échec réécrivait le snapshot d'avant-mutation avec
    l'état DÉJÀ muté, et le rollback restaurait les dégâts.
    """
    if kind not in _KINDS:
        raise ValueError("kind doit être card, dashboard ou collection")
    etat = {}
    for i in ids:
        suffixe = "?legacy-mbql=true" if kind == "card" else ""
        etat[str(i)] = http.get(client, "/api/{}/{}{}".format(kind, i, suffixe))

    chemin = pathlib.Path(dossier)
    chemin.mkdir(parents=True, exist_ok=True)
    fichier = chemin / "{}-{}-{}-{}.json".format(etiquette, kind, len(ids), _horodatage())
    if fichier.exists():
        raise FileExistsError(
            "{} existe déjà. Refus d'écraser un snapshot : il contient peut-être "
            "le seul état d'avant mutation.".format(fichier))
    fichier.write_text(json.dumps(
        {"kind": kind, "ids": list(ids), "etat": etat}, ensure_ascii=False, indent=1))
    return str(fichier)


def restore(client, chemin: str, ids: Optional[List[int]] = None) -> List[int]:
    """Réécrit les objets tels qu'ils étaient dans le snapshot.

    `ids=None` restaure tout ; `ids=[]` ne restaure rien. La distinction compte :
    l'appel naturel après un lot est `restore(mb, chemin, ids=[...les échoués])`,
    et une liste vide doit vouloir dire « rien », pas « tout ».

    Chaque restauration passe par put_card / put_dashboard, donc relit et vérifie.
    Lève à la première écriture qui n'atterrit pas, pour ne pas empiler les dégâts.
    """
    contenu = json.loads(pathlib.Path(chemin).read_text())
    kind, etat = contenu["kind"], contenu["etat"]

    cibles = list(etat) if ids is None else [str(i) for i in ids]
    faits = []
    for i in cibles:
        objet = etat.get(i)
        if objet is None:
            raise ValueError("id {} absent du snapshot {}".format(i, chemin))
        if kind == "card":
            _cards.put_card(client, int(i), objet)
        elif kind == "dashboard":
            _dashboards.put_dashboard(client, int(i), objet)
        else:
            http.put(client, "/api/collection/{}".format(i), json=objet)
        faits.append(int(i))
    return faits


def batch(client, ids: List[int],
          muter: Callable[[Any, int], Any],
          mesurer: Optional[Callable[[Any, int], List[Any]]] = None,
          mode: str = "monitor",
          dry_run: bool = True,
          echantillon: int = 3,
          kind: str = "card",
          dossier: str = _DOSSIER_DEFAUT,
          tolerance: float = 0.0) -> Report:
    """Applique `muter` à chaque id, échantillon d'abord.

    dry_run=True (défaut) ne fait que le snapshot et rend le plan.
    Si `mesurer` est fourni, chaque objet est mesuré avant et après, et le
    différentiel est comparé selon `mode`. En mode "identical", un écart
    ARRÊTE le lot : les objets restants ne sont pas touchés.
    """
    rapport = Report()
    if not ids:
        rapport.add(Finding("batch", "plan", "ok", "aucun id, rien à faire"))
        return rapport

    chemin = snapshot(client, kind, ids, dossier=dossier)
    rapport.add(Finding("batch", "snapshot", "ok",
                        "{} objets sauvegardés dans {}".format(len(ids), chemin)))

    if dry_run:
        rapport.add(Finding("batch", "plan", "ok",
            "dry-run : {} objets seraient modifiés. Relancer avec dry_run=False.".format(len(ids))))
        return rapport

    tete, reste = ids[:echantillon], ids[echantillon:]

    faits = _appliquer(client, tete, muter, mesurer, mode, tolerance, rapport, "échantillon")
    if faits is not True:
        _signaler_arret(rapport, "échantillon", faits, tete, reste, chemin)
        return rapport

    if reste:
        faits = _appliquer(client, reste, muter, mesurer, mode, tolerance, rapport, "lot")
        if faits is not True:
            _signaler_arret(rapport, "lot", faits, reste, [], chemin, deja=len(tete))
            return rapport

    rapport.add(Finding("batch", "rollback", "ok",
                        "{} objets modifiés. Snapshot conservé : {}".format(len(ids), chemin)))
    return rapport


def _signaler_arret(rapport, phase, index_echec, groupe, suivants, chemin, deja=0):
    """Un arrêt doit toujours dire combien d'objets restent intacts et comment revenir."""
    modifies = deja + index_echec
    intacts = len(groupe) - index_echec + len(suivants)
    rapport.add(Finding("batch", "arret", "error",
        "{} en échec. {} objet(s) modifié(s), {} NON touché(s). "
        "Rollback : guard.restore(mb, {!r})".format(phase, modifies, intacts, chemin)))


def _appliquer(client, ids, muter, mesurer, mode, tolerance, rapport, phase):
    """Renvoie True si tout est passé, sinon l'index du premier échec."""
    for rang, i in enumerate(ids):
        cible = "{}#{}".format(phase, i)
        avant = mesurer(client, i) if mesurer else None
        try:
            muter(client, i)
        except Exception as e:
            rapport.add(Finding(cible, "mutation", "error", "{}: {}".format(type(e).__name__, e)))
            return rang
        if mesurer is None:
            rapport.add(Finding(cible, "mutation", "ok", "modifié"))
            continue
        apres = mesurer(client, i)
        ecarts = check_values(cible, avant, apres, mode=mode, tolerance=tolerance)
        for f in ecarts:
            rapport.add(f)
        if any(f.level == "error" for f in ecarts):
            return rang + 1  # la mutation a bien eu lieu, c'est le contrôle qui échoue
    return True


__all__ = ["snapshot", "restore", "batch"]
