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
  localStorage.removeItem('user_picture');
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

// FIX #1: fetch() itself can throw (server down, DNS failure, CORS, offline,
// etc). Previously that exception propagated straight out of apiRequest and,
// since most callers don't wrap the await in try/catch, became an unhandled
// promise rejection — the UI would just hang on "Loading…" forever with only
// a console error. Now a network failure returns null like every other
// "couldn't complete this request" case, so existing `if (!res) return;`
// checks in callers handle it automatically.
async function apiRequest(path, options = {}) {
  // When sending FormData (file uploads), do NOT set Content-Type — the
  // browser sets it automatically with the correct multipart boundary.
  const isFormData = options.isFormData || options.body instanceof FormData;
  const headers = isFormData
    ? { ...(options.headers || {}) }
    : { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  // Strip the helper flag before passing options to fetch
  const { isFormData: _ignored, ...fetchOptions } = options;

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });
  } catch (e) {
    console.error(`Network error on ${path}:`, e);
    return null;
  }

  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      // Retry the original request once with the new access token.
      const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
      try {
        res = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers: retryHeaders });
      } catch (e) {
        console.error(`Network error retrying ${path}:`, e);
        return null;
      }
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

// ── Shared CSV export helper ────────────────────────────────────────────────
// Exports an HTML table to a downloadable CSV file. Skips any column whose
// <th> carries data-no-export (e.g. an "Actions" column with buttons).
function exportTableToCsv(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const headerCells = Array.from(table.querySelectorAll('thead th'));
  const skipIndexes = new Set();
  headerCells.forEach((th, i) => {
    if (th.hasAttribute('data-no-export')) skipIndexes.add(i);
  });

  const escapeCsv = (text) => {
    const str = (text ?? '').toString().replace(/\s+/g, ' ').trim();
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };

  const rows = [];
  rows.push(
    headerCells
      .filter((_, i) => !skipIndexes.has(i))
      .map(th => escapeCsv(th.textContent))
      .join(',')
  );

  table.querySelectorAll('tbody tr').forEach(tr => {
    const cells = Array.from(tr.children)
      .filter((_, i) => !skipIndexes.has(i))
      .map(td => escapeCsv(td.textContent));
    rows.push(cells.join(','));
  });

  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'export.csv';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
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

let sidebarCollapseObserver = null;

// Re-applies the collapsed/expanded state from localStorage to whichever
// #sidebar element currently exists, and (re)watches it for toggle clicks.
// Must be called after every SPA swap too, because #page-content's innerHTML
// swap replaces the sidebar element itself, so any previous observer is left
// watching a detached node and any previous 'collapsed' class is gone.
function syncSidebarCollapsedState() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  if (localStorage.getItem('sidebarCollapsed') === '1') {
    sidebar.classList.add('collapsed');
  }

  if (sidebarCollapseObserver) sidebarCollapseObserver.disconnect();
  sidebarCollapseObserver = new MutationObserver(() => {
    localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
  });
  sidebarCollapseObserver.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
}

syncSidebarCollapsedState();

// ── Lightweight SPA-style sidebar navigation ────────────────────────────────
(function initSpaRouter() {
  const sidebarEl = document.getElementById('sidebar');
  if (!sidebarEl) return;

  function getContentEl(root) {
    return root.getElementById('page-content');
  }

  function ensureScriptLoaded(rawSrc) {
    const absSrc = new URL(rawSrc, window.location.href).href;
    if (absSrc.endsWith('/js/api.js') || absSrc.endsWith('js/api.js')) return Promise.resolve();

    const already = Array.from(document.scripts).some(s => s.src === absSrc);
    if (already) return Promise.resolve();

    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = absSrc;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Failed to load ' + absSrc));
      document.head.appendChild(s);
    });
  }

 function runInlineScript(code) {
     const fnNamePattern = /^\s*(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(/gm;
     const names = new Set();
     let m;
     while ((m = fnNamePattern.exec(code))) names.add(m[1]);
     const exposures = Array.from(names).map(n => `window.${n} = ${n};`).join('\n');

     const wrapped = `(function(){\ntry {\n${code}\n${exposures}\n} catch (err) {\nconsole.error('SPA page script threw — code after the error point did not run:', err);\n}\n})();`;

     const s = document.createElement('script');
     s.textContent = wrapped;
     document.body.appendChild(s);
     document.body.removeChild(s);
   }
  // FIX #3: guards against overlapping navigations. If the user double-clicks
  // a sidebar link, or clicks a second link before the first fetch/parse
  // finishes, only the LAST navigation to start is allowed to actually apply
  // its result — earlier, now-stale navigations quietly no-op instead of
  // possibly winning a race and overwriting newer content.
  let navToken = 0;

  async function navigateTo(url, push) {
    const myToken = ++navToken;

    const contentEl = getContentEl(document);
    if (!contentEl) { window.location.href = url; return; }

    let doc;
    try {
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    } catch (err) {
      console.error('SPA navigation failed, falling back to a full page load:', err);
      if (myToken !== navToken) return; // a newer nav already took over
      window.location.href = url;
      return;
    }

    if (myToken !== navToken) return; // superseded while we were fetching

    const newContentEl = getContentEl(doc);
    if (!newContentEl) { window.location.href = url; return; }

    try {
      const rawSrcs = Array.from(doc.querySelectorAll('script[src]')).map(s => s.getAttribute('src'));
      for (const rawSrc of rawSrcs) await ensureScriptLoaded(rawSrc);
    } catch (err) {
      console.error('SPA navigation failed loading a required script, falling back:', err);
      if (myToken !== navToken) return;
      window.location.href = url;
      return;
    }

    if (myToken !== navToken) return; // superseded while scripts were loading

    contentEl.innerHTML = newContentEl.innerHTML;
    if (doc.title) document.title = doc.title;

    // SPA modal fix: carry over modals that live outside #page-content.
    // Remove any modals that sit outside #page-content (from previous page),
    // then inject the new page's outside modals into the live DOM.
    document.body.querySelectorAll('.modal.fade').forEach(el => {
      if (!contentEl.contains(el)) el.remove();
    });
    doc.querySelectorAll('.modal.fade').forEach(modal => {
      if (!newContentEl.contains(modal)) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = modal.outerHTML;
        const imported = wrapper.firstElementChild;
        document.body.appendChild(imported);
      }
    });

    const newRoles = doc.body.getAttribute('data-allowed-roles');
    if (newRoles) document.body.setAttribute('data-allowed-roles', newRoles);
    else document.body.removeAttribute('data-allowed-roles');

    document.querySelectorAll('.sidebar a.list-group-item').forEach(a => {
      a.classList.toggle('active', a.getAttribute('href') === url);
    });

    applySidebarRoleVisibility();
    enforcePageRoleAccess();
    syncSidebarCollapsedState();

    doc.querySelectorAll('script:not([src])').forEach(scriptEl => {
      runInlineScript(scriptEl.textContent);
    });

    if (push) history.pushState({ spaUrl: url }, '', url);
    window.scrollTo(0, 0);
  }

  // FIX #4: previously only `.sidebar a[href]` clicks were intercepted, so
  // in-page action links (e.g. members.html's "View Attendance" / "View
  // Payments" buttons, which live in the table, not the sidebar) always fell
  // through to a full page reload while every sidebar link did a SPA nav —
  // an inconsistent experience. Any link that should participate in the SPA
  // router now just needs class="spa-link" in addition to (or instead of)
  // living inside .sidebar.
  document.addEventListener('click', (e) => {
    const link = e.target.closest('.sidebar a[href], .spa-link[href]');
    if (!link) return;
    const href = link.getAttribute('href');
    if (!href || /^https?:\/\//.test(href) || href.startsWith('#')) return;

    e.preventDefault();
    const current = window.location.pathname.split('/').pop() || 'dashboard.html';
    if (href === current) return;

    navigateTo(href, true);
  });

  window.addEventListener('popstate', () => {
    const current = window.location.pathname.split('/').pop() || 'dashboard.html';
    navigateTo(current, false);
  });

  const currentFile = window.location.pathname.split('/').pop() || 'dashboard.html';
  history.replaceState({ spaUrl: currentFile }, '', window.location.href);
})();

// Blocks selection of any date before today on the given <input type="date">
// fields (by id). Used on "create new record" forms — assign membership,
// staff joined date, leave requests, locker assignment, equipment purchase,
// and maintenance logging — so past dates can't be picked.
function restrictPastDates(...ids) {
  const todayStr = new Date().toISOString().split('T')[0];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.setAttribute('min', todayStr);
  });
}

// Password show/hide toggle — works on every page (login, Add Member, Add
// Staff, etc.) since it's a single delegated listener on document, not tied
// to the sidebar router above.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.toggle-password');
  if (!btn) return;
  const input = document.getElementById(btn.getAttribute('data-target'));
  if (!input) return;
  const icon = btn.querySelector('i');
  const showing = input.type === 'password';
  input.type = showing ? 'text' : 'password';
  if (icon) {
    icon.classList.toggle('bi-eye', !showing);
    icon.classList.toggle('bi-eye-slash', showing);
  }
});

// FIX #2: this used to live as a per-page inline <script> in every page
// (members.html included), closing any open .dropdown-panel on an outside
// click. Because SPA navigation re-runs each page's inline script via
// runInlineScript on every visit, a document-level listener defined there
// got re-added every single time — visiting the same page 10 times left 10
// stacked, never-removed listeners on `document`. It's declared ONCE here
// instead, in api.js, which is only ever loaded (and executed) a single
// time per session, so it never duplicates. Pages no longer need their own
// copy of this — remove it from any page's inline script if present.
document.addEventListener('click', (e) => {
  if (!e.target.closest('.position-relative')) {
    document.querySelectorAll('.dropdown-panel').forEach(p => p.classList.remove('show'));
  }
});
// FIX #5: toggleSidebar, toggleDropdown, logout, and loadMembersIntoSelect were
// each copy-pasted into every page's own inline <script> (loadMembersIntoSelect
// alone was duplicated byte-for-byte across 5 pages). Under the SPA router above,
// every inline script gets re-run on each navigation via runInlineScript, so
// these were being redefined over and over for no benefit. Declared once here
// instead — api.js is loaded exactly once per session (ensureScriptLoaded
// explicitly skips it on SPA nav), so these stay defined for the whole session
// without needing to live in, or be removed from, each page's own script block.

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  if (window.innerWidth <= 768) {
    sidebar.classList.toggle('mobile-open');
  } else {
    sidebar.classList.toggle('collapsed');
  }
}

function toggleDropdown(id) {
  document.querySelectorAll('.dropdown-panel').forEach(p => {
    if (p.id !== id) p.classList.remove('show');
  });
  const panel = document.getElementById(id);
  if (panel) panel.classList.toggle('show');
}

function logout() {
  clearTokens();
  window.location.href = 'index.html';
}

// Populates the topbar profile chip (name, role, avatar initial) from
// localStorage. Called once on initial load; the SPA router doesn't touch
// the topbar on navigation (only #page-content swaps), so this doesn't need
// to re-run per page.
function initProfileHeader() {
  const userName = localStorage.getItem('user_name') || 'User';
  const userRole = localStorage.getItem('user_role') || '';
  const userPicture = localStorage.getItem('user_picture') || '';
  const nameEl = document.getElementById('profileName');
  const roleEl = document.getElementById('profileRole');
  const avatarEl = document.getElementById('profileAvatar');
  if (nameEl) nameEl.textContent = userName;
  if (roleEl) roleEl.textContent = userRole;
  if (avatarEl) {
    if (userPicture) {
      avatarEl.style.backgroundImage = `url(${userPicture})`;
      avatarEl.style.backgroundSize  = 'cover';
      avatarEl.style.backgroundPosition = 'center';
      avatarEl.style.backgroundRepeat = 'no-repeat';
      avatarEl.textContent           = '';
    } else {
      avatarEl.style.backgroundImage = '';
      avatarEl.style.backgroundSize  = '';
      avatarEl.style.backgroundPosition = '';
      avatarEl.style.backgroundRepeat = '';
      avatarEl.textContent           = userName.charAt(0).toUpperCase();
    }
  }
}
initProfileHeader();

// Populates a <select id="..."> with active members, using each member's
// user_id (not their MemberProfile id — see the members/workouts/diet/
// payments/lockers fix history) as the option value and full_name as the
// label. Was previously copy-pasted identically into attendance.html,
// diet.html, lockers.html, payments.html, and workouts.html.
async function loadMembersIntoSelect(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const res = await apiRequest('/members/?is_active=true');
  if (!res || !res.ok) {
    select.innerHTML = '<option value="">Could not load members</option>';
    return;
  }
  const data = await res.json();
  const members = data.results || data;
  select.innerHTML = members.length
    ? '<option value="">Select a member…</option>' +
      members.map(m => `<option value="${m.user_id}">${m.full_name}</option>`).join('')
    : '<option value="">No active members found</option>';
}


// ── Edit Profile Modal ──────────────────────────────────────────────────────
// Injects the modal HTML once into the page body (if not already present),
// then fetches the current user's profile from /api/auth/me/ and populates it.
// Declared here so it's available on every page without per-page duplication.

function ensureEditProfileModal() {
  if (document.getElementById('editProfileModal')) return;
  const html = `
  <div class="modal fade" id="editProfileModal" tabindex="-1">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-person-gear me-2"></i>Edit Profile</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <form id="editProfileForm">
          <div class="modal-body">

            <!-- Profile picture -->
            <div class="d-flex align-items-center gap-3 mb-4">
              <div class="position-relative" style="width:80px;height:80px;flex-shrink:0">
                <div id="epPicFallback"
                     class="rounded-circle border bg-secondary text-white d-flex align-items-center justify-content-center fw-bold fs-3"
                     style="width:80px;height:80px">?</div>
                <img id="epPicPreview" src="" alt="Profile"
                     class="rounded-circle border position-absolute top-0 start-0"
                     style="width:80px;height:80px;object-fit:cover;display:none">
              </div>
              <div class="flex-grow-1">
                <label class="form-label mb-1 fw-semibold">Profile Picture</label>
                <input type="file" id="epPicInput" class="form-control form-control-sm"
                       accept="image/png,image/jpeg,image/webp,image/gif">
                <div class="form-text">PNG, JPG, WEBP or GIF. Max 5 MB.</div>
                <button type="button" id="epPicRemove" class="btn btn-sm btn-outline-danger mt-1 d-none">
                  <i class="bi bi-trash"></i> Remove picture
                </button>
              </div>
            </div>

            <div class="row g-3">
              <div class="col-md-6">
                <label class="form-label">First Name</label>
                <input type="text" id="epFirstName" class="form-control" required>
              </div>
              <div class="col-md-6">
                <label class="form-label">Last Name</label>
                <input type="text" id="epLastName" class="form-control" required>
              </div>
              <div class="col-12">
                <label class="form-label">Email</label>
                <input type="email" id="epEmail" class="form-control" required>
              </div>
              <div class="col-12">
                <label class="form-label">Phone</label>
                <input type="text" id="epPhone" class="form-control">
              </div>
            </div>
            <hr>
            <p class="text-muted small mb-2">Leave blank to keep your current password.</p>
            <div class="row g-3">
              <div class="col-md-6">
                <label class="form-label">New Password</label>
                <div class="input-group">
                  <input type="password" id="epPassword" class="form-control" placeholder="New password">
                  <button type="button" class="btn btn-outline-secondary toggle-password" data-target="epPassword" tabindex="-1">
                    <i class="bi bi-eye"></i>
                  </button>
                </div>
              </div>
              <div class="col-md-6">
                <label class="form-label">Confirm Password</label>
                <div class="input-group">
                  <input type="password" id="epPasswordConfirm" class="form-control" placeholder="Confirm password">
                  <button type="button" class="btn btn-outline-secondary toggle-password" data-target="epPasswordConfirm" tabindex="-1">
                    <i class="bi bi-eye"></i>
                  </button>
                </div>
              </div>
            </div>
            <div id="editProfileError" class="alert alert-danger d-none mt-3"></div>
            <div id="editProfileSuccess" class="alert alert-success d-none mt-3"></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="submit" class="btn btn-primary">
              <i class="bi bi-check-lg me-1"></i> Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);

  // Live preview when a file is picked
  document.getElementById('epPicInput').addEventListener('change', function () {
    const file = this.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      document.getElementById('epPicPreview').src = e.target.result;
      document.getElementById('epPicPreview').style.display = '';
      document.getElementById('epPicFallback').style.display = 'none';
      document.getElementById('epPicRemove').classList.remove('d-none');
    };
    reader.readAsDataURL(file);
  });

  // Remove / clear the picture selection
  document.getElementById('epPicRemove').addEventListener('click', () => {
    document.getElementById('epPicInput').value = '';
    document.getElementById('epPicRemove').classList.add('d-none');
    // Restore fallback or previously saved picture — reloaded on next open
    document.getElementById('epPicPreview').style.display = 'none';
    document.getElementById('epPicFallback').style.display = '';
    document.getElementById('epPicRemove').dataset.clear = '1';
  });

  document.getElementById('editProfileForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorBox   = document.getElementById('editProfileError');
    const successBox = document.getElementById('editProfileSuccess');
    errorBox.classList.add('d-none');
    successBox.classList.add('d-none');

    const password        = document.getElementById('epPassword').value;
    const passwordConfirm = document.getElementById('epPasswordConfirm').value;
    if (password && password !== passwordConfirm) {
      errorBox.textContent = 'Passwords do not match.';
      errorBox.classList.remove('d-none');
      return;
    }

    // Use FormData so the picture file is sent as multipart
    const formData = new FormData();
    formData.append('first_name', document.getElementById('epFirstName').value.trim());
    formData.append('last_name',  document.getElementById('epLastName').value.trim());
    formData.append('email',      document.getElementById('epEmail').value.trim());
    formData.append('phone',      document.getElementById('epPhone').value.trim());
    if (password) formData.append('password', password);

    const picInput = document.getElementById('epPicInput');
    const clearPic = document.getElementById('epPicRemove').dataset.clear === '1';
    if (picInput.files[0]) {
      formData.append('profile_picture', picInput.files[0]);
    } else if (clearPic) {
      formData.append('profile_picture', '');
    }

    // Use fetch directly — apiRequest forces Content-Type: application/json
    // but multipart needs the browser to set the boundary automatically.
    const token = getAccessToken();
    let res;
    try {
      res = await fetch(`${API_BASE}/auth/me/`, {
        method: 'PATCH',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData,
      });
    } catch (err) {
      errorBox.textContent = 'Network error. Please try again.';
      errorBox.classList.remove('d-none');
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorBox.textContent = formatApiError(err);
      errorBox.classList.remove('d-none');
      return;
    }

    const data = await res.json();

    // Update topbar chip name + avatar
    const fullName = `${data.first_name} ${data.last_name}`.trim();
    localStorage.setItem('user_name', fullName);
    localStorage.setItem('user_picture', data.profile_picture || '');
    const nameEl   = document.getElementById('profileName');
    const avatarEl = document.getElementById('profileAvatar');
    if (nameEl) nameEl.textContent = fullName;

    // Update topbar avatar: picture if available, else initial letter
    if (data.profile_picture) {
      if (avatarEl) {
        avatarEl.style.backgroundImage = `url(${data.profile_picture})`;
        avatarEl.style.backgroundSize  = 'cover';
        avatarEl.style.backgroundPosition = 'center';
        avatarEl.style.backgroundRepeat = 'no-repeat';
        avatarEl.textContent           = '';
      }
    } else {
      if (avatarEl) {
        avatarEl.style.backgroundImage = '';
        avatarEl.style.backgroundSize  = '';
        avatarEl.style.backgroundPosition = '';
        avatarEl.style.backgroundRepeat = '';
        avatarEl.textContent           = fullName.charAt(0).toUpperCase();
      }
    }

    // Reset password fields and clear flag
    document.getElementById('epPassword').value        = '';
    document.getElementById('epPasswordConfirm').value = '';
    document.getElementById('epPicRemove').dataset.clear = '0';

    successBox.textContent = 'Profile updated successfully.';
    successBox.classList.remove('d-none');
  });
}

async function openEditProfileModal() {
  ensureEditProfileModal();

  // Fetch current profile
  const res = await apiRequest('/auth/me/');
  if (!res || !res.ok) return;
  const data = await res.json();

  document.getElementById('epFirstName').value = data.first_name || '';
  document.getElementById('epLastName').value  = data.last_name  || '';
  document.getElementById('epEmail').value     = data.email      || '';
  document.getElementById('epPhone').value     = data.phone      || '';
  document.getElementById('epPassword').value        = '';
  document.getElementById('epPasswordConfirm').value = '';
  document.getElementById('epPicInput').value = '';
  document.getElementById('epPicRemove').dataset.clear = '0';
  document.getElementById('editProfileError').classList.add('d-none');
  document.getElementById('editProfileSuccess').classList.add('d-none');

  // Set profile picture preview
  const preview  = document.getElementById('epPicPreview');
  const fallback = document.getElementById('epPicFallback');
  const removeBtn = document.getElementById('epPicRemove');
  if (data.profile_picture) {
    preview.src = data.profile_picture;
    preview.style.display = '';
    fallback.style.display = 'none';
    removeBtn.classList.remove('d-none');
  } else {
    preview.style.display = 'none';
    fallback.style.display = '';
    fallback.textContent = (data.first_name || '?').charAt(0).toUpperCase();
    removeBtn.classList.add('d-none');
  }

  new bootstrap.Modal(document.getElementById('editProfileModal')).show();
}

// ── Global member search (topbar) ─────────────────────────────────────────
// #globalSearch lives in the topbar, outside #page-content, so it survives
// every SPA navigation untouched. Must be initialized exactly ONCE per
// session here — NOT inside a per-page inline script — or repeated visits
// to a page that used to own this code stack duplicate 'input' listeners.
function initGlobalSearch() {
  const input = document.getElementById('globalSearch');
  const results = document.getElementById('globalSearchResults');
  if (!input || !results) return;
  let debounceTimer = null;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) { results.classList.remove('show'); return; }
    debounceTimer = setTimeout(async () => {
      const res = await apiRequest(`/members/?search=${encodeURIComponent(q)}`);
      if (!res || !res.ok) return;
      const data = await res.json();
      const list = (data.results || data).slice(0, 6);
      results.innerHTML = list.length
        ? list.map(m => `
            <a href="javascript:void(0)" onclick="showMemberQuickView('${m.id}')">
              <i class="bi bi-person-circle text-danger"></i>
              <span>${escapeHtml(m.full_name || (m.user && m.user.full_name) || '')} <span class="text-muted">— ${escapeHtml(m.display_id || m.id)}</span></span>
            </a>`).join('')
        : '<div class="p-2 text-muted small">No members found.</div>';
      results.classList.add('show');
    }, 300);
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !results.contains(e.target)) results.classList.remove('show');
  });
}
initGlobalSearch();

// escapeHtml is currently only defined inside dashboard.html's inline script —
// move that same helper here too, since showMemberQuickView (below) needs it
// and lives outside any page-specific script now.
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

// ── Member quick-view modal (triggered from global search) ────────────────
function ensureMemberQuickViewModal() {
  if (document.getElementById('memberQuickViewModal')) return;
  const html = `
  <div class="modal fade" id="memberQuickViewModal" tabindex="-1">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Member Details</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body" id="memberQuickViewBody">
          <div class="text-center py-4"><div class="spinner-border text-danger"></div></div>
        </div>
        <div class="modal-footer">
          <a href="#" id="memberQuickViewFullLink" class="btn btn-outline-danger btn-sm spa-link">Open full profile</a>
        </div>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
}

async function showMemberQuickView(memberId) {
  ensureMemberQuickViewModal();
  document.getElementById('globalSearchResults').classList.remove('show');

  const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('memberQuickViewModal'));
  document.getElementById('memberQuickViewBody').innerHTML =
    `<div class="text-center py-4"><div class="spinner-border text-danger"></div></div>`;
  document.getElementById('memberQuickViewFullLink').href = `members.html?view=${memberId}`;
  modal.show();

  const res = await apiRequest(`/members/${memberId}/`);
  if (!res || !res.ok) {
    document.getElementById('memberQuickViewBody').innerHTML =
      `<div class="text-danger small">Could not load member details.</div>`;
    return;
  }
  const m = await res.json();
  document.getElementById('memberQuickViewBody').innerHTML = `
    <p class="mb-1"><strong>${escapeHtml(m.full_name || '')}</strong></p>
    <p class="text-muted small mb-2">${escapeHtml(m.display_id || m.id)}</p>
    <p class="mb-1"><i class="bi bi-telephone me-1"></i>${escapeHtml(m.phone || '—')}</p>
    <p class="mb-1"><i class="bi bi-envelope me-1"></i>${escapeHtml(m.email || '—')}</p>
    <p class="mb-0"><i class="bi bi-card-checklist me-1"></i>${escapeHtml(m.membership_status || '—')}</p>
  `;
}

// ── Topbar bell notifications ─────────────────────────────────────────────
// Shared across all pages. Called once on initial page load and after any
// mark-as-read action so the badge + dropdown stay in sync without per-page
// duplication. notifications.html has its own full-page implementation and
// calls refreshTopbarBell() directly — this function is the equivalent used
// by every other page.
async function loadTopbarNotifications() {
  const res = await apiRequest('/notifications/?is_read=false');
  if (!res || !res.ok) return;
  const data = await res.json();
  const items = data.results || data;

  // Badge
  const badge = document.getElementById('notifCount');
  if (badge) {
    if (items.length > 0) {
      badge.style.display = 'inline-block';
      badge.textContent = items.length > 99 ? '99+' : items.length;
    } else {
      badge.style.display = 'none';
    }
  }

  // Mark-all button — enable only when there are unread items
  const markAllBtn = document.getElementById('notifMarkAllBtn');
  if (markAllBtn) markAllBtn.disabled = items.length === 0;

  // List
  const listEl = document.getElementById('notifList');
  if (!listEl) return;
  listEl.innerHTML = items.length
    ? items.slice(0, 6).map(n => `
        <div class="notif-item" onclick="markTopbarNotifRead(${n.id})" style="cursor:pointer;" id="topbar-notif-${n.id}">
          <div style="font-size:0.85rem;font-weight:600;">${escapeHtml(n.title)}</div>
          <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(n.message.length > 80 ? n.message.substring(0, 80) + '…' : n.message)}</div>
        </div>`).join('')
    : '<div class="notif-empty">No new notifications</div>';
}

async function markTopbarNotifRead(id) {
  const res = await apiRequest(`/notifications/${id}/read/`, { method: 'PATCH' });
  if (!res || !res.ok) return;
  // Remove the item from the dropdown immediately
  const row = document.getElementById(`topbar-notif-${id}`);
  if (row) row.remove();
  // Recount badge from remaining items
  const remaining = document.querySelectorAll('#notifList .notif-item').length;
  const badge = document.getElementById('notifCount');
  if (badge) {
    if (remaining > 0) {
      badge.textContent = remaining > 99 ? '99+' : remaining;
    } else {
      badge.style.display = 'none';
      const listEl = document.getElementById('notifList');
      if (listEl) listEl.innerHTML = '<div class="notif-empty">No new notifications</div>';
    }
  }
  const markAllBtn = document.getElementById('notifMarkAllBtn');
  if (markAllBtn) markAllBtn.disabled = remaining === 0;
}

async function markAllTopbarNotificationsRead() {
  const btn = document.getElementById('notifMarkAllBtn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>';
  }
  const res = await apiRequest('/notifications/mark-all-read/', { method: 'POST' });
  if (res && res.ok) {
    await loadTopbarNotifications();
  } else if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-check2-all me-1"></i>Mark all as read';
  }
}
