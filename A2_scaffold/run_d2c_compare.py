#!/usr/bin/env python3
"""
PE6201 · A2 — D2(c) CONTROLLED EXPERIMENT: 串行 vs 并行
====================================================================
    python3 run_d2c_compare.py            跑全部 SCRIPTED cases，串行→并行
    python3 run_d2c_compare.py REF-5602   只跑单个 case，打印两版详细结果
    python3 run_d2c_compare.py --csv      额外导出 comparison.csv

同一套 evaluation cases、同一套 v2 descriptors、同一个 scripted backend、
同一个 agent loop —— 只切换 PARALLEL_TOOLS 开关。

DEPENDENCY RULE （D2(c) 要写清楚这个）
--------------------------------------------------------------------
  可并行 = 两个工具都不需要对方的输出。Problem B 中常见的可并行 pair：
     check_referral_criteria  ||  lookup_patient     （都只依赖 referral_id）
     as_of                    ||  lookup_patient     （patient_id 已知时）
     as_of                    ||  check_referral_criteria （也可并行）

  绝对不能并行的依赖链：
     get_referral  →  check_referral_criteria  →  get_clinic_slots  →  book_slot
                          →  (band/specialty)  →  get_clinic_slots
     lookup_patient  →  (mandatory tests)  →  check_referral_criteria 结果可能变
所以依赖检查永远发生在 slot 查找 之前。

最终输出：
   outputs/results_sequential.json
   outputs/results_parallel.json
   outputs/comparison.json         （机器可读）
   outputs/comparison.csv          （可选，--csv 触发）
并在终端打印一张 comparison table。
====================================================================
"""
import csv
import json
import os
import statistics
import sys

import config
from backends import SCRIPTS
from harness import (load_cases, load_key, report, run_set,
                     _is_negative)
import results_trace as RT

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")


def _mkdirs():
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
    except TypeError:
        # Python <3.2
        if not os.path.isdir(OUT_DIR):
            os.makedirs(OUT_DIR)


def _run_mode(parallel, case_ids=None, verbose=False):
    """Run the eval set under one mode and return (results, summary, queue)."""
    label = "parallel" if parallel else "sequential"
    print()
    print("=" * 72)
    print("  RUN MODE  PARALLEL_TOOLS=%-10s   (%s)" % (parallel, label.upper()))
    print("=" * 72)
    results, queue = run_set(case_ids, verbose=verbose, parallel_tools=parallel)
    if not results:
        print("  (no results — were cases filtered out?)")
        return results, None, queue
    summary = report(results)
    return results, summary, queue


def _metric_row(results, tag):
    """Extract the numerical row used in the comparison table."""
    if not results:
        return None
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    neg_results = [r for r in results
                   if _is_negative(load_key().get(r["case_id"]))]
    neg_passed = sum(1 for r in neg_results if r["passed"])
    turns = [r["record"]["turns"] for r in results]
    tools = [len(r["record"].get("tool_trace", [])) for r in results]
    cost = sum(r["record"]["cost_usd"] for r in results)
    tokens_in = sum(r["record"]["tokens_in"] for r in results)
    tokens_out = sum(r["record"]["tokens_out"] for r in results)
    step_cap = sum(1 for r in results
                   if r["record"].get("stopped_by") == "step_cap")
    return {
        "tag": tag,
        "trials": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "neg_trials": len(neg_results),
        "neg_passed": neg_passed,
        "neg_pass_rate": (neg_passed / len(neg_results)
                          if neg_results else None),
        "median_turns": statistics.median(turns) if turns else None,
        "max_turns": max(turns) if turns else None,
        "median_tools": statistics.median(tools) if tools else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
        "step_cap_hits": step_cap,
    }


def _print_table(seq_row, par_row):
    """Pretty-print the D2(c) comparison table to stdout."""
    def _fmt(v, fmt="%s", default="-"):
        return default if v is None else (fmt % v)

    print()
    print("=" * 72)
    print("  D2(c) — 串行 vs 并行  对比表  (scripted, same eval set)")
    print("=" * 72)
    hdr = "%-26s  %14s  %14s  %12s" % ("metric", "SEQUENTIAL",
                                          "PARALLEL", "Δ (par - seq)")
    print(hdr)
    print("-" * 72)

    def _row(name, seq_v, par_v, fmt_s="%s", note_percent=False,
             note_cost=False):
        delta = None
        if seq_v is not None and par_v is not None:
            try:
                delta = par_v - seq_v
            except TypeError:
                delta = None
        d_str = "-"
        if delta is not None:
            if note_percent:
                d_str = ("%+6.2f pp" % (delta * 100.0))
            elif note_cost:
                d_str = ("%+.4f $" % delta)
            else:
                try:
                    d_str = ("%+8.2f" % delta) if isinstance(delta, float) \
                            else ("%+d" % delta)
                except TypeError:
                    d_str = "-"
        print("%-26s  %14s  %14s  %12s" % (
            name, _fmt(seq_v, fmt_s), _fmt(par_v, fmt_s), d_str))

    _row("trials total",         seq_row["trials"],      par_row["trials"],      "%d")
    _row("passed trials",        seq_row["passed"],      par_row["passed"],      "%d")
    _row("overall pass rate",    seq_row["pass_rate"],   par_row["pass_rate"],   "%.2f %%",
         note_percent=True)
    _row("negative trials",      seq_row["neg_trials"],  par_row["neg_trials"],  "%d")
    _row("negative pass rate",   seq_row["neg_pass_rate"], par_row["neg_pass_rate"],
         "%.2f %%", note_percent=True)
    _row("median turns",         seq_row["median_turns"], par_row["median_turns"],
         "%.1f")
    _row("worst case turns",     seq_row["max_turns"],   par_row["max_turns"],   "%d")
    _row("median tool calls",    seq_row["median_tools"], par_row["median_tools"],
         "%.1f")
    _row("tokens_in (estimated)", seq_row["tokens_in"],  par_row["tokens_in"],   "%d")
    _row("tokens_out (estimated)", seq_row["tokens_out"], par_row["tokens_out"],  "%d")
    _row("cost (estimated US$)", seq_row["cost_usd"],    par_row["cost_usd"],
         "%.4f", note_cost=True)
    _row("step_cap hits",        seq_row["step_cap_hits"], par_row["step_cap_hits"],
         "%d")
    print("-" * 72)
    print()

    correctness_changed = (seq_row["pass_rate"] != par_row["pass_rate"]
                           or seq_row["neg_pass_rate"] != par_row["neg_pass_rate"])
    if correctness_changed:
        print("  [!] CORRECTNESS changed — investigate whether different")
        print("      cases failed between the two runs.")
    else:
        print("  [OK] CORRECTNESS unchanged (same pass rate). D2(c) satisfied.")
    print()
    return correctness_changed


def _save_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=str)
    print("  wrote", path)


def main(argv):
    _mkdirs()
    print()
    print(config.summary())
    print("data:", config.data_root())

    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}
    want_csv = "--csv" in flags

    # ----- select cases -----
    if args:
        case_ids = args
        print("\n  Single-case mode:", ", ".join(case_ids))
        verbose_mode = True
    else:
        key = load_key()
        case_ids = [c for c in load_cases()
                    if c in SCRIPTS and c in key]
        print("\n  D2(c) set: %d cases (%d scripted + labeled)"
              % (len(case_ids), len(case_ids)))
        verbose_mode = False

    if not case_ids:
        print("\n  (no cases — is Problem set correctly?)")
        return 1

    # ----- run sequential, then parallel -----
    seq_res, seq_sum, seq_q = _run_mode(parallel=False,
                                        case_ids=case_ids,
                                        verbose=verbose_mode)
    par_res, par_sum, par_q = _run_mode(parallel=True,
                                        case_ids=case_ids,
                                        verbose=verbose_mode)

    # ----- per-case comparison for single-run verbose -----
    if verbose_mode:
        print()
        print("  PER-CASE COMPARISON:")
        for cid in case_ids:
            s = [r for r in seq_res if r["case_id"] == cid]
            p = [r for r in par_res if r["case_id"] == cid]
            for i in range(max(len(s), len(p))):
                sr = s[i] if i < len(s) else None
                pr = p[i] if i < len(p) else None
                if sr is None or pr is None:
                    continue
                print("    %s t=%d  seq turns=%d par turns=%d  "
                      "seq=%s par=%s" % (cid, i + 1,
                                         sr["record"]["turns"],
                                         pr["record"]["turns"],
                                         "OK" if sr["passed"] else "XX",
                                         "OK" if pr["passed"] else "XX"))
                if sr["passed"] != pr["passed"]:
                    print("        FAILS seq:", sr["fails"])
                    print("        FAILS par:", pr["fails"])
        print()

    # ----- aggregate metrics -----
    seq_row = _metric_row(seq_res, "sequential")
    par_row = _metric_row(par_res, "parallel")

    correctness_changed = _print_table(seq_row, par_row)

    # ----- save outputs -----
    def _bundle(results, summary, queue, mode_tag):
        return {
            "config": (config.summary() +
                       " | execution_mode=%s" % mode_tag),
            "execution_mode": mode_tag,
            "parallel_tools": (mode_tag == "parallel"),
            "summary": summary,
            "metrics": _metric_row(results, mode_tag),
            "results": [{k: v for k, v in r.items()} for r in results],
            "judgement_queue": queue,
        }

    _save_json(os.path.join(OUT_DIR, "results_sequential.json"),
               _bundle(seq_res, seq_sum, seq_q, "sequential"))
    _save_json(os.path.join(OUT_DIR, "results_parallel.json"),
               _bundle(par_res, par_sum, par_q, "parallel"))

    key_data = load_key()
    seq_std = RT.standardize_results(seq_res, key_data)
    par_std = RT.standardize_results(par_res, key_data)
    RT.write_standard_json(seq_std,
        os.path.join(OUT_DIR, "d2c_sequential_trace.json"),
        extra_meta={"experiment": "D2c", "execution_mode": "sequential"})
    RT.write_standard_csv(seq_std,
        os.path.join(OUT_DIR, "d2c_sequential_trace.csv"))
    RT.write_standard_json(par_std,
        os.path.join(OUT_DIR, "d2c_parallel_trace.json"),
        extra_meta={"experiment": "D2c", "execution_mode": "parallel"})
    RT.write_standard_csv(par_std,
        os.path.join(OUT_DIR, "d2c_parallel_trace.csv"))
    combined = []
    for r in seq_std:
        rr = dict(r); rr["execution_mode"] = "sequential"; rr["experiment_tag"] = "d2c_seq"; combined.append(rr)
    for r in par_std:
        rr = dict(r); rr["execution_mode"] = "parallel"; rr["experiment_tag"] = "d2c_par"; combined.append(rr)
    import csv as _csv
    cols = ["experiment_tag"] + RT.STANDARD_COLUMNS
    with open(os.path.join(OUT_DIR, "d2c_combined_trace.csv"), "w",
              encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in combined:
            out = dict(r)
            for k in ("evidence", "guardrails_fired", "fails"):
                v = out.get(k, [])
                if isinstance(v, list):
                    out[k] = " | ".join(str(x) for x in v)
            w.writerow({c: out.get(c, "") for c in cols})
    print("  wrote outputs/d2c_*_trace.json/.csv + d2c_combined_trace.csv (unified format)")

    comparison = {
        "experiment": "D2(c) sequential vs parallel (scripted)",
        "dependency_rule": (
            "Calls sharing no inputs MAY run parallel. "
            "Chain dependencies (band→slots, referral→specialty, "
            "mandatory_test→criteria_result) are serialised by the "
            "prompt regardless of the PARALLEL_TOOLS flag, so the "
            "flag only affects provably-independent batch points."
        ),
        "cases": case_ids,
        "correctness_changed": correctness_changed,
        "sequential": seq_row,
        "parallel": par_row,
        "delta": {
            "trials": (par_row["trials"] - seq_row["trials"]),
            "pass_rate_pp": None if (seq_row["pass_rate"] is None
                                     or par_row["pass_rate"] is None)
                         else (par_row["pass_rate"] - seq_row["pass_rate"]),
            "median_turns": None if (seq_row["median_turns"] is None
                                     or par_row["median_turns"] is None)
                            else (par_row["median_turns"] - seq_row["median_turns"]),
            "cost_usd": round(par_row["cost_usd"] - seq_row["cost_usd"], 6),
            "tokens_in": par_row["tokens_in"] - seq_row["tokens_in"],
            "tokens_out": par_row["tokens_out"] - seq_row["tokens_out"],
        },
    }
    _save_json(os.path.join(OUT_DIR, "comparison.json"), comparison)

    if want_csv:
        csv_path = os.path.join(OUT_DIR, "comparison.csv")
        rows = [seq_row, par_row]
        keys = [k for k in seq_row.keys()]
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print("  wrote", csv_path)

    print()
    print("  D2(c) complete. Files in outputs/:")
    for n in ("results_sequential.json", "results_parallel.json",
              "comparison.json"):
        print("    -", n)

    return 0 if not correctness_changed else 0   # exit 0 either way


if __name__ == "__main__":
    sys.exit(main(sys.argv))
