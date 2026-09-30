/* FitCore PWA bootstrap — registers the service worker.
 * Injected (deferred) into the <head> of every page by
 * scripts/inject_pwa_tags.py, so it also covers pages that never load
 * js/api.js (index.html, member-card.html).
 */
(function () {
  'use strict';

  if (!('serviceWorker' in navigator)) return; // unsupported browser

  window.addEventListener('load', function () {
    // Relative path: resolves against the page URL, so it works on the
    // Live-Server dev origin (:5500) and the production root alike.
    navigator.serviceWorker
      .register('sw.js')
      .then(function (registration) {
        // A new version installs in the background; with skipWaiting() in
        // sw.js it takes over on the next navigation automatically.
        registration.addEventListener('updatefound', function () {
          var worker = registration.installing;
          if (!worker) return;
          worker.addEventListener('statechange', function () {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) {
              console.info('[pwa] FitCore update ready — reload to apply.');
            }
          });
        });
      })
      .catch(function (err) {
        console.warn('[pwa] service worker registration failed:', err);
      });
  });
})();

/* ── Web Push opt-in ─────────────────────────────────────────────────── *
 * window.FitCorePush — three entry points used by the app:
 *   askAfterLogin() — call from a login/signup click handler so the browser's
 *                     permission prompt appears inside the user gesture (iOS
 *                     requires this). Asks at most once ever per browser.
 *   sync()          — silently re-registers an already-granted subscription
 *                     (runs on every authenticated page load; repairs
 *                     subscriptions after the browser rotates endpoints).
 *   logout()        — best-effort server + local unsubscribe on logout.
 * All methods swallow their own errors: push must never break login,
 * navigation, or logout.
 */
window.FitCorePush = (function () {
  'use strict';

  const FLAG_ASKED = 'fitcore_push_asked';

  function supported() {
    return 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window;
  }

  // api.js defines API_BASE globally, but this file also loads on pages that
  // may not have it (or may run before it) — fall back to the same detection.
  function apiBase() {
    try {
      if (typeof API_BASE === 'string' && API_BASE) return API_BASE;
    } catch (e) { /* not defined (yet) */ }
    if (window.FITCORE_API_BASE) return window.FITCORE_API_BASE;
    const host = location.hostname;
    const dev = host === 'localhost' || host === '127.0.0.1' || /^\d{1,3}(\.\d{1,3}){3}$/.test(host);
    return dev && location.port && location.port !== '8000' ? 'http://' + host + ':8000/api' : '/api';
  }

  // Mirror api.js request headers (token captured at call time — important
  // for logout(), which must read it before clearTokens() runs).
  function authHeaders(json) {
    const headers = {};
    const token = localStorage.getItem('access_token');
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const gymId = localStorage.getItem('gym_id');
    if (gymId) headers['X-Gym-ID'] = gymId;
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    return Uint8Array.from(raw.split('').map(function (c) { return c.charCodeAt(0); }));
  }

  // Fetch the VAPID public key, make sure a PushSubscription exists, and
  // register it with the API for the logged-in user.
  async function ensureSubscribed() {
    const keyRes = await fetch(apiBase() + '/notifications/push/public-key/', {
      headers: authHeaders(false),
    });
    if (!keyRes.ok) return false;
    const payload = await keyRes.json();
    if (!payload.key || !payload.enabled) return false; // server has no VAPID keys yet

    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(payload.key),
      });
    }

    const keys = subscription.toJSON().keys || {};
    const res = await fetch(apiBase() + '/notifications/push/subscribe/', {
      method: 'POST',
      headers: authHeaders(true),
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        p256dh: keys.p256dh,
        auth: keys.auth,
        user_agent: navigator.userAgent.slice(0, 300),
      }),
    });
    return res.ok;
  }

  return {
    askAfterLogin: async function () {
      if (!supported()) return;
      try {
        if (Notification.permission === 'granted') {
          await ensureSubscribed();
          return;
        }
        if (Notification.permission === 'denied') return;
        if (localStorage.getItem(FLAG_ASKED) === '1') return; // already declined once — don't nag
        const permission = await Notification.requestPermission(); // inside the login click gesture
        localStorage.setItem(FLAG_ASKED, '1');
        if (permission === 'granted') await ensureSubscribed();
      } catch (err) {
        console.warn('[pwa] push opt-in failed:', err);
      }
    },

    sync: async function () {
      if (!supported() || Notification.permission !== 'granted') return;
      try {
        await ensureSubscribed();
      } catch (err) {
        console.warn('[pwa] push sync failed:', err);
      }
    },

    logout: async function () {
      if (!supported()) return;
      // Capture auth headers NOW — api.js logout() clears tokens right after
      // calling this, and it does not await us.
      const headers = authHeaders(true);
      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (!subscription) return;
        await fetch(apiBase() + '/notifications/push/unsubscribe/', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        }).catch(function () { /* offline — server will reassign on next login */ });
        await subscription.unsubscribe();
      } catch (err) {
        console.warn('[pwa] push logout cleanup failed:', err);
      }
    },
  };
})();
