"""PII detection and redaction engine.

Two detectors sit behind one interface, detect(text) -> findings,
where each finding is a dict with keys: type, value, start, end.

- RulesDetector: deterministic pattern and checksum detection. Card
  numbers must pass a Luhn check. Social Security numbers must pass
  the SSA validity rules (area number not 000, 666, or 900-999;
  group not 00; serial not 0000). Emails and US phone numbers are
  pattern matches. Names and street addresses are simple heuristics
  and are labeled as such: they only fire after trigger phrases like
  "my name is" or on a number-plus-street-suffix shape. They are
  weak by design and the README says so.

- ComprehendDetector: calls Amazon Comprehend DetectPiiEntities and
  maps its entity types onto the same finding shape. It runs only
  where boto3 and AWS credentials exist, which in this project means
  the deployed Lambda. Nothing in the local demo calls it, and no
  local result in this repo comes from Comprehend.

redact() swaps each finding for a typed placeholder such as
[CARD_1] and returns the per-request mapping. rehydrate() puts the
original values back. The mapping is built to live in one request's
memory and nowhere else: this module has no storage, no logging of
values, and no file or network writes.
"""

import re

# ---------------------------------------------------------------- cards

_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_ok(digits):
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _find_cards(text):
    findings = []
    for match in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            findings.append(_finding("CARD", match))
    return findings


# ------------------------------------------------------------------ SSN

_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")


def _find_ssns(text):
    findings = []
    for match in _SSN_RE.finditer(text):
        area, group, serial = (int(match.group(i)) for i in (1, 2, 3))
        if area == 0 or area == 666 or area >= 900:
            continue
        if group == 0 or serial == 0:
            continue
        findings.append(_finding("SSN", match))
    return findings


# ---------------------------------------------------------------- email

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _find_emails(text):
    return [_finding("EMAIL", m) for m in _EMAIL_RE.finditer(text)]


# ---------------------------------------------------------------- phone

_PHONE_RE = re.compile(
    r"(?:\+1[\s.-]?)?(?:\(\d{3}\)[\s.]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}\b"
)


def _find_phones(text):
    return [_finding("PHONE", m) for m in _PHONE_RE.finditer(text)]


# ------------------------------------------------- name and address
# Heuristics, and weak ones. A name only counts when the writer
# introduces it ("my name is", "I am", "this is", "signed,"). An
# address only counts on the number + street name + suffix shape.
# Both miss plenty and the README says so plainly.

_NAME_RE = re.compile(
    r"(?i:\bmy name is|\bi am|\bthis is|\bsigned,?)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
)

_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct)\b"
)


def _find_names(text):
    findings = []
    for match in _NAME_RE.finditer(text):
        start, end = match.span(1)
        findings.append(
            {"type": "NAME", "value": match.group(1), "start": start, "end": end}
        )
    return findings


def _find_addresses(text):
    return [_finding("ADDRESS", m) for m in _ADDRESS_RE.finditer(text)]


def _finding(kind, match):
    return {
        "type": kind,
        "value": match.group(),
        "start": match.start(),
        "end": match.end(),
    }


# -------------------------------------------------------------- detectors

_RULE_FINDERS = (
    _find_cards,
    _find_ssns,
    _find_emails,
    _find_phones,
    _find_addresses,
    _find_names,
)


class RulesDetector:
    """Deterministic local detection. Same text, same findings."""

    name = "rules"

    def detect(self, text):
        accepted = []
        for finder in _RULE_FINDERS:
            for finding in finder(text):
                if any(
                    finding["start"] < kept["end"] and kept["start"] < finding["end"]
                    for kept in accepted
                ):
                    continue
                accepted.append(finding)
        accepted.sort(key=lambda f: f["start"])
        return accepted


_COMPREHEND_TYPE_MAP = {
    "CREDIT_DEBIT_NUMBER": "CARD",
    "SSN": "SSN",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
    "NAME": "NAME",
    "ADDRESS": "ADDRESS",
}


class ComprehendDetector:
    """Amazon Comprehend DetectPiiEntities behind the same interface.

    Runs only on AWS: it needs boto3 and credentials with the
    comprehend:DetectPiiEntities permission, which the SAM template
    grants to the deployed Lambda and nothing else. A client can be
    injected, which is how the tests exercise the type mapping
    without an AWS account.
    """

    name = "comprehend"

    def __init__(self, client=None):
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "comprehend mode needs boto3 and AWS credentials; "
                    "it runs only in the deployed Lambda"
                ) from exc
            client = boto3.client("comprehend")
        self._client = client

    def detect(self, text):
        response = self._client.detect_pii_entities(
            Text=text, LanguageCode="en"
        )
        findings = []
        for entity in response.get("Entities", []):
            kind = _COMPREHEND_TYPE_MAP.get(entity["Type"])
            if kind is None:
                continue
            start, end = entity["BeginOffset"], entity["EndOffset"]
            findings.append(
                {"type": kind, "value": text[start:end], "start": start, "end": end}
            )
        findings.sort(key=lambda f: f["start"])
        return findings


def get_detector(mode):
    if mode == "rules":
        return RulesDetector()
    if mode == "comprehend":
        return ComprehendDetector()
    raise ValueError(f"unknown mode: {mode!r} (expected 'rules' or 'comprehend')")


# ------------------------------------------------------- redact / restore

def redact(text, findings):
    """Replace findings with typed placeholders.

    Returns (redacted_text, mapping) where mapping links each
    placeholder to the original value. The same value always gets
    the same placeholder within one request.
    """
    counters = {}
    placeholder_by_value = {}
    mapping = {}
    for finding in findings:
        key = (finding["type"], finding["value"])
        if key not in placeholder_by_value:
            counters[finding["type"]] = counters.get(finding["type"], 0) + 1
            placeholder = f"[{finding['type']}_{counters[finding['type']]}]"
            placeholder_by_value[key] = placeholder
            mapping[placeholder] = finding["value"]
        finding["placeholder"] = placeholder_by_value[key]

    redacted = text
    for finding in sorted(findings, key=lambda f: f["start"], reverse=True):
        redacted = (
            redacted[: finding["start"]]
            + finding["placeholder"]
            + redacted[finding["end"] :]
        )
    return redacted, mapping


def rehydrate(text, mapping):
    """Put original values back in place of their placeholders."""
    restored = text
    for placeholder, value in mapping.items():
        restored = restored.replace(placeholder, value)
    return restored


def process_prompt(text, mode="rules"):
    """Full guard pass over one prompt.

    Returns a dict with the detector's findings (each carrying its
    placeholder), the redacted prompt, and the placeholder mapping.
    The mapping belongs to this call only; nothing here persists it.
    """
    detector = get_detector(mode)
    findings = detector.detect(text)
    redacted, mapping = redact(text, findings)
    return {
        "mode": mode,
        "findings": findings,
        "redacted_prompt": redacted,
        "mapping": mapping,
    }
