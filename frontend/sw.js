/* FitCore service worker — installable PWA with an offline fallback.
 *
 * Caching policy:
 *   - Static shell (CSS/JS/icons/manifest/offline page): precached on install,
 *     then stale-while-revalidate so updates land in the background.
 *   - Navigations: network-first; if offline, fall back to a cached copy of
 *     the landing page, otherwise offline.html. HTML is NOT written to cache
 *     here, so pages never go stale while online.
 *   - /api/*: strict network-only and NEVER cached — responses are
 *     JWT-protected and user-specific (and include downloads/receipts).
 *   - Cross-origin assets (Bootstrap CDN, Google Fonts): stale-while-revalidate
 *     so the shell renders offline after the first visit.
 *
 * Bump VERSION below to force a full cache refresh for all clients.
 */
'use strict';

const VERSION = 'v1';
const CACHE_PREFIX = 'fitcore-';
const STATIC_CACHE = `${CACHE_PREFIX}static-${VERSION}`;
const RUNTIME_CACHE = `${CACHE_PREFIX}runtime-${VERSION}`;
const CURRENT_CACHES = [STATIC_CACHE, RUNTIME_CACHE];

const PRECACHE_URLS = [
  './',
  'offline.html',
  'logo.png',
  'manifest.webmanifest',
  'css/theme.css',
  'css/landing.css',
  'css/login.css',
  'js/api.js',
  'js/validate.js',
  'js/bottom-tabs.js',
  'js/pwa.js',
];

/* ── Install: seed the offline shell ─────────────────────────────────── */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      // Individually so one missing file never fails the whole install.
      Promise.all(
        PRECACHE_URLS.map((url) =>
          cache.add(new Request(url, { cache: 'reload' })).catch((err) => {
            console.warn('[sw] precache skipped:', url, err);
          })
        )
      )
    )
  );
  self.skipWaiting(); // activate new version without waiting for old tabs
});

/* ── Activate: drop caches from previous versions ────────────────────── */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && !CURRENT_CACHES.includes(key))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

/* ── Fetch strategies ────────────────────────────────────────────────── */

function isCacheable(response) {
  // Opaque (no-cors CDN) responses are cacheable but unreadable; skip 206.
  return !!response && (response.ok || response.type === 'opaque') && response.status !== 206;
}

async function networkFirstNavigation(request) {
  try {
    return await fetch(request);
  } catch (err) {
    // Offline: cached landing page if we have it, else the offline page.
    const cached = await caches.match(request);
    if (cached) return cached;
    const landing = await caches.match('./');
    if (landing && new URL(request.url).pathname === '/') return landing;
    const offline = await caches.match('offline.html');
    if (offline) return offline;
    return Response.error();
  }
}

async function staleWhileRevalidate(event, request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const networkUpdate = fetch(request)
    .then((response) => {
      if (isCacheable(response)) cache.put(request, response.clone());
      return response;
    })
    .catch(() => undefined);

  if (cached) {
    // Serve the cached copy now, refresh it in the background.
    event.waitUntil(networkUpdate);
    return cached;
  }
  const response = await networkUpdate;
  return response || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return; // POST/PUT/PATCH/DELETE always hit network

  const url = new URL(request.url);

  // 1. API: network-only, never cached; friendly JSON when offline.
  if (url.pathname.startsWith('/api')) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(JSON.stringify({ detail: 'You are offline.' }), {
          status: 503,
          statusText: 'Offline',
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );
    return;
  }

  // 2. Page navigations: network-first with offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  // 3. Same-origin static assets: stale-while-revalidate.
  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(event, request, STATIC_CACHE));
    return;
  }

  // 4. Third-party assets (Bootstrap, fonts, icons): cache so the shell
  //    renders offline after the first visit.
  event.respondWith(staleWhileRevalidate(event, request, RUNTIME_CACHE));
});
