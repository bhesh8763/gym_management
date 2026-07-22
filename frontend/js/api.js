const API_BASE = 'http://127.0.0.1:8000/api';

function getAccessToken() {
  return localStorage.getItem('access_token');
}

function getRefreshToken() {
  return localStorage.getItem('refresh_token');
}

function saveTokens(access, refresh) {
  localStorage.setItem('access_token', access);
  if (refresh) localStorage.setItem('refresh_token', refresh);
}

function clearTokens() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user_id');
  localStorage.removeItem('user_role');
  localStorage.removeItem('user_name');
}

// Tracks a refresh that's currently in progress, so multiple simultaneous
// 401s (from several API calls firing at once) share ONE refresh attempt
// instead of each independently burning the one-time-use refresh token.
let refreshPromise = null;

async function performRefresh() {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  try {
    const res = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });

    if (res.ok) {
      const data = await res.json();
      saveTokens(data.access, data.refresh);
      return data.access;
    }

    // Our refresh token was rejected — but maybe a DIFFERENT tab already
    // refreshed successfully in the meantime and wrote a newer one.
    // Check localStorage one more time before giving up.
    const currentRefresh = getRefreshToken();
    if (currentRefresh && currentRefresh !== refresh) {
      const retryRes = await fetch(`${API_BASE}/auth/token/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: currentRefresh }),
      });
      if (retryRes.ok) {
        const retryData = await retryRes.json();
        saveTokens(retryData.access, retryData.refresh);
        return retryData.access;
      }
    }

    return null;
  } catch (e) {
    return null;
  }
}

async function refreshAccessToken() {
  // If a refresh is already running (from this tab), wait for that
  // one instead of starting a second, competing refresh.
  if (refreshPromise) {
    return refreshPromise;
  }
  refreshPromise = performRefresh().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function apiRequest(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      // Retry the original request once with the new access token.
      const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
      res = await fetch(`${API_BASE}${path}`, { ...options, headers: retryHeaders });
    }
    if (res.status === 401) {
      // Refresh failed, or the retry itself still came back unauthorized —
      // either way, this is a real logout.
      clearTokens();
      window.location.href = 'index.html';
      return null;
    }
  }

  if (res.status >= 500) {
    console.error(`Server error (${res.status}) on ${path}`);
  }

  return res;
}

function formatApiError(err) {
  if (!err || typeof err !== 'object') return 'Something went wrong. Please try again.';
  const lines = [];
  for (const [field, messages] of Object.entries(err)) {
    const msgList = Array.isArray(messages) ? messages : [messages];
    const label = field === 'non_field_errors' ? '' : `${field}: `;
    msgList.forEach(m => lines.push(`${label}${m}`));
  }
  return lines.join('\n') || 'Something went wrong. Please try again.';
}

// ── Role-based sidebar ──────────────────────────────────────────────────────
// Every page shares the same sidebar markup. Links that should only be visible
// to certain roles carry a data-roles="OWNER,STAFF" attribute (see dashboard.html
// etc.) — links with no data-roles attribute are visible to everyone. This runs
// automatically on every page that loads api.js, so no page needs to call it itself.
function applySidebarRoleVisibility() {
  const role = localStorage.getItem('user_role');
  if (!role) return;

  document.querySelectorAll('.sidebar a[data-roles]').forEach(link => {
    const allowedRoles = link.dataset.roles.split(',');
    link.style.display = allowedRoles.includes(role) ? '' : 'none';
  });

  document.querySelectorAll('.nav-section-label').forEach(label => {
    let sibling = label.nextElementSibling;
    let anyVisible = false;
    while (sibling && sibling.tagName === 'A') {
      if (sibling.style.display !== 'none') anyVisible = true;
      sibling = sibling.nextElementSibling;
    }
    label.style.display = anyVisible ? '' : 'none';
  });
}

applySidebarRoleVisibility();

// ── Page-level role guard ───────────────────────────────────────────────────
// Restricted pages carry <body data-allowed-roles="OWNER,STAFF">. This stops
// someone from bypassing the hidden sidebar link by typing the URL directly —
// without this, the page shell would still render even though its data calls
// would fail with 403 from the backend's own RBAC.
function enforcePageRoleAccess() {
  const allowedRoles = document.body.dataset.allowedRoles;
  if (!allowedRoles) return;

  const role = localStorage.getItem('user_role');
  if (!role || !allowedRoles.split(',').includes(role)) {
    window.location.href = 'dashboard.html';
  }
}

enforcePageRoleAccess();
