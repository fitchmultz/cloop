"""Static accessibility regression tests for the web UI.

Purpose:
    Guard high-value accessibility semantics in frontend source assets.

Responsibilities:
    - Verify skip-link and status/live-region semantics.
    - Verify key inputs have labels.
    - Verify tab controls declare panel relationships.
    - Verify icon-only controls in render templates have aria labels.

Scope:
    - Source-level HTML/CSS/JS accessibility contract checks.

Usage:
    - Run with `uv run pytest tests/test_accessibility.py`.

Invariants/Assumptions:
    - `frontend/index.html` is the canonical source shell for the Vite frontend.
    - `frontend/src/styles/*` and `frontend/src/surfaces/*.ts` preserve current UX semantics.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "frontend" / "index.html"
BASE_CSS = ROOT / "frontend" / "src" / "styles" / "base.css"
MODALS_CSS = ROOT / "frontend" / "src" / "styles" / "modals.css"
OPERATOR_CSS = ROOT / "frontend" / "src" / "styles" / "operator.css"
RENDER_TS = ROOT / "frontend" / "src" / "surfaces" / "render.ts"
STATIC_SURFACE_DIR = ROOT / "frontend" / "src" / "surfaces"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skip_link_exists_and_targets_operator_workspace() -> None:
    html = _read(INDEX_HTML)
    assert 'class="skip-link" href="#operator-main"' in html
    assert 'id="operator-main"' in html


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
    assert 'id="app-dialog"' in html
    assert 'aria-labelledby="app-dialog-title"' in html
    assert 'aria-describedby="app-dialog-description"' in html
    assert 'id="app-dialog-form"' in html
    assert 'id="app-dialog-error"' in html


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


def test_state_navigation_and_surface_roots_expose_control_relationships() -> None:
    html = _read(INDEX_HTML)
    for shell_state in ["operator", "capture", "do", "decide", "plan", "review", "recall"]:
        assert f'data-shell-state="{shell_state}"' in html

    assert 'id="recall-subnav"' in html
    for recall_tool in ["chat", "memory", "rag"]:
        assert f'data-recall-tool="{recall_tool}"' in html

    for panel_id in [
        "inbox-main",
        "next-main",
        "chat-main",
        "memory-main",
        "rag-main",
        "review-main",
    ]:
        assert f'id="{panel_id}"' in html
        assert re.search(rf'<main[^>]*id="{re.escape(panel_id)}"[^>]*style="display: none;"', html)

    assert 'id="do-query-filter"' in html
    assert 'id="working-set-focus-banner"' in html
    assert 'id="working-set-focus-summary"' in html
    assert 'id="working-set-focus-items"' in html
    assert 'id="working-set-focus-toggle-btn"' in html
    assert 'id="working-set-exit-focus-btn"' in html
    assert 'id="shell-command-palette-btn"' in html
    assert 'aria-controls="command-palette"' in html
    assert 'id="command-palette"' in html
    assert 'id="command-palette-input"' in html
    assert 'id="command-palette-results"' in html
    assert 'id="command-palette-detail"' in html
    assert 'id="command-palette-status"' in html
    assert 'role="listbox" aria-label="Command results"' in html
    assert 'id="review-redesign-shell"' in html
    assert 'role="tablist" aria-label="Review modes"' in html
    assert (
        'id="review-shell-status" class="support-status" role="status" aria-live="polite"' in html
    )
    assert 'id="review-shell-queue-title"' in html
    assert 'id="review-shell-workspace-title"' in html
    assert 'id="review-shell-impact-title"' in html


def test_skip_link_and_focus_styles_exist() -> None:
    css = _read(BASE_CSS)
    assert ".skip-link" in css
    assert ":focus-visible" in css


def test_modal_styles_support_mobile_safe_dialog_layout() -> None:
    css = _read(MODALS_CSS)
    assert ".app-dialog-overlay" in css
    assert ".app-dialog-actions" in css
    assert ".app-dialog-input:focus" in css
    assert "@media (max-width: 640px)" in css
    assert "align-items: flex-end" in css


def test_operator_shell_styles_exist_for_state_nav_and_workspace() -> None:
    css = _read(OPERATOR_CSS)
    assert ".state-nav" in css
    assert ".state-nav-btn" in css
    assert ".operator-main" in css
    assert ".operator-grid" in css
    assert ".operator-action-card" in css
    assert ".operator-action-preview-list" in css
    assert ".working-set-focus-banner" in css
    assert ".working-set-item-card" in css
    assert ".working-set-card" in css
    assert ".command-palette" in css
    assert ".command-palette-panel" in css
    assert ".command-palette-results" in css
    assert ".command-palette-detail" in css
    assert ".shell-focus-hidden" in css
    assert "body.shell-focus-mode" in css
    assert ".is-shell-focus" in css


def test_review_shell_styles_exist_for_redesigned_decision_workspace() -> None:
    css = _read(ROOT / "frontend" / "src" / "styles" / "review.css")
    assert ".review-shell-panel" in css
    assert ".review-shell-layout" in css
    assert ".review-shell-pane" in css
    assert ".review-shell-rail-card" in css
    assert ".review-shell-focus-card" in css
    assert ".review-shell-impact-card" in css
    assert ".review-shell-chip" in css
    assert ".review-shell-toolbar-group--fields" in css
    assert ".review-shell-toolbar-group--actions" in css
    assert ".review-shell-inline-actions--decision" in css
    assert ".review-shell-inline-actions--nav" in css
    assert ".review-shell-inline-actions--stack-mobile" in css


def test_static_web_ui_does_not_use_native_browser_dialogs() -> None:
    native_dialog_pattern = re.compile(r"\b(prompt|alert|confirm)\s*\(")
    offenders: list[str] = []

    for path in STATIC_SURFACE_DIR.glob("*.ts"):
        if native_dialog_pattern.search(_read(path)):
            offenders.append(path.name)

    assert offenders == []


def test_render_templates_have_accessible_labels_for_icon_controls() -> None:
    js = _read(RENDER_TS)
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
