# PE6201 A2 - Outpatient Referral Coordination

Team **A-1** | Problem **B** | Single-agent ReAct system

This project handles a referral using local fixture records and returns one of
three outcomes: book a simulated appointment, request a named missing test, or
escalate to a triage nurse. A hand-written control loop connects the model to
six tools, code guardrails, an evaluation harness, and cost instrumentation.

## 1. Quick start: reproduce the scripted run

### Requirements and project layout

Python 3.12 is required; verification was performed with Python 3.12.14.
The command-line scripts use only the Python standard library, so no additional
packages are required.

Clone the repository:

```bash
git clone https://github.com/dejavu-ada/PE6201-A-1.git
cd PE6201-A-1
```

Run the following in **PowerShell**:

```powershell
python --version
python A2_reference_data/check_my_data.py
cd A2_scaffold

$env:A2_BACKEND = "scripted"
$env:A2_CALL_MODE = "parallel"
$env:DESCRIPTOR_VERSION = "v2"
python run_eval.py
```

On macOS/Linux, use `python3` if necessary and replace the three environment
assignments with:

```bash
export A2_BACKEND=scripted
export A2_CALL_MODE=parallel
export DESCRIPTOR_VERSION=v2
python3 run_eval.py
```

Expected headline output:

```text
Running 50 cases in parallel mode.
RESULTS   70 of 70 trials passed   (100%)
trials              70
cases               50
negative trials     30/30 passed
median turns        4.0
worst case turns    4
```

The fixture checker should report that the data hangs together. The evaluation
writes `results/d4_d5a_scripted_results.json` and refreshes derived result
files. Inspect the reported pass counts as well as the process exit status:
the full-battery command currently returns zero even when individual trials
fail.

Dollar amounts depend on the configured token prices. Elapsed time and timestamps also vary between runs.

### Inspect a successful case and a negative case

All subsequent commands assume the terminal is in `A2_scaffold/`.

```powershell
python run_eval.py REF-5602
python run_eval.py REF-5590
python run_eval.py REF-5711
```

| Case | Expected outcome |
|---|---|
| `REF-5602` | Book `OPH-C2`, `2026-10-14`, `11:20`, inside the routine window |
| `REF-5590` | Escalate for `red_flag_term`; do not book |
| `REF-5711` | Escalate for `instruction_in_referral_free_text`; do not book |

Single-case mode prints tool observations, the decision record, and grading
details. Negative cases still run three trials under the harness rule; the
printed decision record is the first trial. Single-case mode does not save a
full model-battery result.

### Run the remaining offline checks

```powershell
python run_guardrail_checklist.py
python demo_loop_failure.py
python -m unittest -v test_poka_yoke.py
python run_descriptor_experiment.py --prompt-only
```

Expected results: **10/10 guardrail cases**, **two recovered failure
demonstrations**, and **8 passing interface tests**. Prompt-only mode measures
the size of the current prompt without contacting a model.

Successful booking calls append to `bookings.jsonl`. Full evaluation runs
replace the selected model/version/call-mode entry in its JSON file, retaining
other entries; derived files are regenerated. Use a separate project copy if
you need to preserve the supplied evidence exactly.

## 2. What the system does

| Outcome | When it applies | Required result |
|---|---|---|
| `book` | Checks pass and a slot exists in the correct urgency band and time window | Clinic, date, time, urgency/window, test evidence, and duplicate check |
| `request_information` | A mandatory pre-referral test is missing | The exact missing test name and code |
| `escalate` | Red flag, specialty mismatch, future same-specialty appointment, no eligible slot, or instructions embedded in referral text | One specific trigger and referral to the triage nurse |

The authoritative clock is `data_B/as_of.json`, currently
`2026-09-09`. Windows are measured from that date, not from the operating
system clock or automatically from `date_received`.

The first action representing a real-world commitment is `book_slot`.
Here it only appends a local JSONL record. There is no real booking,
notification, patient-system integration, or slot-capacity update.

### Why a loop?

A red-flag referral should stop before slot search. A complete referral needs
patient and protocol checks followed by a suitable slot search and a gated
write. The live model chooses its next calls after reading observations, so
different cases require different amounts of work.

A fixed workflow enumerates the fixture rules in code. This implementation
uses a model-directed loop with observations after each tool-calling step,
recording tool use, stopping behaviour, failures, and cost. The scripted
backend replays predefined moves to verify the implementation and harness;
the live backend evaluates model behaviour.

Five observable criteria for a good run are:

1. Ground the decision in the correct referral and supporting fixture records.
2. Return the correct outcome and its specific trigger, missing test, or slot.
3. Execute the simulated booking exactly once on a booking case and never on a negative case.
4. Stop or escalate explicitly when data, tool execution, or a guardrail prevents completion.
5. Record turns, token usage or estimates, and costs so unnecessary work is detectable.

## 3. Architecture, tools, and guardrails

```text
Referral ID
    |
run_case() <----> ScriptedBackend or LiveBackend
    |
    +-- model/script move --> duplicate and autonomy checks
    |                              |
    |                         local fixture tools
    |                              |
    +<--------- observations ------+
    |
Final decision + trace + guardrail events + usage/cost
    |
Code checks + human judgement queue + result files
```

`agent.py` owns the control loop. `prompt.py` assembles the routing rules,
tool descriptors, scheduling instructions, and response contract.
`backends.py::_live_call` contains the HTTP integration with OpenRouter.
No agent framework or multi-agent orchestration owns the loop.

### Tool set and justification

Each definition adds prompt text on every live request, even when unused.
The six-field v2 contracts are in `tools.py::DESCRIPTORS_V2`: signature,
purpose, input, bounded return description, failure conditions, and whether
the action is irreversible.

| Tool | Task that needs it | Boundary from neighbouring tools / cost of retaining it |
|---|---|---|
| `get_referral(referral_id)` | Resolve the referral, patient ID, specialty, and submitted tests | Entry-point record lookup; does not evaluate clinical criteria. Adds a descriptor and the initial lookup. |
| `check_referral_criteria(specialty, referral_id)` | Identify red flags, missing tests, mismatch, hostile text, and urgency | Returns protocol facts, not patient appointments or available slots. One combined interface avoids separate tools for each check. |
| `lookup_patient(patient_id)` | Find existing appointments and contact details | Reads patient history, not clinic availability. Contacts are included, avoiding a separate contact lookup tool. |
| `as_of()` | Apply a reproducible date to duplicate and window checks | Fixture clock, not the referral's receipt date. Its descriptor remains in the prompt even when a scripted path already carries fixed dates. |
| `get_clinic_slots(specialty, band, **window)` | Find a slot with capacity in the correct band and window | Read-only search; does not book. Removing it prevents the booking trajectory in D7. |
| `book_slot(clinic, date, time, referral_id)` | Record the simulated appointment | The only Problem B write; adds both a descriptor and the need for an autonomy gate. |

#### D2(a) three-question scoring table

| Tool | 1. Does a task actually fail without it? | 2. Could the model confuse it with a neighbour? | 3. What does it cost when it is never called? |
|---|---|---|---|
| `get_referral` | Without the patient, specialty, and clinical summary, every later tool argument fails. | No. It is the only referral entry point. | 622 descriptor characters, approximately 155 prefix tokens per model turn; it also enlarges the callable surface. |
| `check_referral_criteria` | The agent can choose the wrong red-flag, department, mandatory-test, or urgency route. | It is closest to `lookup_patient`, but this tool returns protocol rules rather than patient state. | 1,103 descriptor characters, approximately 275 prefix tokens per model turn; it also enlarges the callable surface. |
| `lookup_patient` | The agent can miss a future appointment in the same specialty and create a duplicate booking. | It is closest to `check_referral_criteria`, but this tool returns patient state rather than protocol rules. | 725 descriptor characters, approximately 181 prefix tokens per model turn; it also enlarges the callable surface. |
| `as_of` | The model can invent the current date or incorrectly use `date_received` to calculate the booking window. | No. It is the only authoritative zero-argument date tool. | 533 descriptor characters, approximately 133 prefix tokens per model turn; it also enlarges the callable surface. |
| `get_clinic_slots` | No legal, available appointment inside the permitted window can be established. | It is closest to `book_slot`, but this tool is a read-only search rather than a write action. | 1,258 descriptor characters, approximately 314 prefix tokens per model turn; it also enlarges the callable surface. |
| `book_slot` | No confirmed appointment can be recorded. | It is closest to `get_clinic_slots`, but this is the only gated write action. | 855 descriptor characters, approximately 213 prefix tokens per model turn; it also enlarges the callable surface. |

The token figures are rough prompt-prefix estimates based on approximately four characters per token; exact counts vary by model tokenizer. Each retained tool either changes the routing decision or supplies an argument that another tool cannot safely infer.

No separate web-search, contact-only, or letter-generation tool is exposed
for Problem B. The required evidence is local, contact data comes with the
patient lookup, and the required write is a log record.

Two interface protections are implemented and tested: criteria calls reject
unknown or mismatched specialties; slot queries require recognised specialty
and urgency values and explicit, valid, ordered `from`/`to` dates.
See [the interface design notes](A2_scaffold/POKA_YOKE_B1.md).

### Dependency rule and multi-call turns

Fetch the referral first. Once its identifiers are known, required patient,
criteria, and clock lookups can share a turn. Apply stopping rules before
querying slots. Slot search depends on the urgency/window; booking depends
on an eligible returned slot and the autonomy gate.

`A2_CALL_MODE=parallel` groups multiple calls into one agent turn.
The Python functions execute serially within that group: this is **batched
tool calling**, not concurrent threads. `sequential` splits calls into
separate counted turns. Scripted splitting does not add real model requests,
so its turn savings are not a measurement of live API latency savings.
The dependency rule is expressed in the prompt; the executor does not
validate a dependency graph.

### Four code controls

| Control | Default / behaviour |
|---|---|
| Step cap | `MAX_TURNS = 8`; excessive tool-calling turns stop explicitly |
| Token ceiling | `MAX_TOKENS_PER_RUN = 60000`; checked after a backend response, so a call can exceed it |
| Action de-duplication | Rejects a repeated tool name with identical arguments within one run |
| Autonomy gate | `AUTONOMY = "confirm"`; checked immediately before `book_slot` |

**The default runner supplies automatic approval**, including when the
backend is live. It exercises the gate for the simulation but is not an
interactive human approval workflow. A caller can pass its own
`approve(action, payload)` callback to `run_case`; the guardrail checklist
tests denied approval and `suggest` mode.

Each run has fresh guardrail state and a fresh transcript. Fixtures are read
through a process-level cache, and bookings are not read back as state for
later cases. The log accumulates across runs without changing the fixture
answers.

## 4. Evaluation and supplied evidence

The answer key contains **50 cases**: 40 booking cases run once and
10 negative cases run three times, for **70 trials per configuration**.
The negative families include red flags, missing tests, specialty mismatch,
duplicate future appointments, unavailable slots, and hostile referral text.

`harness.py::code_check` compares the outcome, required trigger or missing
item, expected slot fields, required tool evidence, and booking-call count.
A separate six-case judgement queue checks whether the written reason and
evidence satisfy the answer key's `must_record` requirements.

To review the selected saved backend/model/version/mode interactively:

```powershell
python run_eval.py --judge
```

This asks a human to mark each requirement and saves the verdicts without
making model calls. Human judgements are recorded separately; the numerical
rates below are **code-check pass rates**.

### Six-model live battery

The live battery contains **six models**, each with 70 v2/parallel trials
(420 trials in total). GPT-5 Mini also has a 70-trial v1/parallel run and a
70-trial v2/sequential run, bringing the saved live evidence to **560 trials**.
Team responsibilities are recorded in [CONTRIBUTIONS.md](CONTRIBUTIONS.md).

Source: [D5 model battery summary](A2_scaffold/results/d5_model_battery_summary.json),
rebuilt from the six per-model result files. Token counts come from API usage;
dollar costs use each experiment's recorded prices.

| Model | Passed / trials | Pass rate | Negative passed / trials | Median turns | Total token cost, USD |
|---|---:|---:|---:|---:|---:|
| Claude Haiku 4.5 | 70/70 | 100.00% | 30/30 | 4 | 1.000074 |
| DeepSeek V4 Flash 0731 | 60/70 | 85.71% | 30/30 | 3 | 0.048088 |
| Gemini 3.1 Flash Lite | 70/70 | 100.00% | 30/30 | 4 | 0.232769 |
| GPT-5 Mini | 60/70 | 85.71% | 26/30 | 3.5 | 0.391598 |
| Mistral Small 3.2 24B | 55/70 | 78.57% | 18/30 | 4 | 0.062803 |
| Qwen3 30B A3B Instruct 2507 | 25/70 | 35.71% | 17/30 | 2 | 0.035334 |

Fewer turns do not indicate better results: Qwen has the fewest median turns
and the lowest observed pass rate. These are fixture results, not estimates
of clinical reliability.

All six runs are labelled v2/parallel. The saved system-prompt lengths are
9,048 characters for GPT-5 Mini and 9,297 for each of the other five models.

### D2(b): GPT-5 Mini v1 versus v2

The [live descriptor comparison](A2_scaffold/results/d2b_descriptor_comparison_openai_gpt_5_mini.json)
uses GPT-5 Mini in parallel mode, with 70 trials per version.

| Version | Passed / trials | Pass rate | Negative passed / trials | Median turns | Total token cost, USD |
|---|---:|---:|---:|---:|---:|
| v1 | 38/70 | 54.29% | 7/30 | 2 | 0.304640 |
| v2 | 60/70 | 85.71% | 26/30 | 3.5 | 0.391598 |

The observed pass rate increases by **31.43 percentage points**, and
negative-case passes increase from 7 to 26. Token cost increases by
USD 0.086958 (28.54%). The better result takes more turns; it is not a
turn-reduction result.

The raw runs are stored in
[the GPT-5 Mini result file](A2_scaffold/results/results_openai_gpt_5_mini.json).
The version switch changes both tool descriptions and the response contract;
the experiment compares these two prompt configurations.

To run a new comparison with the same model and recorded price assumptions,
set `OPENROUTER_API_KEY` as described in section 5, then run:

```powershell
$env:A2_BACKEND = "live"
$env:A2_MODEL = "openai/gpt-5-mini"
$env:A2_PRICE_TIER = "cheap"
$env:A2_PRICE_IN = "0.25"
$env:A2_PRICE_OUT = "2.00"
$env:A2_CALL_MODE = "parallel"
$env:DESCRIPTOR_VERSION = "v1"
python run_eval.py
$env:DESCRIPTOR_VERSION = "v2"
python run_eval.py
```

These are paid runs using the current source prompt. They replace the
matching saved experiment entries; use a separate project copy to retain
the historical results.

### D2(c): sequential versus batched tool calling

The [GPT-5 Mini live scheduling comparison](A2_scaffold/results/d2c_sequential_parallel_openai_gpt_5_mini_v2.json)
contains both v2 modes, each with 70 trials.

| Mode | Passed / trials | Negative passed / trials | Median turns | Maximum turns | Total token cost, USD |
|---|---:|---:|---:|---:|---:|
| sequential | 56/70 | 24/30 | 3.5 | 6 | 0.452362 |
| parallel | 60/70 | 26/30 | 3.5 | 4 | 0.391598 |

The observed token cost falls by **USD 0.060764 (13.43%)**. Median turns stay
at 3.5, while maximum turns fall from 6 to 4. Pass rate changes from 80.00%
to 85.71%; this live experiment does not show unchanged correctness.

The separate scripted comparison passes 70/70 in both modes, with median
turns falling from 5 to 4 and maximum turns from 6 to 4. Its token and cost
fields remain estimates.

To compare scheduling, keep the model, descriptor version, cases, and prices
fixed. The commands below use whichever backend is currently selected:
`scripted` is free; `live` makes paid model calls.

```powershell
$env:DESCRIPTOR_VERSION = "v2"
$env:A2_CALL_MODE = "sequential"
python run_eval.py
$env:A2_CALL_MODE = "parallel"
python run_eval.py
```

### Reproduced failures

| Failure | Before | Broken | Recovered | Fix location |
|---|---|---|---|---|
| D7 F1: repeated checks with action de-duplication removed | 4 turns, 6 tool calls | 6 turns, 10 calls; still passes the outcome check | 4 turns, 6 calls | Code / loop control |
| D7 F2: `get_clinic_slots` removed from the registry | Correct booking | Stops with `tool_error`; booking check fails | Correct booking | Tool interface |

F1 shows why pass rate alone misses wasted work. Its demonstration also
injects repeated scripted moves and restores both the script and the guard;
it is not a live-model loop failure. F2 requires restoring the missing
capability: changing a prompt cannot execute a tool absent from the registry.
Full traces and estimates are in
[D7 results](A2_scaffold/results/d7_failure_results.json).

## 5. Optional live runs and configuration

A live evaluation sends fixture text to OpenRouter and consumes API credit.
The offline quick start does not need this section.

The example below selects a model already represented in the supplied
results. The prices shown reproduce that recorded experiment's assumptions;
they are not a statement of current provider pricing.

```powershell
$env:A2_BACKEND = "live"
$env:A2_MODEL = "google/gemini-3.1-flash-lite"
$env:A2_PRICE_TIER = "mid"
$env:A2_PRICE_IN = "0.25"
$env:A2_PRICE_OUT = "1.50"
$env:A2_CALL_MODE = "parallel"
$env:DESCRIPTOR_VERSION = "v2"
$env:OPENROUTER_API_KEY = "<your-local-key>"

python run_eval.py REF-5602
python run_eval.py
```

Keep the real key out of source files, notebooks, result files, and commits.
Confirm the selected model's availability and prices before a new paid run.
Switch back to `$env:A2_BACKEND = "scripted"` when finished.

| Setting | Default | How to change it |
|---|---|---|
| Backend | `scripted` | `A2_BACKEND` |
| Model | `openai/gpt-4o-mini` | `A2_MODEL` |
| API endpoint | `https://openrouter.ai/api/v1` | `BASE_URL` in `config.py` |
| Call mode | `parallel` | `A2_CALL_MODE`: `parallel` or `sequential` |
| Descriptor version | `v2` | `DESCRIPTOR_VERSION` |
| Price tier | `cheap` | `A2_PRICE_TIER`: `cheap`, `mid`, or `frontier` |
| Input/output price | Lookup by model, with fallback values | `A2_PRICE_IN` / `A2_PRICE_OUT`, USD per million tokens |
| Fixture directory | Sibling `A2_reference_data/` | `A2_DATA`, pointing to the directory containing `data_B/` |
| Caps, autonomy, economic assumptions | Values in `config.py` | Edit those constants in `config.py` |

A model slug selects its recorded price lookup but does not automatically
select its price tier. Set tier and prices explicitly for each experiment.

After collecting result files, rebuild summaries without API calls:

```powershell
python run_eval.py --refresh
```

This regenerates D2/D5/D6 derived files from saved runs; it does not rerun
models, complete human judgements, or fill missing experiment arms.

## 6. Cost-to-serve

The baseline uses measured input/output tokens and each run's recorded
prices. Local fixture tools have no usage fee. The calculation applies no
prompt-cache discount and adds no separate reasoning-token estimate.

### Three cost layers

```text
Layer 1: C_token = total recorded token cost / trials
Layer 2: C_fallback = (1 - P) * F
         F = round(USD 55/hour * 10 minutes / 60, 2) = USD 9.17
Layer 3: C_fixed = USD 2,920 per month

C_variable = C_token + C_fallback
C_month = C_fixed + 4,000 * C_variable
```

`P` is the code-check pass rate. Volume is 4,000 referrals per month.
The fixed USD 2,920 is the operating-cost assumption in `config.py`.
The model prices failure as human escalation rather than retrying the agent.
Correct clinical escalations count as successful outcomes; their routine
human handling is not priced separately in this failure-cost baseline.

| Model, v2/parallel | Token cost / task, USD | Expected fallback / task, USD | Total monthly cost, USD |
|---|---:|---:|---:|
| Claude Haiku 4.5 | 0.014287 | 0.000 | 2,977.15 |
| DeepSeek V4 Flash 0731 | 0.000687 | 1.310 | 8,162.75 |
| Gemini 3.1 Flash Lite | 0.003325 | 0.000 | 2,933.30 |
| GPT-5 Mini | 0.005594 | 1.310 | 8,182.38 |
| Mistral Small 3.2 24B | 0.000897 | 1.965 | 10,783.59 |
| Qwen3 30B A3B Instruct 2507 | 0.000505 | 5.895 | 26,502.02 |

These values come from the per-model `summary.economics` records.
Gemini has the lowest modelled monthly total in this battery.

### Four cost levers

| Lever | Comparison | Before | After |
|---|---|---|---|
| Tool block size B | Current six-tool descriptor block, v1 to v2 | 4,028 characters; approximately 1,007 tokens | 5,101 characters; approximately 1,275 tokens |
| Turn count T | GPT-5 Mini v2, sequential to parallel | Median 3.5, maximum 6; 754,663 input tokens | Median 3.5, maximum 4; 637,992 input tokens |
| Observation size D | GPT-5 Mini parallel, v1 to v2 | 306 returned observations; mean 163.67 characters, approximately 40.92 tokens | 321 returned observations; mean 162.88 characters, approximately 40.72 tokens |
| Success rate | GPT-5 Mini parallel, v1 to v2 | 38/70; expected variable cost USD 4.196352/task | 60/70; expected variable cost USD 1.315594/task |

Tool-block sizes are measured from the current rendered descriptors.
Observation sizes use `len(repr(observation))` for each non-null observation
in the saved traces. Size estimates use `characters / 4`; live costs use API
token counts. The observation averages include the actual mix of tools
executed in each arm.

Success rate dominates the descriptor comparison: expected fallback cost
falls from USD 4.192 to USD 1.310 per task, while token cost rises from
USD 0.004352 to USD 0.005594. The larger tool block is accompanied by higher
task success.

### Sensitivity

For Gemini, hold token cost at USD 0.00332527/task and vary success rate
within +/-10 percentage points of the observed 100%, bounded to [0, 1].
The distinct values in the saved 2-point-step sensitivity table are:

| Success rate | Expected variable cost / task, USD | Total monthly cost, USD |
|---|---:|---:|
| 90% | 0.920325 | 6,601.30 |
| 92% | 0.736925 | 5,867.70 |
| 94% | 0.553525 | 5,134.10 |
| 96% | 0.370125 | 4,400.50 |
| 98% | 0.186725 | 3,666.90 |
| 100% | 0.003325 | 2,933.30 |

### Cheap-model break-even

Compare DeepSeek with Gemini using the assignment's escalation-cost model:

```text
C = DeepSeek token cost / task = USD 0.00068697
E = Gemini token cost + expected fallback / task = USD 0.00332527
F = human fallback cost = USD 9.17

P_break_even = 1 - (E - C) / F = 99.9712%
```

DeepSeek's measured success rate is **85.71%**, below the **99.9712%**
break-even threshold by 14.26 percentage points. Its lower token price does
not offset its observed fallback cost. The exported
`break_even_pass_rate_vs_human` field is a separate comparison against
human-only handling.

For the reliability diagnostic, GPT-5 Mini v2/parallel has
`P = 60/70`, `T = 3.5`, and `s = P^(1/T) = 0.956913`.
This is an implied value calculated from whole-run outcomes, not a direct
measurement of independent step reliability.

## 7. Repository and evidence map

| Path | Purpose |
|---|---|
| `A2_scaffold/agent.py` | D1 loop, tool execution, per-run traces and usage |
| `A2_scaffold/tools.py` | D2 tools, registry, v1/v2 descriptors, simulated booking log |
| `A2_scaffold/prompt.py` | Routing rules, scheduling and response contracts |
| `A2_scaffold/guardrails.py` | D3 caps, duplicate-action checks and autonomy gate |
| `A2_scaffold/backends.py` | Deterministic scripts and live HTTP adapter |
| `A2_scaffold/config.py` | Backend/model settings, limits and cost assumptions |
| `A2_scaffold/harness.py`, `run_eval.py` | D4/D5 grading, result storage, D6 calculations |
| `A2_reference_data/data_B/` | Synthetic referrals, patients, specialties, slots, contacts and clock |
| `A2_reference_data/expected_outcomes_B.json` | Labels, triggers and judgement requirements |
| `A2_reference_data/make_fixtures_B.py` | Fixture generator; not needed for the quick start |
| `A2_reference_data/check_my_data.py` | Data structure, links and supplied-record checks |
| `A2_scaffold/run_guardrail_checklist.py` | D3 checklist |
| `A2_scaffold/demo_loop_failure.py` | D7 failure and recovery demonstrations |
| `A2_scaffold/A2_Scaffold_Tour_ProblemB.ipynb` | Optional notebook tour; CLI is the reproduction entry point |
| `CONTRIBUTIONS.md` | Team responsibilities and AI-assistance declaration |

The fixture files are already included. Regenerating them is unnecessary for
reproduction and can overwrite local data changes.

| File under `A2_scaffold/results/` | Evidence |
|---|---|
| `d4_d5a_scripted_results.json` | Offline trials, code-check outcomes and judgement queue |
| `results_<model>.json` | Live per-trial records, saved prompt-version/mode arms and measured usage |
| `d2b_descriptor_prompt_only.json` | Static prompt-size estimates; refresh for current source |
| `d2b_descriptor_comparison_<model>.json` | Comparison when matching v1/v2 arms exist |
| `d2c_sequential_parallel_<model>_<version>.json` | Comparison when both scheduling arms exist |
| `d3_guardrail_results.json` | Ten checklist outcomes, including three hostile-text cases |
| `d5_model_battery_summary.json` | Cross-model table and completeness checks |
| `d6_cost_analysis_<model>.json` | Cost assumptions, sensitivity and human-baseline break-even |
| `d7_failure_results.json` | Before/broken/recovered failure evidence |

`bookings.jsonl` is a minimal write ledger containing booking identifiers
and run metadata. The richer decision, reason, observations, guardrail
events, and costs are stored in the evaluation records; they are not all
embedded in each ledger row.

## 8. Known limits and troubleshooting

The system uses synthetic local fixtures and records simulated bookings.
Clinical and hostile-text checks use fixed substring matching. The three
scripted hostile-text tests verify predefined escalation paths.

| Symptom | What to check |
|---|---|
| `python` is not found | Use the installed interpreter, `py -3.12` on Windows, or `python3` where appropriate |
| Reference data cannot be found | Keep the two project directories adjacent or set `A2_DATA` to the parent of `data_B/` |
| Offline run unexpectedly requests a key | Explicitly set `A2_BACKEND=scripted`; environment variables override defaults |
| No script exists for a new case | Add both its label/fixture and its replay moves in `backends.py::SCRIPTS` |
| Changes to fixtures are not visible in a notebook | Restart the Python process/kernel to clear the fixture cache |
| Costs differ from saved scripted results | Compare explicit prices and token-source labels; scripted costs are hypothetical |
| Judgement summary is absent | Run `--judge` with the settings matching an existing saved run |
| Live model returns an API error | Check its slug, API access and available credit; use scripted mode to verify local behaviour |

