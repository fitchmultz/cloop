/**
 * openapi-ts.config.ts - Hey API contract generation config for the frontend.
 *
 * Purpose:
 *   Define the single source of truth for generating frontend OpenAPI contract types.
 *
 * Responsibilities:
 *   - Point Hey API at the exported backend OpenAPI document.
 *   - Generate only the frontend contract artifacts the app consumes today.
 *   - Keep code generation deterministic inside frontend/src/generated.
 *
 * Scope:
 *   - Frontend OpenAPI type generation only.
 *
 * Usage:
 *   - Run `pnpm run generate:contracts` from `frontend/`.
 *
 * Invariants/Assumptions:
 *   - `openapi.json` is refreshed before this config runs.
 *   - Hey API is the only frontend OpenAPI generator.
 *   - The TypeScript plugin output is the canonical contract source of truth.
 */

import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "./openapi.json",
  output: "./src/generated",
  plugins: ["@hey-api/typescript"],
});
