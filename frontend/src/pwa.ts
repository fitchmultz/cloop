/**
 * pwa.ts - TypeScript-owned browser runtime bootstrap.
 *
 * Purpose:
 *   Own browser-global PWA runtime behavior outside the shell and work-surface
 *   bootstrap flow.
 *
 * Responsibilities:
 *   - Register the service worker from the Vite-built root asset path.
 *   - Keep the offline banner synchronized with browser connectivity.
 *   - Best-effort register background sync when connectivity returns.
 *
 * Scope:
 *   - Browser-global runtime only.
 *
 * Usage:
 *   - Imported by frontend/src/main.ts during frontend startup.
 *
 * Invariants/Assumptions:
 *   - The built service worker is served from /sw.js.
 *   - The offline banner is rendered in frontend/index.html with id=offline-banner.
 *   - Failures here must not block the rest of the UI from loading.
 */

const OFFLINE_BANNER_ID = "offline-banner";
const CAPTURE_SYNC_TAG = "sync-captures";

interface SyncCapableServiceWorkerRegistration extends ServiceWorkerRegistration {
  sync?: {
    register(tag: string): Promise<void>;
  };
}

let initialized = false;

function getOfflineBanner(): HTMLElement | null {
  return document.getElementById(OFFLINE_BANNER_ID);
}

function setOfflineBannerVisible(visible: boolean): void {
  getOfflineBanner()?.classList.toggle("visible", visible);
}

async function registerCaptureSync(): Promise<void> {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  try {
    const registration =
      (await navigator.serviceWorker.ready) as SyncCapableServiceWorkerRegistration;
    await registration.sync?.register(CAPTURE_SYNC_TAG);
  } catch {
    // Background sync is best-effort only.
  }
}

async function registerServiceWorker(): Promise<void> {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch (error) {
    console.error("Service worker registration failed:", error);
  }
}

function handleOnline(): void {
  setOfflineBannerVisible(false);
  void registerCaptureSync();
}

function handleOffline(): void {
  setOfflineBannerVisible(true);
}

function initializePwaRuntime(): void {
  if (initialized) {
    return;
  }
  initialized = true;

  setOfflineBannerVisible(!navigator.onLine);
  window.addEventListener("online", handleOnline);
  window.addEventListener("offline", handleOffline);

  void registerServiceWorker().then(() => {
    if (navigator.onLine) {
      void registerCaptureSync();
    }
  });
}

export function bootstrapPwaRuntime(): void {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializePwaRuntime, { once: true });
    return;
  }

  initializePwaRuntime();
}
