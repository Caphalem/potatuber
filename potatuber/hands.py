"""The potato's hands: things she can actually DO, not just say.

A tool is a plain Python function plus a schema describing it to the LLM.
Register both, and the brain takes care of the rest. Want to give her a
new ability? Write a function, describe it, register it. That's all.

Tools return a string — that's what she "learns" happened. If a tool also
needs to tell the browser something (like changing her expression), it can
return (string, [events]) instead.
"""

from potatuber.events import SetExpression


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


def make_default_hands(expressions: list[str]) -> Hands:
    """The potato's starter kit: one tool, her own face."""
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
                "description": f"Change your facial expression. Available: {', '.join(expressions)}",
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

    return hands