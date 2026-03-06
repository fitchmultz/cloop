"""Static accessibility regression tests for the web UI.

Purpose:
    Guard high-value accessibility semantics in static HTML/CSS/JS assets.

Responsibilities:
    - Verify skip-link and status/live-region semantics.
    - Verify key inputs have labels.
    - Verify tab controls declare panel relationships.
    - Verify icon-only controls in render templates have aria labels.

Non-scope:
    - Full browser-based accessibility auditing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "cloop" / "static" / "index.html"
BASE_CSS = ROOT / "src" / "cloop" / "static" / "css" / "base.css"
RENDER_JS = ROOT / "src" / "cloop" / "static" / "js" / "render.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skip_link_exists_and_targets_main() -> None:
    html = _read(INDEX_HTML)
    assert 'class="skip-link" href="#inbox-main"' in html


def test_status_and_offline_banners_use_live_region_semantics() -> None:
    html = _read(INDEX_HTML)
    assert 'id="status"' in html
    assert (
        'id="status" class="loop-meta" role="status" aria-live="polite" aria-atomic="true"' in html
    )
    assert 'id="offline-banner" class="offline-banner" role="status" aria-live="polite"' in html
    assert 'id="export-btn" aria-label="Export loops"' in html
    assert 'id="import-btn" aria-label="Import loops"' in html
    assert 'id="capture-details-toggle"' in html
    assert 'aria-controls="capture-details"' in html


def test_critical_form_controls_have_programmatic_labels() -> None:
    html = _read(INDEX_HTML)
    labeled_ids = [
        "raw-text",
        "due-date",
        "next-action",
        "time-minutes",
        "activation-energy",
        "project",
        "tags",
        "chat-input",
        "rag-input",
    ]
    for control_id in labeled_ids:
        assert f'for="{control_id}"' in html or f'id="{control_id}" aria-label=' in html


def test_tabs_expose_control_relationships() -> None:
    html = _read(INDEX_HTML)
    for tab_name, panel_id in {
        "inbox": "inbox-main",
        "next": "next-main",
        "chat": "chat-main",
        "rag": "rag-main",
        "review": "review-main",
        "metrics": "metrics-main",
    }.items():
        assert f'id="tab-{tab_name}"' in html
        assert f'aria-controls="{panel_id}"' in html
        assert f'data-tab="{tab_name}"' in html


def test_skip_link_and_focus_styles_exist() -> None:
    css = _read(BASE_CSS)
    assert ".skip-link" in css
    assert ":focus-visible" in css


def test_render_templates_have_accessible_labels_for_icon_controls() -> None:
    js = _read(RENDER_JS)
    assert "compact-card" in js
    assert "mobile-text-collapsible" in js
    assert "compact-actions-menu" in js
    assert 'data-action="toggle-compact"' in js
    assert 'data-action="toggle-card-body"' in js
    assert "compact-summary-strip" in js
    assert "compact-next-action-summary" in js
    assert 'class="loop-card-shell"' in js
    assert 'class="loop-header"' in js
    assert 'class="loop-content"' in js
    assert 'class="loop-footer"' in js
    assert 'aria-label="Remove tag' in js
    assert 'aria-label="Cancel completion note"' in js
    assert 'data-action="confirm-complete"' in js
    assert 'data-snooze-duration="1h"' in js
    assert re.search(r"<button type=\"button\" class=\"snooze-option\"", js)
    assert 'aria-keyshortcuts="T"' in js
    assert 'aria-keyshortcuts="C"' in js
    assert 'aria-keyshortcuts="S"' in js
    assert 'aria-keyshortcuts="E"' in js
    assert 'aria-keyshortcuts="R"' in js
    assert '<span class="shortcut-hint">t</span>' not in js
    assert '<span class="shortcut-hint">c</span>' not in js
