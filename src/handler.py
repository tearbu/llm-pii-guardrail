"""Lambda handler for POST /guard.

Request body (JSON):
    {"prompt": "...", "mode": "rules"}       mode is optional

Response body (JSON):
    mode             the detector that ran
    redacted_prompt  the prompt with PII swapped for placeholders;
                     this is the only version the model ever sees
    findings         [{type, placeholder}] per value found; the
                     values themselves are not echoed back in this
                     list, they stay in the request's memory only
    model_reply      the stub model's reply to the redacted prompt
    rehydrated_reply the same reply with placeholders resolved back
                     to the original values, done locally so the
                     caller reads a normal answer

The placeholder mapping is built inside guard.process_prompt, used
to rehydrate this one reply, and then dropped. There is no database,
no bucket, and no log line in this project that holds a raw prompt
or a mapping. That is a deliberate design decision; ARCHITECTURE.md
explains why.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard
import model_stub


def handle_request(prompt, mode="rules"):
    result = guard.process_prompt(prompt, mode=mode)
    reply = model_stub.generate_model_reply(result["redacted_prompt"])
    return {
        "mode": result["mode"],
        "redacted_prompt": result["redacted_prompt"],
        "findings": [
            {"type": f["type"], "placeholder": f["placeholder"]}
            for f in result["findings"]
        ],
        "model_reply": reply,
        "rehydrated_reply": guard.rehydrate(reply, result["mapping"]),
    }


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "request body must be JSON"})
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _response(400, {"error": "body must include a non-empty 'prompt'"})
    mode = body.get("mode", "rules")
    try:
        result = handle_request(prompt, mode=mode)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})
    except RuntimeError as exc:
        return _response(501, {"error": str(exc)})
    return _response(200, result)


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
