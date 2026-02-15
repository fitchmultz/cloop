/**
 * Cloop Service Worker - Offline-first PWA support
 *
 * Purpose:
 *     Enable offline access and background sync for loop capture.
 *
 * Responsibilities:
 *     - Cache static assets for offline access
 *     - Queue loop captures when offline via IndexedDB
 *     - Background sync queued captures when online
 *     - Handle push notifications for due loops
 *
 * Non-scope:
 *     - API business logic (handled by server)
 *     - UI rendering (handled by main thread)
 *
 * Invariants:
 *     - Cache version must be incremented when assets change
 *     - Capture queue is persisted in IndexedDB until sync succeeds
 */
const CACHE_VERSION = "cloop-v1";
const STATIC_ASSETS = [
  "/",
  "/static/manifest.json",
  // Note: index.html is served at /, CSS/JS is inline in the single HTML file
];

const CAPTURE_QUEUE_DB = "cloop-offline";
const CAPTURE_QUEUE_STORE = "capture-queue";

// Install: cache static assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clear old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: cache-first for static, network-first for API
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API requests: try network, fall back to queue
  if (url.pathname.startsWith("/loops/")) {
    event.respondWith(networkFirstWithQueue(event.request));
    return;
  }

  // Static assets: cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});

// Background Sync: flush queued captures
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-captures") {
    event.waitUntil(flushCaptureQueue());
  }
});

// Push notifications for due loops
self.addEventListener("push", (event) => {
  const data = event.data?.json() ?? {};
  event.waitUntil(
    self.registration.showNotification(data.title || "Loop Due", {
      body: data.body || "You have a loop due soon",
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});

// Helper: Network-first with offline queueing for captures
async function networkFirstWithQueue(request) {
  try {
    const response = await fetch(request);
    return response;
  } catch (error) {
    // Only queue POST /loops/capture requests
    if (request.method === "POST" && new URL(request.url).pathname === "/loops/capture") {
      const clonedRequest = request.clone();
      const body = await clonedRequest.json();
      await queueCapture(body);
      return new Response(JSON.stringify({ queued: true, offline: true }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

// IndexedDB helpers for capture queue
async function queueCapture(payload) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CAPTURE_QUEUE_STORE, "readwrite");
    const store = tx.objectStore(CAPTURE_QUEUE_STORE);
    const request = store.add({
      payload,
      queuedAt: new Date().toISOString(),
    });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function openQueueDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(CAPTURE_QUEUE_DB, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(CAPTURE_QUEUE_STORE, { autoIncrement: true });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function flushCaptureQueue() {
  const db = await openQueueDB();
  const tx = db.transaction(CAPTURE_QUEUE_STORE, "readwrite");
  const store = tx.objectStore(CAPTURE_QUEUE_STORE);
  const getAllKeys = store.getAllKeys();
  const getAll = store.getAll();

  return new Promise((resolve, reject) => {
    getAll.onsuccess = async () => {
      const keys = getAllKeys.result;
      const items = getAll.result;
      for (let i = 0; i < items.length; i++) {
        try {
          const response = await fetch("/loops/capture", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(items[i].payload),
          });
          if (response.ok) {
            store.delete(keys[i]);
          }
        } catch (e) {
          // Keep in queue if sync fails
          console.error("Sync failed for item:", e);
        }
      }
      resolve();
    };
    getAll.onerror = () => reject(getAll.error);
  });
}
