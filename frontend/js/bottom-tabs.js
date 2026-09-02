/* ==========================================================================
   FitCore — Bottom Tab Bar (Mobile Navigation)
   Injected by api.js on member-facing pages.
   ========================================================================== */

function injectBottomTabBar() {
  // Only inject for MEMBER role on member-facing pages
  const role = localStorage.getItem('user_role');
  if (role !== 'MEMBER') return;

  // Don't inject if already exists or if on login/signup pages
  if (document.getElementById('bottomTabBar')) return;
  if (document.querySelector('.login-page, .landing-page')) return;

  const currentPage = window.location.pathname.split('/').pop() || 'dashboard.html';

  const tabs = [
    { href: 'dashboard.html', icon: 'bi-house-fill', label: 'Home' },
    { href: 'my-workouts.html', icon: 'bi-heart-pulse', label: 'Workouts' },
    { href: 'messages.html', icon: 'bi-chat-dots', label: 'Messages' },
    { href: 'my-progress.html', icon: 'bi-graph-up', label: 'Progress' },
    { href: 'my-memberships.html', icon: 'bi-person', label: 'More' },
  ];

  const bar = document.createElement('div');
  bar.id = 'bottomTabBar';
  bar.className = 'bottom-tab-bar';
  bar.innerHTML = `
    <div class="tab-items">
      ${tabs.map(t => `
        <a href="${t.href}" class="tab-item ${currentPage === t.href ? 'active' : ''}">
          <i class="bi ${t.icon}"></i>
          <span>${t.label}</span>
        </a>
      `).join('')}
    </div>
  `;

  document.body.appendChild(bar);
}

// Inject after DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', injectBottomTabBar);
} else {
  injectBottomTabBar();
}
