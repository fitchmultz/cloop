/**
 * main.ts - Frontend application bootstrap entrypoint.
 *
 * Purpose:
 *   Load the stylesheet stack and bootstrap the TypeScript-bundled Cloop web UI.
 *
 * Responsibilities:
 *   - Import the current CSS modules through Vite.
 *   - Load the ported application entry module.
 *   - Keep browser startup behavior aligned with the existing shell.
 *
 * Scope:
 *   - Frontend entrypoint only.
 *
 * Usage:
 *   - Loaded by frontend/index.html in development and the Vite-built app in production.
 *
 * Invariants/Assumptions:
 *   - The DOM structure in frontend/index.html preserves the current UI ids/classes.
 *   - The init module owns DOMContentLoaded coordination and feature bootstrap.
 */

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./styles/operator.css";
import "./styles/loop.css";
import "./styles/review.css";
import "./styles/chat-rag.css";
import "./styles/memory.css";
import "./styles/comments.css";
import "./styles/modals.css";

import { bootstrapReviewWorkspace } from "./review-workspace";
import { bootstrapShell } from "./shell";

bootstrapShell();
void import("./legacy/init.js").then(() => {
  bootstrapReviewWorkspace();
});
