/**
 * shell-routing.test.ts - Regression tests for canonical shell routing helpers.
 *
 * Purpose:
 *   Guard the extracted shell-routing module so hash parsing, hash encoding,
 *   and canonical location construction remain stable during shell refactors.
 *
 * Responsibilities:
 *   - Assert createLocation applies the expected shell defaults.
 *   - Assert parseHash and locationToHash preserve key deep-link routes.
 *   - Assert location comparisons stay sensitive to working-set scope and saved queries.
 *
 * Scope:
 *   - Pure shell-routing helpers only.
 *
 * Usage:
 *   - Run with `pnpm --dir frontend test`.
 *
 * Invariants/Assumptions:
 *   - Tests avoid DOM or localStorage dependencies.
 *   - Hash routes remain the canonical shareable shell URL format.
 */

import {
  createLocation,
  defaultLocationForState,
  isWorkState,
  locationToHash,
  locationsMatch,
  parseHash,
  workingSetSessionLocation,
} from "./shell-routing";

describe("createLocation", () => {
  it("fills in shell defaults for omitted fields", () => {
    expect(createLocation({ state: "do", loopId: 42 })).toEqual({
      state: "do",
      recallTool: "chat",
      reviewFocus: null,
      sessionId: null,
      loopId: 42,
      viewId: null,
      memoryId: null,
      workingSetId: null,
      query: null,
      includeLoopContext: null,
      includeMemoryContext: null,
      includeRagContext: null,
    });
  });
});

describe("defaultLocationForState", () => {
  it("preserves working-set scope when switching between states", () => {
    expect(
      defaultLocationForState("review", createLocation({ state: "do", loopId: 42, workingSetId: 9 })),
    ).toEqual(createLocation({ state: "review", reviewFocus: "cohorts", workingSetId: 9 }));
  });

  it("preserves the current work deep link when reopening the same work state", () => {
    expect(
      defaultLocationForState("plan", createLocation({ state: "plan", reviewFocus: "planning", sessionId: 12, workingSetId: 4 })),
    ).toEqual(createLocation({ state: "plan", reviewFocus: "planning", sessionId: 12, workingSetId: 4 }));
  });
});

describe("isWorkState", () => {
  it("recognizes the mobile work-state cluster", () => {
    expect(isWorkState("do")).toBe(true);
    expect(isWorkState("review")).toBe(true);
    expect(isWorkState("recall")).toBe(false);
  });
});

describe("locationToHash / parseHash", () => {
  it("round-trips a working-set session route", () => {
    const location = workingSetSessionLocation(7);
    expect(locationToHash(location)).toBe("#working-set/7");
    expect(parseHash("#working-set/7")).toEqual(location);
  });

  it("round-trips review and plan routes with working-set context", () => {
    const planningLocation = createLocation({
      state: "plan",
      reviewFocus: "planning",
      sessionId: 12,
      workingSetId: 3,
    });
    const reviewLocation = createLocation({
      state: "decide",
      reviewFocus: "relationship",
      sessionId: 22,
      workingSetId: 3,
    });

    expect(locationToHash(planningLocation)).toBe("#plan/session/12?ws=3");
    expect(parseHash("#plan/session/12?ws=3")).toEqual(planningLocation);
    expect(locationToHash(reviewLocation)).toBe("#decide/relationship/22?ws=3");
    expect(parseHash("#decide/relationship/22?ws=3")).toEqual(reviewLocation);
  });

  it("round-trips recall query routes", () => {
    const location = createLocation({
      state: "recall",
      recallTool: "rag",
      query: "what changed today",
      workingSetId: 5,
      includeLoopContext: true,
      includeMemoryContext: false,
      includeRagContext: true,
    });
    expect(locationToHash(location)).toBe("#recall/rag/query/what%20changed%20today?ws=5&lc=1&mc=0&rc=1");
    expect(parseHash("#recall/rag/query/what%20changed%20today?ws=5&lc=1&mc=0&rc=1")).toEqual(location);
  });

  it("parses review query routes into cohort review focus", () => {
    expect(parseHash("#review/query/status%3Ablocked?ws=4")).toEqual(
      createLocation({ state: "review", reviewFocus: "cohorts", query: "status:blocked", workingSetId: 4 }),
    );
  });
});

describe("locationsMatch", () => {
  it("treats identical locations as equal", () => {
    expect(
      locationsMatch(
        createLocation({ state: "plan", reviewFocus: "planning", sessionId: 9 }),
        createLocation({ state: "plan", reviewFocus: "planning", sessionId: 9 }),
      ),
    ).toBe(true);
  });

  it("treats saved queries as distinct locations", () => {
    expect(
      locationsMatch(
        createLocation({ state: "do", query: "status:blocked" }),
        createLocation({ state: "do", query: "status:open" }),
      ),
    ).toBe(false);
  });
});
