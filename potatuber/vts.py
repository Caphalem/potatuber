"""VTube Studio as her body.

Two flavors:
  mode = "model": she IS the model loaded in VTS. We drive MouthOpen and
                  her expressions directly.
  mode = "item":  she's a Live2D item pinned to YOUR model — the companion
                  on your shoulder. We drive a custom tracking input called
                  PotaTuberMouth (so your own lip sync is untouched) and
                  trigger her expressions through the item's hotkeys.

Python plays the audio itself and streams the volume in at ~30Hz. The first
connection makes VTS ask "allow this plugin?" — the token is saved to
vts_token.json so you're only asked once.
"""

import asyncio
import json
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets

TOKEN_FILE = Path("vts_token.json")
PLUGIN = {"pluginName": "PotaTuber", "pluginDeveloper": "PotaTuber"}
CUSTOM_MOUTH = "PotaTuberMouth"
CUSTOM_FORM = "PotaTuberMouthForm"


class VTS:
    def __init__(self, cfg, toggles: list[str] = (), form_range: list[float] = (1750, 2800), volume: float = 1.0):
        self.url = f"ws://localhost:{cfg.port}"
        self.mode = cfg.mode
        self.item_name = cfg.item_name
        self.mouth_gain = cfg.mouth_gain
        # In item mode we inject OUR parameter, not MouthOpen — otherwise
        # we'd be stomping the streamer's own mouth every time she talks.
        self.mouth_param = CUSTOM_MOUTH if cfg.mode == "item" else cfg.mouth_param
        self.mouth = 0.0
        self.ws = None
        self.toggles = set(toggles)
        self.form_range = form_range
        self.form_param = (CUSTOM_FORM if cfg.mode == "item" else cfg.mouth_form_param)
        self.form = 0.5
        self.volume = volume
        self.output_device = cfg.output_device
        # Only these expressions are hers. Empty = all of them.
        self.allowed = set(cfg.expressions)
        self._id = 0
        self._lock = asyncio.Lock()
        self._instance = None      # item mode: her instance ID in the scene
        self._hotkeys = {}         # item mode: expression name -> hotkeyID
        self._clear_hotkey = None  # item mode: a RemoveAllExpressions hotkey
        self._active = None        # item mode: which expression we toggled on
        self._toggle_on = set()  # item mode: which toggles WE turned on

    def _mine(self, name: str) -> bool:
        return not self.allowed or name in self.allowed
    
    # ── plumbing ──────────────────────────────────────────────────────

    async def request(self, message_type: str, data: dict | None = None) -> dict:
        """One request, one response. The lock keeps the heartbeat and tool
        calls from reading each other's replies off the single pipe."""
        async with self._lock:
            self._id += 1
            await self.ws.send(json.dumps({
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": str(self._id),
                "messageType": message_type,
                "data": data or {},
            }))
            response = json.loads(await self.ws.recv())
        if response["messageType"] == "APIError":
            raise RuntimeError(f"VTS: {response['data']['message']}")
        return response["data"]

    async def connect(self) -> None:
        # 127.0.0.1 rather than localhost: VTS listens on IPv4, and Windows
        # likes to try ::1 first. Takes the resolver out of the equation.
        # Retries because VTS can be slow to answer right after our parts
        # finish loading and the CPU is still catching its breath.
        last_error = None
        for attempt in range(5):
            try:
                self.ws = await websockets.connect(self.url, open_timeout=30)
                break
            except OSError as e:
                last_error = e
                print(f"🥔 VTS not answering ({type(e).__name__}: {e}) — "
                      f"retrying in 2s ({attempt + 1}/5)...")
                await asyncio.sleep(2)
        else:
            raise RuntimeError(
                "Can't reach VTube Studio — is it running with the API enabled?"
            ) from last_error

        token = None
        if TOKEN_FILE.exists():
            token = json.loads(TOKEN_FILE.read_text()).get("token")
        if not token:
            print("🥔 Asking VTube Studio for permission — click Allow in VTS!")
            data = await self.request("AuthenticationTokenRequest", PLUGIN)
            token = data["authenticationToken"]
            TOKEN_FILE.write_text(json.dumps({"token": token}))

        data = await self.request(
            "AuthenticationRequest", {**PLUGIN, "authenticationToken": token}
        )
        if not data["authenticated"]:
            TOKEN_FILE.unlink(missing_ok=True)
            raise RuntimeError("VTS rejected our token. Run again to re-authorize.")

        # Always create our custom inputs, even in model mode — so a model
        # with a built-in mascot can route just the mascot's mouth to us
        # (set mouth_param / mouth_form_param to the PotaTuber ones).
        await self._ensure_parameters()
        if self.mode == "item":
            if await self._find_item() is None:
                print(f"🥔 Live2D item '{self.item_name}' isn't in the scene yet — "
                      f"load and pin her in VTS, I'll keep looking.")

        asyncio.create_task(self._heartbeat())

    async def _heartbeat(self) -> None:
        """VTS forgets injected parameters after one second of silence, so we
        send the mouth values continuously — that's also what makes lip sync live."""
        complained = False
        while True:
            values = [{"id": self.mouth_param, "value": self.mouth}]
            if self.form_param:
                values.append({"id": self.form_param, "value": self.form})
            try:
                await self.request("InjectParameterDataRequest", {
                    # False: we're injecting a couple of parameters, not tracking
                    # a face. Claiming "face found" makes VTS let tracking override
                    # her idle animation — she'd freeze into her default pose.
                    "faceFound": False,
                    "mode": "set",
                    "parameterValues": values,
                })
            except Exception as e:
                if not complained:
                    print(f"🥔 VTS heartbeat error: {type(e).__name__}: {e}")
                    complained = True
            await asyncio.sleep(1 / 30)

    # ── item mode helpers ─────────────────────────────────────────────

    async def _ensure_parameters(self) -> None:
        """Create our custom tracking inputs. Safe to repeat — VTS just updates
        them if they exist. Persists in VTS's config between sessions."""
        for name, explanation in [
            (CUSTOM_MOUTH, "Driven by PotaTuber's voice. Map your item's mouth-open to this."),
            (CUSTOM_FORM, "PotaTuber's vowel shape (0 = round, 1 = wide). Map your item's mouth form to this."),
        ]:
            await self.request("ParameterCreationRequest", {
                "parameterName": name,
                "explanation": explanation,
                "min": 0, "max": 1, "defaultValue": 0,
            })

    async def _find_item(self) -> str | None:
        """Her instance ID in the scene, cached once found. Looked up lazily so
        she can be loaded into VTS after PotaTuber has already started."""
        if self._instance:
            return self._instance
        data = await self.request("ItemListRequest", {
            "includeItemInstancesInScene": True,
            "onlyItemsWithFileName": self.item_name,
        })
        items = data["itemInstancesInScene"]
        self._instance = items[0]["instanceID"] if items else None
        return self._instance

    async def _load_item_hotkeys(self) -> bool:
        """True if the item exists in VTS's Items folder and we read its hotkeys.

        Names come from the expression FILE, not the hotkey's name field —
        so they match the browser and model mode (and the toggles config)
        no matter what the hotkey was called in VTS."""
        try:
            data = await self.request("HotkeysInCurrentModelRequest",
                                      {"live2DItemFileName": self.item_name})
        except RuntimeError:
            return False
        for hk in data["availableHotkeys"]:
            if hk["type"] == "ToggleExpression":
                file = hk.get("file") or ""
                name = file.rsplit("/", 1)[-1].removesuffix(".exp3.json") or hk["name"]
                if name and self._mine(name):
                    self._hotkeys[name] = hk["hotkeyID"]
            elif hk["type"] == "RemoveAllExpressions":
                self._clear_hotkey = hk["hotkeyID"]
        return True

    async def _live2d_item_files(self) -> list[str]:
        """Folder names of every Live2D item VTS knows about — for hints."""
        data = await self.request("ItemListRequest", {"includeAvailableItemFiles": True})
        return [f["fileName"] for f in data["availableItemFiles"] if f["type"] == "Live2D"]

    # ── what server.py calls ──────────────────────────────────────────

    async def expressions(self) -> list[str]:
        """Names for the set_expression tool, from whichever body she's wearing."""
        if self.mode == "item":
            if not await self._load_item_hotkeys():
                available = await self._live2d_item_files()
                print(f"🥔 No Live2D item called '{self.item_name}' in VTS's Items folder, "
                      f"so she has no faces for now. Live2D items VTS can see: {available}")
                return []
            return list(self._hotkeys)
        data = await self.request("ExpressionStateRequest", {"details": False})
        return [e["name"] for e in data["expressions"] if self._mine(e["name"])]

    async def set_expression(self, name: str) -> None:
        if self.mode == "item":
            await self._set_item_expression(name)
            return
        data = await self.request("ExpressionStateRequest", {"details": False})
        files = {e["name"]: e["file"] for e in data["expressions"]}
        for e in data["expressions"]:
            if (e["active"] and e["name"] != name
                    and e["name"] not in self.toggles
                    and self._mine(e["name"])):
                await self.request("ExpressionActivationRequest",
                                   {"expressionFile": e["file"], "active": False})
        if name != "Neutral" and name in files and self._mine(name):
            await self.request("ExpressionActivationRequest",
                               {"expressionFile": files[name], "active": True})

    async def set_toggle(self, name: str, on: bool) -> None:
        if self.mode == "item":
            await self._set_item_toggle(name, on)
            return
        if on:
            # Same rule as the browser: toggles sharing a parameter are a
            # group, so turning one on evicts the others. VTS tells us the
            # parameters with details=True — no file reading needed.
            data = await self.request("ExpressionStateRequest", {"details": True})
            mine = {p["name"] for e in data["expressions"] if e["name"] == name
                    for p in e.get("parameters", [])}
            for e in data["expressions"]:
                if e["active"] and e["name"] in self.toggles and e["name"] != name:
                    if mine & {p["name"] for p in e.get("parameters", [])}:
                        await self.request("ExpressionActivationRequest",
                                           {"expressionFile": e["file"], "active": False})
        await self.request("ExpressionActivationRequest",
                           {"expressionFile": f"{name}.exp3.json", "active": on})

    async def _set_item_toggle(self, name: str, on: bool) -> None:
        """Item hotkeys only TOGGLE, so we track what we turned on and only
        fire when the state actually needs to change. Items don't tell us
        parameters, so toggles are treated as one mutually exclusive group."""
        instance = await self._find_item()
        if not instance or name not in self._hotkeys:
            return

        async def trigger(hk):
            await self.request("HotkeyTriggerRequest",
                               {"hotkeyID": hk, "itemInstanceID": instance})

        if on:
            for other in list(self._toggle_on):
                if other != name:
                    await trigger(self._hotkeys[other])
                    self._toggle_on.discard(other)
            if name not in self._toggle_on:
                await trigger(self._hotkeys[name])
                self._toggle_on.add(name)
        elif name in self._toggle_on:
            await trigger(self._hotkeys[name])
            self._toggle_on.discard(name)

    async def _set_item_expression(self, name: str) -> None:
        """Items only expose expressions through hotkeys, and those TOGGLE —
        so we remember what we turned on and toggle it off before the next.
        Toggles (outfits) are left alone: they have their own method."""
        instance = await self._find_item()
        if not instance:
            print(f"🥔 Can't make a face — item '{self.item_name}' isn't loaded.")
            return

        async def trigger(hk):
            await self.request("HotkeyTriggerRequest",
                               {"hotkeyID": hk, "itemInstanceID": instance})

        # RemoveAllExpressions would nuke the scarf too, so only use it when
        # the model has no toggles at all.
        if self._clear_hotkey and not self.toggles and not self.allowed:
            await trigger(self._clear_hotkey)
        elif self._active in self._hotkeys:
            await trigger(self._hotkeys[self._active])  # toggle the old face off
        self._active = None

        if name != "Neutral" and name in self._hotkeys and name not in self.toggles:
            await trigger(self._hotkeys[name])
            self._active = name

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play one sentence through the set sound output device,
        updating self.mouth as it goes. Blocking — call via asyncio.to_thread."""
        block = int(sample_rate * 0.03)
        with sd.OutputStream(
            samplerate=sample_rate, channels=1, dtype="int16",
            device=self.output_device or None,
        ) as out:
            for i in range(0, len(audio), block):
                chunk = audio[i:i + block]
                floats = chunk.astype(np.float32) / 32768
                rms = np.sqrt(np.mean(floats ** 2))
                self.mouth = float(min(1.0, rms * self.mouth_gain))
                if self.form_param and self.mouth > 0.05:
                    # Mirror the browser's AnalyserNode: it weighs bins in
                    # DECIBELS (clamped to -100..-30 dB).
                    window = np.hanning(len(floats))
                    spectrum = np.abs(np.fft.rfft(floats * window)) / len(floats)
                    db = 20 * np.log10(spectrum + 1e-9)
                    weights = np.clip((db + 100) / 70, 0, 1)
                    freqs = np.fft.rfftfreq(len(floats), 1 / sample_rate)
                    band = freqs < 6000
                    total = weights[band].sum()
                    centroid = (freqs[band] * weights[band]).sum() / total if total else 0
                    lo, hi = self.form_range
                    t = (centroid - lo) / (hi - lo)
                    self.form += (float(min(1.0, max(0.0, t))) - self.form) * 0.25
                out.write(np.clip(chunk * self.volume, -32768, 32767).astype(np.int16))
        self.mouth = 0.0
        self.form = 0.5