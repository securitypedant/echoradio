/* Shared UI behaviour: theme, toasts, copy buttons, confirm modal, password reveal, htmx errors. */
(function () {
  'use strict';
  if (window.__erApp) { window.__erApp.settle(); return; }

  // ---- theme ---------------------------------------------------------------
  const root = document.documentElement;
  function applyTheme() {
    let pref = null;
    try { pref = localStorage.getItem('er-theme'); } catch (e) { /* ignore */ }
    const theme = pref || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    root.setAttribute('data-bs-theme', theme);
  }
  applyTheme();
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#themeToggle')) return;
    const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('er-theme', next); } catch (e2) { /* ignore */ }
    root.setAttribute('data-bs-theme', next);
  });

  // ---- toasts --------------------------------------------------------------
  window.showToast = function (message, category) {
    const container = document.getElementById('toasts');
    if (!container) return;
    const kind = category === 'danger' ? 'danger' : (category === 'warning' ? 'warning' : 'success');
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + kind + ' border-0';
    el.setAttribute('role', 'alert');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    el.querySelector('.toast-body').textContent = message;
    container.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 5000 });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    // Dismiss on any tap: on iPhone Safari the delegated close-button handler is unreliable near the
    // bottom toolbar, and a tap anywhere on a notice is the natural gesture on a phone anyway.
    el.addEventListener('click', () => t.hide());
    t.show();
  };
  function marquee() {
    document.querySelectorAll('.mq-line').forEach((line) => {
      const inner = line.querySelector('.mq');
      if (!inner) return;
      const icon = line.querySelector('.bi');
      const avail = line.clientWidth - (icon ? icon.getBoundingClientRect().width + 8 : 0);
      const overflow = inner.scrollWidth - avail;
      if (overflow > 4) {
        const duration = 6 + overflow / 25;           // 3 s pause + scroll + 2 s pause, scaled to length
        inner.style.setProperty('--mq-shift', (-overflow) + 'px');
        inner.style.setProperty('--mq-duration', duration + 's');
        // Phase from a global clock so re-rendered cards continue the same scroll instead of restarting.
        inner.style.animationDelay = (-((performance.now() / 1000) % duration)) + 's';
        line.classList.add('marquee');
      } else {
        line.classList.remove('marquee');
        inner.style.animationDelay = '';
      }
    });
  }
  window.addEventListener('resize', marquee);

  function settle() {
    marquee();
    document.querySelectorAll('.toast[data-autoshow]').forEach((el) => {
      el.removeAttribute('data-autoshow');
      const t = new bootstrap.Toast(el, { delay: 6000 });
      el.addEventListener('hidden.bs.toast', () => el.remove());
      t.show();
    });
  }
  window.__erApp = { settle };
  settle();
  document.body.addEventListener('htmx:afterSettle', settle);

  // ---- copy to clipboard ---------------------------------------------------
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.copy-btn');
    if (!btn) return;
    const text = btn.getAttribute('data-copy');
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (e2) { /* ignore */ }
      ta.remove();
    }
    const icon = btn.querySelector('i');
    const original = icon ? icon.className : null;
    if (icon) icon.className = 'bi bi-check2';
    showToast('Copied: ' + text, 'success');
    setTimeout(() => { if (icon && original) icon.className = original; }, 1500);
  });

  // ---- confirm modal -------------------------------------------------------
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.confirm-action');
    const modalEl = document.getElementById('confirmModal');
    if (!btn || !modalEl) return;
    document.getElementById('confirmForm').setAttribute('action', btn.dataset.action);
    document.getElementById('confirmTitle').textContent = btn.dataset.title || 'Confirm';
    document.getElementById('confirmBody').textContent = btn.dataset.body || 'Are you sure?';
    document.getElementById('confirmButton').textContent = btn.dataset.button || 'Confirm';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  });

  // ---- password reveal -----------------------------------------------------
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.toggle-password');
    if (!btn) return;
    const input = document.getElementById(btn.dataset.target);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
    const icon = btn.querySelector('i');
    if (icon) { icon.classList.toggle('bi-eye'); icon.classList.toggle('bi-eye-slash'); }
  });

  // ---- htmx ----------------------------------------------------------------
  document.body.addEventListener('htmx:responseError', (e) => {
    const status = e.detail.xhr ? e.detail.xhr.status : 0;
    if (status === 401) { window.location.href = '/login'; return; }
    showToast('Request failed (' + status + ').', 'danger');
  });
  document.body.addEventListener('htmx:sendError', () => showToast('Server unreachable.', 'danger'));

  // ---- service worker (installable app) -----------------------------------
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* ignore */ });
  }
})();
