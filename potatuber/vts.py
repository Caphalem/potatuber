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


class VTS:
    def __init__(self, cfg):
        self.url = f"ws://localhost:{cfg.port}"
        self.mode = cfg.mode
        self.item_name = cfg.item_name
        self.mouth_gain = cfg.mouth_gain
        # In item mode we inject OUR parameter, not MouthOpen — otherwise
        # we'd be stomping the streamer's own mouth every time she talks.
        self.mouth_param = CUSTOM_MOUTH if cfg.mode == "item" else cfg.mouth_param
        self.mouth = 0.0
        self.ws = None
        self._id = 0
        self._lock = asyncio.Lock()
        self._instance = None      # item mode: her instance ID in the scene
        self._hotkeys = {}         # item mode: expression name -> hotkeyID
        self._clear_hotkey = None  # item mode: a RemoveAllExpressions hotkey
        self._active = None        # item mode: which expression we toggled on

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
        try:
            self.ws = await websockets.connect(self.url)
        except OSError as e:
            raise RuntimeError(
                "Can't reach VTube Studio — is it running with the API enabled?"
            ) from e

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

        if self.mode == "item":
            await self._ensure_parameters()
            if await self._find_item() is None:
                print(f"🥔 Live2D item '{self.item_name}' isn't in the scene yet — "
                      f"load and pin her in VTS, I'll keep looking.")

        asyncio.create_task(self._heartbeat())

    async def _heartbeat(self) -> None:
        """VTS forgets injected parameters after one second of silence, so we
        send the mouth value continuously — that's also what makes lip sync live."""
        complained = False
        while True:
            try:
                await self.request("InjectParameterDataRequest", {
                    "faceFound": True,
                    "mode": "set",
                    "parameterValues": [{"id": self.mouth_param, "value": self.mouth}],
                })
            except Exception as e:
                if not complained:
                    print(f"🥔 VTS heartbeat error: {type(e).__name__}: {e}")
                    complained = True
            await asyncio.sleep(1 / 30)

    # ── item mode helpers ─────────────────────────────────────────────

    async def _ensure_parameters(self) -> None:
        """Create our custom tracking input. Safe to repeat — VTS just updates
        it if it already exists. Persists in VTS's config between sessions."""
        await self.request("ParameterCreationRequest", {
            "parameterName": CUSTOM_MOUTH,
            "explanation": "Driven by PotaTuber's voice. Map your item's mouth to this.",
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
        """True if the item exists in VTS's Items folder and we read its hotkeys."""
        try:
            data = await self.request("HotkeysInCurrentModelRequest",
                                      {"live2DItemFileName": self.item_name})
        except RuntimeError:
            return False  # item file doesn't exist (yet) — see expressions()
        for hk in data["availableHotkeys"]:
            if hk["type"] == "ToggleExpression" and hk["name"]:
                self._hotkeys[hk["name"]] = hk["hotkeyID"]
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
        return [e["name"] for e in data["expressions"]]

    async def set_expression(self, name: str) -> None:
        if self.mode == "item":
            await self._set_item_expression(name)
            return
        data = await self.request("ExpressionStateRequest", {"details": False})
        for e in data["expressions"]:
            if e["active"] and e["name"] != name:
                await self.request("ExpressionActivationRequest",
                                   {"expressionFile": e["file"], "active": False})
        if name != "neutral":
            await self.request("ExpressionActivationRequest",
                               {"expressionFile": f"{name}.exp3.json", "active": True})

    async def _set_item_expression(self, name: str) -> None:
        """Items only expose expressions through hotkeys, and those TOGGLE —
        so we remember what we turned on and toggle it off before the next."""
        instance = await self._find_item()
        if not instance:
            print(f"🥔 Can't make a face — item '{self.item_name}' isn't loaded.")
            return

        async def trigger(hotkey_id):
            await self.request("HotkeyTriggerRequest",
                               {"hotkeyID": hotkey_id, "itemInstanceID": instance})

        if self._clear_hotkey:
            await trigger(self._clear_hotkey)
        elif self._active in self._hotkeys:
            await trigger(self._hotkeys[self._active])  # toggle it back off
        self._active = None

        if name != "neutral" and name in self._hotkeys:
            await trigger(self._hotkeys[name])
            self._active = name

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play one sentence through the speakers, updating self.mouth as it
        goes. Blocking — call via asyncio.to_thread."""
        block = int(sample_rate * 0.03)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16") as out:
            for i in range(0, len(audio), block):
                chunk = audio[i:i + block]
                rms = np.sqrt(np.mean((chunk.astype(np.float32) / 32768) ** 2))
                self.mouth = float(min(1.0, rms * self.mouth_gain))
                out.write(chunk)
        self.mouth = 0.0