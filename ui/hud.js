/* AUDEN HUD controller: streaming chat, speech in/out, telemetry, approvals. */
(() => {
  'use strict';

  const TOKEN = document.querySelector('meta[name="auden-token"]').content;
  const BOOT = window.__BOOT__ || {};
  const CFG = BOOT.config || {};
  const V = CFG.voice || {};
  const W = CFG.wake || {};

  const $ = (id) => document.getElementById(id);
  const el = {
    clock: $('clock'), date: $('date'), state: $('stateLabel'), subtitle: $('subtitle'),
    heard: $('heard'), feed: $('feed'), feedCount: $('feedCount'), input: $('chatInput'),
    form: $('chatForm'), micBtn: $('micBtn'), voiceBtn: $('voiceBtn'), sendBtn: $('sendBtn'),
    modeBtn: $('modeBtn'),
    confirmLayer: $('confirmLayer'), confirmBody: $('confirmBody'),
    confirmYes: $('confirmYes'), confirmNo: $('confirmNo'),
    pillCore: $('pillCore'), pillMic: $('pillMic'), pillLink: $('pillLink'), pillVoice: $('pillVoice'),
    mCpu: $('mCpu'), mRam: $('mRam'), mDisk: $('mDisk'), battery: $('battery'), uptime: $('uptime'),
    model: $('model'), tools: $('tools'), facts: $('facts'), backend: $('backend'), modules: $('modules'),
  };

  const orb = new window.Orb($('orb'), CFG.accent || '#37d8ff');

  let busy = false;
  let current = '';
  let spokenChars = 0;
  let feedItems = 0;
  let lastReply = '';
  let speaking = false;
  let speechEnabled = V.enabled !== false;
  let suppressUntil = 0;
  let audioUnlocked = false;
  let pendingGreeting = '';
  let listening = false;
  let wantListening = false;
  let recog = null;
  let ptt = false;

  /* ------------------------------------------------------------------ */
  /* helpers                                                            */
  /* ------------------------------------------------------------------ */
  const header = { 'Content-Type': 'application/json', 'X-Auden-Token': TOKEN };

  async function api(path, body) {
    const res = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: header,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  }

  /* Window form factors. The page cannot resize its own window, so the server
     asks the OS; the layout follows immediately. */
  const MODES = ['full', 'mini', 'orb'];
  let winMode = document.documentElement.dataset.mode || 'full';

  function setWindowMode(mode, persist) {
    if (!MODES.includes(mode)) mode = 'full';
    winMode = mode;
    document.documentElement.dataset.mode = mode;
    try { localStorage.setItem('auden.mode', mode); } catch (e) { /* private mode */ }
    if (el.modeBtn) {
      el.modeBtn.textContent = mode === 'full' ? 'MINI' : mode === 'mini' ? 'ORB' : 'FULL';
    }
    if (persist !== false) {
      api('/api/window', { mode })
        .then((res) => {
          if (!res.ok) addFeed('sys', 'SYSTEM', `Window mode unavailable: ${res.error || 'unknown'}`);
        })
        .catch(() => {});
    }
    if (mode !== 'orb') {
      setTimeout(() => { try { el.input.focus(); } catch (e) { /* ignore */ } }, 80);
    }
  }

  function cycleWindowMode() {
    setWindowMode(MODES[(MODES.indexOf(winMode) + 1) % MODES.length]);
  }

  function pill(node, state) {
    node.classList.remove('on', 'warn', 'bad', 'live');
    if (state) String(state).split(/\s+/).filter(Boolean).forEach((cls) => node.classList.add(cls));
  }

  function stamp() {
    return new Date().toLocaleTimeString('en-GB', { hour12: false });
  }

  function codeBlock(code, lang) {
    const wrap = document.createElement('div');
    wrap.className = 'code';
    const head = document.createElement('div');
    head.className = 'code-head';
    const label = document.createElement('span');
    label.textContent = (lang || 'code').toUpperCase();
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.textContent = 'COPY';
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code);
        copy.textContent = 'COPIED';
      } catch (e) {
        copy.textContent = 'COPY FAILED';
      }
      setTimeout(() => { copy.textContent = 'COPY'; }, 1400);
    });
    head.append(label, copy);
    const pre = document.createElement('pre');
    const codeEl = document.createElement('code');
    codeEl.textContent = code;
    pre.appendChild(codeEl);
    wrap.append(head, pre);
    return wrap;
  }

  function renderRich(target, text) {
    const src = String(text || '');
    target.textContent = '';
    target.classList.add('rich');
    const fence = /```([\w+#.\-]*)[ \t]*\n?([\s\S]*?)```/g;
    let last = 0;
    let m;
    while ((m = fence.exec(src)) !== null) {
      const before = src.slice(last, m.index).trim();
      if (before) target.appendChild(document.createTextNode(before + '\n'));
      target.appendChild(codeBlock(m[2].replace(/\n+$/, ''), m[1]));
      last = m.index + m[0].length;
    }
    const tail = src.slice(last).trim();
    if (tail) target.appendChild(document.createTextNode(tail));
    if (!target.childNodes.length) target.textContent = src;
  }

  function proseOnly(text) {
    const src = String(text || '');
    const cut = src.indexOf('```');
    return cut < 0 ? src : src.slice(0, cut);
  }

  function addFeed(kind, tag, text) {
    const entry = document.createElement('div');
    entry.className = `entry ${kind}`;
    const label = document.createElement('span');
    label.className = 'tag';
    label.textContent = `${tag} · ${stamp()}`;
    const body = document.createElement('div');
    body.className = 'body';
    if (kind === 'auden') renderRich(body, text);
    else body.textContent = text;
    entry.append(label, body);
    el.feed.appendChild(entry);
    feedItems += 1;
    el.feedCount.textContent = String(feedItems);
    while (el.feed.children.length > 260) el.feed.firstChild.remove();
    el.feed.scrollTop = el.feed.scrollHeight;
  }

  function showState(label, cls) {
    el.state.textContent = label;
    el.state.className = 'state' + (cls ? ' ' + cls : '');
    orb.setWarm(label === 'PROCESSING' || label === 'THINKING');
  }

  function renderSubtitle(text, live) {
    el.subtitle.innerHTML = '';
    el.subtitle.append(document.createTextNode(text));
    if (live) {
      const caret = document.createElement('span');
      caret.className = 'caret';
      el.subtitle.appendChild(caret);
    }
  }

  function cleanForSpeech(text) {
    return (text || '')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/https?:\/\/\S+/g, 'link')
      .replace(/[*_#`>]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /* ------------------------------------------------------------------ */
  /* speech out                                                         */
  /* ------------------------------------------------------------------ */
  const queue = [];
  let voice = null;

  function pickVoice() {
    const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    if (!voices.length) return null;
    const prefs = (V.preferred_voices || []).map((p) => p.toLowerCase());
    const gb = voices.filter((v) => /en[-_]gb/i.test(v.lang));
    for (const p of prefs) {
      const hit = gb.find((v) => v.name.toLowerCase().includes(p)) || voices.find((v) => v.name.toLowerCase().includes(p));
      if (hit) return hit;
    }
    return gb[0] || voices.find((v) => /^en/i.test(v.lang)) || voices[0];
  }

  if (window.speechSynthesis) {
    pickVoice();
    speechSynthesis.onvoiceschanged = () => { voice = pickVoice(); };
  }

  function say(text) {
    const clean = cleanForSpeech(text);
    if (!clean || !speechEnabled || !window.speechSynthesis) return;
    queue.push(clean);
    pump();
  }

  function pump() {
    if (speaking || !speechEnabled || !queue.length) return;
    const text = queue.shift();
    const u = new SpeechSynthesisUtterance(text);
    if (!voice) voice = pickVoice();
    if (voice) u.voice = voice;
    u.lang = V.lang || 'en-GB';
    u.rate = V.rate || 1.04;
    u.pitch = V.pitch || 0.86;
    u.volume = V.volume === undefined ? 1 : V.volume;
    const finish = () => {
      speaking = false;
      speakingSince = 0;
      suppressUntil = Date.now() + 1200;
      orb.setAmp(0);
      if (!busy) showState('STANDBY');
      pump();
    };
    u.onstart = () => {
      speaking = true;
      speakingSince = Date.now();
      speakGuard = 5000 + (text.length / Math.max(0.6, u.rate)) * 95;
      suppressUntil = Date.now() + 60000;
      showState('SPEAKING');
      pill(el.pillVoice, 'on live');
    };
    u.onend = finish;
    u.onerror = finish;
    try { speechSynthesis.speak(u); } catch (e) { finish(); }
  }

  let speakingSince = 0;
  let speakGuard = 0;
  setInterval(() => {
    if (speaking && speakingSince && Date.now() - speakingSince > speakGuard) {
      speaking = false;
      speakingSince = 0;
      try { window.speechSynthesis.cancel(); } catch (e) {}
      suppressUntil = Date.now() + 600;
      if (!busy) showState('STANDBY');
    }
  }, 800);

  function stopSpeech() {
    queue.length = 0;
    if (window.speechSynthesis) speechSynthesis.cancel();
    speaking = false;
    suppressUntil = Date.now() + 400;
    orb.setAmp(0);
    if (!busy) showState('STANDBY');
  }

  setInterval(() => {
    if (speaking) {
      orb.setAmp(0.28 + Math.random() * 0.42 + Math.sin(Date.now() / 90) * 0.12);
    }
  }, 70);

  /* ------------------------------------------------------------------ */
  /* speech in                                                          */
  /* ------------------------------------------------------------------ */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  function similarity(a, b) {
    const norm = (s) => s.toLowerCase().replace(/[^a-z0-9 ]/g, '').split(/\s+/).filter(Boolean);
    const A = norm(a), B = norm(b);
    if (!A.length || !B.length) return 0;
    const setB = new Set(B);
    const shared = A.filter((w) => setB.has(w)).length;
    return shared / Math.max(A.length, B.length);
  }

  function initRecog() {
    if (!SR) return null;
    const r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = V.lang || 'en-GB';
    r.maxAlternatives = 1;

    r.onstart = () => {
      listening = true;
      el.micBtn.classList.add('listening');
      pill(el.pillMic, 'on live');
      if (!busy && !speaking) showState('LISTENING');
    };

    r.onresult = (ev) => {
      let interim = '';
      let final = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) final += res[0].transcript;
        else interim += res[0].transcript;
      }
      if (interim) el.heard.textContent = interim.trim();
      if (!final) return;
      el.heard.textContent = '';
      const text = final.trim();
      if (!text) return;
      if (Date.now() < suppressUntil || speaking) return;
      if (lastReply && similarity(text, lastReply) > 0.6) return;

      const wake = (W.words || ['auden']).map((w) => w.toLowerCase());
      const lower = text.toLowerCase();
      let command = text;
      let hit = null;
      for (const w of wake) {
        const idx = lower.indexOf(w);
        if (idx >= 0 && idx < 24) { hit = w; break; }
      }
      if (hit) {
        command = text.slice(lower.indexOf(hit) + hit.length).replace(/^[\s,.!?]+/, '');
        if (/^(are you (there|awake)|you there|status)/i.test(command)) command = 'status report';
        if (!command) { command = 'Say that again?'; }
      } else if (W.require_wake_word && !ptt) {
        return;
      }
      ptt = false;
      if (command) sendText(command);
    };

    r.onerror = (ev) => {
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
        wantListening = false;
        pill(el.pillMic, 'bad');
        addFeed('bad', 'MIC', 'Microphone permission denied.');
      }
    };

    r.onend = () => {
      listening = false;
      el.micBtn.classList.remove('listening');
      if (!wantListening) {
        pill(el.pillMic, '');
        if (!busy && !speaking) showState('STANDBY');
        return;
      }
      setTimeout(() => {
        try { r.start(); } catch (e) { /* already running */ }
      }, 320);
    };
    return r;
  }

  function startListening() {
    if (!SR) {
      addFeed('bad', 'MIC', 'This browser has no speech recognition. Type instead.');
      return;
    }
    if (!recog) recog = initRecog();
    if (!recog) return;
    wantListening = true;
    try { recog.start(); } catch (e) { /* already started */ }
    startMicMeter();
  }

  function stopListening() {
    wantListening = false;
    if (recog) { try { recog.stop(); } catch (e) {} }
    el.micBtn.classList.remove('listening');
    pill(el.pillMic, '');
    if (!busy) showState('STANDBY');
  }

  let meterStream = null;
  async function startMicMeter() {
    if (meterStream || !navigator.mediaDevices) return;
    try {
      meterStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = ctx.createMediaStreamSource(meterStream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!wantListening) return;
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i] - 128) / 128);
        if (!speaking) orb.setAmp(Math.min(1, peak * 3.2));
        requestAnimationFrame(tick);
      };
      tick();
    } catch (e) { /* meter is a nicety */ }
  }

  /* ------------------------------------------------------------------ */
  /* chat                                                               */
  /* ------------------------------------------------------------------ */
  function splitSpeakable(text, from) {
    if (text.length <= from) return from;
    const tail = text.slice(from);
    const match = tail.match(/^[\s\S]*?[.!?…](?=\s|$)/);
    if (!match || match[0].trim().length < 24) {
      if (text.length - from > 260) {
        const cut = text.lastIndexOf(',', text.length);
        if (cut > from + 60) { say(text.slice(from, cut + 1)); return cut + 1; }
      }
      return from;
    }
    say(match[0]);
    return from + match[0].length;
  }

  async function sendText(raw) {
    const text = (raw || '').trim();
    if (!text || busy) return;
    busy = true;
    ptt = false;
    current = '';
    spokenChars = 0;
    lastReply = '';
    el.input.value = '';
    addFeed('user', 'YOU', text);
    renderSubtitle('', true);
    showState('THINKING');
    el.sendBtn.disabled = true;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST', headers: header, body: JSON.stringify({ text }),
      });
      if (!res.ok || !res.body) throw new Error(`server ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          handleFrame(frame);
        }
      }
    } catch (err) {
      addFeed('bad', 'LINK', `Connection lost: ${err.message}`);
      showState('ERROR', 'error');
      pill(el.pillLink, 'bad');
    } finally {
      busy = false;
      el.sendBtn.disabled = false;
      if (!speaking && !listening) showState('STANDBY');
    }
  }

  function handleFrame(frame) {
    let event = 'message';
    let data = null;
    for (const line of frame.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7).trim();
      else if (line.startsWith('data: ')) {
        try { data = JSON.parse(line.slice(6)); } catch (e) { data = null; }
      }
    }
    if (!data) return;

    switch (event) {
      case 'token': {
        current += data.text || '';
        const prose = proseOnly(current);
        renderSubtitle(prose || (current ? 'Writing code…' : ''), true);
        spokenChars = splitSpeakable(prose, spokenChars);
        break;
      }
      case 'discard': {
        current = '';
        spokenChars = 0;
        renderSubtitle('', true);
        break;
      }
      case 'tool': {
        const args = data.args || {};
        const brief = Object.entries(args).map(([k, v]) => {
          const s = (typeof v === 'string' ? v : JSON.stringify(v)).replace(/\s+/g, ' ');
          return `${k}=${s.length > 64 ? s.slice(0, 64) + '…' : s}`;
        }).join(', ');
        addFeed('tool', 'EXEC', `${data.name}(${brief})`);
        markModule(data.name);
        showState('PROCESSING');
        break;
      }
      case 'tool_result': {
        const text = String(data.result || '').replace(/\s+/g, ' ').slice(0, 300);
        addFeed(data.ok ? 'tool' : 'bad', data.ok ? 'RESULT' : 'FAILED', text);
        break;
      }
      case 'notice':
        addFeed('sys', 'NOTICE', data.text || '');
        break;
      case 'confirm':
        showConfirm(data);
        break;
      case 'done': {
        const final = data.text || current;
        lastReply = final;
        const prose = proseOnly(final).trim();
        renderSubtitle(prose || (final ? 'Code ready, sir — see the activity log.' : ''), false);
        if (final) addFeed('auden', 'AUDEN', final);
        if (spokenChars < prose.length) say(prose.slice(spokenChars));
        spokenChars = prose.length;
        current = '';
        if (data.telemetry) paintTelemetry(data.telemetry);
        break;
      }
      case 'error':
        addFeed('bad', 'ERROR', data.message || 'Unknown error');
        showState('ERROR', 'error');
        break;
      case 'hello':
      case 'ping':
        break;
      default:
        break;
    }
  }

  /* ------------------------------------------------------------------ */
  /* confirmations                                                      */
  /* ------------------------------------------------------------------ */
  let confirmId = null;
  function showConfirm(data) {
    confirmId = data.id;
    if (winMode === 'orb') setWindowMode('mini');
    const args = data.args || {};
    if (data.tool === 'write_file' && args.content !== undefined) {
      const body = String(args.content);
      const preview = body.length > 2200 ? body.slice(0, 2200) + '\n…' : body;
      el.confirmBody.textContent = `write_file\n${args.path || '(no path)'}\n\n${preview}`;
      el.confirmBody.classList.add('code-view');
    } else {
      el.confirmBody.classList.remove('code-view');
      const pretty = Object.entries(args).map(([k, v]) => `${k}: ${String(v).slice(0, 160)}`).join('\n');
      el.confirmBody.textContent = `${data.tool}\n\n${pretty || '(no arguments)'}`;
    }
    el.confirmLayer.hidden = false;
    addFeed('sys', 'AUTH', `Awaiting authorisation for ${data.tool}.`);
    say('I need your authorisation for that, sir.');
  }

  async function resolveConfirm(approved) {
    const id = confirmId;
    confirmId = null;
    el.confirmLayer.hidden = true;
    if (!id) return;
    try { await api('/api/confirm', { id, approved }); } catch (e) { /* ignore */ }
    addFeed(approved ? 'sys' : 'bad', 'AUTH', approved ? 'Authorised.' : 'Denied.');
  }

  el.confirmYes.addEventListener('click', () => resolveConfirm(true));
  el.confirmNo.addEventListener('click', () => resolveConfirm(false));

  /* ------------------------------------------------------------------ */
  /* telemetry                                                          */
  /* ------------------------------------------------------------------ */
  function setMeter(node, pct) {
    const value = Math.max(0, Math.min(100, Number(pct) || 0));
    node.querySelector('.fill').style.width = `${value}%`;
    node.querySelector('b').textContent = `${Math.round(value)}%`;
    node.classList.toggle('hot', value > 78);
  }

  function fmtUptime(secs) {
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
    return [h, m, s].map((n) => String(n).padStart(2, '0')).join(':');
  }

  let warmingNoted = false;

  function paintTelemetry(t) {
    if (!t || t.error) return;
    setMeter(el.mCpu, t.cpu);
    setMeter(el.mRam, t.ram);
    setMeter(el.mDisk, t.disk);
    el.battery.textContent = t.battery === null || t.battery === undefined ? 'N/A' : `${t.battery}%${t.charging ? ' ⚡' : ''}`;
    el.uptime.textContent = fmtUptime(t.uptime || 0);
    el.model.textContent = (t.model || '—').split(':')[0].split('-').slice(0, 2).join('-').toUpperCase();
    el.tools.textContent = String(t.tool_count || 0);
    el.facts.textContent = String(t.facts || 0);
    const online = !!t.online;
    pill(el.pillCore, online ? 'on' : 'bad');
    el.backend.textContent = !online ? 'OFFLINE'
      : (t.provider === 'openai' ? 'LLM SERVER' : 'OLLAMA');

    if (online && t.warmed === false && !busy && !speaking && !listening) {
      showState('WARMING');
      if (!warmingNoted) {
        warmingNoted = true;
        renderSubtitle('Bringing the cognitive core online. One moment, sir.', false);
      }
    } else if (online && t.warmed && warmingNoted && !busy && !speaking && !listening) {
      warmingNoted = false;
      showState('STANDBY');
      renderSubtitle('Core online. At your service.', false);
    }
  }

  async function pollTelemetry() {
    try {
      const t = await api('/api/telemetry');
      paintTelemetry(t);
      pill(el.pillLink, 'on');
    } catch (e) {
      pill(el.pillLink, 'bad');
      pill(el.pillCore, 'bad');
    }
  }

  function markModule(toolName) {
    const chip = el.modules.querySelector(`[data-tool="${toolName}"]`);
    if (!chip) return;
    chip.classList.add('active');
    setTimeout(() => chip.classList.remove('active'), 2200);
  }

  async function buildModules() {
    try {
      const state = await api('/api/state');
      const tools = state.tools || [];
      el.modules.innerHTML = '';
      for (const t of tools) {
        const chip = document.createElement('span');
        chip.className = 'mod';
        chip.dataset.tool = t.name;
        chip.textContent = t.name.replace(/_/g, ' ');
        el.modules.appendChild(chip);
      }
      paintTelemetry(state.telemetry);
      pill(el.pillCore, state.telemetry && state.telemetry.online ? 'on' : 'bad');
    } catch (e) {
      addFeed('bad', 'BOOT', 'Could not read system state.');
    }
  }

  /* ------------------------------------------------------------------ */
  /* clock + events                                                     */
  /* ------------------------------------------------------------------ */
  function tickClock() {
    const now = new Date();
    el.clock.textContent = now.toLocaleTimeString('en-GB', { hour12: false });
    el.date.textContent = now.toLocaleDateString('en-GB', {
      weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
    }).toUpperCase();
  }

  async function listenForEvents() {
    try {
      const res = await fetch('/api/events', { headers: { 'X-Auden-Token': TOKEN } });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let event = 'message', data = null;
          for (const line of frame.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7).trim();
            else if (line.startsWith('data: ')) { try { data = JSON.parse(line.slice(6)); } catch (e) {} }
          }
          if (event === 'alarm' && data) {
            addFeed('sys', 'ALARM', `${data.label} — ${data.seconds}s elapsed.`);
            say(`Sir, your ${data.label} timer has elapsed.`);
            showState('ALERT');
            setTimeout(() => { if (!busy && !speaking) showState('STANDBY'); }, 4000);
          }
        }
      }
    } catch (e) {
      /* reconnection handled by the polling fallback */
    }
    setTimeout(listenForEvents, 2500);
  }

  /* ------------------------------------------------------------------ */
  /* boot                                                               */
  /* ------------------------------------------------------------------ */
  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    try {
      const u = new SpeechSynthesisUtterance(' ');
      u.volume = 0.01;
      speechSynthesis.speak(u);
    } catch (e) {}
    if (pendingGreeting) {
      say(pendingGreeting);
      pendingGreeting = '';
    }
    el.heard.textContent = '';
  }

  ['pointerdown', 'keydown'].forEach((evt) =>
    window.addEventListener(evt, unlockAudio, { once: true })
  );

  el.form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    stopSpeech();
    sendText(el.input.value);
  });

  el.micBtn.addEventListener('click', () => {
    unlockAudio();
    if (wantListening) stopListening();
    else startListening();
  });

  el.voiceBtn.addEventListener('click', () => {
    speechEnabled = !speechEnabled;    el.voiceBtn.textContent = speechEnabled ? 'VOICE ON' : 'VOICE OFF';
    el.voiceBtn.classList.toggle('off', !speechEnabled);
    pill(el.pillVoice, speechEnabled ? 'on' : '');
    if (!speechEnabled) stopSpeech();
    else say('Voice enabled.');
  });

  el.modeBtn.addEventListener('click', () => cycleWindowMode());
  document.querySelector('.orb-wrap').addEventListener('click', () => {
    if (winMode === 'orb') setWindowMode('mini');
  });
  setWindowMode(winMode, false);

  window.addEventListener('keydown', (ev) => {
    if (ev.altKey && (ev.key === 'm' || ev.key === 'M')) {
      ev.preventDefault();
      cycleWindowMode();
    }
    if (ev.key === 'Escape') {
      stopSpeech();
      if (busy) {
        addFeed('sys', 'SYSTEM', 'Output cancelled.');
      }
    }
    if (ev.altKey && ev.code === 'Space') {
      ev.preventDefault();
      unlockAudio();
      if (!SpeechRecognition && !window.webkitSpeechRecognition) return;
      if (!recog) recog = initRecog();
      ptt = true;
      wantListening = true;
      try { recog.start(); } catch (e) {}
      startMicMeter();
    }
  });

  window.addEventListener('keyup', (ev) => {
    if (ev.altKey && ev.code === 'Space' && ptt) {
      setTimeout(() => {
        if (recog) { try { recog.stop(); } catch (e) {} }
        wantListening = false;
      }, 700);
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopSpeech();
  });

  async function boot() {
    tickClock();
    setInterval(tickClock, 1000);
    el.voiceBtn.textContent = speechEnabled ? 'VOICE ON' : 'VOICE OFF';
    el.voiceBtn.classList.toggle('off', !speechEnabled);
    pill(el.pillVoice, speechEnabled ? 'on' : '');
    pill(el.pillMic, '');
    pill(el.pillLink, 'on');

    await buildModules();
    pollTelemetry();
    setInterval(pollTelemetry, 2500);
    listenForEvents();

    if (CFG.greet) {
      try {
        const g = await api('/api/greeting');
        renderSubtitle(g.text, false);
        pendingGreeting = g.text;
        addFeed('auden', 'AUDEN', g.text);
        say(g.text);
      } catch (e) {}
    }

    if (W.enabled) {
      setTimeout(() => {
        if (!wantListening && SR) {
          const wake = (W.words || ['auden'])[0];
          const pretty = wake.charAt(0).toUpperCase() + wake.slice(1);
          addFeed('sys', 'SYSTEM', `Hands-free armed. Say "${pretty}".`);
        }
      }, 1200);
    }

    el.input.focus();
  }

  boot();
})();
