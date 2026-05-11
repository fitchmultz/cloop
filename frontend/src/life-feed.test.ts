/**
 * life-feed.test.ts - Regression tests for the Life feed.
 *
 * Purpose:
 *   Verify Life response rendering stays aligned with the backend Life contract.
 *
 * Responsibilities:
 *   - Guard clarification-answer receipts in the conversational feed.
 *   - Guard cleanup recommendation bucket rendering from agent-owned plans.
 *
 * Scope:
 *   - Browser-side Life feed behavior with mocked transport.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { requestJson } from "./http";
import { bootstrapLifeFeed } from "./life-feed";

vi.mock("./http", () => ({
  requestJson: vi.fn(),
}));

function createLifeFixture(): void {
  document.body.innerHTML = `
    <form id="life-form" aria-busy="false">
      <textarea id="life-input"></textarea>
      <button type="button" id="life-quick-dump-btn">Use sample dump</button>
      <button type="button" id="life-missing-btn">What am I missing?</button>
      <button type="button" id="life-matters-btn">What matters today?</button>
      <button type="button" id="life-quiz-btn">Quiz me</button>
      <button type="button" id="life-history-btn">Show archive</button>
      <button type="button" id="life-cleanup-btn">Review cleanup</button>
      <button type="button" id="life-voice-btn" aria-pressed="false">Voice</button>
      <button type="button" id="life-evidence-btn">Attach</button>
      <input id="life-evidence-input" type="file" multiple>
      <div id="life-evidence-list"></div>
      <button type="submit" id="life-submit-btn">Send</button>
      <p id="life-status">Ready.</p>
    </form>
    <div id="life-response" hidden></div>
    <div id="life-captured-list"></div>
    <div id="life-groups-list"></div>
  `;
}

function loopFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 101,
    raw_text: "Need to pick up medicine.",
    title: "Pick up medicine",
    summary: "Pick up medicine at Costco.",
    status: "open",
    captured_at_utc: "2026-05-07T17:00:00Z",
    captured_tz_offset_min: -360,
    created_at_utc: "2026-05-07T17:00:00Z",
    updated_at_utc: "2026-05-07T17:00:00Z",
    next_action: "Pick up medicine at Costco.",
    time_minutes: 15,
    ...overrides,
  };
}

interface FakeSpeechRecognitionEvent {
  results: {
    length: number;
    [index: number]: {
      length: number;
      [alternativeIndex: number]: {
        transcript: string;
      };
    };
  };
}

class FakeSpeechRecognition {
  static instance: FakeSpeechRecognition | null = null;

  continuous = false;
  interimResults = false;
  lang = "";
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onresult: ((event: FakeSpeechRecognitionEvent) => void) | null = null;

  start(): void {
    FakeSpeechRecognition.instance = this;
  }

  stop(): void {
    this.onend?.();
  }

  abort(): void {
    this.onend?.();
  }
}

async function flushAsyncHandlers(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("Life feed", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete (window as typeof window & { SpeechRecognition?: typeof FakeSpeechRecognition })
      .SpeechRecognition;
    FakeSpeechRecognition.instance = null;
    vi.clearAllMocks();
  });

  it("renders recorded clarification answers from the Life response", async () => {
    createLifeFixture();
    vi.mocked(requestJson).mockResolvedValueOnce({
      mode: "capture",
      reply: "Got it. I updated the pickup location.",
      captured: [],
      updated: [
        {
          loop: loopFixture(),
          life_state: "active",
          rationale: "The user answered the pending pharmacy clarification.",
          prepared_next_action: "Pick up medicine at Costco.",
          prepared_actions: [],
        },
      ],
      clarifications: [],
      answered_clarifications: [
        {
          clarification_id: 501,
          loop_id: 101,
          question: "Is this CostMedica, or a different pharmacy?",
          answer: "Costco",
          rationale: "This answers the pending pharmacy question.",
        },
      ],
      groups: [],
      cleanup: null,
    });

    bootstrapLifeFeed();
    const input = document.getElementById("life-input");
    const form = document.getElementById("life-form");
    if (!(input instanceof HTMLTextAreaElement) || !(form instanceof HTMLFormElement)) {
      throw new Error("Missing Life fixture controls");
    }
    input.value = "Actually Costco.";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flushAsyncHandlers();

    expect(document.querySelector(".life-answered-clarification")?.textContent).toContain(
      "Costco",
    );
    expect(document.getElementById("life-captured-list")?.textContent).toContain(
      "Pick up medicine",
    );
  });

  it("renders cleanup recommendation buckets from the agent plan", async () => {
    createLifeFixture();
    vi.mocked(requestJson).mockResolvedValueOnce({
      mode: "cleanup",
      reply: "We have some cleanup.",
      captured: [],
      updated: [],
      clarifications: [],
      answered_clarifications: [],
      groups: [],
      cleanup: {
        open_count: 17,
        recommendation: "Want to go two at a time?",
        close_candidates: [
          {
            loop: loopFixture({ id: 102, title: "Send recruiter availability" }),
            life_state: "completed",
            rationale: "Looks handled.",
            prepared_next_action: "Mark complete if the email was sent.",
            prepared_actions: [],
          },
        ],
        archive_candidates: [
          {
            loop: loopFixture({ id: 103, title: "Research old supplement" }),
            life_state: "stale",
            rationale: "No longer active.",
            prepared_next_action: "Archive unless it matters this week.",
            prepared_actions: [],
          },
        ],
        keep_active: [],
        review_needed: [],
        applied_automatic_cleanup: [],
        undo: [],
      },
    });

    bootstrapLifeFeed();
    const button = document.getElementById("life-cleanup-btn");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Missing cleanup button");
    }
    button.click();
    await flushAsyncHandlers();

    expect(document.querySelector(".life-cleanup-plan")?.textContent).toContain(
      "Want to go two at a time?",
    );
    expect(document.querySelector(".life-cleanup-plan")?.textContent).toContain(
      "Research old supplement",
    );
  });

  it("appends browser voice input to the Life message box", () => {
    createLifeFixture();
    (window as typeof window & { SpeechRecognition?: typeof FakeSpeechRecognition })
      .SpeechRecognition = FakeSpeechRecognition;

    bootstrapLifeFeed();
    const button = document.getElementById("life-voice-btn");
    const input = document.getElementById("life-input");
    if (!(button instanceof HTMLButtonElement) || !(input instanceof HTMLTextAreaElement)) {
      throw new Error("Missing voice fixture controls");
    }

    button.click();
    FakeSpeechRecognition.instance?.onresult?.({
      results: {
        length: 1,
        0: { length: 1, 0: { transcript: "pick up medicine" } },
      },
    });
    FakeSpeechRecognition.instance?.onend?.();

    expect(input.value).toBe("pick up medicine");
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("reports unsupported voice input without changing the message", () => {
    createLifeFixture();
    bootstrapLifeFeed();
    const button = document.getElementById("life-voice-btn");
    const input = document.getElementById("life-input");
    const status = document.getElementById("life-status");
    if (
      !(button instanceof HTMLButtonElement)
      || !(input instanceof HTMLTextAreaElement)
      || !(status instanceof HTMLElement)
    ) {
      throw new Error("Missing voice fixture controls");
    }
    input.value = "already typed";

    button.click();

    expect(input.value).toBe("already typed");
    expect(status.textContent).toContain("not supported");
  });

  it("sends Life prompt buttons as ordinary agent messages", async () => {
    createLifeFixture();
    vi.mocked(requestJson).mockResolvedValue({
      mode: "resurface",
      reply: "Checked.",
      captured: [],
      updated: [],
      clarifications: [],
      answered_clarifications: [],
      groups: [],
      cleanup: null,
    });

    bootstrapLifeFeed();
    const buttonIds = [
      "life-missing-btn",
      "life-matters-btn",
      "life-quiz-btn",
      "life-history-btn",
      "life-cleanup-btn",
    ];
    for (const buttonId of buttonIds) {
      const button = document.getElementById(buttonId);
      if (!(button instanceof HTMLButtonElement)) {
        throw new Error(`Missing ${buttonId}`);
      }
      button.click();
      await flushAsyncHandlers();
    }

    const messages = vi.mocked(requestJson).mock.calls.map((call) => {
      const body = call[1]?.body as { message?: string } | undefined;
      return body?.message;
    });
    expect(messages).toEqual([
      "What am I missing?",
      "What matters today?",
      "Quiz me on what is open.",
      "Show my history and archive.",
      "Review my open loops and clean up what your authority allows.",
    ]);
  });

  it("sends attached file evidence as source metadata", async () => {
    createLifeFixture();
    vi.mocked(requestJson).mockResolvedValueOnce({
      mode: "capture",
      reply: "Captured with evidence.",
      captured: [],
      updated: [],
      clarifications: [],
      answered_clarifications: [],
      groups: [],
      cleanup: null,
    });

    bootstrapLifeFeed();
    const input = document.getElementById("life-input");
    const fileInput = document.getElementById("life-evidence-input");
    const form = document.getElementById("life-form");
    if (
      !(input instanceof HTMLTextAreaElement)
      || !(fileInput instanceof HTMLInputElement)
      || !(form instanceof HTMLFormElement)
    ) {
      throw new Error("Missing evidence fixture controls");
    }

    const file = new File(["screenshot"], "pharmacy.png", { type: "image/png" });
    Object.defineProperty(fileInput, "files", {
      configurable: true,
      value: [file],
    });
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    input.value = "This is the pharmacy pickup screenshot.";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flushAsyncHandlers();

    expect(document.getElementById("life-evidence-list")?.textContent).not.toContain(
      "pharmacy.png",
    );
    expect(vi.mocked(requestJson).mock.calls[0]?.[1]?.body).toMatchObject({
      external_inputs: [
        {
          kind: "image",
          label: "pharmacy.png",
          media_type: "image/png",
          size_bytes: file.size,
        },
      ],
    });
  });

  it("turns typed links into source metadata for the Life agent", async () => {
    createLifeFixture();
    vi.mocked(requestJson).mockResolvedValueOnce({
      mode: "capture",
      reply: "Captured link context.",
      captured: [],
      updated: [],
      clarifications: [],
      answered_clarifications: [],
      groups: [],
      cleanup: null,
    });

    bootstrapLifeFeed();
    const input = document.getElementById("life-input");
    const form = document.getElementById("life-form");
    if (!(input instanceof HTMLTextAreaElement) || !(form instanceof HTMLFormElement)) {
      throw new Error("Missing link fixture controls");
    }
    input.value = "Look at https://example.com/jobs/123.";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flushAsyncHandlers();

    expect(vi.mocked(requestJson).mock.calls[0]?.[1]?.body).toMatchObject({
      external_inputs: [
        {
          kind: "link",
          label: "https://example.com/jobs/123",
          source_url: "https://example.com/jobs/123",
        },
      ],
    });
  });
});
