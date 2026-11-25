"""Tests for the guardrail engine and handler.

Run with: python3 -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import guard
import handler


def types_of(text, mode="rules"):
    return [f["type"] for f in guard.get_detector(mode).detect(text)]


class DetectionTests(unittest.TestCase):
    def test_card_detected_with_spaces(self):
        self.assertIn("CARD", types_of("card 4111 1111 1111 1111 on file"))

    def test_card_detected_without_separators(self):
        self.assertIn("CARD", types_of("card 4111111111111111 on file"))

    def test_card_failing_luhn_is_not_flagged(self):
        # Same shape as a card, one digit off: the checksum fails.
        self.assertNotIn("CARD", types_of("order 4111 1111 1111 1112 shipped"))

    def test_ssn_detected(self):
        self.assertIn("SSN", types_of("SSN is 123-45-6789 today"))

    def test_ssn_with_area_900_rejected(self):
        self.assertNotIn("SSN", types_of("ID 900-12-3456 here"))

    def test_ssn_with_area_000_rejected(self):
        self.assertNotIn("SSN", types_of("ID 000-45-6789 here"))

    def test_ssn_with_area_666_rejected(self):
        self.assertNotIn("SSN", types_of("ID 666-45-6789 here"))

    def test_email_detected(self):
        self.assertIn("EMAIL", types_of("write to maria.torres@example.com please"))

    def test_phone_detected_in_formats(self):
        self.assertIn("PHONE", types_of("call (212) 555-0147 today"))
        self.assertIn("PHONE", types_of("call 415-555-0132 today"))
        self.assertIn("PHONE", types_of("call +1 415 555 0132 today"))

    def test_name_heuristic_needs_trigger_phrase(self):
        self.assertIn("NAME", types_of("Hi, my name is Priya Nair and I moved"))
        self.assertNotIn("NAME", types_of("the launch Steve Jobs announced in 2007"))

    def test_address_heuristic(self):
        self.assertIn("ADDRESS", types_of("ship to 482 Willow Creek Drive please"))

    def test_date_is_not_flagged(self):
        self.assertEqual([], guard.get_detector("rules").detect("placed on 2026-11-23"))

    def test_clean_prompt_has_no_findings(self):
        text = "Explain the difference between TCP and UDP to a junior engineer."
        self.assertEqual([], guard.get_detector("rules").detect(text))


class RedactionTests(unittest.TestCase):
    def test_placeholders_are_typed_and_numbered(self):
        result = guard.process_prompt(
            "card 4111 1111 1111 1111, email maria.torres@example.com"
        )
        self.assertIn("[CARD_1]", result["redacted_prompt"])
        self.assertIn("[EMAIL_1]", result["redacted_prompt"])
        self.assertNotIn("4111", result["redacted_prompt"])
        self.assertNotIn("maria.torres", result["redacted_prompt"])

    def test_same_value_reuses_one_placeholder(self):
        result = guard.process_prompt(
            "email daniel.okafor@example.com, copy daniel.okafor@example.com"
        )
        self.assertEqual(2, result["redacted_prompt"].count("[EMAIL_1]"))
        self.assertNotIn("[EMAIL_2]", result["redacted_prompt"])
        self.assertEqual(1, len(result["mapping"]))

    def test_rehydration_round_trip(self):
        original = "My SSN is 123-45-6789 and my card is 4111 1111 1111 1111."
        result = guard.process_prompt(original)
        restored = guard.rehydrate(result["redacted_prompt"], result["mapping"])
        self.assertEqual(original, restored)

    def test_clean_prompt_passes_through_unchanged(self):
        text = "Write a Python function that sorts a list of integers."
        result = guard.process_prompt(text)
        self.assertEqual(text, result["redacted_prompt"])
        self.assertEqual({}, result["mapping"])
        self.assertEqual([], result["findings"])


class _FakeComprehendClient:
    """Stands in for boto3's Comprehend client: canned entities only."""

    def detect_pii_entities(self, Text, LanguageCode):
        email = "maria.torres@example.com"
        start = Text.index(email)
        return {
            "Entities": [
                {
                    "Type": "EMAIL",
                    "BeginOffset": start,
                    "EndOffset": start + len(email),
                    "Score": 0.99,
                },
                {"Type": "BANK_ACCOUNT_NUMBER", "BeginOffset": 0, "EndOffset": 4, "Score": 0.5},
            ]
        }


class ComprehendModeTests(unittest.TestCase):
    def test_type_mapping_with_injected_client(self):
        detector = guard.ComprehendDetector(client=_FakeComprehendClient())
        findings = detector.detect("reach maria.torres@example.com soon")
        self.assertEqual(["EMAIL"], [f["type"] for f in findings])
        self.assertEqual("maria.torres@example.com", findings[0]["value"])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            guard.get_detector("magic")


class HandlerTests(unittest.TestCase):
    def test_handle_request_shape(self):
        result = handler.handle_request("my card is 4111 1111 1111 1111")
        self.assertEqual("rules", result["mode"])
        self.assertEqual(
            [{"type": "CARD", "placeholder": "[CARD_1]"}], result["findings"]
        )
        self.assertIn("[CARD_1]", result["model_reply"])
        self.assertIn("4111 1111 1111 1111", result["rehydrated_reply"])

    def test_lambda_handler_parses_api_gateway_event(self):
        event = {"body": json.dumps({"prompt": "email me at a.b@example.com"})}
        response = handler.lambda_handler(event, None)
        self.assertEqual(200, response["statusCode"])
        body = json.loads(response["body"])
        self.assertIn("[EMAIL_1]", body["redacted_prompt"])

    def test_lambda_handler_rejects_empty_prompt(self):
        response = handler.lambda_handler({"body": json.dumps({})}, None)
        self.assertEqual(400, response["statusCode"])


if __name__ == "__main__":
    unittest.main()
