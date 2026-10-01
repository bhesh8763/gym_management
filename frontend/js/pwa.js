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

/* ── Install prompt (Add to Home Screen / Install app) ──────────────── *
 * window.FitCorePWA — one entry point for every platform:
 *   Android/desktop Chrome: captures beforeinstallprompt and runs the
 *     native install dialog via install().
 *   iOS Safari (no such event exists): shows step-by-step
 *     "Share → Add to Home Screen" instructions instead.
 *
 * The buttons are injected by this file (no per-page HTML needed):
 *   - a floating "Install app" pill on EVERY page (public and app pages) —
 *     the dedicated install entry point, always available while the app is
 *     not installed, so it can be (re-)installed at any time, including
 *     after the user uninstalled it
 *   - an "Install app" item in the profile dropdown on app pages
 * The pill's × hides it for the current session only (sessionStorage), so
 * the option always comes back on the next visit — it can never get lost
 * permanently the way the old localStorage dismissal could.
 */
window.FitCorePWA = (function () {
  'use strict';

  let deferredPrompt = null;
  let installed = false;
  let installing = false;
  const FLAG_DISMISSED = 'fitcore_install_dismissed';
  // Older builds persisted the dismissal in localStorage forever, so a single
  // × made the install option disappear permanently — after uninstalling the
  // app the site could never offer it again. Drop the stale flag; dismissal
  // is now session-scoped (see ensurePill).
  try { localStorage.removeItem(FLAG_DISMISSED); } catch (e) { /* storage blocked */ }

  window.addEventListener('beforeinstallprompt', (event) => {
    // Chrome/Edge fire this when the PWA is installable. Suppress the default
    // mini-infobar — we offer our own button instead.
    event.preventDefault();
    deferredPrompt = event;
    document.dispatchEvent(new Event('fitcore:installable'));
  });

  window.addEventListener('appinstalled', () => {
    installed = true;
    deferredPrompt = null;
    removePill();
    removeMenuItem();
    document.dispatchEvent(new Event('fitcore:installed'));
  });

  // Keep the install UI in sync with the real display mode: when the app is
  // uninstalled (the browser tab's display-mode flips back to "browser") the
  // entry points must reappear so the app can be installed again.
  const standaloneQuery = window.matchMedia('(display-mode: standalone)');
  const onDisplayModeChange = () => {
    installed = standaloneQuery.matches || window.navigator.standalone === true;
    if (installed) {
      removePill();
      removeMenuItem();
    } else {
      inject();
    }
  };
  if (standaloneQuery.addEventListener) standaloneQuery.addEventListener('change', onDisplayModeChange);
  else if (standaloneQuery.addListener) standaloneQuery.addListener(onDisplayModeChange); // older Safari

  function platform() {
    const standalone =
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true; // iOS Safari
    if (standalone) return 'installed';
    const ua = navigator.userAgent;
    // iPadOS 13+ reports a desktop Mac UA but is still touch-only Safari.
    const ios = /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (ios) return 'ios';
    if (/android/i.test(ua)) return 'android';
    return 'desktop';
  }

  // ── Instructions modal (self-contained — works on every page) ───────
  const STEPS = {
    ios: {
      title: 'Add FitCore to your Home Screen',
      icon: '<i class="bi bi-phone" style="color:#e63946;"></i>',
      steps: [
        'Tap the <b>Share</b> button <b>⬆︎</b> — the square with an arrow, at the bottom of the Safari screen',
        'Scroll down and tap <b>Add to Home Screen</b>',
        'Tap <b>Add</b> in the top-right corner',
      ],
      note: 'FitCore now opens from your home screen — full screen, offline fallback, and push notifications (iOS 16.4+).',
    },
    android: {
      title: 'Install FitCore on your device',
      icon: '<i class="bi bi-download" style="color:#e63946;"></i>',
      steps: [
        'Tap the <b>⋮</b> menu in the top-right corner of Chrome',
        'Tap <b>Install app</b> (or <b>Add to Home screen</b>)',
        'Tap <b>Install</b> to confirm',
      ],
      note: 'FitCore installs like a regular app — its own icon, full screen, and push notifications.',
    },
    desktop: {
      title: 'Install FitCore on your computer',
      icon: '<i class="bi bi-display" style="color:#e63946;"></i>',
      steps: [
        'Click the <b>install icon</b> at the right end of the address bar, <b>or</b>',
        'Open the <b>⋮</b> menu → <b>Install FitCore</b>',
      ],
      note: 'FitCore opens in its own window and launches from your desktop shortcut.',
    },
  };

  function showInstructions(kind) {
    const info = STEPS[kind] || STEPS.desktop;
    let overlay = document.getElementById('fitcoreInstallModal');
    if (overlay) { overlay.style.display = 'flex'; return; }
    overlay = document.createElement('div');
    overlay.id = 'fitcoreInstallModal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', info.title);
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:3000;background:rgba(0,0,0,.65);' +
      'display:flex;align-items:center;justify-content:center;padding:20px;' +
      'font-family:inherit;';
    const card = document.createElement('div');
    card.style.cssText =
      'background:#17181d;color:#e8e8ee;border:1px solid #2c2d36;border-radius:14px;' +
      'max-width:420px;width:100%;padding:22px 22px 18px;box-shadow:0 18px 50px rgba(0,0,0,.5);';
    const stepsHtml = info.steps
      .map((s, i) =>
        '<li style="margin:0 0 10px;padding-left:4px;display:flex;gap:10px;align-items:flex-start;">' +
        '<b style="color:#e63946;flex:none;">' + (i + 1) + '.</b><span>' + s + '</span></li>')
      .join('');
    card.innerHTML =
      '<div style="font-size:1.6rem;">' + info.icon + '</div>' +
      '<h3 style="margin:6px 0 12px;font-size:1.05rem;font-weight:600;">' + info.title + '</h3>' +
      '<ol style="list-style:none;margin:0 0 12px;padding:0;font-size:.93rem;line-height:1.45;">' +
      stepsHtml + '</ol>' +
      '<p style="margin:0 0 16px;font-size:.82rem;color:#9a9ba6;">' + info.note + '</p>' +
      '<button type="button" style="width:100%;padding:10px;border:0;border-radius:8px;' +
      'background:#e63946;color:#fff;font-weight:600;cursor:pointer;">Got it</button>';
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const close = () => { overlay.style.display = 'none'; };
    card.querySelector('button').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  }

  // ── Injected UI ─────────────────────────────────────────────────────
  function removePill() {
    const pill = document.getElementById('fitcoreInstallPill');
    if (pill) pill.remove();
  }

  function removeMenuItem() {
    const item = document.getElementById('fitcoreInstallMenuItem');
    if (item) item.remove();
  }

  function ensurePill() {
    if (!document.body) return; // event fired before the DOM was parsed
    if (installed || platform() === 'installed') return;
    // Dismissal lasts for the current session only — the pill returns on the
    // next visit, so the dedicated install option is always available again.
    if (sessionStorage.getItem(FLAG_DISMISSED) === '1') return;
    if (document.getElementById('fitcoreInstallPill')) return;
    // Shown on every page (public and app) and on every platform, WITHOUT
    // waiting for beforeinstallprompt: the browser may withhold that event
    // (engagement heuristics, right after an uninstall, …), and the install
    // option must work anyway. Clicking runs the native dialog when one was
    // captured, and falls back to the step-by-step instructions otherwise.

    const pill = document.createElement('button');
    pill.id = 'fitcoreInstallPill';
    pill.type = 'button';
    pill.style.cssText =
      'position:fixed;right:14px;bottom:16px;z-index:2500;display:flex;align-items:center;gap:8px;' +
      'padding:10px 14px;border:0;border-radius:999px;background:#e63946;color:#fff;' +
      'font-size:.9rem;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.35);cursor:pointer;';
    pill.innerHTML =
      '<i class="bi bi-download" aria-hidden="true"></i> Install app' +
      '<span aria-label="Dismiss" title="Dismiss" style="margin-left:2px;padding-left:8px;' +
      'border-left:1px solid rgba(255,255,255,.4);line-height:1;">×</span>';
    pill.addEventListener('click', (e) => {
      if (e.target.textContent.trim() === '×') {
        sessionStorage.setItem(FLAG_DISMISSED, '1'); // session-only — back next visit
        removePill();
        return;
      }
      window.FitCorePWA.install();
    });
    document.body.appendChild(pill);
  }

  function ensureMenuItem() {
    if (installed || platform() === 'installed') return;
    const panel = document.getElementById('profilePanel');
    if (!panel || document.getElementById('fitcoreInstallMenuItem')) return;
    const item = document.createElement('button');
    item.id = 'fitcoreInstallMenuItem';
    item.type = 'button';
    item.innerHTML = '<i class="bi bi-download"></i> Install app';
    item.addEventListener('click', () => window.FitCorePWA.install());
    const hr = panel.querySelector('hr');
    if (hr) panel.insertBefore(item, hr);
    else panel.appendChild(item);
  }

  // Both hooks: inject as soon as the DOM exists and whenever the
  // installability event arrives (Android/Chrome fires it late).
  function inject() { ensureMenuItem(); ensurePill(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject, { once: true });
  } else {
    inject();
  }
  document.addEventListener('fitcore:installable', inject);
  document.addEventListener('fitcore:installed', inject);

  // Resolves with the deferred prompt, waiting up to `timeout` ms for the
  // browser to report installability. Chrome fires beforeinstallprompt late
  // (engagement heuristics) and re-fires it after the user dismisses the
  // native dialog — an install click right after that must still install
  // directly instead of falling back to manual instructions.
  function waitForPrompt(timeout) {
    return new Promise((resolve) => {
      if (deferredPrompt) return resolve(deferredPrompt);
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        document.removeEventListener('fitcore:installable', onInstallable);
        resolve(value);
      };
      const onInstallable = () => finish(deferredPrompt);
      document.addEventListener('fitcore:installable', onInstallable);
      const timer = setTimeout(() => finish(null), timeout);
    });
  }

  return {
    platform: platform,
    isInstallable: () => !!deferredPrompt,

    // One call for every entry point (dropdown item, floating pill, …).
    install: async function () {
      const kind = platform();
      if (installed || kind === 'installed') return 'installed';
      if (installing) return 'pending'; // ignore double-clicks while a prompt is open
      installing = true;
      try {
        // iOS Safari (any browser on iOS) never fires an install event —
        // its "Share → Add to Home Screen" instructions are the only path.
        if (kind === 'ios') {
          showInstructions('ios');
          return 'instructions';
        }
        // Android/desktop: install directly through the native dialog.
        // Wait briefly if the browser hasn't reported installability yet.
        if (!deferredPrompt) await waitForPrompt(2000);
        if (deferredPrompt) {
          const promptEvent = deferredPrompt;
          deferredPrompt = null; // the event can only be used once
          try {
            promptEvent.prompt();
            const choice = await promptEvent.userChoice;
            return choice.outcome; // 'accepted' | 'dismissed'
          } catch (err) {
            console.warn('[pwa] install prompt failed:', err);
            return 'error';
          }
        }
        // Last resort only (browser without the install API, or Chrome
        // deciding the app isn't installable): manual step-by-step steps.
        showInstructions(kind);
        return 'instructions';
      } finally {
        installing = false;
      }
    },

    showInstructions: showInstructions,
  };
})();
