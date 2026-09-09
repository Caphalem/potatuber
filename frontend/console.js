// The console: watch the conversation, type into it. No audio plays here,
// so no wake button is needed — only audio requires a user gesture.

const log = document.getElementById("log");
const banner = document.getElementById("banner");
let ws = null;
let botLine = null; // her sentences accumulate into one entry per reply

function append(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
  return p;
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
        else append("her", m.text);
      }
    }

    if (event.type === "you_said") {
      append("you", "You: " + event.text);
      botLine = null;
    }

    if (event.type === "speak_start") {
      if (!botLine) botLine = append("her", "");
      botLine.textContent += (botLine.textContent ? " " : "") + event.text;
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
    }
  };

  ws.onclose = () => {
    // The backend went away — restarted, probably. Keep knocking until it's
    // back; the history event will rebuild the log when it is.
    banner.style.display = "block";
    setTimeout(connect, 1000);
  };
}

connect();

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