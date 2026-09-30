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
