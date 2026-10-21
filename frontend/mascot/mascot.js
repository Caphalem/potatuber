// The potato's face: renders the Live2D model and animates it from
// the events flowing through the WebSocket. This page is the mascot —
// input happens in the console, timing of audio happens right here.

let mouthOpen = 0; // written by the volume meter, read by the puppet

async function wakeUp() {
  document.getElementById("wake").style.display = "none";

  const full = await (await fetch("/config")).json();
  const cfg = full.face;

  // ── Audio: one analyser sits between all speech and the speakers ──
  const audioCtx = new AudioContext();
  const analyser = audioCtx.createAnalyser();
  const gain = audioCtx.createGain();
  analyser.fftSize = 1024;
  gain.gain.value = full.voice.volume;
  analyser.connect(gain);
  gain.connect(audioCtx.destination);
  let playhead = 0;

  // ── Mouth form: a crude vowel shape from spectral brightness ──
  const spectrum = new Uint8Array(analyser.frequencyBinCount);
  const hzPerBin = audioCtx.sampleRate / analyser.fftSize;
  let mouthForm = 0;

  // ── Stage: PixiJS canvas + the Live2D model ──
  const app = new PIXI.Application({
    view: document.getElementById("stage"),
    resizeTo: window,
    backgroundAlpha: 0,
  });

  // Fetch the model's settings ourselves so we can tweak them before
  // Live2D sees them. The url field lets relative file paths resolve.
  const settingsUrl = "/" + cfg.model;
  const settings = await (await fetch(settingsUrl)).json();
  settings.url = settingsUrl;
  // Her expressions come from scanning the folder, not from this array —
  // see scan_expressions() in server.py. Same rule as VTube Studio.
  settings.FileReferences.Expressions = full.expressions;

  if (cfg.idle_motion) {
    // pixi-live2d-display autoplays whatever is in the "Idle" group — so
    // replacing that group is all it takes to give her a custom idle.
    // (This is also the pattern you'd use to add a play_motion tool.)
    settings.FileReferences.Motions ??= {};
    // FadeInTime 0: idle motions loop forever, so there's nothing to fade in
    // from — and a nonzero fade caused a strange progressive eyelid flicker
    // whenever an expression was active. Zero fade fixed it.
    settings.FileReferences.Motions.Idle = [
      { File: cfg.idle_motion, FadeInTime: 0, FadeOutTime: 0 },
    ];
  }

  const model = await PIXI.live2d.Live2DModel.from(settings, {
    autoInteract: false, // Python drives focus() — see follow_cursor()
  });
  app.stage.addChild(model);
  model.anchor.set(0.5, 0);
  model.x = window.innerWidth / 2;

  if (cfg.idle_motion) {
    // A custom idle owns her eyes — same rule as VTube Studio. Auto-blink
    // would otherwise steal single frames at each loop boundary, advancing
    // the blink one step at a time: a slow, creepy eyelid staircase.
    // Want her to blink? Put blink keyframes in your idle motion.
    model.internalModel.eyeBlink = undefined;
  }

  // Python feeds us the cursor position (see follow_cursor). We store it as
  // a target and ease toward it every frame — macOS delivers those updates
  // unevenly, and this makes arrival timing stop mattering.
  let lookTarget = null;
  let lookCurrent = null;

  window.lookAt = (x, y) => { lookTarget = { x, y }; };

  // Fit her to the window once, then let the user zoom on top of that.
  const baseScale = (window.innerHeight * 0.95) / model.internalModel.height;
  let zoom = parseFloat(localStorage.getItem("zoom") ?? "1");
  model.scale.set(baseScale * zoom);

  document.getElementById("stage").addEventListener("wheel", (e) => {
    e.preventDefault();
    zoom *= e.deltaY < 0 ? 1.1 : 0.9;
    zoom = Math.min(3, Math.max(0.2, zoom));
    model.scale.set(baseScale * zoom);
    localStorage.setItem("zoom", zoom);
  });

  // ── Toggles: outfit pieces that survive her emotions ──
  // pixi-live2d-display only holds ONE expression at a time, so a scarf
  // routed through model.expression() would vanish the moment she smiled.
  // Instead we load the toggle files ourselves and apply their parameters
  // every frame — in the same hook as the mouth flap.
  const modelDir = cfg.model.substring(0, cfg.model.lastIndexOf("/") + 1);
  const toggles = {};               // name -> [{Id, Value, Blend}]
  const activeToggles = new Set();
  for (const e of model.internalModel.settings.expressions ?? []) {
    if (!cfg.toggles.includes(e.Name)) continue;
    const exp = await (await fetch("/" + modelDir + e.File)).json();
    toggles[e.Name] = exp.Parameters;
  }

  // Toggles are applied AFTER the motion manager saves its parameters — the
  // same place expressions live. Applying them before the save bakes their
  // Add values into the baseline forever (ask the yellow scarf).
  model.internalModel.on("beforeModelUpdate", () => {
    const core = model.internalModel.coreModel;
    for (const name of activeToggles) {
      for (const p of toggles[name]) {
        const blend = p.Blend ?? "Add";
        if (blend === "Add") core.addParameterValueById(p.Id, p.Value);
        else if (blend === "Multiply") core.multiplyParameterValueById(p.Id, p.Value);
        else core.setParameterValueById(p.Id, p.Value);
      }
    }
  });

  // ── Mouth flap: idle motions overwrite parameters every frame, so we
  // sneak our mouth value in right AFTER the motion update. ──
  const mm = model.internalModel.motionManager;
  const originalUpdate = mm.update.bind(mm);
  mm.update = (...args) => {
    const result = originalUpdate(...args);
    const core = model.internalModel.coreModel;
    if (cfg.mouth_form_param && Math.abs(mouthForm) > 0.01) {
      core.setParameterValueById(cfg.mouth_form_param, mouthForm);
    }
    for (const param of cfg.mouth_params) {
      core.setParameterValueById(param, mouthOpen);
    }
    return result;
  };

  // ── Volume meter: how loud is she right now? → how open is the mouth and in what form ──
  const samples = new Uint8Array(analyser.fftSize);
  app.ticker.add(() => {
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (const s of samples) {
      const dev = (s - 128) / 128;
      sum += dev * dev;
    }
    const volume = Math.sqrt(sum / samples.length);
    const target = Math.min(1, volume * cfg.mouth_gain);
    mouthOpen += (target - mouthOpen) * 0.3;

    if (cfg.mouth_form_param) {
      if (mouthOpen > 0.05) {
        analyser.getByteFrequencyData(spectrum);
        // Only the speech band: the crunchy cloning artifacts above ~6 kHz
        // would otherwise drag the centroid bright on every voice.
        const maxBin = Math.min(spectrum.length, Math.floor(6000 / hzPerBin));
        let weighted = 0, total = 0;
        for (let i = 0; i < maxBin; i++) {
          weighted += i * hzPerBin * spectrum[i];
          total += spectrum[i];
        }
        const centroid = total ? weighted / total : 0;
        const [lo, hi] = cfg.mouth_form_range;
        const t = (centroid - lo) / (hi - lo);
        const target = Math.max(-1, Math.min(1, t * 2 - 1));
        mouthForm += (target - mouthForm) * 0.25;
      } else {
        // Silent: ease back to neutral. Because we write BEFORE the motion
        // manager saves, our value becomes the baseline — so the last vowel
        // would stick to her face forever if we just stopped writing.
        mouthForm += (0 - mouthForm) * 0.1;
      }
    }

    if (lookTarget) {
      if (!lookCurrent) lookCurrent = { ...lookTarget };
      lookCurrent.x += (lookTarget.x - lookCurrent.x) * 0.15;
      lookCurrent.y += (lookTarget.y - lookCurrent.y) * 0.15;
      model.focus(lookCurrent.x, lookCurrent.y);
    }
  });

  // ── The pipe ──
  const ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    // This page loads the model, so it's the one who reports her wardrobe.
    // (The server adds "Neutral" itself — it works for any body she wears.)
    const expressions =
      (model.internalModel.settings.expressions ?? []).map((e) => e.Name);
    ws.send(JSON.stringify({ type: "model_info", expressions }));
  };

  let pendingSubtitle = null; // set by speak_start, scheduled by its audio
  let subtitleSeq = 0;

  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);

    if (event.type === "speak_start") {
      pendingSubtitle = event.text;
    }

    if (event.type === "audio_chunk") {
      const bytes = Uint8Array.from(atob(event.data), (c) => c.charCodeAt(0));
      const int16 = new Int16Array(bytes.buffer);
      const floats = Float32Array.from(int16, (s) => s / 32768);

      const buffer = audioCtx.createBuffer(1, floats.length, event.sample_rate);
      buffer.getChannelData(0).set(floats);

      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(analyser);

      playhead = Math.max(playhead, audioCtx.currentTime);
      source.start(playhead);

      // Announce this sentence exactly when its audio starts playing.
      if (pendingSubtitle !== null) {
        const text = pendingSubtitle;
        pendingSubtitle = null;
        subtitleSeq++;
        const delay = (playhead - audioCtx.currentTime) * 1000;
        setTimeout(() => {
          ws.send(JSON.stringify({ type: "now_saying", text }));
        }, delay);
      }

      playhead += buffer.duration;
    }

    if (event.type === "speak_end") {
      if (pendingSubtitle !== null) {
        // No audio ever came (an emoji-only "sentence") — drop it, or it
        // would get shown on top of the NEXT sentence's audio.
        pendingSubtitle = null;
        return;
      }
      // All of this sentence's audio is queued now, so the playhead sits
      // exactly at its end. That's when the subtitle should disappear —
      // unless a newer sentence has taken the stage by then.
      const seq = subtitleSeq;
      const delay = (playhead - audioCtx.currentTime) * 1000 + 400;
      setTimeout(() => {
        if (seq === subtitleSeq) {
          ws.send(JSON.stringify({ type: "now_saying", text: "" }));
        }
      }, delay);
    }

    if (event.type === "response_end") {
      const delay = Math.max(0, (playhead - audioCtx.currentTime) * 1000);
      setTimeout(() => ws.send(JSON.stringify({ type: "playback_done" })), delay);
    }

    if (event.type === "set_expression") {
      if (event.name.toLowerCase() === "neutral") {
        // Not a file — this clears whatever expression is applied and
        // returns her to the model's default parameters.
        model.internalModel.motionManager.expressionManager?.resetExpression();
      } else {
        model.expression(event.name);
      }
    }

    if (event.type === "set_toggle") {
      if (event.on) {
        // Toggles that touch the same parameters are mutually exclusive —
        // a rigger zeroing a sibling's parameter is the tell.
        const ids = new Set(toggles[event.name].map((p) => p.Id));
        for (const other of activeToggles) {
          if (toggles[other].some((p) => ids.has(p.Id))) activeToggles.delete(other);
        }
        activeToggles.add(event.name);
      } else {
        activeToggles.delete(event.name);
      }
    }
  };

  // Helps people whose rigger used non-standard names — see mouth_params.
  // coreModel is the framework wrapper; getModel() is the raw Cubism core.
  console.log(
    "Live2D parameters:",
    model.internalModel.coreModel.getModel().parameters.ids
  );
}

document.getElementById("wake").onclick = wakeUp;