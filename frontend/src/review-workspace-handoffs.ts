/**
 * review-workspace-handoffs.ts - Pure handoff helpers for review-workspace impact cards.
 *
 * Purpose:
 *   Build shared workflow-handoff metadata for planning execution impact cards
 *   inside the review workspace.
 *
 * Responsibilities:
 *   - Resolve working-set metadata from loaded working-set payloads.
 *   - Convert launch-surface and follow-up-resource payloads into
 *     `OperatorActionHandoff` summaries.
 *   - Keep breadcrumb and next-step shaping deterministic and testable.
 *
 * Scope:
 *   - Pure data shaping only; no DOM access or network requests.
 *
 * Usage:
 *   - Imported by `frontend/src/review-workspace.ts` and unit tests.
 *
 * Invariants/Assumptions:
 *   - Working-set names/counts come from caller-provided `WorkingSetResponse` data.
 *   - Launch-surface `web.working_set_id` is the canonical propagated working-set id
 *     when present.
 */

import type { OperatorActionHandoff, WorkingSetSessionMetadata } from "./contracts-ui";
import type {
  PlanningExecutionFollowUpResourceResponse,
  PlanningExecutionLaunchSurfaceResponse,
  WorkingSetResponse,
} from "./domain";

export interface ReviewWorkspaceHandoffContext {
  breadcrumbPrefix: string[];
  fallbackWorkingSetId: number | null;
  workingSets: readonly WorkingSetResponse[];
}

function webWorkingSetId(
  surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
): number | null {
  const web = surface?.web;
  if (!web || typeof web !== "object") {
    return null;
  }
  const value = web["working_set_id"];
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

export function resolveWorkingSetSessionMetadata(
  workingSets: readonly WorkingSetResponse[],
  workingSetId: number | null | undefined,
): WorkingSetSessionMetadata | null {
  if (workingSetId == null) {
    return null;
  }
  const workingSet = workingSets.find((candidate) => candidate.id === workingSetId) ?? null;
  if (!workingSet) {
    return null;
  }
  return {
    workingSetId: workingSet.id,
    workingSetName: workingSet.name,
    itemCount: workingSet.item_count,
    missingItemCount: workingSet.missing_item_count,
  };
}

export function launchSurfaceWorkingSetId(
  surface: PlanningExecutionLaunchSurfaceResponse | null | undefined,
  fallbackWorkingSetId: number | null,
): number | null {
  return webWorkingSetId(surface) ?? fallbackWorkingSetId;
}

export function buildLaunchSurfaceHandoff(
  surface: PlanningExecutionLaunchSurfaceResponse,
  context: ReviewWorkspaceHandoffContext,
): OperatorActionHandoff {
  const workingSetId = launchSurfaceWorkingSetId(surface, context.fallbackWorkingSetId);
  return {
    changeSummary: surface.reason || "A downstream surface is ready to open.",
    createdResources: [`${surface.resource_type} #${surface.resource_id}`],
    nextStep: `Open ${surface.label} with its saved workflow context restored.`,
    breadcrumbs: [...context.breadcrumbPrefix, surface.label],
    workingSet: resolveWorkingSetSessionMetadata(context.workingSets, workingSetId),
  };
}

export function buildFollowUpResourceHandoff(
  resource: PlanningExecutionFollowUpResourceResponse,
  context: ReviewWorkspaceHandoffContext,
): OperatorActionHandoff | null {
  if (!resource.launch_surface) {
    return null;
  }
  const launchSurfaceHandoff = buildLaunchSurfaceHandoff(resource.launch_surface, context);
  return {
    ...launchSurfaceHandoff,
    changeSummary: resource.operation_summary,
    createdResources: [resource.label || `${resource.resource_type} #${resource.resource_id}`],
    nextStep: `Open ${resource.launch_surface.label} to continue the follow-up created by this checkpoint.`,
  };
}
