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

async function apiRequest(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearTokens();
    window.location.href = 'index.html';
    return null;
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