/**
 * push.js - Web Push subscription management
 *
 * Purpose:
 *   Subscribe the browser to push notifications using VAPID.
 *
 * Responsibilities:
 *   - Convert VAPID key to Uint8Array
 *   - Subscribe to push manager
 *   - Send subscription to server
 *
 * Non-scope:
 *   - Toast notifications (see notifications.js)
 *   - SSE handling (see sse.js)
 */

/**
 * Convert a base64-encoded VAPID key to Uint8Array.
 * @param {string} base64String - Base64-encoded public key
 * @returns {Uint8Array}
 */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
  return out;
}

/**
 * Ensure the browser is subscribed to push notifications.
 * Only subscribes if:
 * - Service worker is supported
 * - PushManager is available
 * - Notification permission is granted
 * - VAPID public key is available from server
 */
export async function ensurePushSubscribed() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;

  const reg = await navigator.serviceWorker.ready;

  const keyRes = await fetch('/push/vapid_public_key');
  if (!keyRes.ok) return;

  const { public_key } = await keyRes.json();
  if (!public_key) return;

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    });
  }

  await fetch('/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub.toJSON()),
  });
}
