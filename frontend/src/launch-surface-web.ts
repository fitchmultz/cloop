/**
 * launch-surface-web.ts - Normalize planning execution launch-surface `web` payloads.
 *
 * Coerces `session_id` and `working_set_id` the same way for shell operator
 * cards and review workspace handoffs/action cards so backend payloads that
 * stringify ids still navigate with full context.
 */

import type { PlanningExecutionLaunchSurfaceResponse } from "./domain";
import { createLocation } from "./shell-routing";
import type { ShellLocation } from "./shell-types";
import { coerceJsonInteger } from "./coerce-json-integer";

export { coerceJsonInteger as coerceLaunchSurfaceInteger };

export function readLaunchSurfaceWeb(
  surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
): Record<string, unknown> | null {
  const webValue = surface?.web;
  return webValue && typeof webValue === "object" ? (webValue as Record<string, unknown>) : null;
}

export function launchSurfaceWorkingSetId(
  surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
  fallbackWorkingSetId?: number | null,
): number | null {
  const fromWeb = coerceJsonInteger(readLaunchSurfaceWeb(surface)?.["working_set_id"]);
  if (fromWeb != null) {
    return fromWeb;
  }
  if (fallbackWorkingSetId != null) {
    return fallbackWorkingSetId;
  }
  return null;
}

export interface LaunchSurfaceLocationOptions {
  fallbackWorkingSetId?: number | null;
}

export function launchSurfaceToLocation(
  surface: PlanningExecutionLaunchSurfaceResponse,
  options: LaunchSurfaceLocationOptions = {},
): ShellLocation | null {
  const web = readLaunchSurfaceWeb(surface);
  const fallbackWorkingSetId = options.fallbackWorkingSetId ?? null;
  const reviewKind = typeof web?.["review_kind"] === "string" ? web["review_kind"] : null;
  const sessionId = coerceJsonInteger(web?.["session_id"]);
  const workingSetId = launchSurfaceWorkingSetId(surface, fallbackWorkingSetId);

  if (web?.["surface"] === "review_session" && reviewKind === "relationship") {
    return createLocation({ state: "decide", reviewFocus: "relationship", sessionId, workingSetId });
  }
  if (web?.["surface"] === "review_session" && reviewKind === "enrichment") {
    return createLocation({ state: "decide", reviewFocus: "enrichment", sessionId, workingSetId });
  }
  if (web?.["surface"] === "recall_chat") {
    return createLocation({
      state: "recall",
      recallTool: "chat",
      workingSetId,
      query: typeof web["query"] === "string" ? web["query"] : null,
      includeLoopContext: typeof web["include_loop_context"] === "boolean" ? web["include_loop_context"] : null,
      includeMemoryContext: typeof web["include_memory_context"] === "boolean" ? web["include_memory_context"] : null,
      includeRagContext: typeof web["include_rag_context"] === "boolean" ? web["include_rag_context"] : null,
    });
  }
  return null;
}
