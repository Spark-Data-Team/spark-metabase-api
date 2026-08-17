"""Écritures de masse : snapshot, échantillon, lot, rollback.

Le mode d'échec visé : un lot qui casse au milieu et laisse la production dans
un état incohérent, sans moyen de revenir en arrière.

La règle imposée ici est celle qu'on appliquait à la main : sauvegarder l'état
complet AVANT de toucher quoi que ce soit, valider sur un échantillon, puis
seulement lancer le reste. Le rollback n'existe que s'il a été écrit avant.

    from spark_metabase_api import connect, guard

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

import json
import pathlib
from typing import Any, Callable, Dict, List, Optional

from . import http
from .diff import Finding, Report, check_values

_DOSSIER_DEFAUT = "migration"


def snapshot(client, kind: str, ids: List[int], dossier: str = _DOSSIER_DEFAUT,
             etiquette: str = "snapshot") -> str:
    """Sauvegarde l'état complet des objets sur disque. Renvoie le chemin.

    À appeler AVANT toute mutation. Sans ça, il n'y a pas de rollback possible.
    """
    if kind not in ("card", "dashboard", "collection"):
        raise ValueError("kind doit être card, dashboard ou collection")
    etat = {}
    for i in ids:
        suffixe = "?legacy-mbql=true" if kind == "card" else ""
        etat[str(i)] = http.get(client, "/api/{}/{}{}".format(kind, i, suffixe))
    chemin = pathlib.Path(dossier)
    chemin.mkdir(parents=True, exist_ok=True)
    fichier = chemin / "{}-{}-{}.json".format(etiquette, kind, len(ids))
    fichier.write_text(json.dumps({"kind": kind, "etat": etat}, ensure_ascii=False, indent=1))
    return str(fichier)


def restore(client, chemin: str, ids: Optional[List[int]] = None) -> List[int]:
    """Réécrit les objets tels qu'ils étaient dans le snapshot.

    Renvoie la liste des ids restaurés. Lève à la première écriture qui échoue,
    pour ne pas empiler les dégâts."""
    contenu = json.loads(pathlib.Path(chemin).read_text())
    kind, etat = contenu["kind"], contenu["etat"]
    cibles = [str(i) for i in ids] if ids else list(etat)
    faits = []
    for i in cibles:
        objet = etat.get(i)
        if objet is None:
            raise ValueError("id {} absent du snapshot {}".format(i, chemin))
        http.put(client, "/api/{}/{}".format(kind, i), json=objet)
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
    différentiel est comparé selon `mode`. En mode "identical", un écart sur
    l'échantillon ARRÊTE le lot : les objets restants ne sont pas touchés.
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

    if not _appliquer(client, tete, muter, mesurer, mode, tolerance, rapport, "échantillon"):
        rapport.add(Finding("batch", "arret", "error",
            "échantillon en échec, les {} objets restants n'ont PAS été touchés. "
            "Rollback : guard.restore(mb, {!r})".format(len(reste), chemin)))
        return rapport

    if reste:
        _appliquer(client, reste, muter, mesurer, mode, tolerance, rapport, "lot")

    rapport.add(Finding("batch", "rollback", "ok", "snapshot conservé : {}".format(chemin)))
    return rapport


def _appliquer(client, ids, muter, mesurer, mode, tolerance, rapport, phase) -> bool:
    """Renvoie False dès qu'un objet est en erreur, sans continuer."""
    for i in ids:
        cible = "{}#{}".format(phase, i)
        avant = mesurer(client, i) if mesurer else None
        try:
            muter(client, i)
        except Exception as e:
            rapport.add(Finding(cible, "mutation", "error", "{}: {}".format(type(e).__name__, e)))
            return False
        if mesurer is None:
            rapport.add(Finding(cible, "mutation", "ok", "modifié"))
            continue
        apres = mesurer(client, i)
        ecarts = check_values(cible, avant, apres, mode=mode, tolerance=tolerance)
        for f in ecarts:
            rapport.add(f)
        if any(f.level == "error" for f in ecarts):
            return False
    return True


__all__ = ["snapshot", "restore", "batch"]
