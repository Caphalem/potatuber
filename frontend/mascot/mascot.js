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

  // Leading slash matters: this page lives at /mascot/, the model doesn't.
  const model = await PIXI.live2d.Live2DModel.from("/" + cfg.model, {
    autoInteract: cfg.follow_mouse,
  });
  app.stage.addChild(model);
  model.anchor.set(0.5, 0);
  model.x = window.innerWidth / 2;

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
    model.internalModel.coreModel.setParameterValueById(
      "ParamMouthOpenY", mouthOpen
    );
    model.internalModel.coreModel.setParameterValueById(
      "ParamMouthOpen", mouthOpen
    );
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
    const target = Math.min(1, volume * 8);
    mouthOpen += (target - mouthOpen) * 0.3;
  });

  // ── The pipe ──
  const ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    // This page loads the model, so it's the one who reports her wardrobe.
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

      // Announce this sentence exactly when its audio starts playing —
      // the mascot is the timing authority for everyone else.
      if (pendingSubtitle !== null) {
        const text = pendingSubtitle;
        pendingSubtitle = null;
        const delay = (playhead - audioCtx.currentTime) * 1000;
        const seq = ++subtitleSeq;
        setTimeout(() => {
          ws.send(JSON.stringify({ type: "now_saying", text }));
        }, delay);

        // Clear after this sentence's audio ends — unless a newer
        // sentence has taken the stage by then.
        const clearDelay = delay + buffer.duration * 1000 + 400;
        setTimeout(() => {
          if (seq === subtitleSeq) {
            ws.send(JSON.stringify({ type: "now_saying", text: "" }));
          }
        }, clearDelay);
      }

      playhead += buffer.duration;
    }

    if (event.type === "set_expression") {
      model.expression(event.name);
    }
  };
}

document.getElementById("wake").onclick = wakeUp;