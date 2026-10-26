/* Add / edit stream form: searchable timezone pickers, live delay preview, URL test, fallback previews. */
(function () {
  'use strict';
  const csrf = document.body.dataset.csrf;
  const srcSel = document.getElementById('source_tz');
  const tgtSel = document.getElementById('target_tz');
  const preview = document.getElementById('delayPreviewText');
  const previewBox = document.getElementById('delayPreview');

  const tsOpts = { create: false, maxOptions: 2000, allowEmptyOption: false, placeholder: 'Search a city…',
    sortField: [{ field: '$order' }], plugins: ['dropdown_input'] };
  new TomSelect(srcSel, tsOpts);
  const tgtTS = new TomSelect(tgtSel, tsOpts);

  const city = (z) => z.split('/').pop().replace(/_/g, ' ');

  async function updateDelay() {
    const s = srcSel.value, t = tgtSel.value;
    if (!s || !t) {
      preview.textContent = 'Pick both timezones to see the delay.';
      previewBox.className = 'alert alert-info d-flex gap-3 align-items-center mb-0';
      return;
    }
    try {
      const r = await fetch('/api/delay?source=' + encodeURIComponent(s) + '&target=' + encodeURIComponent(t));
      if (!r.ok) throw new Error('bad response');
      const d = await r.json();
      preview.innerHTML = 'Plays <strong>' + d.delay_text + '</strong> behind the live broadcast. ' +
        'Right now it is ' + d.source_now + ' in ' + city(s) + ' (' + d.source_offset + ') and ' +
        d.listener_now + ' in ' + city(t) + ' (' + d.target_offset + '); you would hear what aired at <strong>' +
        d.aired_at + '</strong> ' + city(s) + ' time.' +
        (s === t ? ' <br><span class="small">Same timezone: the stream replays yesterday\'s broadcast.</span>' : '');
      previewBox.className = 'alert alert-success d-flex gap-3 align-items-center mb-0';
    } catch (e) {
      preview.textContent = 'Could not compute the delay.';
    }
  }
  srcSel.addEventListener('change', updateDelay);
  tgtSel.addEventListener('change', updateDelay);
  updateDelay();

  document.getElementById('useMyTz').addEventListener('click', () => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (tz && tgtTS.options[tz]) { tgtTS.setValue(tz); } else { showToast('Could not detect a matching timezone.', 'warning'); }
  });

  // Test URL
  const testBtn = document.getElementById('testUrl');
  const testOut = document.getElementById('testUrlResult');
  testBtn.addEventListener('click', async () => {
    const url = document.getElementById('stream_url').value.trim();
    if (!url) { testOut.textContent = 'Enter a URL first.'; return; }
    testBtn.disabled = true; testOut.textContent = 'Testing…'; testOut.className = 'form-text';
    try {
      const r = await fetch('/api/test-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ url: url })
      });
      const d = await r.json();
      testOut.textContent = d.message || (d.ok ? 'Reachable.' : 'Failed.');
      testOut.className = 'form-text ' + (d.ok ? 'text-success' : 'text-danger');
    } catch (e) {
      testOut.textContent = 'Test failed.'; testOut.className = 'form-text text-danger';
    } finally { testBtn.disabled = false; }
  });

  // Fallback previews
  const player = document.getElementById('previewPlayer');
  document.querySelectorAll('.preview-audio').forEach((btn) => {
    btn.addEventListener('click', () => {
      const src = btn.dataset.src;
      if (!player.paused && player.dataset.src === src) { player.pause(); return; }
      player.src = src; player.dataset.src = src; player.play().catch(() => {});
    });
  });

  // Disk estimate
  const bitrate = document.getElementById('bitrate');
  const est = document.getElementById('diskEstimate');
  function updateEstimate() {
    const k = parseInt(bitrate.value, 10) || 128;
    est.textContent = Math.round(k * 1000 / 8 * 3600 * 1.04 / (1024 * 1024));
  }
  bitrate.addEventListener('change', updateEstimate); updateEstimate();
})();

/* Station directory modal */
(function () {
  'use strict';
  const modalEl = document.getElementById('directoryModal');
  if (!modalEl) return;
  const input = document.getElementById('dirSearch');
  const results = document.getElementById('dirResults');
  const status = document.getElementById('dirStatus');
  let debounce = null, seq = 0;

  const esc = (s) => String(s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function search(q) {
    const mine = ++seq;
    status.textContent = 'Searching…';
    try {
      const r = await fetch('/api/directory?q=' + encodeURIComponent(q), { cache: 'no-store' });
      if (r.status === 401) { window.location.href = '/login'; return; }
      const d = await r.json();
      if (mine !== seq) return;
      render(d);
    } catch (e) {
      if (mine === seq) status.textContent = 'Search failed.';
    }
  }

  function render(d) {
    results.innerHTML = '';
    if (!d.results.length) {
      status.textContent = d.query ? 'No stations found for “' + d.query + '”.' : 'Type to search.';
    } else {
      status.textContent = d.results.length + ' station' + (d.results.length === 1 ? '' : 's') +
        (d.errors && d.errors['radio-browser'] ? ' (Radio Browser unavailable)' : '');
    }
    for (const st of d.results) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'list-group-item list-group-item-action';
      const meta = [st.country, st.state, st.codec ? (st.codec + (st.bitrate ? ' ' + st.bitrate + 'k' : '')) : ''].filter(Boolean).join(' · ');
      btn.innerHTML = '<div class="d-flex justify-content-between align-items-start gap-2">' +
        '<div class="min-w-0"><div class="fw-semibold text-truncate">' + esc(st.name) + '</div>' +
        '<div class="small text-body-secondary text-truncate">' + esc(meta) + (st.tags ? ' · ' + esc(String(st.tags).split(',').slice(0, 4).join(', ')) : '') + '</div></div>' +
        '<span class="badge ' + (st.source === 'bbc' ? 'text-bg-danger' : 'text-bg-secondary') + ' flex-shrink-0">' + (st.source === 'bbc' ? 'BBC' : 'Radio Browser') + '</span></div>';
      btn.addEventListener('click', () => pick(st));
      results.appendChild(btn);
    }
  }

  function pick(st) {
    const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
    set('stream_name', st.name);
    set('stream_url', st.url);
    const desc = document.getElementById('stream_description');
    if (desc && !desc.value) desc.value = (st.description || '').slice(0, 200);
    const src = document.getElementById('source_tz');
    if (st.timezone && src && src.tomselect) { src.tomselect.setValue(st.timezone); }
    bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    showToast('Filled in “' + st.name + '”' + (st.timezone ? ' (station timezone ' + st.timezone + ')' : ' — pick the station timezone'), 'success');
    document.getElementById('stream_name').focus();
  }

  input.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(() => search(input.value.trim()), 250); });
  document.querySelectorAll('.dir-quick').forEach((b) => b.addEventListener('click', () => { input.value = b.dataset.q; search(b.dataset.q); }));
  modalEl.addEventListener('shown.bs.modal', () => { input.focus(); if (!results.children.length) search(input.value.trim()); });
})();
