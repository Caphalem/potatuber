// The console: watch the conversation, type into it. No audio plays here,
// so no wake button is needed — only audio requires a user gesture.

const log = document.getElementById("log");
const banner = document.getElementById("banner");
let ws = null;
let botLine = null; // her sentences accumulate into one entry per reply
let herName = "Her";
let wake = null;
let cancel = null;

function append(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
  return p;
}

function appendTool(name, args, result) {
  const shown = typeof args === "string" ? args : JSON.stringify(args);
  append("tool", `⚙ ${name}(${shown}) → ${result}`);
  botLine = null;  // her next sentence starts a new line, below the tool
}

function sleep(ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    cancel = () => { clearTimeout(timer); resolve(); };
  });
}

async function waitForServer() {
  // Knock on the HTTP door until someone answers, THEN open the socket.
  // Each knock gets 2 seconds — some browsers (Librewolf) let a fetch to a
  // vanished server hang for 90s instead of failing fast.
  while (true) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 2000);
    cancel = () => abort.abort();
    try {
      const r = await fetch("/config", { cache: "no-store", signal: abort.signal });
      if (r.ok) return;
    } catch {}
    clearTimeout(timeout);
    await sleep(1000);
  }
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    banner.style.display = "none";
  };

  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);

    if (event.type === "history") {
      // Rebuild the log from what the brain actually remembers. After a
      // backend restart that's nothing — which is the truth.
      log.replaceChildren();
      botLine = null;
      for (const m of event.messages) {
        if (m.role === "user") append("you", "You: " + m.text);
        else if (m.role === "tool") appendTool(m.name, m.args, m.result);
        else append("her", herName + ": " + m.text);
      }
    }

    if (event.type === "you_said") {
      append("you", "You: " + event.text);
      botLine = null;
    }

    if (event.type === "speak_start") {
      if (!botLine) botLine = append("her", herName + ":");
      botLine.textContent += " " + event.text;
      log.scrollTop = log.scrollHeight;
    }

    if (event.type === "state") {
      const el = document.getElementById("state");
      el.dataset.state = event.state;
      el.querySelector("b").textContent = event.state;
    }

    if (event.type === "eyes_state") {
      document.getElementById("eyes").style.display = event.available ? "flex" : "none";
      document.getElementById("eyes-toggle").checked = event.enabled;
      document.getElementById("seen").style.display = event.enabled ? "block" : "none";
    }

    if (event.type === "seen") {
      const box = document.getElementById("seen");
      const img = box.querySelector("img");
      img.src = "data:image/jpeg;base64," + event.image;
      img.style.display = "block";
      box.querySelector(".hint").style.display = "none";
      box.querySelector("summary").textContent =
        "What she saw (" + new Date().toLocaleTimeString() + ")";
    }

    if (event.type === "tool_use") {
      const args = typeof event.args === "string" ? event.args : JSON.stringify(event.args);
      append("tool", `⚙ ${event.name}(${args}) → ${event.result}`);
      botLine = null;  // her next sentence starts a new line, below the tool
    }

    if (event.type === "tools") {
      const box = document.getElementById("tools");
      const n = event.tools.length;
      box.querySelector("summary").textContent =
        n ? `🖐 ${n} tool${n === 1 ? "" : "s"}` : "🖐 No hands yet";
      box.querySelector("ul").replaceChildren(...event.tools.map((t) => {
        const li = document.createElement("li");
        li.innerHTML = `<b>${t.name}</b> — ${t.description}`;
        return li;
      }));
    }
  };

  ws.onclose = () => {
    banner.style.display = "block";
    waitForServer().then(connect);
  };
}

(async () => {
  const cfg = await (await fetch("/config")).json();
  herName = cfg.character.name;
  document.title = `${herName} - PotaTuber Console 🥔`;
  connect();
})();


document.getElementById("chat").onsubmit = (e) => {
  e.preventDefault();
  if (ws.readyState !== WebSocket.OPEN) return; // she's not listening right now
  const input = document.getElementById("text");
  ws.send(JSON.stringify({ type: "user_says", text: input.value }));
  input.value = "";
};

document.getElementById("eyes-toggle").onchange = (e) => {
  ws.send(JSON.stringify({ type: "set_eyes", enabled: e.target.checked }));
};

document.getElementById("reconnect").onclick = () => { if (cancel) cancel(); };