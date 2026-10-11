"""The potato's hands: things she can actually DO, not just say.

A tool is a plain Python function plus a schema describing it to the LLM.
Register both, and the brain takes care of the rest. Want to give her a
new ability? Write a function, describe it, register it. That's all.

Tools return a string — that's what she "learns" happened. If a tool also
needs to tell the browser something (like changing her expression), it can
return (string, [events]) instead.
"""

from potatuber.events import SetExpression, SetToggle


class Hands:
    def __init__(self):
        self.functions = {}
        self.schemas = []

    def register(self, func, schema: dict) -> None:
        self.functions[schema["function"]["name"]] = func
        self.schemas.append(schema)

    def run(self, name: str, args: dict) -> tuple[str, list]:
        """Run one tool. Always returns (result_text, events_for_browser)."""
        if name not in self.functions:
            return f"Error: no tool named '{name}'.", []
        try:
            result = self.functions[name](**args)
        except Exception as e:  # she WILL fumble sometimes. Be kind about it.
            return f"Error: {e}", []
        if isinstance(result, tuple):
            return result
        return result, []


def make_default_hands(expressions: list[str], toggles: list[str]) -> Hands:
    """The potato's starter kit."""
    hands = Hands()

    if expressions:  # no expressions in the model = she never gets this tool
        def set_expression(name: str):
            if name not in expressions:
                return f"You don't have a '{name}' expression. You have: {expressions}"
            return f"You are now making the '{name}' face.", [SetExpression(name=name)]

        hands.register(set_expression, {
            "type": "function",
            "function": {
                "name": "set_expression",
                "description": (
                    f"Change your facial expression. Use 'Neutral' to return to your "
                    f"resting face when a reaction has passed. Available: {', '.join(expressions)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": expressions,
                            "description": "Which face to make.",
                        }
                    },
                    "required": ["name"],
                },
            },
        })

    if toggles:  # same rules as expressions
        def set_toggle(name: str, on: bool = True):
            if name not in toggles:
                return f"You don't have a '{name}' toggle. You have: {list(toggles)}"
            return (f"'{name}' is now {'on' if on else 'off'}.",
                    [SetToggle(name=name, on=on)])

        hands.register(set_toggle, {
            "type": "function",
            "function": {
                "name": "set_toggle",
                "description": (
                    f"Put on or take off an outfit piece. Unlike expressions, "
                    f"toggles stay until you switch them off. Available: {', '.join(toggles)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": list(toggles)},
                        "on": {"type": "boolean",
                               "description": "true to put it on, false to take it off"},
                    },
                    "required": ["name", "on"],
                },
            },
        })

    return hands