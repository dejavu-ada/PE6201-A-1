# Contribution — ZHU YIN (B2 Guardrail Layer)

## Files implemented or materially changed

- `guardrails.py`: allowlist, fail-closed stops, referral-level booking idempotency, untrusted-output control.
- `agent.py`: safe execution order, Live confirmation fix, structured escalation, trace redaction.
- `tools.py`: strict Problem B tool-call contracts and untrusted-text detection.
- `backends.py`: added `as_of()` to all 50 Problem B scripted flows.
- `guardrail_cases.json`: 15-case D3(b) battery with three hostile cases.
- `run_guardrails.py`: deterministic integration drivers, assertions and JSON/CSV evidence.
- `D3_GUARDRAIL_CHECKLIST.md`: Week 6 and OWASP LLM Top 10 (2025) mapping.
- `D3_REPORT_DRAFT.md`: report and demo material.
- `B2_MERGE_CHANGES.md`: merge rationale, verification and remaining team tasks.

## Verified result

- Guardrails: 15/15 passed; hostile cases: 3/3 passed.
- Problem B scripted evaluation: 70/70 in parallel and 70/70 in sequential mode.
- Poka-yoke tests: 8/8 passed.
- No Live Model or API key was used for the B2 guardrail battery.

Suggested commit message:

```text
Implement B2 D3 guardrails and scripted security tests
```
