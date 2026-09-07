// The potato's face: renders the Live2D model and animates it from
// the events flowing through the WebSocket. This page is the mascot —
// input happens in the console, timing of audio happens right here.

let mouthOpen = 0; // written by the volume meter, read by the puppet

async function wakeUp() {
  document.getElementById("wake").style.display = "none";

  const cfg = await (await fetch("/config")).json();

  // ── Audio: one analyser sits between all speech and the speakers ──
  const audioCtx = new AudioContext();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.connect(audioCtx.destination);
  let playhead = 0;

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

  // ── Mouth flap: idle motions overwrite parameters every frame, so we
  // sneak our mouth value in right AFTER the motion update. ──
  const mm = model.internalModel.motionManager;
  const originalUpdate = mm.update.bind(mm);
  mm.update = (...args) => {
    const result = originalUpdate(...args);
    for (const param of cfg.mouth_params) {
      model.internalModel.coreModel.setParameterValueById(param, mouthOpen);
    }
    return result;
  };

  // ── Volume meter: how loud is she right now? → how open is the mouth ──
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

    if (lookTarget) {
      if (!lookCurrent) lookCurrent = { ...lookTarget };
      lookCurrent.x += (lookTarget.x - lookCurrent.x) * 0.15;
      lookCurrent.y += (lookTarget.y - lookCurrent.y) * 0.15;
      model.focus(lookCurrent.x, lookCurrent.y);
    }
  });

  // ── The pipe ──
  const ws = new WebSocket(`ws://${location.host}/ws`);

  if (event.type === "set_expression") {
    if (event.name === "neutral") {
      // Not a file — this clears whatever expression is applied and
      // returns her to the model's default parameters.
      model.internalModel.motionManager.expressionManager?.resetExpression();
    } else {
      model.expression(event.name);
    }
  }

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

    if (event.type === "set_expression") {
      model.expression(event.name);
    }
  };

  // Helps people whose rigger used non-standard names — see mouth_params.
  console.log("Live2D parameters:", model.internalModel.coreModel.parameters.ids);
}

document.getElementById("wake").onclick = wakeUp;