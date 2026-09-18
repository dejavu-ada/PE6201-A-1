#!/usr/bin/env python3
"""Run the controlled D2(b) v1-versus-v2 descriptor experiment.

Prompt-only mode is free and reports static prompt size. Live mode runs the
same cases on the same configured model for both descriptor versions and
records measured tokens, latency, turns, cost, and code-check pass rate.
"""
import argparse
import json
import os
import statistics
from datetime import datetime, timezone

import config
import prompt
from harness import load_cases, run_set
from run_eval import RESULTS_DIR, _safe_name, _write_json


VERSIONS = ("v1", "v2")


def prompt_metrics(problem, version):
    text = prompt.build_system_prompt(problem, version)
    return {
        "characters": len(text),
        "rough_tokens_chars_div_4": len(text) // 4,
    }


def measured_summary(results):
    records = [row["record"] for row in results]
    total = len(results)
    passed = sum(1 for row in results if row["passed"])
    tokens_in = [row["tokens_in"] for row in records]
    tokens_out = [row["tokens_out"] for row in records]
    seconds = [row["seconds"] for row in records]
    turns = [row["turns"] for row in records]
    return {
        "trials": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "total_tokens_in": sum(tokens_in),
        "total_tokens_out": sum(tokens_out),
        "mean_tokens_per_trial": (
            (sum(tokens_in) + sum(tokens_out)) / total if total else 0.0),
        "median_latency_seconds": (
            statistics.median(seconds) if seconds else None),
        "median_turns": statistics.median(turns) if turns else None,
        "total_cost_usd": round(
            sum(row["cost_usd"] for row in records), 6),
    }


def serialisable_results(results):
    return [
        {
            "case_id": row["case_id"],
            "trial": row["trial"],
            "family": row["family"],
            "passed": row["passed"],
            "fails": row["fails"],
            "record": row["record"],
        }
        for row in results
    ]


def run_experiment(case_ids, problem, prompt_only=False):
    output = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "problem": problem,
        "model": config.MODEL,
        "backend": "prompt_only" if prompt_only else config.BACKEND,
        "controlled_variables": {
            "same_model": config.MODEL,
            "same_cases": case_ids,
            "temperature": 0,
            "versions": list(VERSIONS),
        },
        "versions": {},
    }

    for version in VERSIONS:
        entry = {"prompt": prompt_metrics(problem, version)}
        if not prompt_only:
            config.DESCRIPTOR_VERSION = version
            results, judgement_queue = run_set(case_ids, problem=problem)
            entry["summary"] = measured_summary(results)
            entry["results"] = serialisable_results(results)
            entry["judgement_queue"] = judgement_queue
        output["versions"][version] = entry
    return output


def print_summary(output):
    print()
    print("D2(b) DESCRIPTOR COMPARISON")
    print("model: %s" % output["model"])
    print("backend: %s" % output["backend"])
    for version in VERSIONS:
        entry = output["versions"][version]
        p = entry["prompt"]
        line = "%s: prompt=%d chars (~%d tokens)" % (
            version, p["characters"], p["rough_tokens_chars_div_4"])
        if "summary" in entry:
            s = entry["summary"]
            line += (", pass=%d/%d (%.1f%%), measured tokens=%d, "
                     "median latency=%.3fs" % (
                         s["passed"], s["trials"], 100 * s["pass_rate"],
                         s["total_tokens_in"] + s["total_tokens_out"],
                         s["median_latency_seconds"]))
        print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", help="case ids; default is all")
    parser.add_argument("--prompt-only", action="store_true",
                        help="compare prompt sizes without calling a model")
    parser.add_argument(
        "--output", default=None,
        help="optional path; default uses the purpose-specific results folder")
    args = parser.parse_args()

    if not args.prompt_only and config.BACKEND != "live":
        raise SystemExit(
            "Measured comparison requires A2_BACKEND=live. "
            "Use --prompt-only for the free static comparison.")
    if not args.prompt_only and not config.API_KEY:
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. Do not report scripted token "
            "estimates as measured results.")

    case_ids = args.cases or load_cases(config.PROBLEM)
    output = run_experiment(case_ids, config.PROBLEM, args.prompt_only)
    print_summary(output)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False, default=str)
        print("wrote %s" % args.output)
    else:
        name = (
            "d2b_descriptor_prompt_only.json"
            if args.prompt_only
            else "d2b_descriptor_experiment_%s.json"
                 % _safe_name(config.MODEL)
        )
        path = os.path.join(RESULTS_DIR, name)
        _write_json(path, output)
        print("wrote results/%s" % name)


if __name__ == "__main__":
    main()
