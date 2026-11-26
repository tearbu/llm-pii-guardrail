# Deployment record: llm-pii-guardrail

I deployed this project live on 25 November 2026. Rules mode
works end to end against the live API. Comprehend mode does
not, and this file records exactly why.

## Where it went

- Account: 762103021017
- Region: us-east-1
- Stack: llm-pii-guardrail
- Final stack status: CREATE_COMPLETE
- Tooling: AWS SAM, run from CloudShell
- Function: llm-pii-guardrail-guard
- ApiUrl: https://a8y7o0ixr3.execute-api.us-east-1.amazonaws.com/Prod

The endpoint is POST /guard on that base URL.

One process note: SAM's deploy progress display stalled in
CloudShell even though CloudFormation finished the stack. I
verified the stack state with describe-stacks instead of
trusting the spinner.

## Rules mode, verified live

I sent this request to the live API:

```json
{"prompt": "My card is 4111 1111 1111 1111 and my SSN is 123-45-6789, email me at john.doe@example.com", "mode": "rules"}
```

It came back with HTTP 200. The response carried:

- redacted_prompt: "My card is [CARD_1] and my SSN is [SSN_1], email me at [EMAIL_1]"
- Findings for CARD, SSN, and EMAIL, each with its placeholder
- A stub model reply written from the placeholders only, so the
  model side never saw the raw values
- A rehydrated reply with the original values restored locally
  from the request mapping

I also sent a clean prompt, "What is the capital of France?",
in rules mode. It came back with HTTP 200, no findings, and
the prompt unchanged.

## Comprehend mode, blocked by the account

I sent the same first prompt with "mode": "comprehend". The
API returned HTTP 502 with this body:

```json
{"message": "Internal server error"}
```

The Lambda log gave the real cause: a ClientError,
SubscriptionRequiredException, from DetectPiiEntities, with
the message "The AWS Access Key Id needs a subscription for
the service".

In plain terms, Amazon Comprehend is not enabled on this
account. The request reached Comprehend and the service
refused it for an account-level reason. The code, the IAM
permission, and the API path all did their part. Comprehend
mode stays unverified until the service is enabled on the
account and I run this test again.

One secondary point I am recording honestly: the API surfaces
this failure as a generic 502, so a caller cannot tell a
service refusal from a code bug without reading the logs.
Making that error clearer is future work.
