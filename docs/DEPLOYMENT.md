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

In plain terms, the request reached Comprehend and the
service refused it for an account-level reason. The code, the
IAM permission, and the API path all did their part.

I chased the root cause afterwards. Opening the Amazon
Comprehend console does not open Comprehend at all; it
redirects to an AWS page titled "Complete your account
setup". The account registration is incomplete, and the
account sits on the free plan, which limits access to certain
services. The page asks for a payment method, identity
verification, and a support plan selection before services
fully activate, and it warns that activation can take up to
24 hours. There is no Comprehend-specific switch to flip; the
gate is the account itself.

That is the accurate version of what I first recorded as "the
account is not subscribed to Amazon Comprehend". The direct
CLI call to DetectPiiEntities still returns
SubscriptionRequiredException, and both guardrail API calls
in comprehend mode still return HTTP 502. I have decided to
leave the account registration incomplete for now, so
Comprehend mode stays unverified by decision, not because the
route is unknown. The route is recorded here for later:
complete the registration on the "Complete your account
setup" page (payment method, identity verification, and a
support plan selection), wait for activation, then run this
test again.

One secondary point I am recording honestly: the API surfaces
this failure as a generic 502, so a caller cannot tell a
service refusal from a code bug without reading the logs.
Making that error clearer is future work.

## Findings from the live run

- Rules mode is fully verified against the live API: redaction,
  findings, placeholder-only model input, and local
  rehydration all behaved exactly as the local demo and the 22
  tests said they would.
- Comprehend mode is blocked by the account, not by the code.
  The proof is in the shape of the failure: the call travels
  through API Gateway, the handler, and the IAM permission,
  reaches DetectPiiEntities, and is refused by the service
  itself. Every layer I control did its job.
- The blocking fact about the account, an incomplete
  registration on the free plan, was invisible from every
  local check and from the deployment itself. It only appeared
  when I went looking for a Comprehend activation page that
  does not exist.

## Lessons learned

- A template can validate perfectly and a deployment can
  succeed while a feature still fails, because the gate sits
  at the account level where no local check can see it. Live
  verification has to exercise every mode, not just the happy
  path.
- A generic 502 hides the difference between a code bug and a
  service refusal. The Lambda logs were the only place the
  truth appeared. Surfacing clearer errors to the caller is
  real future work, not polish.
- The free plan covered Lambda, API Gateway, SNS, and
  CloudTrail in the projects I deployed that day, but not
  every service sits inside it. What an account plan includes
  is part of a design's real constraints, and I only learned
  it by running the thing.
