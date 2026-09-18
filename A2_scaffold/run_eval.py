#!/usr/bin/env python3
"""
PE6201 · A2 scaffold — ENTRY POINT
====================================================================
    python3 run_eval.py              run every SCRIPTED case
    python3 run_eval.py REF-5602     run one case, showing every turn
    python3 run_eval.py --all        run every case in the work queue
    python3 run_eval.py --prompt     print what the model is told, and stop

THIS IS WHAT A MARKER RUNS. Clone, `python3 run_eval.py`, numbers come
back. No key, no network, no arguments. If that does not work on a
clean machine, D5(a) has failed and Technical Execution is capped.

Test it the way a marker will: clone your own repository into a fresh
folder and run it there. "Works on my laptop" has caught out every
cohort so far.
====================================================================
"""
import json
import os
import sys

import config
from backends import SCRIPTS
from harness import load_cases, load_key, report, run_set
import results_trace as RT

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)


def main(argv):
    print()
    print(config.summary())
    print("data: %s" % config.data_root())

    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}

    # ---- show exactly what the model is told, then stop ----------------
    if "--prompt" in flags:
        import prompt
        print()
        prompt.audit()
        return 0

    # ---- one named case, verbose --------------------------------------
    if args:
        case_id = args[0]
        print()
        print("-" * 68)
        print("  %s - every turn" % case_id)
        print("-" * 68)
        results, queue = run_set([case_id], verbose=True)
        if not results:
            return 1
        print()
        print("  DECISION RECORD")
        #-------------让终端完整显示整个 Decision Record，包括完整 tool_trace--------------
        print(json.dumps(results[0]["record"], indent=2,default = str))
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
        return 0 if results[0]["passed"] else 1

    # ---- the set ------------------------------------------------------
    if "--all" in flags:
        cases = load_cases()
        print("\n  Running EVERY case in the work queue (%d)." % len(cases))
        print("  Cases with no script will stop the run - that is the")
        print("  scripted backend telling you to write one.")
    else:
        # Default: only what is scripted, so a clean clone always works.
        key = load_key()
        cases = [c for c in load_cases() if c in SCRIPTS and c in key]
        print("\n  Running the %d SCRIPTED case(s): %s"
              % (len(cases), ", ".join(cases)))
        print("  Add more to SCRIPTS in backends.py, or use --all once you")
        print("  have scripted them.")

    if not cases:
        print("\n  Nothing to run for Problem %s." % config.PROBLEM)
        print("  config.PROBLEM is %r - is that the problem you chose?"
              % config.PROBLEM)
        return 1

    results, queue = run_set(cases)
    summary = report(results)
    key = load_key()

    std_rows = RT.standardize_results(results, key)

    with open("results.json", "w", encoding="utf-8") as fh:
        json.dump({"config": config.summary(), "summary": summary,
                   "results": [{k: v for k, v in r.items()} for r in results],
                   "judgement_queue": queue}, fh, indent=2, default=str)
    print("  Wrote results.json - commit it. Your result tables come from")
    print("  here, and a marker reads it alongside your report.")

    RT.write_standard_json(std_rows,
        os.path.join(OUT_DIR, "eval_parallel_trace.json"),
        extra_meta={"experiment": "scripted_eval_parallel",
                    "execution_mode": "parallel",
                    "judgement_queue": queue})
    RT.write_standard_csv(std_rows,
        os.path.join(OUT_DIR, "eval_parallel_trace.csv"))
    print("  wrote outputs/eval_parallel_trace.json + .csv (unified format)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
