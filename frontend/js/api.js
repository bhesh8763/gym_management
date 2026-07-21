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

// Access tokens expire after 60 minutes (see SIMPLE_JWT in settings.py), but the
// refresh token is valid for 7 days. Without this, anyone using the dashboard for
// over an hour gets silently kicked back to the login page even though they have
// a valid refresh token sitting unused in localStorage.
let refreshInFlight = null;

async function refreshAccessToken() {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  // Avoid firing multiple simultaneous refresh calls if several requests
  // 401 at the same time (e.g. Promise.all on the dashboard).
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        saveTokens(data.access, data.refresh); // refresh rotates (ROTATE_REFRESH_TOKENS=True)
        return true;
      })
      .catch(() => false)
      .finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
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
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // Retry the original request once with the new access token.
      headers['Authorization'] = `Bearer ${getAccessToken()}`;
      res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    }
    if (res.status === 401) {
      // Refresh token is also invalid/expired — this is a real logout.
      clearTokens();
      window.location.href = 'index.html';
      return null;
    }
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
