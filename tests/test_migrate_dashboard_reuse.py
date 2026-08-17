#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_dashboard_reuse as reuse


def test_copy_dashcard_payload_preserves_deep_copy_card_ids_and_is_independent():
    copy_dashcard = {
        "id": 900,
        "card_id": 800,
        "row": 1,
        "col": 2,
        "size_x": 12,
        "size_y": 4,
        "series": [{"id": 801}],
        "parameter_mappings": [{"card_id": 800}],
        "visualization_settings": {"card.title": "Copied question"},
        "dashboard_tab_id": 700,
        "entity_id": "must-not-be-sent",
    }

    payload = reuse.copy_dashcard_payload(copy_dashcard)

    assert payload["card_id"] == 800
    assert payload["series"] == [{"id": 801}]
    assert payload["parameter_mappings"] == [{"card_id": 800}]
    assert payload["dashboard_tab_id"] == 700
    assert "entity_id" not in payload
    assert "id" not in payload
    payload["series"][0]["id"] = 999
    assert copy_dashcard["series"][0]["id"] == 801


def test_reuse_uses_transactional_dashboard_writer():
    # Le contrat de sécurité est partagé avec le fallback : snapshot complet, relecture
    # stricte et rollback best-effort au moindre doute.
    assert reuse.put_dashboard_verified.__module__ == "generate_fallback"
