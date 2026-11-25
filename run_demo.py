#!/usr/bin/env python3
"""Run the guardrail locally over every sample prompt.

Reads sample-data/, sends each prompt through the handler's request
path in rules mode (the same code the Lambda runs), and prints the
findings, the redacted prompt the model would see, and the stub
model's reply. No AWS account, no installs, no network.

Comprehend mode is not exercised here: it runs only in the deployed
Lambda, where boto3 and the scoped IAM permission exist.

Usage: python3 run_demo.py
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

import handler


def main():
    paths = sorted(glob.glob(os.path.join(ROOT, "sample-data", "*.txt")))
    print(f"Running {len(paths)} sample prompts through the guardrail (rules mode)...")
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            prompt = handle.read().strip()
        result = handler.handle_request(prompt, mode="rules")
        name = os.path.basename(path)
        if result["findings"]:
            found = ", ".join(
                f"{f['type']} -> {f['placeholder']}" for f in result["findings"]
            )
        else:
            found = "none"
        print()
        print(f"--- {name}")
        print(f"Findings: {found}")
        print(f"Redacted prompt: {result['redacted_prompt']}")
        print(f"Model reply: {result['model_reply']}")
    print()
    print("Demo complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
