/**
 * js-modules.d.ts - Wildcard JS module declarations for the frontend bundle.
 *
 * Purpose:
 *   Tell strict TypeScript that the temporary legacy JavaScript compatibility
 *   modules can be imported during the shell cutover.
 *
 * Responsibilities:
 *   - Declare generic `.js` module imports for side-effect and compatibility
 *     loading during the migration period.
 *
 * Scope:
 *   - TypeScript declaration coverage for JavaScript module imports only.
 *
 * Usage:
 *   - Picked up automatically by the frontend tsconfig include patterns.
 *
 * Invariants/Assumptions:
 *   - This declaration is temporary scaffolding while legacy JS is retired in
 *     favor of fully typed TypeScript modules.
 */

declare module "*.js";