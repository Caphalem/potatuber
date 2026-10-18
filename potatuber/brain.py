"""The potato's brain: turns conversation into a reply, one sentence at a time.

She doesn't run the LLM herself — she talks to one over the OpenAI-compatible
API that basically every LLM tool speaks these days (LM Studio, Ollama,
llama-server, even actual cloud APIs). That standardization is why this file
is so short: one client, every backend.

Try it standalone (with LM Studio's server running):
    uv run python -m potatuber.brain "What are you, exactly?"
"""

import json

from openai import NOT_GIVEN, OpenAI

from potatuber.events import ToolUse

SENTENCE_ENDINGS = ".!?…"


class Brain:
    def __init__(self, base_url, model, system_prompt, max_history, reminder="", hands=None):
        # api_key is required by the client but ignored by local servers.
        self.client = OpenAI(base_url=base_url, api_key="potato")
        self.model = model
        self.messages = [{"role": "system", "content": system_prompt}]
        self.hands = hands
        self.max_history_chars = max_history
        self.reminder = reminder

    def _trim_history(self) -> None:
        """Keep the conversation from outgrowing the model's context window.

        We can't count tokens — every provider does it differently — so we
        use the classic approximation: 1 token is roughly 4 characters.
        When the history gets too big, the OLDEST exchanges are forgotten
        first. The system prompt is never dropped: it's who she is.

        We always cut at a user-message boundary. Cutting mid-exchange
        could orphan a tool result from its tool call, which breaks the API.
        """
        def size() -> int:
            return sum(len(str(m.get("content") or "")) for m in self.messages)

        while size() > self.max_history_chars and len(self.messages) > 3:
            del self.messages[1]  # oldest message after the system prompt
            while len(self.messages) > 1 and self.messages[1]["role"] != "user":
                del self.messages[1]  # ...and its whole exchange

    def _ephemeral(self, user_text: str, image: str | None) -> dict:
        """The user's latest message, with everything that should exist for
        ONE request only glued on: character reminder, screenshot, whatever
        comes later. None of it is ever stored in self.messages."""
        text = user_text
        if self.reminder:
            text = f"[Reminder: {self.reminder}]\n\n{text}"
        if image is None:
            return {"role": "user", "content": text}
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            ],
        }

    def think(self, user_text, image: str | None):
        """Reply to the user, yielding items as they form:
            ("say", sentence)  — speak this
            ("event", event)   — a tool did something the browser should know

        Tool calls arrive as STREAMING FRAGMENTS — a name here, half a JSON
        string there — keyed by index. We glue them together until the
        stream ends, run the tools, tell her what happened, and let her
        continue. That loop is the whole secret of "agents", by the way.
        """
        checkpoint = len(self.messages)
        # History stores the CLEAN message — the reminder is glued on
        # transiently per-request, so it always sits right next to where
        # she's generating instead of fading into the distant past.
        self.messages.append({"role": "user", "content": user_text})

        try:
            while True:
                request_messages = list(self.messages)
                if self.reminder:
                    request_messages[checkpoint] = self._ephemeral(user_text, image)

                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=request_messages,
                    tools=self.hands.schemas if self.hands else NOT_GIVEN,
                    stream=True
                )

                reply, sentence, calls = "", "", {}
                for chunk in stream:
                    delta = chunk.choices[0].delta

                    for tc in delta.tool_calls or []:
                        acc = calls.setdefault(
                            tc.index, {"id": "", "name": "", "arguments": ""}
                        )
                        acc["id"] = tc.id or acc["id"]
                        if tc.function:
                            acc["name"] = tc.function.name or acc["name"]
                            acc["arguments"] += tc.function.arguments or ""

                    token = delta.content or ""
                    reply += token
                    sentence += token
                    if token and token[-1] in SENTENCE_ENDINGS:
                        yield ("say", sentence.strip())
                        sentence = ""
                if sentence.strip():
                    yield ("say", sentence.strip())

                if not calls:  # no tools wanted: we're done
                    self.messages.append({"role": "assistant", "content": reply})
                    self._trim_history()
                    return

                # She wants to use her hands. Record the request...
                self.messages.append({
                    "role": "assistant",
                    "content": reply or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": c["arguments"]
                            },
                        }
                        for c in calls.values()
                    ],
                })

                # ...run each tool, tell her what happened...
                for c in calls.values():
                    try:
                        args = json.loads(c["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = c["arguments"]
                        result, events = "Error: your arguments weren't valid JSON.", []
                    else:
                        result, events = self.hands.run(c["name"], args)
                    yield ("event", ToolUse(name=c["name"], args=args, result=result))
                    for event in events:
                        yield ("event", event)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": c["id"],
                        "content": result
                    })
                # ...and loop: she sees the results and continues her reply.
        except Exception:
            # A failed request must never leave half an exchange behind —
            # the API demands alternating user/assistant roles, so a
            # stranded user message poisons every future request.
            # Roll back to the last known-good history and re-raise.
            del self.messages[checkpoint:]
            raise

    def add_instructions(self, text: str) -> None:
        """Append extra instructions to the system prompt.

        Used for things we only learn at runtime — like which expressions
        the Live2D model actually has, which the frontend tells us after
        it loads. Skips duplicates, since a page reload re-sends model_info.
        """
        if text not in self.messages[0]["content"]:
            self.messages[0]["content"] += "\n" + text

if __name__ == "__main__":
    import sys

    from potatuber.config import load

    config = load()
    brain = Brain(
        base_url=config.brain.base_url,
        model=config.brain.model,
        system_prompt=config.character.system_prompt,
        max_history_chars=config.brain.max_history
    )

    text = " ".join(sys.argv[1:]) or "Hello! Who are you?"
    for sentence in brain.think(text):
        print(f"🥔 {sentence}")