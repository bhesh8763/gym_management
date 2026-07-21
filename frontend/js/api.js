const API_BASE = 'http://127.0.0.1:8000/api';

function getAccessToken() {
  return localStorage.getItem('access_token');
}

function saveTokens(access, refresh) {
  localStorage.setItem('access_token', access);
  localStorage.setItem('refresh_token', refresh);
}

function clearTokens() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
}

// Tracks a refresh that's currently in progress, so multiple simultaneous
// 401s (from several API calls firing at once) share ONE refresh attempt
// instead of each independently burning the one-time-use refresh token.
let refreshPromise = null;

async function performRefresh() {
  const refresh = localStorage.getItem('refresh_token');
  if (!refresh) return null;

  try {
    const res = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });

    if (res.ok) {
      const data = await res.json();
      localStorage.setItem('access_token', data.access);
      if (data.refresh) {
        localStorage.setItem('refresh_token', data.refresh);
      }
      return data.access;
    }

    // Our refresh token was rejected — but maybe a DIFFERENT tab already
    // refreshed successfully in the meantime and wrote a newer one.
    // Check localStorage one more time before giving up.
    const currentRefresh = localStorage.getItem('refresh_token');
    if (currentRefresh && currentRefresh !== refresh) {
      const retryRes = await fetch(`${API_BASE}/auth/token/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: currentRefresh }),
      });
      if (retryRes.ok) {
        const retryData = await retryRes.json();
        localStorage.setItem('access_token', retryData.access);
        if (retryData.refresh) {
          localStorage.setItem('refresh_token', retryData.refresh);
        }
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
      const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
      res = await fetch(`${API_BASE}${path}`, { ...options, headers: retryHeaders });
    } else {
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