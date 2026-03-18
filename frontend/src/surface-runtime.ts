/**
 * surface-runtime.ts - Typed launch contracts for the TS-owned work surfaces.
 *
 * Purpose:
 *   Give the operator shell one typed way to activate capture, do, and recall
 *   surfaces without relying on hidden bridge tabs or direct DOM clicks.
 *
 * Responsibilities:
 *   - Define the shell-to-surface launch contracts.
 *   - Map shell locations into concrete surface activations.
 *   - Bootstrap the shared capture/do/recall surface runtime.
 *
 * Scope:
 *   - Browser-only surface activation contracts.
 *
 * Usage:
 *   - Imported by frontend/src/main.ts and frontend/src/shell.ts.
 *
 * Invariants/Assumptions:
 *   - frontend/src/surfaces/bootstrap.ts owns the non-shell capture/do/recall
 *     event wiring and data loading.
 *   - Shell hash routes remain the canonical navigation model.
 */

import type { RecallTool, ShellState } from "./contracts-ui";
import {
  activateSurface as activateSurfaceRuntime,
  bootstrapSurfaceRuntime as bootstrapSurfaceRuntimeImpl,
  refreshSurface as refreshSurfaceRuntime,
} from "./surfaces/bootstrap";

export interface CaptureSurfaceContract {
  state: "capture";
}

export interface DoSurfaceContract {
  state: "do";
}

export interface RecallSurfaceContract {
  state: "recall";
  recallTool: RecallTool;
}

export interface WorkingSetSurfaceContract {
  state: "working_set";
  workingSetId: number;
}

export type SurfaceLaunchContract =
  | CaptureSurfaceContract
  | DoSurfaceContract
  | RecallSurfaceContract
  | WorkingSetSurfaceContract;

export interface FrontendSurfaceRegistry {
  activate(contract: SurfaceLaunchContract): Promise<void>;
  refresh(contract: SurfaceLaunchContract): Promise<void>;
}

interface ShellSurfaceLocation {
  state: ShellState;
  recallTool: RecallTool;
  workingSetId?: number | null;
}

function surfaceKeyFromContract(contract: SurfaceLaunchContract): "inbox" | "next" | RecallTool | null {
  if (contract.state === "capture") {
    return "inbox";
  }
  if (contract.state === "do") {
    return "next";
  }
  if (contract.state === "recall") {
    return contract.recallTool;
  }
  return null;
}

export function contractFromLocation(location: ShellSurfaceLocation): SurfaceLaunchContract | null {
  if (location.state === "capture") {
    return { state: "capture" };
  }
  if (location.state === "do") {
    return { state: "do" };
  }
  if (location.state === "recall") {
    return {
      state: "recall",
      recallTool: location.recallTool,
    };
  }
  if (location.state === "working_set" && location.workingSetId != null) {
    return {
      state: "working_set",
      workingSetId: location.workingSetId,
    };
  }
  return null;
}

export function bootstrapFrontendSurfaceRegistry(): FrontendSurfaceRegistry {
  bootstrapSurfaceRuntimeImpl();

  return {
    async activate(contract: SurfaceLaunchContract): Promise<void> {
      const key = surfaceKeyFromContract(contract);
      if (!key) {
        return;
      }
      await activateSurfaceRuntime(key);
    },
    async refresh(contract: SurfaceLaunchContract): Promise<void> {
      const key = surfaceKeyFromContract(contract);
      if (!key) {
        return;
      }
      await refreshSurfaceRuntime(key);
    },
  };
}
