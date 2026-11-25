# Architecture

## The flow

A client wants to ask a model something, and the prompt contains
personal data: a card number typed into a chat box, an SSN pasted
into a support question. Sending that text to a third-party model
API means the data leaves the building, lands in someone else's
logs, and stays there. This middleware sits in front of the model so
the raw prompt never makes that trip.

```
 client prompt (raw, may contain PII)
       |
       v
 +-------------+   detect    +----------------------+
 | API Gateway | ----------> | Guard Lambda         |
 | POST /guard |             |  src/handler.py      |
 +-------------+             |  src/guard.py        |
                             +----+-----------+-----+
                                  |           |
                     redacted     |           |  mapping kept in
                     prompt       v           |  request memory only
                             +----------+     |
                             | Stub     |     |
                             | model    |     |
                             +----+-----+     |
                                  |           |
                       reply with |           |
                       placehold. v           v
                             rehydrate locally, return reply,
                             findings, and redacted prompt
```

## What each part does

**Guard engine** (`src/guard.py`). One interface, detect(text), two
detectors. Rules mode is deterministic: card numbers must pass a
Luhn checksum, Social Security numbers must pass the SSA validity
rules for area, group, and serial numbers, emails and US phone
numbers match patterns, and names and street addresses match simple
heuristics that only fire in narrow shapes. Comprehend mode calls
Amazon Comprehend DetectPiiEntities and maps its entity types onto
the same finding shape, so the rest of the pipeline cannot tell the
two apart. redact() swaps each finding for a typed placeholder,
[CARD_1], [SSN_1], and so on, and returns the mapping. rehydrate()
reverses it.

**Model stub** (`src/model_stub.py`). Stands in for the LLM API.
It receives only the redacted prompt, and its reply is a short
deterministic note about what it received. A real deployment swaps
this one function for an actual model call and nothing else changes,
because the stub's input is already the safe version of the text.

**Handler** (`src/handler.py`). The Lambda entry point and the same
code path the local demo runs. It takes {prompt, mode}, runs the
guard pass, gets the model reply, rehydrates the reply with the
request's mapping, and returns the redacted prompt, the findings
(types and placeholders, never values), the model reply, and the
rehydrated reply.

**SAM template** (`template.yaml`). One function, one API event,
one output. The function's role holds exactly one permission,
comprehend:DetectPiiEntities, which rules mode never uses and
comprehend mode needs. DetectPiiEntities does not support
resource-level permissions in IAM, so the resource is "*"; the
scope control here is that this single action is the only thing the
function can do in AWS at all.

## Decisions

**Raw prompts are never stored.** The mapping between placeholders
and real values exists in one request's memory and is dropped when
the handler returns. There is no database, no bucket, and no log
statement in this project that writes a prompt or a mapping. The
reason is simple: a store of mappings is a store of PII with extra
steps. The cost of the decision is real too. Nothing can be audited
or replayed after the fact, and a caller who loses the response
cannot recover the mapping. For a guardrail whose whole job is
keeping personal data out of other systems, that trade is the right
way round.

**Two detectors behind one interface.** Rules mode runs anywhere,
costs nothing, and behaves identically every run, which is what
makes the local demo and the tests meaningful. Its limits are plain:
patterns cannot judge context, and names or free-form addresses slip
past heuristics. Comprehend mode is the deployed answer to those
limits, a managed model trained for exactly this. Keeping both
behind detect(text) means the comparison between them is a config
value, not a rewrite.

**Typed placeholders instead of masks.** Replacing a card with
[CARD_1] rather than asterisks keeps the prompt readable for the
model, keeps the reply rehydratable, and keeps two different cards
in one prompt distinguishable. A mask destroys all three.

**Python standard library only, locally.** The engine, handler, demo,
and tests need no installs. boto3 appears only inside the Comprehend
detector, imported lazily, because on AWS it ships with the Lambda
runtime and everywhere else its absence is the honest signal that
comprehend mode cannot run there.
