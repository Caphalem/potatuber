// The console: watch the conversation, type into it. No audio plays here,
// so no wake button is needed — only audio requires a user gesture.

const log = document.getElementById("log");
let botLine = null; // her sentences accumulate into one entry per reply

function append(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
  return p;
}

const ws = new WebSocket(`ws://${location.host}/ws`);

ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);

  if (event.type === "you_said") {
    append("you", "You: " + event.text);
    botLine = null;
  }

  if (event.type === "speak_start") {
    if (!botLine) botLine = append("her", "");
    botLine.textContent += (botLine.textContent ? " " : "") + event.text;
    log.scrollTop = log.scrollHeight;
  }

  if (event.type === "eyes_state") {
    document.getElementById("eyes").style.display = event.available ? "inline" : "none";
    document.getElementById("eyes-toggle").checked = event.enabled;
  }
};

document.getElementById("chat").onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById("text");
  ws.send(JSON.stringify({ type: "user_says", text: input.value }));
  input.value = "";
};

document.getElementById("eyes-toggle").onchange = (e) => {
  ws.send(JSON.stringify({ type: "set_eyes", enabled: e.target.checked }));
};