/**
 * workflow-handoff.ts - Shared HTML rendering for workflow handoff summaries.
 *
 * Purpose:
 *   Render a consistent workflow-handoff block anywhere the frontend already
 *   has structured `OperatorActionHandoff` metadata.
 *
 * Responsibilities:
 *   - Render working-set badges from `handoff.workingSet`.
 *   - Render created-resource lists, next-step cues, and breadcrumbs.
 *   - Keep handoff markup consistent across operator cards and downstream surfaces.
 *
 * Scope:
 *   - Pure HTML string rendering for handoff summaries only.
 *
 * Usage:
 *   - Imported by operator-card and review-workspace renderers when a surface
 *     needs to display structured workflow handoff metadata.
 *
 * Invariants/Assumptions:
 *   - Callers provide already-validated `OperatorActionHandoff` data.
 *   - Styling is owned by the shared operator/review CSS layers.
 */

import type { OperatorActionHandoff } from "./contracts-ui";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderWorkflowHandoff(handoff: OperatorActionHandoff | null): string {
  if (!handoff) {
    return "";
  }

  const workingSetLine = handoff.workingSet
    ? `
      <p>
        <strong>Working set:</strong>
        ${escapeHtml(handoff.workingSet.workingSetName)}
        · ${handoff.workingSet.itemCount} item${handoff.workingSet.itemCount === 1 ? "" : "s"}
        ${handoff.workingSet.missingItemCount ? ` · ${handoff.workingSet.missingItemCount} missing` : ""}
      </p>
    `
    : "";

  return `
    <section class="operator-action-handoff" aria-label="Workflow handoff">
      <p class="operator-action-section-title">Workflow handoff</p>
      <p>${escapeHtml(handoff.changeSummary)}</p>
      ${workingSetLine}
      ${
        handoff.createdResources.length
          ? `
            <ul class="operator-action-trust-list">
              ${handoff.createdResources.map((resource) => `<li>${escapeHtml(resource)}</li>`).join("")}
            </ul>
          `
          : ""
      }
      ${handoff.nextStep ? `<p><strong>Next:</strong> ${escapeHtml(handoff.nextStep)}</p>` : ""}
      ${
        handoff.breadcrumbs.length
          ? `<p class="operator-action-breadcrumbs">${handoff.breadcrumbs.map((crumb) => escapeHtml(crumb)).join(" / ")}</p>`
          : ""
      }
    </section>
  `;
}
