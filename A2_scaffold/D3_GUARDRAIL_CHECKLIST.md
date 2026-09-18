# D3 Guardrail Checklist — Problem B

This checklist records the code-layer controls, their deterministic tests, and
the remaining risks. The safety battery uses the Scripted Backend only: it
requires no API key, makes no network request, and performs no real booking.

## Week 6 checklist mapping

| Required control | Implementation | Evidence | Status |
|---|---|---|---|
| Maximum turns / steps | `Guardrails.check_turns()`; 8 parallel or 16 sequential turns | `GR_STEPCAP_01` | Implemented |
| Budget ceiling | `Guardrails.check_budget()`; default 60,000 estimated tokens | `GR_BUDGET_01` | Implemented |
| Repeated-call detection | Canonical tool name + arguments | `GR_DEDUP_01` | Implemented |
| Tool allowlist | Every call is checked against `tools.REGISTRY[problem]` before dispatch | `GR_ALLOWLIST_01` | Implemented |
| Strict argument validation | Exact keys, types, IDs, enums, dates, time, legal windows and real available slot checks | `GR_ARGS_01`; `test_poka_yoke.py` | Implemented for Problem B |
| Autonomy gate before write | `book_slot` is gated immediately before execution | `GR_GATE_01`, `GR_GATE_02` | Implemented |
| Idempotency | `book_slot + referral_id` is the idempotency key even if the slot changes | `GR_DEDUP_02`, `GR_IDEMPOTENCY_01` | Implemented within one run |
| Untrusted external text | Referral/tool-output instruction markers stop in code before entering the transcript | `GR_HOSTILE_01`–`03` | Implemented |
| Safe failure and human escalation | Safety stops emit `human_review_required`, `blocked_action`, `escalation_trigger`, and `escalation_target` | `GR_ESCALATION_01` | Implemented |
| Live confirmation fails closed | A live backend without a real approval callback cannot book | `GR_LIVE_FAIL_CLOSED_01` | Implemented |

## OWASP Top 10 for LLM Applications (2025)

Reference: <https://genai.owasp.org/llm-top-10/>

| OWASP risk | Applicability to this agent | Current control / evidence | Residual risk |
|---|---|---|---|
| LLM01 Prompt Injection | High | Untrusted referral/tool text is scanned and blocked before transcript insertion; three hostile cases pass | Marker detection is deterministic and may miss novel paraphrases; human review remains required |
| LLM02 Sensitive Information Disclosure | High | Persisted `tool_trace` redacts clinical summaries, patient identity and contact data | In-memory tool results still contain data required for the case; production access control is outside this scaffold |
| LLM03 Supply Chain | Partial | Scripted tests have no third-party runtime dependency or network call | Live model/provider and future dependency pinning require deployment controls |
| LLM04 Data and Model Poisoning | Partial | Reference fixtures are checked by `check_my_data.py`; hostile free text is treated as untrusted | No provenance/signature mechanism exists for production referral feeds |
| LLM05 Improper Output Handling | High | Tool allowlist and strict validation run before dispatch | Problem A does not yet have the same domain-specific validation contracts |
| LLM06 Excessive Agency | High | `confirm` autonomy, pre-write gate, and referral-level idempotency | Approval identity/authentication is represented only by a callback in this scaffold |
| LLM07 System Prompt Leakage | Partial | The agent does not persist or return the system prompt in decision records | No dedicated prompt-exfiltration detector is implemented |
| LLM08 Vector and Embedding Weaknesses | Not applicable | Problem B uses fixed JSON tools, not vector search or embeddings | Reassess if RAG is introduced |
| LLM09 Misinformation | High | Decisions must be grounded in deterministic tool evidence; 50 labelled cases and a human judgement queue are retained | A correct code-check decision can still contain a weak reason; manual/second-model judgement is still required |
| LLM10 Unbounded Consumption | High | Turn cap, budget ceiling and duplicate-call stop | Production also needs per-user rate limits and provider-side quotas |

## Verified results

- Reference-data integrity: 50 referrals, 42 patients, 42 contacts, 24 slots; passed.
- Ordinary scripted evaluation: 70/70 trials passed in parallel mode.
- Ordinary scripted evaluation: 70/70 trials passed in sequential mode.
- Guardrail battery: 15/15 passed.
- Hostile free-text/tool-output cases: 3/3 passed.
- Poka-yoke unit tests: 8/8 passed.

## Honest boundaries

The guardrail suite proves that the code blocks specified actions even if a
model produces a dangerous call. It does not measure a live model's ability to
recognise every prompt injection. Booking idempotency is stored in the fresh
per-run guard object; a production system must also persist an idempotency key
in the booking service or database across processes and retries.
