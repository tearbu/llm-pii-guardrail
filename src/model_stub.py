"""Stand-in for the model behind the guardrail.

A real deployment would forward the redacted prompt to an LLM API
at this point. This project never does that: no API keys, no network
calls, nothing leaves the machine. The stub is deterministic on
purpose. It reads the redacted prompt, notes which placeholders it
can see, and writes a short reply that echoes the shape of the
request, which is enough to prove the middleware flow end to end:
prompt in, redaction, model reply out, rehydration on the way back.

Because the stub only ever receives the redacted text, any
placeholder in its reply stands where a real value would go, and the
handler can rehydrate the reply locally for the caller.
"""

import re

_PLACEHOLDER_RE = re.compile(r"\[[A-Z]+_\d+\]")


def generate_model_reply(redacted_prompt):
    words = redacted_prompt.split()
    placeholders = _PLACEHOLDER_RE.findall(redacted_prompt)
    if placeholders:
        seen = ", ".join(dict.fromkeys(placeholders))
        detail = f"I can see redacted values in it ({seen}), so I will answer without the personal details."
    else:
        detail = "It contains no redacted values."
    return (
        f"Stub model reply: I received a {len(words)}-word prompt. {detail} "
        "Here is a draft answer based only on the redacted text."
    )
