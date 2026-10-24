(function () {
  "use strict";

  const token = document.querySelector('meta[name="auden-token"]').content;
  const $ = (id) => document.getElementById(id);

  const state = {
    scan: null,
    engine: "auto",
    model: "",
    units: "metric",
    polling: null,
    micStream: null,
    micAudio: null,
    micTimer: null,
    lastMessage: "",
  };

  const steps = ["step-check", "step-engine", "step-install", "step-profile", "step-done"];
  const stepIndex = { "step-check": 1, "step-engine": 2, "step-install": 2, "step-profile": 3, "step-done": 4 };

  async function api(path, options) {
    const opts = options || {};
    const headers = Object.assign({
      "X-Auden-Token": token,
      "Content-Type": "application/json",
    }, opts.headers || {});
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }

  function showStep(id) {
    steps.forEach((step) => {
      const node = $(step);
      if (node) node.classList.toggle("hidden", step !== id);
    });
    const active = stepIndex[id] || 1;
    document.querySelectorAll("#stepBar span").forEach((node) => {
      const n = Number(node.dataset.step);
      node.classList.toggle("active", n === active);
      node.classList.toggle("done", n < active);
    });
  }

  function setNotice(id, text, isError) {
    const node = $(id);
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("hidden", !text);
    node.classList.toggle("error", !!isError);
  }

  function fmtGb(value) {
    return (Number(value) || 0).toFixed(1) + " GB";
  }

  function renderScan(scan) {
    state.scan = scan;
    $("statRam").textContent = fmtGb(scan.ram_gb);
    $("statRam").className = scan.ram_gb >= 7.5 ? "good" : "warn";
    $("statDisk").textContent = fmtGb(scan.free_gb);
    $("statDisk").className = scan.free_gb >= 7 ? "good" : "bad";

    const ollama = $("statOllama");
    if (scan.existing_ollama) {
      ollama.textContent = "RUNNING";
      ollama.className = "good";
    } else if (scan.installed_exe) {
      ollama.textContent = "INSTALLED";
      ollama.className = "warn";
    } else {
      ollama.textContent = "NOT FOUND";
      ollama.className = "warn";
    }

    const model = $("statModel");
    if (scan.current_model) {
      model.textContent = scan.current_model;
      model.className = "good";
    } else if (scan.existing_models && scan.existing_models.length) {
      model.textContent = scan.existing_models[0];
      model.className = "warn";
    } else {
      model.textContent = "NOT INSTALLED";
      model.className = "warn";
    }

    const bits = [];
    if (scan.existing_ollama) bits.push("Ollama is already running; AUDEN can reuse it.");
    else if (scan.installed_exe) bits.push("Ollama is installed but not running; AUDEN can start it.");
    else bits.push("No Ollama found. AUDEN will install a private copy.");
    if (scan.free_gb < 7) bits.push("Disk space is tight: the engine and model need about 5 GB free.");
    setNotice("scanNotice", bits.join(" "), scan.free_gb < 5);

    renderEngines(scan);
    renderModels(scan);
    $("toEngine").disabled = false;
  }

  function renderEngines(scan) {
    const host = $("engineChoices");
    host.textContent = "";
    (scan.engine_choices || []).forEach((choice) => {
      const label = document.createElement("label");
      label.className = "choice" + (choice.available ? "" : " disabled") + (choice.id === state.engine ? " selected" : "");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "engine";
      radio.value = choice.id;
      radio.disabled = !choice.available;
      radio.checked = choice.id === state.engine;
      radio.addEventListener("change", () => {
        state.engine = choice.id;
        host.querySelectorAll(".choice").forEach((n) => n.classList.remove("selected"));
        label.classList.add("selected");
      });
      const body = document.createElement("div");
      const title = document.createElement("b");
      title.textContent = choice.label;
      const detail = document.createElement("small");
      detail.textContent = choice.detail;
      body.appendChild(title);
      body.appendChild(detail);
      label.appendChild(radio);
      label.appendChild(body);
      host.appendChild(label);
    });
  }

  function renderModels(scan) {
    const host = $("modelChoices");
    host.textContent = "";
    const models = scan.models || [];
    if (!state.model) {
      const preferred = models.find((m) => m.recommended) || models[0];
      state.model = preferred ? preferred.tag : "";
    }
    models.forEach((m) => {
      const card = document.createElement("div");
      card.className = "model" + (m.installed ? " installed" : "");
      if (m.tag === state.model) card.classList.add("selected");
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      const name = document.createElement("div");
      name.className = "model-name";
      name.textContent = m.label;
      const size = document.createElement("div");
      size.className = "model-size";
      size.textContent = (m.size_gb ? m.size_gb.toFixed(1) + " GB" : "installed") + " · " + m.tag;
      const note = document.createElement("div");
      note.className = "model-note";
      note.textContent = m.note || "";
      card.appendChild(name);
      card.appendChild(size);
      card.appendChild(note);
      if (m.installed) {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = "READY";
        card.appendChild(badge);
      }
      const choose = () => {
        state.model = m.tag;
        host.querySelectorAll(".model").forEach((n) => n.classList.remove("selected"));
        card.classList.add("selected");
      };
      card.addEventListener("click", choose);
      card.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); choose(); }
      });
      host.appendChild(card);
    });
  }

  function stopPolling() {
    if (state.polling) {
      clearInterval(state.polling);
      state.polling = null;
    }
  }

  function addLog(message, stage) {
    const log = $("installLog");
    if (!message) return;
    const line = document.createElement("div");
    line.textContent = (stage ? "[" + String(stage).toUpperCase() + "] " : "") + message;
    log.appendChild(line);
    while (log.children.length > 12) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
  }

  function updateProgress(status) {
    const pct = Math.max(0, Math.min(100, Number(status.percent) || 0));
    $("barFill").style.width = pct + "%";
    $("progressPct").textContent = Math.round(pct) + "%";
    $("progressStage").textContent = String(status.stage || "working").toUpperCase();
    if (status.message && status.message !== state.lastMessage) {
      state.lastMessage = status.message;
      $("installMessage").textContent = status.message;
      addLog(status.message, status.stage);
    }
  }

  function startPolling() {
    stopPolling();
    state.polling = setInterval(async () => {
      try {
        const status = await api("/api/setup/status");
        updateProgress(status);
        if (status.error) {
          stopPolling();
          setNotice("installError", status.error, true);
          $("retryInstall").classList.remove("hidden");
          $("cancelInstall").classList.remove("hidden");
          $("installLead").textContent = "Setup stopped. Fix the issue and try again.";
          return;
        }
        if (status.done) {
          stopPolling();
          setNotice("installError", "", false);
          showStep("step-profile");
          const name = $("nameInput");
          if (name) name.focus();
        }
      } catch (err) {
        // The server may be restarting; keep polling a few times.
      }
    }, 700);
  }

  async function beginInstall() {
    setNotice("installError", "", false);
    $("retryInstall").classList.add("hidden");
    $("cancelInstall").classList.add("hidden");
    $("startInstall").disabled = true;
    $("installLog").textContent = "";
    state.lastMessage = "";
    $("barFill").style.width = "0%";
    $("progressPct").textContent = "0%";
    $("progressStage").textContent = "STARTING";
    $("installMessage").textContent = "Starting setup...";
    $("installLead").textContent = "This can take a while on a slow connection. Leave this window open.";
    showStep("step-install");
    try {
      const result = await api("/api/setup/start", {
        method: "POST",
        body: JSON.stringify({ engine: state.engine, model: state.model }),
      });
      if (!result.ok) throw new Error("Setup is already running.");
      startPolling();
    } catch (err) {
      setNotice("installError", err.message || String(err), true);
      $("retryInstall").classList.remove("hidden");
    } finally {
      $("startInstall").disabled = false;
    }
  }

  async function finishSetup() {
    const button = $("finishSetup");
    button.disabled = true;
    setNotice("profileError", "", false);
    try {
      const result = await api("/api/setup/finish", {
        method: "POST",
        body: JSON.stringify({
          name: $("nameInput").value.trim() || "sir",
          city: $("cityInput").value.trim(),
          units: state.units,
          voice: $("voiceToggle").checked,
        }),
      });
      if (!result.ok) throw new Error("Could not save the profile.");
      showStep("step-done");
      setTimeout(() => { try { window.close(); } catch (e) { /* the launcher closes it */ } }, 1400);
    } catch (err) {
      setNotice("profileError", err.message || String(err), true);
      button.disabled = false;
    }
  }

  async function scan() {
    try {
      const result = await api("/api/setup/scan");
      renderScan(result);
    } catch (err) {
      setNotice("scanNotice", "Could not inspect this PC: " + (err.message || err), true);
      $("toEngine").disabled = true;
    }
  }

  async function testMic() {
    const button = $("micTest");
    const hint = $("micHint");
    if (state.micStream) {
      stopMic();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      hint.textContent = "Microphone access is not available in this window.";
      return;
    }
    try {
      button.disabled = true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.micStream = stream;
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      state.micAudio = { ctx, source, analyser };
      const data = new Uint8Array(analyser.frequencyBinCount);
      hint.textContent = "Listening... speak normally.";
      button.textContent = "Stop";
      button.disabled = false;
      const tick = () => {
        if (!state.micAudio) return;
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i];
        const level = Math.min(100, (sum / data.length) * 2.4);
        $("micLevel").style.width = level + "%";
        requestAnimationFrame(tick);
      };
      tick();
      state.micTimer = setTimeout(stopMic, 12000);
    } catch (err) {
      button.disabled = false;
      hint.textContent = "Microphone permission was not granted. You can still type.";
    }
  }

  function stopMic() {
    if (state.micTimer) { clearTimeout(state.micTimer); state.micTimer = null; }
    if (state.micStream) {
      state.micStream.getTracks().forEach((track) => track.stop());
      state.micStream = null;
    }
    if (state.micAudio) {
      try { state.micAudio.ctx.close(); } catch (e) { /* ignore */ }
      state.micAudio = null;
    }
    $("micLevel").style.width = "0%";
    const button = $("micTest");
    if (button) { button.textContent = "Test mic"; button.disabled = false; }
    $("micHint").textContent = "Optional. Voice input uses the browser's speech recognition.";
  }

  $("toEngine").addEventListener("click", () => showStep("step-engine"));
  $("backCheck").addEventListener("click", () => showStep("step-check"));
  $("startInstall").addEventListener("click", beginInstall);
  $("retryInstall").addEventListener("click", beginInstall);
  $("cancelInstall").addEventListener("click", async () => {
    stopPolling();
    try { await api("/api/setup/cancel", { method: "POST", body: "{}" }); } catch (e) { /* ignore */ }
    $("installMessage").textContent = "Setup cancelled. AUDEN will close.";
  });
  $("finishSetup").addEventListener("click", finishSetup);
  $("micTest").addEventListener("click", testMic);

  document.querySelectorAll("#unitSeg button").forEach((button) => {
    button.addEventListener("click", () => {
      state.units = button.dataset.unit;
      document.querySelectorAll("#unitSeg button").forEach((n) => n.classList.toggle("on", n === button));
    });
  });

  scan();
}());
