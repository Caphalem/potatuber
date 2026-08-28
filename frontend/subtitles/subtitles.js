// The subtitle window: displays whatever the mascot says she's saying.
// No audio, no model, no input — the dumbest page in the potato. 🥔

const ws = new WebSocket(`ws://${location.host}/ws`);

ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);
  if (event.type === "now_saying") {
    document.getElementById("subtitle").textContent = event.text;
  }
};