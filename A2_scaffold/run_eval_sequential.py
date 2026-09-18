#!/usr/bin/env python3
"""
PE6201 · A2 scaffold — ENTRY POINT · SEQUENTIAL VERSION
====================================================================
    python run_eval_sequential.py              run every SCRIPTED case (sequential)
    python run_eval_sequential.py REF-5602     run one case, showing every turn
    python run_eval_sequential.py --all        run every case in the work queue
    python run_eval_sequential.py --prompt     print what the model is told, and stop
    set A2_BACKEND=live && python run_eval_sequential.py   (LIVE - costs money)

SEQUENTIAL MODE: Each turn calls ONE tool only.
This is the serial version for comparison against the parallel version.
Supports both scripted and live backends.
====================================================================
"""
import json
import sys
import os

import config
from backends import SCRIPTS
from harness import load_cases, load_key, code_check, prepare_judgement_check, report as _report
from agent_sequential import run_case
import results_trace as RT

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)


def run_set(case_ids=None, problem=None, trials_for=None, verbose=False):
    problem = problem or config.PROBLEM
    key = load_key(problem)
    case_ids = case_ids or load_cases(problem)

    def _is_negative(expected):
        if not expected:
            return False
        return expected.get("expected_decision") in (
            "escalate", "request_document", "request_information")

    trials_for = trials_for or (lambda cid: 3 if _is_negative(key.get(cid)) else 1)

    results, judgement_queue = [], []

    for cid in case_ids:
        expected = key.get(cid)
        if expected is None:
            print("  SKIP %s - no label in the answer key" % cid)
            continue

        for trial in range(1, trials_for(cid) + 1):
            record = run_case(cid, problem=problem, verbose=verbose)
            passed, fails = code_check(record, expected)
            results.append({"case_id": cid, "trial": trial, "passed": passed,
                            "fails": fails, "record": record,
                            "family": expected.get("family")})
            if trial == 1:
                judgement_queue.append(prepare_judgement_check(record, expected))

    return results, judgement_queue


def main(argv):
    print()
    print("=" * 68)
    print("  SEQUENTIAL EXECUTION MODE - ONE TOOL CALL PER TURN")
    print("=" * 68)
    print(config.summary())
    print("data: %s" % config.data_root())

    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}

    if "--prompt" in flags:
        import prompt_sequential as prompt
        print()
        prompt.audit()
        return 0

    if args:
        case_id = args[0]
        print()
        print("-" * 68)
        print("  %s - every turn (SEQUENTIAL MODE)" % case_id)
        print("-" * 68)
        results, queue = run_set([case_id], verbose=True)
        if not results:
            return 1
        print()
        print("  DECISION RECORD")
        print(json.dumps(results[0]["record"], indent=2, default=str))
        print()
        print("  CODE CHECK   %s" % ("PASS" if results[0]["passed"] else "FAIL"))
        for f in results[0]["fails"]:
            print("      %s" % f)
        print()
        print("  JUDGEMENT CHECK - not automated. Someone reads the reason")
        print("  and rules on each item:")
        for item in queue[0]["must_record"]:
            print("      [ ] %s" % item)
        print()
        print("  EXECUTION MODE: SEQUENTIAL (one tool call per turn)")
        turns = results[0]["record"]["turns"]
        tool_calls = len(results[0]["record"]["tool_trace"])
        print("  Turns recorded: %d   Tool calls made: %d" % (turns, tool_calls))
        print()
        return 0 if results[0]["passed"] else 1

    if "--all" in flags:
        cases = load_cases()
        print("\n  Running EVERY case in the work queue (%d) - SEQUENTIAL MODE."
              % len(cases))
        print("  Cases with no script will stop the run - that is the")
        print("  scripted backend telling you to write one.")
    else:
        key = load_key()
        cases = [c for c in load_cases() if c in SCRIPTS and c in key]
        print("\n  Running the %d SCRIPTED case(s): %s  [SEQUENTIAL MODE]"
              % (len(cases), ", ".join(cases)))
        print("  Add more to SCRIPTS in backends.py, or use --all once you")
        print("  have scripted them.")

    if not cases:
        print("\n  Nothing to run for Problem %s." % config.PROBLEM)
        print("  config.PROBLEM is %r - is that the problem you chose?"
              % config.PROBLEM)
        return 1

    results, queue = run_set(cases)
    summary = _report(results)
    key = load_key()

    std_rows = RT.standardize_results(results, key)

    out_filename = "results_sequential.json"
    with open(out_filename, "w", encoding="utf-8") as fh:
        json.dump({"config": config.summary() + " | EXECUTION_MODE=sequential",
                   "summary": summary,
                   "execution_mode": "sequential",
                   "results": [{k: v for k, v in r.items()} for r in results],
                   "judgement_queue": queue}, fh, indent=2, default=str)
    print("  Wrote %s - this contains the sequential-mode results."
          % out_filename)
    print("  Compare against results.json (parallel mode) for D2(c) analysis.")

    RT.write_standard_json(std_rows,
        os.path.join(OUT_DIR, "eval_sequential_trace.json"),
        extra_meta={"experiment": "scripted_eval_sequential",
                    "execution_mode": "sequential",
                    "judgement_queue": queue})
    RT.write_standard_csv(std_rows,
        os.path.join(OUT_DIR, "eval_sequential_trace.csv"))
    print("  wrote outputs/eval_sequential_trace.json + .csv (unified format)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
