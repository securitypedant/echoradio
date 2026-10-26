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
  window.__erPlayer = { destroy() { timers.forEach(clearInterval); try { if (hls) hls.destroy(); } catch (e) { /* ignore */ } try { media.pause(); } catch (e) { /* ignore */ } } };
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
    if (pc) {
      ui.aired.textContent = fmtSrcSec.format(pc);
      if (pl) ui.listener.textContent = fmtTgt.format(Date.now() - (pl - pc));
    }
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
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: cfg.sourceTz, minute: 'numeric', second: 'numeric' }).formatToParts(new Date(pdt));
    const get = (type) => parseInt((parts.find((p) => p.type === type) || { value: '0' }).value, 10) || 0;
    const target = pdt - (get('minute') * 60 + get('second')) * 1000;
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
  function sleepLabel() {
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
      liveMaxLatencyDuration: cfg.leadSeconds + 90,
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
      navigator.mediaSession.metadata = new MediaMetadata({
        title: cfg.name, artist: 'Echo Radio', album: cfg.description || '',
        artwork: [{ src: cfg.artwork, sizes: '512x512', type: 'image/png' }]
      });
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
  async function poll() {
    try {
      const r = await fetch(cfg.apiUrl, { cache: 'no-store' });
      if (r.ok) apiState = await r.json();
    } catch (e) { /* ignore */ }
  }
  poll();
  every(poll, 30000);
  update();

  // Arriving via a "Listen" button: start right away. The click on the previous page counts as the
  // user gesture in most browsers; if playback is still refused, the play button stays ready.
  if (cfg.autoplay) {
    console.info('[player] autoplay requested');
    start();
    history.replaceState(null, '', window.location.pathname);
  }
})();
