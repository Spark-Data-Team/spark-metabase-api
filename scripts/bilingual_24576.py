#!/usr/bin/env python3
"""Rend bilingue (FR + EN) les cartes texte/heading d'un onglet du dashboard 24576.

Piloté par une table CONTENT : {dashcard_id: {"text": <nouveau md>, "h": <hauteur>}}.
Après modification des hauteurs, REFLOW automatique : décale le `row` des cartes
situées sous une carte agrandie, sur le même onglet, du delta de hauteur.

Headings : bilingue inline « FR · EN » (pas de changement de hauteur).
Body : bloc FR puis `---` puis bloc EN (hauteur augmentée).

Réversible (snapshot). Usage :
  python3 scripts/bilingual_24576.py --tab accueil            # dry-run (montre reflow)
  python3 scripts/bilingual_24576.py --tab accueil --yes      # applique + snapshot
"""
import argparse, json, sys, copy, requests
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

MIG = REPO / "migration"
DASH = 24576
TABS = {"accueil": 8020, "global": 7657, "seo": 7659, "sea": 7990}

SEP = "\n\n---\n\n"

CONTENT = {
    # ---------- ACCUEIL (tab 8020) ----------
    127507: {"text": "🏠 Accueil · Home", "h": 1},
    127474: {"text": "💡 Lexique · Glossary", "h": 1},
    127506: {"h": 7, "text": (
        "- L'onglet **Global** permet de visualiser une vue d'ensemble de toutes les sources d'acquisition digitale de votre centre et leur impact sur les réservations.\n\n"
        "- L'onglet **SEA / SMA** permet de suivre votre acquisition payante (Google Ads, Meta, TikTok). Si vous n'avez pas d'acquisition payante, il est normal de voir les métriques à 0.\n\n"
        "- L'onglet **SEO** permet de comprendre comment votre centre est trouvé sur Google de manière naturelle, et si ce trafic génère des réservations."
        + SEP +
        "- The **Global** tab gives an overview of all your center's digital acquisition sources and their impact on bookings.\n\n"
        "- The **SEA / SMA** tab tracks your paid acquisition (Google Ads, Meta, TikTok). If you don't run paid acquisition, it's normal to see the metrics at 0.\n\n"
        "- The **SEO** tab explains how your center is found on Google organically, and whether that traffic generates bookings."
    )},
    127473: {"h": 31, "text": (
        "**Canaux d'acquisition**\n\n"
        "- **SEO** : recherche Google naturelle.\n\n"
        "- **SEA** : publicités Google Ads.\n\n"
        "- **SMA** : publicités sur les réseaux sociaux (Meta, TikTok…).\n\n\n"
        "**Plateformes**\n\n"
        "- **Meta** : Regroupe les publicités diffusées sur **Facebook**, **Instagram**, **Messenger** et le **Réseau d'audience Meta** (sites et applications partenaires).\n\n"
        "- **Google** : Regroupe les publicités diffusées sur le **moteur de recherche Google**, **YouTube**, **Gmail**, **Google Maps** et le **Réseau Display Google** (bannières sur des millions de sites et applications partenaires).\n\n"
        "> [Vidéo explicative : différences entre Meta et Google](https://www.youtube.com/watch?v=Cp5nkhRyhe4) (jusqu'à la moitié)\n\n\n"
        "**Métriques**\n\n"
        "- **Coûts** : Budget dépensé sur la campagne et les actions marketing Google, YouTube, Instagram, Facebook (hors frais de gestion).\n\n"
        "- **Impressions** : Nombre de fois qu'une publicité est affichée sur l'écran d'un utilisateur. Une même personne peut générer plusieurs impressions si elle voit la publicité plusieurs fois.\n\n"
        "- **Clics** : Nombre de fois qu'un utilisateur clique sur une publicité ou un lien pour accéder à votre site. Un même utilisateur peut générer plusieurs clics.\n\n"
        "- **Visites** : Nombre total de sessions ouvertes sur votre site, toutes sources confondues (SEO, SEA, SMA, accès direct, etc.). Une session correspond à une période d'activité continue d'un utilisateur sur le site.\n\n"
        "- **Nouveaux visiteurs** : Personnes qui découvrent votre centre pour la première fois.\n\n"
        "- **Conversion** : Une action concrète réalisée par un visiteur (réservation, formulaire, appel).\n\n"
        "- **Taux de conversion** : Pourcentage de visites ayant abouti à une action concrète (réservation, formulaire, appel). Calculé en divisant le nombre de conversions par le nombre total de visites.\n\n"
        "- **Réservations** : Nombre de réservations confirmées en ligne.\n\n"
        "- **Contacts** : Nombre de personnes ayant affiché vos coordonnées ou envoyé un formulaire de contact."
        + SEP +
        "**Acquisition channels**\n\n"
        "- **SEO**: organic Google search.\n\n"
        "- **SEA**: Google Ads paid advertising.\n\n"
        "- **SMA**: paid advertising on social networks (Meta, TikTok…).\n\n\n"
        "**Platforms**\n\n"
        "- **Meta**: Covers ads shown on **Facebook**, **Instagram**, **Messenger** and the **Meta Audience Network** (partner sites and apps).\n\n"
        "- **Google**: Covers ads shown on **Google Search**, **YouTube**, **Gmail**, **Google Maps** and the **Google Display Network** (banners across millions of partner sites and apps).\n\n"
        "> [Explainer video: differences between Meta and Google](https://www.youtube.com/watch?v=Cp5nkhRyhe4) (up to the halfway point)\n\n\n"
        "**Metrics**\n\n"
        "- **Costs**: Budget spent on the campaign and on Google, YouTube, Instagram and Facebook marketing actions (excluding management fees).\n\n"
        "- **Impressions**: Number of times an ad is displayed on a user's screen. The same person can generate several impressions if they see the ad multiple times.\n\n"
        "- **Clicks**: Number of times a user clicks on an ad or a link to reach your site. The same user can generate several clicks.\n\n"
        "- **Visits**: Total number of sessions opened on your site, all sources combined (SEO, SEA, SMA, direct access, etc.). A session is a period of continuous activity by a user on the site.\n\n"
        "- **New visitors**: People discovering your center for the first time.\n\n"
        "- **Conversion**: A concrete action taken by a visitor (booking, form, call).\n\n"
        "- **Conversion rate**: Percentage of visits that led to a concrete action (booking, form, call). Calculated by dividing the number of conversions by the total number of visits.\n\n"
        "- **Bookings**: Number of bookings confirmed online.\n\n"
        "- **Contacts**: Number of people who viewed your contact details or submitted a contact form."
    )},
}


def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", required=True, choices=list(TABS))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    tab_id = TABS[args.tab]

    mb = connect()
    d = mb.get(f"/api/dashboard/{DASH}")
    dcs = copy.deepcopy(d.get("dashcards") or [])
    by_id = {dc["id"]: dc for dc in dcs}

    # cibles présentes sur cet onglet
    targets = {cid: c for cid, c in CONTENT.items() if cid in by_id and by_id[cid].get("dashboard_tab_id") == tab_id}
    if not targets:
        sys.exit(f"Aucune cible CONTENT sur l'onglet {args.tab} ({tab_id}).")

    # 1) calcul des deltas de hauteur (boundary = bas de la carte, en coords d'origine)
    orig_row = {dc["id"]: dc.get("row") for dc in dcs}
    deltas = []  # (boundary_row, delta)
    for cid, spec in targets.items():
        dc = by_id[cid]
        old_h = dc.get("size_y")
        if spec["h"] != old_h:
            deltas.append((dc.get("row") + old_h - 1, spec["h"] - old_h))

    # 2) appliquer texte + hauteur
    for cid, spec in targets.items():
        dc = by_id[cid]
        dc["visualization_settings"]["text"] = spec["text"]
        dc["size_y"] = spec["h"]

    # 3) reflow : pour chaque carte de l'onglet, somme des deltas dont la boundary
    #    est < à sa row d'origine (donc située au-dessus). Calcul sur coords figées.
    for dc in dcs:
        if dc.get("dashboard_tab_id") != tab_id:
            continue
        shift = sum(delta for b, delta in deltas if b < orig_row[dc["id"]])
        dc["row"] += shift

    print(f"Onglet {args.tab}: {len(targets)} carte(s) bilingue(s), deltas={deltas}")
    for cid in targets:
        dc = by_id[cid]
        print(f"  id={cid} row={dc['row']} h={dc['size_y']} | {dc['visualization_settings']['text'][:45]!r}")

    if not args.yes:
        print("\n(DRY-RUN — aucune modification.)")
        return

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    MIG.mkdir(exist_ok=True)
    (MIG / f"bilingual-snapshot-{DASH}-{args.tab}-{ts}.json").write_text(
        json.dumps({"dashboard": DASH, "dashcards": d.get("dashcards")}, ensure_ascii=False, indent=2))
    payload = {"dashcards": dcs}
    if d.get("tabs"):
        payload["tabs"] = d["tabs"]
    r = requests.put(mb.domain + f"/api/dashboard/{DASH}", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
    print(f"PUT: {r.status_code}")
    r.raise_for_status()


if __name__ == "__main__":
    main()
