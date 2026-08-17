"""Classement des descriptions live avant écriture (garde anti-écrasement)."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from apply_top100_descriptions import classify  # noqa: E402

PROPOSED = "Total blended media spend across all connected ad platforms."


def test_description_vide():
    assert classify("", PROPOSED) == "vide"
    assert classify(None, PROPOSED) == "vide"
    assert classify("   ", PROPOSED) == "vide"


def test_marqueur_manual_verification():
    assert classify("manual_verification", PROPOSED) == "manual_verification"


def test_dump_auto_une_ligne():
    assert classify("KPIs: cost          Display: smartscalar", PROPOSED) == "auto"


def test_dump_auto_deux_lignes_kpis_majuscules():
    """Format des cartes 165/162/716/717 : saut de ligne + KPIS en capitales."""
    assert classify("Breakdown by campaign_category\n\nKPIS: revenue", PROPOSED) == "auto"


def test_dump_auto_breakdown_multi_dimensions():
    assert classify("Breakdown by date, campaign_channel\n\nKPIS: revenue", PROPOSED) == "auto"


def test_description_deja_posee_par_nous():
    assert classify(PROPOSED, PROPOSED) == "identique"
    assert classify(f"  {PROPOSED}  ", PROPOSED) == "identique"


def test_description_humaine_preservee():
    assert classify("Coût média total, hors frais d'agence.", PROPOSED) == "humaine"


def test_description_humaine_mentionnant_kpis_plus_loin():
    """« KPIs » au milieu d'une phrase ne doit pas passer pour un dump auto."""
    assert classify("Ce tableau reprend les KPIs: coût et clics.", PROPOSED) == "humaine"
