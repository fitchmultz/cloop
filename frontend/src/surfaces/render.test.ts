/**
 * render.test.ts - Regression tests for surface DOM rendering helpers.
 *
 * Purpose:
 *   Verify loop-card HTML communicates optional AI organization states clearly.
 *
 * Responsibilities:
 *   - Exercise renderLoop against backend-shaped loop payloads.
 *   - Guard calm enrichment-failure and skipped/idle copy.
 *   - Confirm retry labels are connected to the visible enrichment status.
 *
 * Scope:
 *   - DOM output from frontend/src/surfaces/render.ts only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test -- surfaces/render.test.ts`.
 *
 * Invariants/Assumptions:
 *   - Enrichment is optional assistance; failed enrichment must not make the loop
 *     card read like the task itself is broken.
 */

import { describe, expect, it } from "vitest";

import type { SurfaceLoop } from "./contracts";
import { renderLoop } from "./render";

function loop(overrides: Partial<SurfaceLoop> = {}): SurfaceLoop {
  return {
    id: 1,
    raw_text: "Test loop",
    title: "Test loop",
    summary: null,
    definition_of_done: null,
    next_action: null,
    status: "inbox",
    captured_at_utc: "2026-04-27T00:00:00Z",
    captured_tz_offset_min: 0,
    due_date: null,
    due_at_utc: null,
    snooze_until_utc: null,
    time_minutes: null,
    activation_energy: null,
    urgency: null,
    importance: null,
    blocked_reason: null,
    completion_note: null,
    project: null,
    project_id: null,
    tags: [],
    user_locks: [],
    provenance: {},
    enrichment_state: "idle",
    enrichment_status: {
      state: "idle",
      label: "AI organization optional",
      message: "This loop is usable. AI organization has not run yet.",
      tone: "neutral",
      retryable: true,
      action_label: "Run AI organization",
      reason: null,
      last_event_id: null,
      last_event_at_utc: null,
    },
    recurrence_rrule: null,
    recurrence_tz: null,
    next_due_at_utc: null,
    recurrence_enabled: false,
    parent_loop_id: null,
    created_at_utc: "2026-04-27T00:00:00Z",
    updated_at_utc: "2026-04-27T00:00:00Z",
    closed_at_utc: null,
    latest_reversible_event_id: null,
    latest_reversible_event_type: null,
    ...overrides,
  } as SurfaceLoop;
}

describe("renderLoop enrichment status", () => {
  it("renders failed enrichment as usable and retryable", () => {
    const card = renderLoop(loop({
      enrichment_state: "failed",
      enrichment_status: {
        state: "failed",
        label: "AI organization needs attention",
        message: "This loop is usable, but AI organization could not finish.",
        tone: "attention",
        retryable: true,
        action_label: "Retry AI organization",
        reason: "AI provider settings need attention.",
        last_event_id: 42,
        last_event_at_utc: "2026-04-27T00:01:00Z",
      },
    }));

    expect(card.textContent).toContain("AI organization needs attention");
    expect(card.textContent).toContain("This loop is usable");
    expect(card.textContent).toContain("AI provider settings need attention");
    expect(card.querySelector('[data-action="enrich"]')?.textContent).toContain("Retry AI organization");
  });

  it("renders idle enrichment as optional instead of failed", () => {
    const card = renderLoop(loop());

    expect(card.textContent).toContain("AI organization optional");
    expect(card.textContent).toContain("This loop is usable");
    expect(card.textContent).not.toContain("Enrichment failed");
    expect(card.querySelector('[data-action="enrich"]')?.textContent).toContain("Run AI organization");
  });

  it("renders pending enrichment as in-progress and disables duplicate runs", () => {
    const card = renderLoop(loop({
      enrichment_state: "pending",
      enrichment_status: {
        state: "pending",
        label: "AI organization running",
        message: "This loop is usable while AI organization works in the background.",
        tone: "working",
        retryable: false,
        action_label: null,
        reason: null,
        last_event_id: 43,
        last_event_at_utc: "2026-04-27T00:02:00Z",
      },
    }));

    const enrichButton = card.querySelector('[data-action="enrich"]');
    expect(card.textContent).toContain("AI organization running");
    expect(card.textContent).toContain("works in the background");
    expect(enrichButton?.textContent).toContain("Run AI organization");
    expect(enrichButton).toHaveProperty("disabled", true);
  });
});
