#!/usr/bin/env python3
"""Traduit en anglais le clone EN du dashboard Franchisés Quiz Room.

- Cartes texte/heading : ciblées par (onglet, row) -> texte EN.
- Titres KPI existants (card.title) : map FR -> EN.
- Graphes sans override affichant un nom technique : AJOUT d'un card.title EN (par card_id).
- Onglet 'Accueil' -> 'Home'.
NE renomme JAMAIS les cartes partagées (override par dashcard uniquement).

Usage:
  python3 scripts/translate_en_24576.py --dashboard 25467            # dry-run
  python3 scripts/translate_en_24576.py --dashboard 25467 --yes      # applique + snapshot
"""
import argparse, json, sys, copy, requests
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
MIG = REPO / "migration"

# --- textes par (onglet, row) ---
POS_TEXT = {
    ("Accueil", 0): "🏠 Home",
    ("Accueil", 4): "💡 Glossary",
    ("Accueil", 1): (
        "- The **Global** tab gives an overview of all your center's digital acquisition sources and their impact on bookings.\n\n"
        "- The **SEA / SMA** tab tracks your paid acquisition (Google Ads, Meta, TikTok). If you don't run paid acquisition, it's normal to see the metrics at 0.\n\n"
        "- The **SEO** tab explains how your center is found on Google organically, and whether that traffic generates bookings."
    ),
    ("Accueil", 5): (
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
    ),
    ("Global", 0): "1. How many users land on my pages?",
    ("Global", 1): (
        "Total number of visits, all sources combined: Google search, ads, social networks, direct access.\n\n"
        "Visits that are neither SEO, SEA nor SMA come from direct access, referrals and other sources."
    ),
    ("Global", 15): "2. How many bookings are generated?",
    ("Global", 16): (
        "The player count is your center's actual footfall, all sources combined.\n\n"
        "Conversions count concrete actions on the site (bookings, forms, calls)."
    ),
    ("Global", 30): "3. Budget usage",
    ("Global", 31): (
        "The amount invested in advertising (Google Ads and social networks) this month; this budget only covers ad spend.\n\n"
        "SEO does not generate any direct media cost — it's \"free\" traffic earned through content and organic search work."
    ),
    ("SEA / SMA", 0): "Advertising",
    ("SEA / SMA", 7): "History",
    ("SEO", 0): "1. Is my site attracting visitors?",
    ("SEO", 1): "How many people find your center via Google (organic search, excluding ads).",
    ("SEO", 23): "2. Is this traffic converting?",
    ("SEO", 24): (
        "Your site's traffic segmented by page type: what brings visitors to each page family, and which content drives the most engagement.\n"
        "Clicks are the number of times a user clicks an organic link from Google to reach your site. The same user can generate several clicks.\n"
        "Visits are the total number of sessions opened on your site, all sources combined (SEO, SEA, SMA, direct access, etc.). A session is a period of continuous activity on the site.\n\n"
        "Pages are grouped into 4 families:\n\n"
        "- **Home page**: the site's main homepage\n"
        "- **City home**: main pages by location\n"
        "- **Landing pages**: dedicated pages (birthdays, team building, etc.)\n"
        "- **Blog**: editorial articles"
    ),
    ("SEO", 43): (
        "⚠️  You may see small differences between certain totals (sessions, new users) across the dashboard's questions. "
        "This is normal: each view is built from a report generated from a different angle, so sessions aren't always counted in exactly the same way — "
        "but the orders of magnitude remain reliable."
    ),
    ("SEO", 46): "3. Which pages perform best?",
    ("SEO", 47): (
        "The tables below rank your pages by volume of visits on Google.\n"
        "The Google position shows your rank in search results (the lower the number, the better). The conversion rate is the percentage of people who click your link when it appears in the results.\n\n"
        "Reading tip: a well-ranked page (position < 10) with a low conversion rate may benefit from improving its title and description on Google. A page with many visits but few conversions may need a stronger call to action on the page."
    ),
}

# --- titres KPI existants : FR -> EN ---
TITLE_MAP = {
    "Budget SEA (Google Ads)": "SEA Budget (Google Ads)",
    "Budget SMA (Meta)": "SMA Budget (Meta)",
    "Budget total media": "Total media budget",
    "Clics": "Clicks",
    "Contacts": "Contacts",
    "Conversions SEA": "SEA Conversions",
    "Conversions SEO": "SEO Conversions",
    "Conversions SMA": "SMA Conversions",
    "Impressions": "Impressions",
    "Nombre de Joueurs": "Player count",
    "Nouveaux utilisateurs SEO": "New SEO users",
    "Réservations": "Bookings",
    "Synthèse des performances": "Performance summary",
    "Taux de conversions SEO": "SEO conversion rate",
    "Visites": "Visits",
    "Visites SEA": "SEA Visits",
    "Visites SEO": "SEO Visits",
    "Visites SMA": "SMA Visits",
    "Visites par type de page": "Visits by page type",
}

# --- graphes sans override : card_id -> titre EN à AJOUTER ---
ADD_TITLE = {
    47181: "Visits by source",
    46950: "Traffic trend by source — last 13 months",
    46989: "Conversions by channel — last 3 months (N vs N-1)",
    46988: "Player count — last 3 months (N vs N-1)",
    47018: "Media budget — 12-month trend",
    60: "Media budget by channel",
    41662: "Cost, contacts & bookings by date",
    41661: "Impressions by date",
    47049: "Sessions — last 3 months",
    47082: "Traffic breakdown (GSC)",
    47083: "Clicks by traffic (GSC)",
    47084: "Clicks by traffic (GSC) — N vs N-1",
    47676: "Sessions by page type (GA4)",
    47808: "Sessions by page type (GA4) — year N vs N-1",
    48303: "Performance by page (GSC & GA4)",
}

TAB_RENAME = {"Accueil": "Home"}


def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    d = mb.get(f"/api/dashboard/{args.dashboard}")
    dcs = copy.deepcopy(d.get("dashcards") or [])
    tabs = copy.deepcopy(d.get("tabs") or [])
    tabname = {t["id"]: t["name"] for t in tabs}

    n_text = n_title = n_add = 0
    miss_text = []
    for dc in dcs:
        vs = dc.get("visualization_settings") or {}
        tab = tabname.get(dc.get("dashboard_tab_id"))
        vc = vs.get("virtual_card") or {}
        # text/heading by (tab,row)
        if vc.get("display") in ("text", "heading") and (vs.get("text") or "").strip():
            key = (tab, dc.get("row"))
            if key in POS_TEXT:
                vs["text"] = POS_TEXT[key]; n_text += 1
            else:
                miss_text.append((tab, dc.get("row"), (vs.get("text") or "")[:40]))
        # existing KPI title override
        if vs.get("card.title") in TITLE_MAP:
            vs["card.title"] = TITLE_MAP[vs["card.title"]]; n_title += 1
        # add EN title to no-override charts
        elif not vs.get("card.title") and dc.get("card_id") in ADD_TITLE:
            vs["card.title"] = ADD_TITLE[dc["card_id"]]; n_add += 1
        dc["visualization_settings"] = vs

    for t in tabs:
        if t["name"] in TAB_RENAME:
            t["name"] = TAB_RENAME[t["name"]]

    print(f"text/heading traduits: {n_text} | titres KPI traduits: {n_title} | titres ajoutés: {n_add}")
    if miss_text:
        print("NON-traduits (texte hors FAQ non mappé):")
        for m in miss_text:
            if m[0] and "FAQ" not in (m[0] or ""):
                print("  ", m)

    if not args.yes:
        print("\n(DRY-RUN — aucune modification.)")
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    MIG.mkdir(exist_ok=True)
    (MIG / f"translate-en-snapshot-{args.dashboard}-{ts}.json").write_text(
        json.dumps({"dashboard": args.dashboard, "dashcards": d.get("dashcards"), "tabs": d.get("tabs")}, ensure_ascii=False, indent=2))
    r = requests.put(mb.domain + f"/api/dashboard/{args.dashboard}", headers=mb.header, auth=mb.auth,
                     json={"dashcards": dcs, "tabs": tabs}, timeout=120)
    print("PUT:", r.status_code); r.raise_for_status()


if __name__ == "__main__":
    main()
