"""VTube Studio as her body.

Instead of the browser mascot, PotaTuber drives a model loaded in VTube
Studio through its public API (JSON over WebSocket, port 8001 by default).
Python plays the audio itself and streams the volume in as MouthOpen.

The first connection makes VTS pop up an "allow this plugin?" dialog. The
token it hands back is saved to vts_token.json so you're only asked once.
"""

import asyncio
import json
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets

TOKEN_FILE = Path("vts_token.json")
PLUGIN = {"pluginName": "PotaTuber", "pluginDeveloper": "PotaTuber"}


class VTS:
    def __init__(self, port: int = 8001, mouth_param: str = "MouthOpen", mouth_gain: int = 4):
        self.url = f"ws://localhost:{port}"
        self.mouth_param = mouth_param
        self.ws = None
        self.mouth = 0  # written by playback, read by the heartbeat
        self.mouth_gain = mouth_gain
        self._id = 0
        self._lock = asyncio.Lock()

    async def request(self, message_type: str, data: dict | None = None) -> dict:
        """One request, one response. Every VTS message has this shape.

        The lock matters: a WebSocket is a single pipe, and the heartbeat is
        constantly talking on it. Without this, two coroutines would wait for
        the same reply and get each other's responses back.
        """
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
        self.ws = await websockets.connect(self.url)

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
            TOKEN_FILE.unlink(missing_ok=True)  # revoked — ask again next run
            raise RuntimeError("VTS rejected our token. Run again to re-authorize.")

        asyncio.create_task(self._heartbeat())

    async def _heartbeat(self) -> None:
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

    async def expressions(self) -> list[str]:
        """Names of the loaded model's expressions, for the set_expression tool."""
        data = await self.request("ExpressionStateRequest", {"details": False})
        return [e["name"] for e in data["expressions"]]

    async def set_expression(self, name: str) -> None:
        data = await self.request("ExpressionStateRequest", {"details": False})
        for e in data["expressions"]:
            if e["active"] and e["name"] != name:
                await self.request("ExpressionActivationRequest",
                                   {"expressionFile": e["file"], "active": False})
        if name != "neutral":
            await self.request("ExpressionActivationRequest",
                               {"expressionFile": f"{name}.exp3.json", "active": True})

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play one sentence through the speakers, updating self.mouth as it
        goes. Blocking — call via asyncio.to_thread."""
        block = int(sample_rate * 0.03)  # ~30ms chunks
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16") as out:
            for i in range(0, len(audio), block):
                chunk = audio[i:i + block]
                rms = np.sqrt(np.mean((chunk.astype(np.float32) / 32768) ** 2))
                self.mouth = float(min(1.0, rms * self.mouth_gain))  # plain float — numpy types aren't JSON
                out.write(chunk)
        self.mouth = 0.0