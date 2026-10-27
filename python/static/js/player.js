/* Echo Radio web player: hls.js (or native HLS on Safari) over the time-shifted DVR playlist. */
(function () {
  'use strict';
  if (window.__erPlayer) { try { window.__erPlayer.destroy(); } catch (e) { /* ignore */ } }
  const cfg = JSON.parse(document.getElementById('player-config').textContent);
  const media = document.getElementById('media');
  const clientId = Math.random().toString(36).slice(2, 10);
  const playlistUrl = cfg.dvrUrl + (cfg.dvrUrl.includes('?') ? '&' : '?') + 'c=' + clientId;
  const ua = navigator.userAgent;
  const isAppleBrowser = /iPhone|iPad|iPod/.test(ua) || (/Safari/.test(ua) && !/Chrome|Chromium|CriOS|Edg|Android/.test(ua));
  const nativeHlsType = media.canPlayType('application/vnd.apple.mpegurl');
  const timers = [];
  const every = (fn, ms) => { const id = setInterval(fn, ms); timers.push(id); return id; };
  window.__erPlayer = { destroy() { timers.forEach(clearInterval); try { if (hls) hls.destroy(); } catch (e) { /* ignore */ } try { media.pause(); } catch (e) { /* ignore */ } try { if (window.__erAudioCtx) window.__erAudioCtx.close(); } catch (e) { /* ignore */ } } };
  const $ = (id) => document.getElementById(id);
  const ui = {
    play: $('btnPlay'), playIcon: $('playIcon'), live: $('btnLive'), back: $('btnBack'), fwd: $('btnFwd'), hour: $('btnHour'),
    tl: $('timeline'), tlStart: $('tlStart'), tlEnd: $('tlEnd'), tlHint: $('tlHint'),
    aired: $('airedClock'), listener: $('listenerClock'), liveBadge: $('liveBadge'), fillBadge: $('fillBadge'),
    status: $('statusLine'), vol: $('volume'), mute: $('btnMute'), muteIcon: $('muteIcon'), sleepLabel: $('sleepLabel')
  };
  const fmt = (tz, seconds) => new Intl.DateTimeFormat([], Object.assign({ hour: '2-digit', minute: '2-digit', timeZone: tz }, seconds ? { second: '2-digit' } : {}));
  const fmtSrc = fmt(cfg.sourceTz, false), fmtSrcSec = fmt(cfg.sourceTz, true), fmtTgt = fmt(cfg.targetTz, false);
  const hintDefault = ui.tlHint.textContent;

  let hls = null;          // hls.js instance (null when using native HLS)
  let native = false;
  let details = null;      // latest hls.js LevelDetails
  let started = false;     // user pressed play at least once
  let dragging = false;
  let wantPlaying = false;
  let mediaErrors = 0;
  let restartTimer = null;
  let sleepTimer = null;
  let waitingSince = null;
  let apiState = null;

  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  const setStatus = (text) => { ui.status.textContent = text || ''; };

  // ---- timeline mapping ----------------------------------------------------
  function range() {
    if (native) {
      const s = media.seekable;
      if (!s || !s.length) return null;
      const start = s.start(0), end = s.end(s.length - 1);
      let base = null;
      try { const d = media.getStartDate && media.getStartDate(); if (d && !isNaN(d.getTime())) base = d.getTime(); } catch (e) { /* ignore */ }
      return { start: start, end: end, live: Math.max(start, end - cfg.leadSeconds),
        pdtAt: (t) => (base === null ? null : base + t * 1000),
        timeAt: (pdt) => (base === null ? start : (pdt - base) / 1000) };
    }
    const f = details && details.fragments ? details.fragments : [];
    if (!f.length) return null;
    const start = f[0].start;
    const last = f[f.length - 1];
    const end = last.start + last.duration;
    const sync = hls ? hls.liveSyncPosition : null;
    const live = (typeof sync === 'number' && !isNaN(sync)) ? clamp(sync, start, end) : Math.max(start, end - cfg.leadSeconds);
    const pdtAt = (t) => {
      let lo = 0, hi = f.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (f[mid].start <= t) lo = mid; else hi = mid - 1; }
      const fr = f[lo];
      return fr.programDateTime == null ? null : fr.programDateTime + (t - fr.start) * 1000;
    };
    const timeAt = (pdt) => {
      for (let i = f.length - 1; i >= 0; i--) {
        const fr = f[i];
        if (fr.programDateTime != null && fr.programDateTime <= pdt) {
          return fr.start + Math.min((pdt - fr.programDateTime) / 1000, fr.duration);
        }
      }
      return start;
    };
    return { start: start, end: end, live: live, pdtAt: pdtAt, timeAt: timeAt };
  }

  function seekTo(t) {
    const r = range();
    if (!r) return;
    media.currentTime = clamp(t, r.start, r.live);
  }
  function sliderTime(r) { return r.start + (parseInt(ui.tl.value, 10) / 1000) * Math.max(0.001, r.live - r.start); }
  function humanize(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h) return h + 'h ' + m + 'm';
    if (m) return m + 'm ' + (s ? s + 's' : '');
    return s + 's';
  }
  function badge(text, cls) {
    ui.liveBadge.textContent = text;
    ui.liveBadge.className = 'badge rounded-pill ' + cls;
  }

  // ---- periodic UI refresh ----------------------------------------------------
  function update() {
    const r = range();
    if (!r) {
      ui.tl.disabled = true;
      if (!started) badge('Ready', 'text-bg-secondary');
      return;
    }
    ui.tl.disabled = false;
    const t = media.currentTime;
    const span = Math.max(0.001, r.live - r.start);
    if (!dragging) ui.tl.value = Math.round(clamp((t - r.start) / span, 0, 1) * 1000);
    const ps = r.pdtAt(r.start), pl = r.pdtAt(r.live);
    const shown = dragging ? sliderTime(r) : t;
    const pc = r.pdtAt(shown);
    ui.tlStart.textContent = ps ? fmtSrc.format(ps) : '—';
    ui.tlEnd.textContent = pl ? fmtSrc.format(pl) : '—';
    if (pc) ui.aired.textContent = fmtSrcSec.format(pc);
    ui.listener.textContent = fmtTgt.format(Date.now());
    const behind = r.live - t;
    if (!started) badge('Ready', 'text-bg-secondary');
    else if (behind < 20) badge('Live', 'is-live');
    else badge('Rewound ' + humanize(behind), 'is-rewound');
    ui.tlHint.textContent = (dragging && pc) ? ('Go to ' + fmtSrc.format(pc) + ' station time') : hintDefault;
    const nearLive = behind < 20;
    ui.fillBadge.classList.toggle('d-none', !(apiState && apiState.playing_kind === 'fill' && nearLive && started));
  }
  every(update, 500);

  // ---- controls -------------------------------------------------------------------
  function play() {
    wantPlaying = true;
    const p = media.play();
    if (p && p.catch) p.catch((err) => {
      wantPlaying = false;
      if (err && err.name === 'NotAllowedError') {
        console.info('[player] autoplay refused by the browser; showing tap-to-play');
        showTap(true);
      } else if (err && err.name !== 'AbortError') {
        setStatus('Could not start playback (' + (err && err.name) + ').');
      }
    });
  }
  function pause() { wantPlaying = false; media.pause(); }
  const tap = $('tapToPlay');
  function showTap(on) { if (tap) tap.classList.toggle('d-none', !on); }
  if (tap) tap.addEventListener('click', () => { showTap(false); if (!started) start(); else play(); });
  media.addEventListener('playing', () => showTap(false));
  ui.play.addEventListener('click', () => {
    if (!started) { start(); return; }
    if (media.paused) play(); else pause();
  });
  ui.live.addEventListener('click', () => {
    const r = range();
    if (r) media.currentTime = r.live;
    if (!started) start(); else if (media.paused) play();
  });
  ui.back.addEventListener('click', () => seekTo(media.currentTime - 30));
  ui.fwd.addEventListener('click', () => seekTo(media.currentTime + 30));
  ui.hour.addEventListener('click', () => {
    const r = range();
    if (!r) return;
    const pdt = r.pdtAt(media.currentTime);
    if (!pdt) return;
    if (guideHourSeek(r, pdt)) return;
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: cfg.sourceTz, minute: 'numeric', second: 'numeric' }).formatToParts(new Date(pdt));
    const get = (type) => parseInt((parts.find((p) => p.type === type) || { value: '0' }).value, 10) || 0;
    let target = pdt - (get('minute') * 60 + get('second')) * 1000;
    // Already at (or within 15 s of) the top of this hour: step back to the previous hour instead,
    // so repeated presses walk back an hour at a time.
    if (pdt - target < 15000) target -= 3600000;
    const startPdt = r.pdtAt(r.start);
    if (startPdt !== null && target < startPdt) { seekTo(r.start); showToast('Start of the recording buffer.', 'warning'); return; }
    seekTo(r.timeAt(target));
  });
  ui.tl.addEventListener('input', () => { dragging = true; update(); });
  ui.tl.addEventListener('change', () => {
    const r = range();
    dragging = false;
    if (!r) return;
    seekTo(sliderTime(r));
    if (!started) start();
  });
  ui.vol.addEventListener('input', () => { media.volume = parseFloat(ui.vol.value); media.muted = media.volume === 0; });
  ui.mute.addEventListener('click', () => { media.muted = !media.muted; });
  media.addEventListener('volumechange', () => {
    ui.muteIcon.className = (media.muted || media.volume === 0) ? 'bi bi-volume-mute-fill' : 'bi bi-volume-up-fill';
  });
  let sleepEnd = null;
  const sleepBtn = ui.sleepLabel.closest('button');
  function sleepLabel() {
    if (sleepBtn) sleepBtn.classList.toggle('sleep-active', !!sleepEnd);
    if (!sleepEnd) { ui.sleepLabel.textContent = 'Sleep timer'; return; }
    const left = Math.max(0, sleepEnd - Date.now());
    ui.sleepLabel.textContent = left >= 60000 ? ('Sleep in ' + Math.ceil(left / 60000) + ' min') : ('Sleep in ' + Math.ceil(left / 1000) + ' s');
  }
  document.querySelectorAll('.sleep-opt').forEach((btn) => btn.addEventListener('click', () => {
    const minutes = parseInt(btn.dataset.minutes, 10);
    if (sleepTimer) { clearTimeout(sleepTimer); sleepTimer = null; }
    sleepEnd = null;
    if (minutes > 0) {
      sleepEnd = Date.now() + minutes * 60000;
      sleepTimer = setTimeout(() => { pause(); sleepEnd = null; sleepLabel(); showToast('Sleep timer: playback stopped.', 'success'); }, minutes * 60000);
      showToast('Playback will stop in ' + minutes + ' minutes.', 'success');
    }
    sleepLabel();
  }));
  every(sleepLabel, 1000);
  document.addEventListener('keydown', (e) => {
    if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    if (e.code === 'Space') { e.preventDefault(); ui.play.click(); }
    else if (e.code === 'ArrowLeft') seekTo(media.currentTime - 30);
    else if (e.code === 'ArrowRight') seekTo(media.currentTime + 30);
  });

  // ---- media element events -----------------------------------------------------
  media.addEventListener('play', () => { ui.playIcon.className = 'bi bi-pause-fill'; ui.play.classList.add('is-playing'); ui.play.title = 'Pause'; });
  media.addEventListener('pause', () => { ui.playIcon.className = 'bi bi-play-fill'; ui.play.classList.remove('is-playing'); ui.play.title = 'Play'; setStatus(''); });
  media.addEventListener('waiting', () => { waitingSince = Date.now(); setStatus('Buffering…'); });
  media.addEventListener('playing', () => { waitingSince = null; setStatus(''); });
  media.addEventListener('stalled', () => { if (!waitingSince) waitingSince = Date.now(); });
  media.addEventListener('error', () => {
    const err = media.error;
    const names = { 1: 'aborted', 2: 'network error', 3: 'decode error', 4: 'source not supported' };
    const text = err ? (names[err.code] || ('error ' + err.code)) + (err.message ? ': ' + err.message : '') : 'unknown error';
    console.warn('[player] media element error: ' + text);
    if (native && started) { setStatus('Playback problem (' + text + '), restarting…'); scheduleRestart(); }
  });

  // ---- start-up / hls.js ------------------------------------------------------------
  function whenHlsReady(fn, waited) {
    waited = waited || 0;
    if (window.Hls || waited > 4000 || media.canPlayType('application/vnd.apple.mpegurl')) { fn(); return; }
    setTimeout(() => whenHlsReady(fn, waited + 100), 100);
  }

  function start() {
    if (!window.Hls && !nativeHlsType) { whenHlsReady(start); return; }
    started = true;
    if (nativeHlsType && (isAppleBrowser || !window.Hls || !Hls.isSupported())) {
      // Safari / iOS: the built-in HLS player is the most reliable path.
      native = true;
      console.info('[player] using native HLS');
      media.src = playlistUrl;
      media.load();
    } else if (window.Hls && Hls.isSupported()) {
      console.info('[player] using hls.js ' + Hls.version);
      initHls();
    } else {
      setStatus('This browser cannot play HLS audio. Use the MP3 link below.');
      return;
    }
    play();
  }

  function initHls() {
    if (hls) { hls.destroy(); hls = null; }
    details = null;
    hls = new Hls({
      liveSyncDuration: cfg.leadSeconds,
      // No liveMaxLatencyDuration: this is a DVR, rewinding must never be "caught up" to live.
      liveDurationInfinity: false,
      maxBufferLength: 60,
      backBufferLength: 600,
      enableWorker: true,
      lowLatencyMode: false
    });
    hls.on(Hls.Events.LEVEL_LOADED, (e, d) => { details = d.details; });
    hls.on(Hls.Events.LEVEL_UPDATED, (e, d) => { details = d.details; });
    hls.on(Hls.Events.ERROR, onHlsError);
    hls.loadSource(playlistUrl);
    hls.attachMedia(media);
  }

  function onHlsError(e, data) {
    const detail = data.details + (data.response && data.response.code ? ' HTTP ' + data.response.code : '') +
      (data.url ? ' ' + data.url.replace(location.origin, '') : '');
    console.warn('[player] hls.js ' + (data.fatal ? 'fatal ' : '') + 'error: ' + detail, data);
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
      setStatus('Reconnecting… (' + detail + ')');
      setTimeout(() => { if (hls) hls.startLoad(); }, 2000);
    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
      mediaErrors += 1;
      if (mediaErrors <= 2 && hls) { setStatus('Recovering…'); hls.recoverMediaError(); } else { scheduleRestart(); }
    } else {
      scheduleRestart();
    }
  }

  function scheduleRestart() {
    if (restartTimer) return;
    setStatus('Restarting player…');
    restartTimer = setTimeout(() => {
      restartTimer = null; mediaErrors = 0;
      if (native) { media.src = playlistUrl; media.load(); } else { initHls(); }
      if (wantPlaying) play();
    }, 3000);
  }

  // Stall watchdog: if we have been buffering for a long time, kick the loader.
  every(() => {
    if (!wantPlaying || !waitingSince || Date.now() - waitingSince < 25000) return;
    waitingSince = null;
    if (hls) { hls.stopLoad(); hls.startLoad(); } else { scheduleRestart(); }
  }, 5000);

  // ---- Media Session (lock screen / headset / keyboard media keys) -------------------
  if ('mediaSession' in navigator) {
    try {
      updateSong(cfg.song);
      const set = (action, handler) => { try { navigator.mediaSession.setActionHandler(action, handler); } catch (e) { /* unsupported */ } };
      set('play', () => { if (!started) start(); else play(); });
      set('pause', pause);
      set('stop', pause);
      set('seekbackward', (d) => seekTo(media.currentTime - (d.seekOffset || 30)));
      set('seekforward', (d) => seekTo(media.currentTime + (d.seekOffset || 30)));
      set('seekto', (d) => { if (typeof d.seekTime === 'number') seekTo(d.seekTime); });
    } catch (e) { /* ignore */ }
  }

  // ---- stream state from the server --------------------------------------------------
  function updateSong(song) {
    const line = $('songLine'), text = $('songText');
    if (line && text) { text.textContent = song || ''; line.classList.toggle('d-none', !song); }
    if ('mediaSession' in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: song || cfg.name, artist: song ? cfg.name : 'Echo Radio', album: cfg.description || 'Echo Radio',
          artwork: [{ src: cfg.artwork, sizes: '512x512', type: 'image/png' }]
        });
      } catch (e) { /* ignore */ }
    }
  }
  async function poll() {
    try {
      const r = await fetch(cfg.apiUrl, { cache: 'no-store' });
      if (r.ok) { apiState = await r.json(); updateSong(apiState.now_playing_song); }
    } catch (e) { /* ignore */ }
  }
  poll();
  every(poll, 30000);
  update();

  // ---- playback speed --------------------------------------------------------------
  const speeds = [1, 1.25, 1.5, 2];
  const speedBtn = $('btnSpeed');
  function setSpeed(v) {
    media.playbackRate = v;
    try { media.preservesPitch = true; } catch (e) { /* ignore */ }
    if (speedBtn) { speedBtn.textContent = v + '×'; speedBtn.classList.toggle('active-feature', v !== 1); }
    try { localStorage.setItem('er-speed', String(v)); } catch (e) { /* ignore */ }
  }
  if (speedBtn) {
    speedBtn.addEventListener('click', () => {
      const i = speeds.indexOf(media.playbackRate);
      setSpeed(speeds[(i + 1) % speeds.length]);
    });
    let saved = 1;
    try { saved = parseFloat(localStorage.getItem('er-speed')) || 1; } catch (e) { /* ignore */ }
    if (speeds.includes(saved)) setSpeed(saved);
  }
  every(() => {
    const r = range();
    if (r && media.playbackRate > 1 && r.live - media.currentTime < 5) { setSpeed(1); setStatus('Caught up to live; back to normal speed.'); }
  }, 2000);

  // ---- programme guide ---------------------------------------------------------------
  let programmes = [];
  let guideLoadedFor = null;
  const guideStrip = $('guideStrip'), progLine = $('progLine'), progText = $('progText');
  const hourLabel = ui.hour ? ui.hour.querySelector('span') : null;
  const progLabel = (p) => p.title + (p.subtitle ? ' — ' + p.subtitle : '');
  async function loadGuide() {
    const r = range();
    if (!r || !cfg.guideUrl) return;
    const from = r.pdtAt(r.start), to = r.pdtAt(r.live);
    if (from === null || to === null) return;
    const key = Math.floor(from / 600000);
    if (guideLoadedFor === key) return;
    try {
      const resp = await fetch(cfg.guideUrl + '?from=' + Math.floor(from / 1000 - 3600) + '&to=' + Math.ceil(to / 1000 + 7200), { cache: 'no-store' });
      if (!resp.ok) return;
      const d = await resp.json();
      programmes = d.programmes || [];
      guideLoadedFor = key;
      if (hourLabel) hourLabel.textContent = programmes.length ? 'Start of show' : 'Top of hour';
      if (ui.hour) ui.hour.title = programmes.length ? 'Start of this show; press again for the previous one' : 'Start of this hour; press again for the previous hour';
      renderGuide();
    } catch (e) { /* ignore */ }
  }
  function programmeAt(pdt) { return programmes.find((p) => p.start * 1000 <= pdt && pdt < p.end * 1000) || null; }
  function renderGuide() {
    const r = range();
    if (!r || !guideStrip) return;
    const from = r.pdtAt(r.start), to = r.pdtAt(r.live);
    if (from === null || to === null) return;
    guideStrip.querySelectorAll('.prog').forEach((el) => el.remove());
    const span = Math.max(1, to - from);
    const cur = r.pdtAt(media.currentTime);
    for (const p of programmes) {
      const a = Math.max(from, p.start * 1000), b = Math.min(to, p.end * 1000);
      if (b <= a) continue;
      const el = document.createElement('div');
      el.className = 'prog' + (cur !== null && p.start * 1000 <= cur && cur < p.end * 1000 ? ' current' : '');
      el.style.left = ((a - from) / span * 100) + '%';
      el.style.width = ((b - a) / span * 100) + '%';
      el.textContent = p.title;
      el.title = progLabel(p) + ' · ' + fmtSrc.format(p.start * 1000) + '–' + fmtSrc.format(p.end * 1000);
      el.addEventListener('click', () => { seekTo(r.timeAt(Math.max(p.start * 1000, from))); if (!started) start(); });
      guideStrip.appendChild(el);
    }
  }
  function updateProgLine() {
    const r = range();
    const pdt = r ? r.pdtAt(media.currentTime) : null;
    const p = pdt !== null ? programmeAt(pdt) : null;
    if (!progLine) return;
    if (p) { progText.textContent = progLabel(p); progLine.classList.remove('d-none'); }
    else if (programmes.length) { progLine.classList.add('d-none'); }
  }
  function guideHourSeek(r, pdt) {
    if (!programmes.length) return false;
    const cur = programmeAt(pdt);
    let target = cur ? cur.start * 1000 : null;
    if (target === null || pdt - target < 15000) {
      const before = programmes.filter((p) => p.start * 1000 < (target !== null ? target : pdt) - 1000);
      if (!before.length) return false;
      target = before[before.length - 1].start * 1000;
    }
    const startPdt = r.pdtAt(r.start);
    if (startPdt !== null && target < startPdt) { seekTo(r.start); showToast('Start of the recording buffer.', 'warning'); return true; }
    seekTo(r.timeAt(target));
    return true;
  }
  every(() => { loadGuide(); renderGuide(); updateProgLine(); }, 5000);

  // ---- markers ---------------------------------------------------------------------
  const markBtn = $('btnMark'), markersList = $('markersList'), ticks = $('markerTicks');
  const csrf = document.body.dataset.csrf;
  let markerItems = [];
  async function loadMarkers() {
    try { const r = await fetch(cfg.markersUrl, { cache: 'no-store' }); if (r.ok) { markerItems = await r.json(); renderMarkers(); } } catch (e) { /* ignore */ }
  }
  function renderMarkers() {
    const r = range();
    if (ticks) {
      ticks.innerHTML = '';
      if (r) {
        const from = r.pdtAt(r.start), to = r.pdtAt(r.live);
        if (from !== null && to !== null) {
          for (const m of markerItems) {
            const t = m.aired_at * 1000;
            if (t < from || t > to) continue;
            const el = document.createElement('span');
            el.className = 'tick'; el.style.left = ((t - from) / (to - from) * 100) + '%';
            ticks.appendChild(el);
          }
        }
      }
    }
    if (!markersList) return;
    markersList.innerHTML = '';
    markersList.classList.toggle('d-none', !markerItems.length);
    if (!markerItems.length) return;
    const head = document.createElement('div');
    head.className = 'small text-body-secondary mb-1';
    head.innerHTML = '<i class="bi bi-bookmark-fill me-1"></i>Markers';
    markersList.appendChild(head);
    for (const m of markerItems.slice().reverse()) {
      const row = document.createElement('div');
      row.className = 'marker-item';
      const inBuffer = r && r.pdtAt(r.start) !== null && m.aired_at * 1000 >= r.pdtAt(r.start);
      row.innerHTML = '<button type="button" class="btn btn-sm ' + (inBuffer ? 'btn-outline-secondary' : 'btn-outline-secondary disabled') + ' time"></button>' +
        '<span class="flex-grow-1 text-truncate label"></span>' +
        '<button type="button" class="btn btn-sm btn-link text-danger p-0 del" title="Delete marker"><i class="bi bi-x-lg"></i></button>';
      row.querySelector('.time').textContent = fmtSrc.format(m.aired_at * 1000);
      row.querySelector('.label').textContent = m.label || new Date(m.aired_at * 1000).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
      row.querySelector('.time').addEventListener('click', () => { const rr = range(); if (rr) { seekTo(rr.timeAt(m.aired_at * 1000)); if (!started) start(); } });
      row.querySelector('.del').addEventListener('click', async () => {
        await fetch(cfg.markersUrl + '/' + encodeURIComponent(m.id), { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } });
        loadMarkers();
      });
      markersList.appendChild(row);
    }
  }
  if (markBtn) markBtn.addEventListener('click', async () => {
    const r = range();
    const pdt = r ? r.pdtAt(media.currentTime) : null;
    if (pdt === null) { showToast('Start playing first.', 'warning'); return; }
    const p = programmeAt(pdt);
    const label = (apiState && apiState.now_playing_song) || (p ? progLabel(p) : '');
    const resp = await fetch(cfg.markersUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ aired_at: pdt / 1000, label: label }) });
    if (resp.ok) { showToast('Marked ' + fmtSrc.format(pdt) + (label ? ' · ' + label : ''), 'success'); loadMarkers(); }
  });
  loadMarkers();
  every(renderMarkers, 10000);

  // ---- AirPlay (Safari) ------------------------------------------------------------
  const airplayBtn = $('btnAirplay');
  if (airplayBtn && window.WebKitPlaybackTargetAvailabilityEvent) {
    media.addEventListener('webkitplaybacktargetavailabilitychanged', (e) => {
      airplayBtn.classList.toggle('d-none', e.availability !== 'available');
    });
    airplayBtn.addEventListener('click', () => { if (!started) start(); media.webkitShowPlaybackTargetPicker(); });
  }

  // ---- Chromecast (Chrome) -----------------------------------------------------------
  const castBtn = $('btnCast');
  const isChrome = /Chrome\//.test(navigator.userAgent) && !/Edg\/|OPR\//.test(navigator.userAgent);
  if (castBtn && isChrome && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    window.__onGCastApiAvailable = (ok) => {
      if (!ok || !window.cast || !window.chrome) return;
      try {
        const ctx = cast.framework.CastContext.getInstance();
        ctx.setOptions({ receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID, autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED });
        castBtn.classList.remove('d-none');
        ctx.addEventListener(cast.framework.CastContextEventType.CAST_STATE_CHANGED, (e) => {
          castBtn.classList.toggle('active-feature', e.castState === cast.framework.CastState.CONNECTED);
          castBtn.classList.toggle('d-none', e.castState === cast.framework.CastState.NO_DEVICES_AVAILABLE);
        });
      } catch (e) { /* ignore */ }
    };
    const sdk = document.createElement('script');
    sdk.src = 'https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1';
    document.head.appendChild(sdk);
    castBtn.addEventListener('click', async () => {
      try {
        const ctx = cast.framework.CastContext.getInstance();
        let session = ctx.getCurrentSession();
        if (!session) { await ctx.requestSession(); session = ctx.getCurrentSession(); }
        if (!session) return;
        const info = new chrome.cast.media.MediaInfo(cfg.castUrl, 'application/x-mpegURL');
        info.streamType = chrome.cast.media.StreamType.LIVE;
        info.hlsSegmentFormat = chrome.cast.media.HlsSegmentFormat.TS;
        const meta = new chrome.cast.media.MusicTrackMediaMetadata();
        meta.title = cfg.name; meta.artist = 'Echo Radio'; meta.albumName = cfg.description || '';
        meta.images = [new chrome.cast.Image(cfg.castArtwork)];
        info.metadata = meta;
        await session.loadMedia(new chrome.cast.media.LoadRequest(info));
        pause();
        setStatus('Playing on ' + session.getCastDevice().friendlyName + '.');
      } catch (e) {
        if (e !== 'cancel') setStatus('Cast failed: ' + (e && (e.description || e.code || e)));
      }
    });
  }

  // ---- Spectrum analyser (Web Audio) -----------------------------------------------
  const vizBtn = $('btnViz'), canvas = $('analyser');
  let audioCtx = null, analyser = null, vizOn = false, vizRaf = null, peaks = [];
  const BANDS = 28;
  function vizSetup() {
    if (audioCtx) return true;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      audioCtx = new Ctx();
      window.__erAudioCtx = audioCtx;
      const src = audioCtx.createMediaElementSource(media);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.82;
      src.connect(analyser);
      analyser.connect(audioCtx.destination);
      return true;
    } catch (e) {
      console.warn('[player] analyser unavailable', e);
      audioCtx = null;
      return false;
    }
  }
  function vizDraw() {
    if (!vizOn) return;
    vizRaf = requestAnimationFrame(vizDraw);
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    const ctx2d = canvas.getContext('2d');
    ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx2d.clearRect(0, 0, w, h);
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    const nyquist = audioCtx.sampleRate / 2, minF = 40, maxF = 16000;
    const gap = 2, bw = (w - gap * (BANDS - 1)) / BANDS;
    for (let i = 0; i < BANDS; i++) {
      const f0 = minF * Math.pow(maxF / minF, i / BANDS), f1 = minF * Math.pow(maxF / minF, (i + 1) / BANDS);
      const b0 = Math.max(0, Math.floor(f0 / nyquist * data.length)), b1 = Math.max(b0 + 1, Math.ceil(f1 / nyquist * data.length));
      let peak = 0;
      for (let b = b0; b < b1 && b < data.length; b++) peak = Math.max(peak, data[b]);
      const v = peak / 255;
      const bh = Math.max(2, v * (h - 6));
      const x = i * (bw + gap);
      const grad = ctx2d.createLinearGradient(0, h, 0, 0);
      grad.addColorStop(0, '#1fd36d'); grad.addColorStop(0.6, '#f4d03f'); grad.addColorStop(1, '#ff4d4d');
      ctx2d.fillStyle = grad;
      // Winamp-style segmented bars
      const seg = 4, segGap = 1;
      for (let y = h - seg; y > h - bh; y -= seg + segGap) ctx2d.fillRect(x, y, bw, seg);
      peaks[i] = Math.max((peaks[i] || 0) - 1.2, bh);
      ctx2d.fillStyle = '#ffffff';
      ctx2d.fillRect(x, h - peaks[i] - 2, bw, 2);
    }
  }
  function vizToggle(on) {
    vizOn = on;
    canvas.classList.toggle('d-none', !on);
    if (vizBtn) vizBtn.classList.toggle('active-feature', on);
    try { localStorage.setItem('er-viz', on ? '1' : '0'); } catch (e) { /* ignore */ }
    if (on) { if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume(); vizDraw(); }
    else if (vizRaf) { cancelAnimationFrame(vizRaf); vizRaf = null; }
  }
  if (vizBtn) {
    vizBtn.addEventListener('click', () => {
      if (vizOn) { vizToggle(false); return; }
      if (native) { showToast("The analyser needs the web player's own decoder; Safari's built-in HLS player does not expose audio data.", 'warning'); return; }
      if (!vizSetup()) { showToast('The analyser is not available in this browser.', 'warning'); return; }
      vizToggle(true);
    });
    let pref = '0';
    try { pref = localStorage.getItem('er-viz') || '0'; } catch (e) { /* ignore */ }
    if (pref === '1' && !isAppleBrowser) {
      // Needs a user gesture for the AudioContext: enable on the first play click.
      ui.play.addEventListener('click', () => { if (!vizOn && !native && vizSetup()) vizToggle(true); }, { once: true });
    }
  }

  // Arriving via a "Listen" button: start right away. The click on the previous page counts as the
  // user gesture in most browsers; if playback is still refused, the play button stays ready.
  if (cfg.autoplay) {
    console.info('[player] autoplay requested');
    start();
    history.replaceState(null, '', window.location.pathname);
  }
})();
