# PE6201 A2 - Problem B

Single-agent referral coordination with a hand-written ReAct loop, local
fixture tools, four code guardrails, scripted/live backends, controlled
experiments and purpose-specific JSON evidence.

## Main command

Edit `config.py`, then run:

```powershell
python run_eval.py
```

The committed default is `BACKEND = "scripted"`, so a marker can reproduce
D4/D5(a) without a network or API key.

## Live model run for each team member

Each member sets these fields before running their assigned model:

```python
BACKEND = "live"
MODEL = "openai/gpt-4o-mini"
PRICE_TIER = "cheap"                 # cheap | mid | frontier
PRICE_IN = 0.10                       # current USD per 1M input tokens
PRICE_OUT = 0.40                      # current USD per 1M output tokens
CALL_MODE = "parallel"               # identical across the D5 battery
DESCRIPTOR_VERSION = "v2"
```

Keep the key outside the repository:

```powershell
$env:OPENROUTER_API_KEY = "your-key"
python run_eval.py
```

The output is named from the model, for example:

```text
results/results_openai_gpt_4o_mini.json
results/results_anthropic_claude_sonnet_4.json
results/results_google_gemini_2_5_flash.json
```

Put all model result files in the same `results/` folder and run the no-cost
refresh command to rebuild `d5_model_battery_summary.json`. Results contain
no member names or team-size metadata; the model family is derived from the
model slug, and the battery target is six v2 live models:

```powershell
python run_eval.py --refresh
```

`backends.py` reads measured input/output token usage from the live API.
Scripted counts are explicitly labelled estimates.

## Controlled experiments

### D2(b) descriptor v1 versus v2

Use the same live model, cases and `CALL_MODE`:

1. Set `DESCRIPTOR_VERSION = "v1"`; run `python run_eval.py`.
2. Set `DESCRIPTOR_VERSION = "v2"`; run `python run_eval.py`.

Both raw arms remain in that model's `results_<model>.json`; the derived
comparison is written as:

```text
results/d2b_descriptor_comparison_<model>.json
```

Free prompt-size evidence:

```powershell
python run_descriptor_experiment.py --prompt-only
```

Output: `results/d2b_descriptor_prompt_only.json`.

### D2(c) sequential versus parallel

Keep model, cases, prompt, descriptor and prices unchanged:

1. Set `CALL_MODE = "sequential"`; run `python run_eval.py`.
2. Set `CALL_MODE = "parallel"`; run `python run_eval.py`.

Raw trials stay in the model result file; the controlled comparison is:

```text
results/d2c_sequential_parallel_<model>_<descriptor>.json
```

### D3, D7 and checks

```powershell
python ..\A2_reference_data\check_my_data.py
python run_guardrail_checklist.py
python demo_loop_failure.py
python -m unittest -v test_poka_yoke.py
```

## Result files by purpose

| Result file | Purpose |
|---|---|
| `results/d4_d5a_scripted_results.json` | Reproducible 50-case/70-trial scripted baseline |
| `results/results_<model>.json` | One member's complete live-model trials, including any v1/v2 and sequential/parallel arms run on that model |
| `results/d2b_descriptor_prompt_only.json` | Free static v1/v2 prompt-size evidence |
| `results/d2b_descriptor_comparison_<model>.json` | Same-model measured v1/v2 comparison |
| `results/d2c_sequential_parallel_<model>_<version>.json` | Same-model sequential/parallel comparison |
| `results/d3_guardrail_results.json` | Ten scripted guardrail cases, including three hostile free-text cases |
| `results/d5_model_battery_summary.json` | Cross-model v2 table and rule checks |
| `results/d6_cost_analysis_<model>.json` | Three-layer cost, sensitivity and break-even for one model |
| `results/d7_failure_results.json` | Two deletion failures with before/broken/recovered evidence |

`bookings.jsonl` is not an experiment result. It is the append-only local
ledger for the gated irreversible booking action.

## D0-D7 code map

| Requirement | File and exact part |
|---|---|
| D0 boundary / why an agent | Report work; code evidence is the variable-length `agent.py::run_case` loop |
| D1 hand-built single-agent loop | `agent.py::run_case` |
| D2(a) tools and interfaces | `tools.py::REGISTRY`, Problem B tool functions, `DESCRIPTORS_V2` |
| D2(b) descriptor rewrite | `tools.py::DESCRIPTORS_V1/V2`, `prompt.py::build_system_prompt`, `run_descriptor_experiment.py`, `run_eval.py::_d2b_comparison` |
| D2(c) execution mode | `config.py::CALL_MODE`, `prompt.py::calling_rule`, `agent.py::run_case`, `run_eval.py::_d2c_comparison` |
| D3(a) four controls | `guardrails.py::Guardrails`; gate runs immediately before `book_slot` |
| D3(b) checklist | `run_guardrail_checklist.py::CASES` |
| D4 cases and graders | `make_fixtures_B.py`, `expected_outcomes_B.json`, `harness.py::run_set/code_check/prepare_judgement_check/report` |
| D5(a) reproducible run | `backends.py::ScriptedBackend`, scripted default in `config.py`, `run_eval.py` |
| D5(b) model battery | `backends.py::LiveBackend/_live_call`, metadata in `config.py`, `run_eval.py::_refresh_d5_model_battery` |
| D6 economics | measured usage in `backends.py`, instrumentation in `agent.py`, calculations in `harness.py::report`, export in `run_eval.py::_d6_cost_analysis` |
| D7 failures | `demo_loop_failure.py::reproduce_dedup_failure/reproduce_missing_tool_failure` |

## Other commands

```powershell
python run_eval.py REF-5602     # one case with every turn displayed
python run_eval.py --prompt     # exact selected prompt/descriptors
python run_eval.py --judge      # grade the selected model/version/mode queue
python run_eval.py --refresh    # rebuild comparisons; makes no model calls
```

The extended set contains 50 labelled cases: 40 ordinary cases run once and
10 negative cases run three times, giving 70 trials per model/configuration.
