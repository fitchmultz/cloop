/**
 * legacy-entry.js - Residual legacy-surface bootstrap entrypoint.
 *
 * Purpose:
 *   Isolate the untouched legacy runtime behind a dedicated HTML module entry
 *   so TypeScript-owned shell surfaces no longer import legacy modules
 *   directly.
 *
 * Responsibilities:
 *   - Load the remaining legacy surface bootstrap for inbox/do/recall and other
 *     residual JS-owned areas.
 *
 * Scope:
 *   - Compatibility bootstrap only.
 *
 * Usage:
 *   - Referenced directly from frontend/index.html.
 *
 * Invariants/Assumptions:
 *   - frontend/src/main.ts remains the TypeScript-owned operator-shell entry.
 *   - frontend/src/legacy/init.js continues to bootstrap only the residual
 *     non-ported surfaces.
 */

import "./legacy/init.js";
