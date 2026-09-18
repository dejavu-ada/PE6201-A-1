# D2(b) descriptor v1 versus v2 experiment

## Controlled variable design

The experiment changes only the descriptor version. Both arms use the same:

- Problem B case IDs and trial-count rule;
- model and temperature (`0`);
- routing rules, tools, Poka-Yoke checks, guardrails, and autonomy setting;
- answer key and code checker.

`DESCRIPTOR_VERSION=v1` selects the preserved baseline and
`DESCRIPTOR_VERSION=v2` selects the six-field rewrite.

## Free static comparison

Run:

```bash
python run_descriptor_experiment.py --prompt-only
```

Current result:

| Metric | v1 | v2 | Change |
|---|---:|---:|---:|
| Prompt characters | 8,922 | 11,270 | +2,348 (+26.3%) |
| Rough prompt tokens (`chars / 4`) | 2,230 | 2,817 | +587 (+26.3%) |

These are prompt-size estimates, not measured API usage. The v2 increase now
includes the canonical five-value trigger enum, the mandatory evidence-rich
`reason` contract discovered by the REF-5684 live smoke test, and the explicit
no-empty-call/four-turn progression discovered by REF-5602.

## Required live comparison

The committed default remains scripted. Set live mode and the API key only in
the shell; never commit the key:

```powershell
$env:A2_BACKEND="live"
$env:A2_MODEL="openai/gpt-4o-mini"
$env:OPENROUTER_API_KEY="<set-locally>"
python run_descriptor_experiment.py
```

For a small paid smoke test before the full battery:

```powershell
python run_descriptor_experiment.py REF-5602 REF-5711
```

The runner saves every trial and summarises, for each version:

- passed/trials and pass rate;
- measured input and output tokens;
- mean measured tokens per trial;
- median end-to-end latency;
- median turns; and
- total model cost.

By default prompt-only evidence is stored at
`results/d2b_descriptor_prompt_only.json`; a dedicated live invocation is
stored at `results/d2b_descriptor_experiment_<model>.json`. The ordinary
`run_eval.py` workflow also creates
`results/d2b_descriptor_comparison_<model>.json` after matching v1 and v2 runs
exist. Pass `--output <path>` only when another export is explicitly needed.
Do not report scripted estimates or `chars / 4` as measured token usage.
