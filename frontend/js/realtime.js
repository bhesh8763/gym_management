/**
 * FitCore realtime messaging — WebSocket client with polling fallback.
 *
 * Connects to `<api-origin>/ws/messages/?token=<JWT>` and listens for
 * `message.new` events pushed by the Django Channels consumer
 * (apps/notifications/consumers.py). On arrival it reloads the conversation
 * list via `window.loadMessages()` — defined by messages.html,
 * my-messages.html and trainer-messages.html — and refreshes the bell badge
 * through `window.loadTopbarNotifications()`.
 *
 * Sending stays plain HTTPS (POST); only DELIVERY back to the recipient is
 * live. The three messaging pages include this file explicitly; api.js also
 * lazy-loads it on every other signed-in page so the badge stays live there.
 * The singleton guard below makes the double include harmless.
 *
 * Behaviour:
 *  - connects only when a signed-in access token exists
 *  - ping every 30s: counts as inbound traffic so the Render free instance
 *    stays awake, and detects dead sockets (no server traffic for 90s ->
 *    close + reconnect)
 *  - capped exponential backoff (1s -> 15s) with jitter; every attempt
 *    re-reads the token from storage (api.js may have refreshed it meanwhile)
 *  - while the socket is down and the tab is visible, polls messages + badge
 *    every 8s so updates still arrive (slower, but never silent)
 *  - on tab focus, reconnects immediately and catches up
 */
(function () {
  'use strict';

  if (window.FitCoreRealtime) return; // singleton guard (page tag + lazy loader)

  var PING_MS = 30000;         // keepalive ping cadence
  var STALE_MS = 90000;        // no server traffic for this long -> reconnect
  var BACKOFF_MIN_MS = 1000;
  var BACKOFF_MAX_MS = 15000;
  var POLL_MS = 8000;          // fallback cadence while disconnected
  var DEBOUNCE_MS = 300;       // a burst of messages collapses to one reload

  var socket = null;
  var backoff = BACKOFF_MIN_MS;
  var reconnectTimer = null;
  var keepaliveTimer = null;
  var pollTimer = null;
  var refreshTimer = null;
  var lastTrafficAt = 0;

  function wsUrl() {
    // API_BASE is '/api' (same-origin, production) or
    // 'http://host:8000/api' (dev: Live Server on another port).
    var base = /^https?:\/\//i.test(API_BASE)
      ? API_BASE
      : location.origin + API_BASE;
    return base.replace(/^http/i, 'ws').replace(/\/api\/?$/, '') + '/ws/messages/';
  }

  function isConnected() {
    return !!socket && socket.readyState === WebSocket.OPEN;
  }

  function refreshUi() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(function () {
      refreshTimer = null;
      if (typeof window.loadMessages === 'function') window.loadMessages();
      if (typeof window.loadTopbarNotifications === 'function') {
        window.loadTopbarNotifications();
      }
    }, DEBOUNCE_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    if (pollTimer || document.visibilityState !== 'visible') return;
    pollTimer = setInterval(function () {
      if (isConnected()) {
        stopPolling();
        return;
      }
      refreshUi();
    }, POLL_MS);
  }

  function stopKeepalive() {
    if (keepaliveTimer) {
      clearInterval(keepaliveTimer);
      keepaliveTimer = null;
    }
  }

  function armKeepalive() {
    stopKeepalive();
    keepaliveTimer = setInterval(function () {
      if (!isConnected()) return;
      if (Date.now() - lastTrafficAt > STALE_MS) {
        socket.close(); // dead pipe: onclose schedules the reconnect
        return;
      }
      socket.send(JSON.stringify({ type: 'ping' }));
    }, PING_MS);
  }

  function scheduleReconnect() {
    startPolling(); // degraded-but-live updates while we wait
    if (reconnectTimer) return;
    var delay = backoff + Math.floor(Math.random() * 400);
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    var token = typeof getAccessToken === 'function' ? getAccessToken() : null;
    if (!token) return; // signed out (or public page) -> stay offline
    if (
      socket &&
      (socket.readyState === WebSocket.CONNECTING ||
        socket.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    try {
      socket = new WebSocket(wsUrl() + '?token=' + encodeURIComponent(token));
    } catch (e) {
      scheduleReconnect();
      return;
    }

    socket.onmessage = function (ev) {
      var data;
      try {
        data = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      lastTrafficAt = Date.now();
      if (!data || typeof data.type !== 'string') return;
      if (data.type === 'connected') {
        backoff = BACKOFF_MIN_MS;
        stopPolling();
        armKeepalive();
        return;
      }
      if (data.type === 'message.new') refreshUi(); // pongs only refresh traffic
    };

    socket.onclose = function () {
      socket = null;
      stopKeepalive();
      scheduleReconnect();
    };

    socket.onerror = function () {
      // Browsers always follow this with onclose, which handles reconnect.
    };
  }

  // ── Visibility: catch up on focus, stop background polls when hidden ─────
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      if (isConnected()) {
        refreshUi(); // catch up on anything missed while the tab slept
      } else if (!reconnectTimer) {
        connect();
      }
    } else {
      stopPolling();
    }
  });

  // ── Test/debug surface (used by the browser smoke test) ──────────────────
  window.FitCoreRealtime = {
    connect: connect,
    isConnected: isConnected,
    status: function () {
      return socket ? socket.readyState : WebSocket.CLOSED;
    },
    lastTrafficAt: function () {
      return lastTrafficAt;
    },
    refreshUi: refreshUi,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connect);
  } else {
    connect();
  }
})();
