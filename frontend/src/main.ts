/**
 * main.ts - Frontend application bootstrap entrypoint.
 *
 * Purpose:
 *   Load the stylesheet stack and bootstrap the TypeScript-bundled Cloop web UI.
 *
 * Responsibilities:
 *   - Import the current CSS modules through Vite.
 *   - Bootstrap the TypeScript-owned shell and review workspaces.
 *   - Keep browser startup behavior aligned with the Vite-built operator shell.
 *
 * Scope:
 *   - Frontend entrypoint only.
 *
 * Usage:
 *   - Loaded by frontend/index.html in development and the Vite-built app in production.
 *
 * Invariants/Assumptions:
 *   - The DOM structure in frontend/index.html preserves the current UI ids/classes.
 *   - Residual legacy-only surfaces, if any, are bootstrapped through their own
 *     dedicated entrypoint rather than through this TypeScript bootstrap.
 */

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./styles/trust-surfaces.css";
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
bootstrapReviewWorkspace();
