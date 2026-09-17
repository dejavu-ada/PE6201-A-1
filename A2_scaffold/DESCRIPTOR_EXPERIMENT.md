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
python run_descriptor_experiment.py --prompt-only \
  --output descriptor_prompt_comparison.json
```

Current result:

| Metric | v1 | v2 | Change |
|---|---:|---:|---:|
| Prompt characters | 8,118 | 8,513 | +395 (+4.9%) |
| Rough prompt tokens (`chars / 4`) | 2,029 | 2,128 | +99 (+4.9%) |

These are prompt-size estimates, not measured API usage.

## Required live comparison

The committed default remains scripted. Set live mode and the API key only in
the shell; never commit the key:

```powershell
$env:A2_BACKEND="live"
$env:A2_MODEL="openai/gpt-4o-mini"
$env:OPENROUTER_API_KEY="<set-locally>"
python run_descriptor_experiment.py `
  --output descriptor_experiment_results.json
```

For a small paid smoke test before the full battery:

```powershell
python run_descriptor_experiment.py REF-5602 REF-5711 `
  --output descriptor_experiment_smoke.json
```

The runner saves every trial and summarises, for each version:

- passed/trials and pass rate;
- measured input and output tokens;
- mean measured tokens per trial;
- median end-to-end latency;
- median turns; and
- total model cost.

Do not report the scripted backend's estimates or the static `chars / 4`
number as measured token usage. Fill the final report table from the live JSON
output and retain the numerator and denominator for every pass rate.
