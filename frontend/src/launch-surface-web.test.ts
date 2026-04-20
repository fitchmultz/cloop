/**
 * launch-surface-web.test.ts - Regression tests for shared launch-surface web parsing.
 */

import type { PlanningExecutionLaunchSurfaceResponse } from "./domain";
import { locationsMatch } from "./shell-routing";
import {
  coerceLaunchSurfaceInteger,
  launchSurfaceToLocation,
  launchSurfaceWorkingSetId,
  readLaunchSurfaceWeb,
} from "./launch-surface-web";

function enrichmentSurface(
  sessionId: unknown,
  workingSetId: unknown,
): PlanningExecutionLaunchSurfaceResponse {
  return {
    resource_type: "review_session",
    resource_id: 99,
    surface: "review_session",
    label: "Queue",
    reason: "Continue",
    web: {
      surface: "review_session",
      review_kind: "enrichment",
      session_id: sessionId,
      working_set_id: workingSetId,
    },
  } as PlanningExecutionLaunchSurfaceResponse;
}

describe("launch-surface-web", () => {
  describe("coerceLaunchSurfaceInteger", () => {
    it.each([
      [41, 41],
      ["41", 41],
      [" 41 ", 41],
      [41.7, null],
      ["abc", null],
      ["", null],
      [null, null],
    ])("coerces %p to %p", (input, expected) => {
      expect(coerceLaunchSurfaceInteger(input)).toBe(expected);
    });
  });

  describe("readLaunchSurfaceWeb", () => {
    it("returns null when web is missing", () => {
      expect(readLaunchSurfaceWeb({} as PlanningExecutionLaunchSurfaceResponse)).toBeNull();
    });
  });

  describe("launchSurfaceWorkingSetId", () => {
    it("uses web id for both number and string forms", () => {
      expect(launchSurfaceWorkingSetId(enrichmentSurface(1, 2), 9)).toBe(2);
      expect(launchSurfaceWorkingSetId(enrichmentSurface(1, "2"), 9)).toBe(2);
    });

    it("falls back when web omits working_set_id", () => {
      const surface = enrichmentSurface(1, null);
      expect(launchSurfaceWorkingSetId(surface, 9)).toBe(9);
      expect(launchSurfaceWorkingSetId(surface, null)).toBeNull();
    });
  });

  describe("launchSurfaceToLocation", () => {
    it("resolves enrichment review locations identically for numeric and string ids", () => {
      const numeric = launchSurfaceToLocation(enrichmentSurface(41, 2), { fallbackWorkingSetId: 9 });
      const strings = launchSurfaceToLocation(enrichmentSurface("41", "2"), { fallbackWorkingSetId: 9 });
      expect(numeric).not.toBeNull();
      expect(strings).not.toBeNull();
      expect(locationsMatch(numeric, strings)).toBe(true);
      expect(numeric!.sessionId).toBe(41);
      expect(numeric!.workingSetId).toBe(2);
    });

    it("applies fallback working set when web omits working_set_id", () => {
      const surface = enrichmentSurface("41", null);
      const loc = launchSurfaceToLocation(surface, { fallbackWorkingSetId: 7 });
      expect(loc?.sessionId).toBe(41);
      expect(loc?.workingSetId).toBe(7);
    });
  });
});
