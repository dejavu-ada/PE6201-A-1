#!/usr/bin/env python3
"""
PE6201 · A2 — run_live.py  (LIVE backend 专用入口，单独放，防止误烧钱)
====================================================================
    python3 run_live.py                        — 先检查 API key，再跑默认 live set
    python3 run_live.py --dry-run              — 只打印计划，不调用模型
    python3 run_live.py --model X/Y            — 临时指定模型
    python3 run_live.py --parallel             — 并行模式（默认也是并行）
    python3 run_live.py --sequential           — 串行模式
    python3 run_live.py REF-5602 REF-5590      — 只跑指定 cases
    python3 run_live.py --all                  — 跑全部工作队列（小心花费）
    python3 run_live.py --repeat 3             — 每个 case 跑 N 次（默认按 harness）
    python3 run_live.py --descriptor v1        — 临时切 descriptor 版本（D2b）

⚠️  这个文件只使用 LIVE backend，每次运行都要花钱。
    默认情况下，只跑在 answer key 里有标签且在 harness 里 scripted 的 cases，
    也就是 D5 marker 的同一批。用 --all 会跑整个工作队列，小心预算。

启动前需要：
    set A2_BACKEND=live
    set OPENROUTER_API_KEY=sk-or-...

或者用环境变量一次性跑完：
    $env:A2_BACKEND="live"; $env:OPENROUTER_API_KEY="sk-or-..."; python run_live.py

产出物全部放在 outputs/live_*，绝不会误写到 run_all_scripted.py 生成的
outputs/comparison.json 等位置，避免覆盖掉免费的 scripted 结果。
====================================================================
"""
import argparse
import datetime
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

LIVE_PREFIX = "live_"


def _force_live_backend():
    import config
    config.BACKEND = "live"
    os.environ["A2_BACKEND"] = "live"


def _banner(msg):
    bar = "!" * 72
    print("\n" + bar)
    for line in msg:
        print("  " + line)
    print(bar + "\n")


def _check_api_key():
    import config
    _force_live_backend()
    ok = bool(config.API_KEY and not config.API_KEY.startswith('"')
              and len(config.API_KEY) > 8)
    if not ok:
        _banner([
            "NO LIVE API KEY FOUND — cannot run.",
            "",
            "Windows (PowerShell):",
            '  $env:OPENROUTER_API_KEY = "sk-or-..."',
            '  $env:A2_BACKEND = "live"',
            "Windows (CMD):",
            '  set OPENROUTER_API_KEY=sk-or-...',
            '  set A2_BACKEND=live',
            "Linux / macOS / Colab:",
            '  export OPENROUTER_API_KEY="sk-or-..."',
            '  export A2_BACKEND="live"',
        ])
        return False
    _banner([
        "LIVE BACKEND SELECTED — this session will call the real model.",
        "backend: %s" % config.BACKEND,
        "model  : %s" % config.MODEL,
        "base URL: %s" % config.BASE_URL,
        "price  : in $%.4f / 1M, out $%.4f / 1M" % (config.PRICE_IN, config.PRICE_OUT),
        "key    : …%s" % config.API_KEY[-6:],
        "",
        "If this is a mistake, press Ctrl+C NOW.",
    ])
    return True


def _estimate(ntrials, per_case_tok_in=16000, per_case_tok_out=800):
    """给出一个粗略的成本估计，用户看了再决定要不要跑。"""
    import config
    usd = (ntrials * per_case_tok_in * config.PRICE_IN / 1e6
           + ntrials * per_case_tok_out * config.PRICE_OUT / 1e6)
    return usd


def _select_cases(args, key, all_cases, scripted_set):
    if args.case_ids:
        cids = [c for c in args.case_ids if c in key]
        missed = [c for c in args.case_ids if c not in key]
        if missed:
            print("  [warn] skipped unlabelled cases: %s" % ", ".join(missed))
        return cids

    if args.all:
        return [c for c in all_cases if c in key]

    return [c for c in all_cases if c in scripted_set and c in key]


def _trials_fn(args, key):
    from harness import _is_negative
    base = lambda cid: 3 if _is_negative(key.get(cid)) else 1
    if args.repeat and args.repeat > 0:
        n = args.repeat
        return lambda cid: n
    return base


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(
        description="A2 LIVE entry (costs money). Separate from run_all_scripted.")
    p.add_argument("case_ids", nargs="*", help="specific case_ids to run (default: labeled scripted set)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan and estimate, do not call the model")
    p.add_argument("--model", default=None,
                   help="override config.MODEL (e.g. openai/gpt-4o, anthropic/claude-sonnet-4)")
    p.add_argument("--descriptor", default=None, choices=("v1", "v2"),
                   help="D2(b): override descriptor version for this run")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--parallel", action="store_true", default=None,
                      help="force PARALLEL_TOOLS=True (default)")
    mode.add_argument("--sequential", action="store_true", default=None,
                      help="force PARALLEL_TOOLS=False")
    p.add_argument("--all", action="store_true",
                   help="run the ENTIRE work queue (not just the scripted set — costs more)")
    p.add_argument("--repeat", type=int, default=None,
                   help="run each case N times regardless of negative status")
    p.add_argument("--confirm", action="store_true",
                   help="skip the 'press Enter to continue' confirmation")
    a = p.parse_args(argv[1:])

    os.environ["A2_BACKEND"] = "live"
    if a.model:
        os.environ["A2_MODEL"] = a.model
    if a.descriptor:
        os.environ["DESCRIPTOR_VERSION"] = a.descriptor
    if a.sequential:
        os.environ["PARALLEL_TOOLS"] = "false"
    elif a.parallel:
        os.environ["PARALLEL_TOOLS"] = "true"

    import importlib
    if "config" in sys.modules:
        importlib.reload(sys.modules["config"])
    import config

    from harness import load_cases, load_key, report, run_set
    from backends import SCRIPTS
    import results_trace as RT

    print()
    print(config.summary())
    print("data:", config.data_root())

    if not _check_api_key():
        return 2

    key = load_key()
    all_cases = load_cases()
    case_ids = _select_cases(a, key, all_cases, set(SCRIPTS.keys()))
    trials_fn = _trials_fn(a, key)

    ntrials = sum(trials_fn(c) for c in case_ids)
    est_usd = _estimate(ntrials)
    mode_tag = ("sequential" if a.sequential else
                ("parallel" if a.parallel else ("sequential" if not config.PARALLEL_TOOLS else "parallel")))
    run_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print()
    print("=" * 68)
    print("  LIVE RUN PLAN")
    print("=" * 68)
    print("  cases selected : %d" % len(case_ids))
    if case_ids:
        print("    sample first 6: %s" % ", ".join(case_ids[:6]))
    print("  trials total   : %d" % ntrials)
    print("  descriptor     : %s" % config.DESCRIPTOR_VERSION)
    print("  execution mode : %s" % ("parallel" if config.PARALLEL_TOOLS else "sequential"))
    print("  model          : %s" % config.MODEL)
    print("  rough cost est : ~$%.4f   (very rough — actual will vary)" % est_usd)
    print("  output tag     : %s" % run_tag)
    print("=" * 68)

    if a.dry_run:
        print()
        print("  --dry-run — exiting without calling the model.")
        print()
        return 0

    if not a.confirm:
        try:
            input("\n  Press Enter to continue (Ctrl+C to cancel) … ")
        except KeyboardInterrupt:
            print("\n  cancelled.")
            return 1

    started_at = datetime.datetime.now().isoformat(timespec="seconds")
    results, queue = run_set(case_ids, trials_for=trials_fn,
                             parallel_tools=config.PARALLEL_TOOLS)
    summary = report(results)

    std_rows = RT.standardize_results(results, key)

    basename = "%s%s_%s" % (LIVE_PREFIX, mode_tag, run_tag)
    json_path = os.path.join(OUT_DIR, basename + ".json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({
            "config": config.summary(),
            "started_at": started_at,
            "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "backend": "live",
            "model": config.MODEL,
            "descriptor_version": config.DESCRIPTOR_VERSION,
            "execution_mode": "parallel" if config.PARALLEL_TOOLS else "sequential",
            "cases": case_ids,
            "trial_count_total": ntrials,
            "estimated_cost_usd_rough": est_usd,
            "summary": summary,
            "results": [{k: v for k, v in r.items()} for r in results],
            "judgement_queue": queue,
        }, fh, indent=2, default=str)
    print("  wrote", json_path)

    trace_json = os.path.join(OUT_DIR, basename + "_trace.json")
    trace_csv = os.path.join(OUT_DIR, basename + "_trace.csv")
    RT.write_standard_json(std_rows, trace_json, extra_meta={
        "backend": "live", "model": config.MODEL,
        "execution_mode": "parallel" if config.PARALLEL_TOOLS else "sequential",
        "run_tag": run_tag,
    })
    RT.write_standard_csv(std_rows, trace_csv)
    print("  wrote", trace_json)
    print("  wrote", trace_csv)

    print()
    print("  Summary:")
    print("    trials: %d, passed: %d (%.1f%%)" % (
        summary["trials"], summary["passed"],
        (100.0 * summary["pass_rate"]) if summary["pass_rate"] is not None else 0.0))
    print("    total cost (LIVE billed): $%.6f" % summary["cost_usd"])
    print("    median turns: %s" % summary["median_turns"])
    print()

    return 0 if summary["passed"] == summary["trials"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
