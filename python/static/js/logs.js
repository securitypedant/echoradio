/* Log viewer: loads a log tail, filters lines client-side with highlighting, optional follow mode. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const viewer = $('logViewer');
  const urlTemplate = viewer.dataset.logUrl;
  const fileSel = $('logFile'), search = $('logSearch'), regexBtn = $('logRegex'), linesSel = $('logLines');
  const output = $('logOutput'), stats = $('logStats'), follow = $('logFollow'), wrap = $('logWrap'), errorsOnly = $('logErrors');
  const refreshBtn = $('logRefresh'), download = $('logDownload'), copyBtn = $('logCopy');
  const ERROR_RE = /\b(error|warn|warning|crit|critical|fatal|exception|traceback|failed|refused)\b/i;

  let lines = [];
  let timer = null;
  let loading = false;

  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function currentUrl() {
    return urlTemplate.replace('__NAME__', encodeURIComponent(fileSel.value)) + '?lines=' + encodeURIComponent(linesSel.value);
  }

  function matcher() {
    const q = search.value.trim();
    if (!q) return null;
    try {
      return new RegExp(regexBtn.classList.contains('active') ? q : escapeRe(q), 'gi');
    } catch (e) {
      return null;
    }
  }

  // The lines currently shown, i.e. after the search and errors-only filters.
  function visibleLines() {
    const re = matcher();
    const onlyErrors = errorsOnly.checked;
    return lines.filter((line) => {
      if (onlyErrors && !ERROR_RE.test(line)) return false;
      if (re) { re.lastIndex = 0; if (!re.test(line)) return false; }
      return true;
    });
  }

  function render() {
    const re = matcher();
    const onlyErrors = errorsOnly.checked;
    const atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
    const out = [];
    let shown = 0;
    for (const line of lines) {
      if (onlyErrors && !ERROR_RE.test(line)) continue;
      if (re) {
        re.lastIndex = 0;
        if (!re.test(line)) continue;
        re.lastIndex = 0;
        let html = '', last = 0, m;
        while ((m = re.exec(line)) !== null) {
          if (m[0] === '') { re.lastIndex++; continue; }
          html += escapeHtml(line.slice(last, m.index)) + '<mark>' + escapeHtml(m[0]) + '</mark>';
          last = m.index + m[0].length;
        }
        html += escapeHtml(line.slice(last));
        out.push(html);
      } else {
        out.push(escapeHtml(line));
      }
      shown++;
    }
    const cls = (l) => ERROR_RE.test(l) ? ' class="log-err"' : '';
    output.innerHTML = out.length
      ? out.map((h) => '<span' + cls(h) + '>' + h + '</span>').join('\n')
      : '<span class="text-body-secondary">' + (lines.length ? 'No lines match.' : 'Log is empty.') + '</span>';
    stats.textContent = shown.toLocaleString() + ' of ' + lines.length.toLocaleString() + ' lines' + (re || onlyErrors ? ' (filtered)' : '');
    if (follow.checked || atBottom) output.scrollTop = output.scrollHeight;
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const r = await fetch(currentUrl(), { cache: 'no-store' });
      if (r.status === 401) { window.location.href = '/login'; return; }
      const text = r.ok ? await r.text() : '(could not load log: HTTP ' + r.status + ')';
      lines = text.replace(/\n$/, '').split('\n');
      download.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
      download.download = fileSel.value;
      render();
    } catch (e) {
      stats.textContent = 'Could not load log.';
    } finally {
      loading = false;
    }
  }

  function schedule() {
    if (timer) { clearInterval(timer); timer = null; }
    if (follow.checked) timer = setInterval(load, 5000);
  }

  fileSel.addEventListener('change', () => {
    const url = new URL(window.location.href);
    url.searchParams.set('file', fileSel.value);
    history.replaceState(null, '', url);
    load();
  });
  linesSel.addEventListener('change', load);
  refreshBtn.addEventListener('click', load);
  copyBtn.addEventListener('click', () => {
    const shown = visibleLines();
    if (!shown.length) { showToast('Nothing to copy.', 'warning'); return; }
    const filtered = search.value.trim() || errorsOnly.checked;
    const text = '# ' + fileSel.value + (filtered ? ' (filtered: ' + (search.value.trim() ? '"' + search.value.trim() + '"' : '') + (errorsOnly.checked ? ' errors only' : '') + ')' : '') +
      ' · ' + shown.length + ' of ' + lines.length + ' lines · copied ' + new Date().toISOString() + '\n' + shown.join('\n') + '\n';
    const done = () => showToast('Copied ' + shown.length.toLocaleString() + ' line' + (shown.length === 1 ? '' : 's') + '.', 'success');
    const fallback = () => {
      const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.focus(); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { showToast('Could not copy to the clipboard.', 'danger'); }
      document.body.removeChild(ta);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  });
  follow.addEventListener('change', schedule);
  wrap.addEventListener('change', () => output.classList.toggle('log-wrap', wrap.checked));
  errorsOnly.addEventListener('change', render);
  regexBtn.addEventListener('click', () => setTimeout(render, 0));
  let debounce = null;
  search.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(render, 120); });

  output.classList.toggle('log-wrap', wrap.checked);
  try {
    const q = new URL(window.location.href).searchParams.get('q');
    if (q) search.value = q;
  } catch (e) { /* ignore */ }
  load();
  schedule();
})();
