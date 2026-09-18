#!/usr/bin/env python3
"""
PE6201 · A2 — D7 FAILURE REPRODUCTIONS
====================================================================
    python3 run_failures.py                run both failures
    python3 run_failures.py 1              only Failure 1 (dedup)
    python3 run_failures.py 2              only Failure 2 (descriptor)
    python3 run_failures.py --verbose      print every trial line

Two failures. Both use the SCRIPTED backend — deterministic, free:

FAILURE 1 — LOOP-CONTROL LAYER (D7a explicit example)
      Delete the action de-duplication guard. Run REF-5711.
      Observe: turns ↑, cost ↑, agent may re-run the same tool multiple
      times because the scripted backend happily returns the same
      observation for a repeated call.
      Restore guard, show before/after delta on the full eval set too.

FAILURE 2 — PROMPT / DESCRIPTOR LAYER (different layer required)
      Temporarily replace tool descriptor `get_clinic_slots` with a v0
      baseline that omits the size bound and omits the
      `which clinics to query` guidance. Agent loses dependency-
      ordering information → picks a clinic first without band
      knowledge → books a slot in wrong band → fails code check.
      Restore v2 descriptors, show before/after delta.

For each failure we capture BEFORE (guards/prompt correct) and AFTER
(guard/prompt temporarily broken) on:
   * pass rate (code check)
   * median turns
   * tokens_in & tokens_out (estimated)
   * total cost (estimated)
   * guardrail / error events
====================================================================
"""
import importlib
import json
import os
import statistics
import sys

import config
import guardrails
from harness import load_key, code_check, load_cases, run_set, _is_negative
from backends import SCRIPTS

OUT_DIR = "outputs"
os.makedirs(OUT_DIR, exist_ok=True)

FAIL_CASE_QUICK = "REF-5711"        # F1: prompt-injection has more turns
FAIL_CASE_F2     = "REF-5602"        # F2: booking flow needs correct slots


# =====================================================================
# FAILURE 1  —  De-duplication guard removed
# =====================================================================
def _install_failure_1(active: bool):
    """Replace Guardrails.check_duplicate with a no-op when active=True."""
    if active:
        def _check_duplicate_NOOP(self, tool, args):
            signature = (tool, repr(sorted(args.items())))
            self.seen_actions.add(signature)
            return
        guardrails.Guardrails.check_duplicate = _check_duplicate_NOOP
    else:
        importlib.reload(guardrails)


def _replay_case_with_duplicate_actions(
    dedup_active: bool,
    case_id: str,
    inject_loop: bool = False
):
    import copy
    import backends
    import agent

    # 保存原来的正常 scripted path
    original_script = copy.deepcopy(backends.SCRIPTS[case_id])

    try:
        # D7 Failure 1：
        # 故意让 agent 重复完全相同的 action
        if inject_loop:
            first_move = copy.deepcopy(original_script[0])

            # 连续重复同一个 action，制造 loop
            backends.SCRIPTS[case_id] = [
                copy.deepcopy(first_move)
                for _ in range(10)
            ]

        # dedup_active=True  -> 正常开启 dedup guard
        # dedup_active=False -> 删除 dedup guard
        _install_failure_1(not dedup_active)

        importlib.reload(agent)

        rec = agent.run_case(
            case_id,
            parallel_tools=True,
            verbose=False
        )

        return rec

    finally:
        # 测试结束后恢复原来的 script 和 guard
        backends.SCRIPTS[case_id] = original_script

        _install_failure_1(False)
        importlib.reload(agent)


def run_failure_1(verbose=False):
    """Failure 1: remove dedup, compare before/after."""
    import agent
    key = load_key()
    all_cases = [c for c in load_cases() if c in SCRIPTS and c in key]

    def _run_one(label, dedup_active, quick_case=None):
        results = []
        case_list = [quick_case] if quick_case else all_cases
        for cid in case_list:
            rec = _replay_case_with_duplicate_actions(dedup_active,cid,inject_loop=(quick_case is not None)
)
            exp = key.get(cid)
            passed, fails = code_check(rec, exp) if exp else (True, [])
            results.append({"case_id": cid, "trial": 1, "passed": passed,
                            "fails": fails, "record": rec,
                            "family": (exp or {}).get("family")})

        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        turns = [r["record"]["turns"] for r in results]
        cost = sum(r["record"]["cost_usd"] for r in results)
        tin = sum(r["record"]["tokens_in"] for r in results)
        tout = sum(r["record"]["tokens_out"] for r in results)
        dedup_fires = sum(1 for r in results
                          for g in r["record"].get("guardrails_fired", [])
                          if g["guardrail"] == "duplicate_action")
        step_cap_hits = sum(1 for r in results
                            if r["record"].get("stopped_by") == "step_cap")
        errors_total = sum(len(r["record"].get("errors", [])) for r in results)
        return {
            "label": label,
            "dedup_guard_active": dedup_active,
            "cases_run": len(case_list),
            "trials": total,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "median_turns": statistics.median(turns) if turns else None,
            "max_turns": max(turns) if turns else None,
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd": round(cost, 6),
            "dedup_guard_fires": dedup_fires,
            "step_cap_hits": step_cap_hits,
            "total_recorded_errors": errors_total,
        }

    print()
    print("=" * 68)
    print("  D7 FAILURE 1 - loop-control layer: dedup guard removed")
    print("=" * 68)
    print()
    print("  Mechanism: Agent loop would repeat the SAME (tool, args) on a")
    print("  stuck path. With dedup guard ON → GuardrailStop. With guard")
    print("  OFF (deleted) → duplicate call executes, turns and cost grow.")
    print()

    print("  Quick single-case evidence on %s:" % FAIL_CASE_QUICK)
    before_q = _run_one("BEFORE (dedup ON)",  True,  quick_case=FAIL_CASE_QUICK)
    after_q  = _run_one("AFTER  (dedup OFF)", False, quick_case=FAIL_CASE_QUICK)
    print()
    print("    Quick %s:" % FAIL_CASE_QUICK)
    print("      BEFORE dedup ON  -> turns=%d, cost=$%.6f, dedup fires=%d"
          % (before_q["max_turns"] or 0, before_q["cost_usd"],
             before_q["dedup_guard_fires"]))
    print("      AFTER  dedup OFF -> turns=%d, cost=$%.6f, dedup fires=%d"
          % (after_q["max_turns"] or 0,  after_q["cost_usd"],
             after_q["dedup_guard_fires"]))
    print()
    print("  Full eval set (%d cases) for final report numbers:"
          % len(all_cases))
    before = _run_one("BEFORE (dedup ON)",  True)
    after  = _run_one("AFTER  (dedup OFF)", False)

    # restore before leaving
    _install_failure_1(False)
    importlib.reload(agent)

    print()
    print("    " + "-" * 62)
    hdr = "%-22s  %12s  %12s  %12s" % ("metric", "BEFORE(guard)",
                                        "AFTER(no guard)", "DELTA")
    print("    " + hdr)
    print("    " + "-" * 62)
    def _row(name, b, a, fmt="%s", cost=False, percent=False):
        try:
            d = None if (b is None or a is None) else a - b
        except TypeError:
            d = None
        ds = "-"
        if d is not None:
            if cost:    ds = "%+.4f $" % d
            elif percent: ds = "%+.2f pp" % (d * 100.0)
            else:       ds = ("%+d" % d) if isinstance(d, int) else ("%+.2f" % d)
        def F(v): return "-" if v is None else (fmt % v)
        print("    %-22s  %12s  %12s  %12s" % (name, F(b), F(a), ds))

    _row("trials",             before["trials"],          after["trials"],          "%d")
    _row("passed trials",      before["passed"],          after["passed"],          "%d")
    _row("pass_rate",          before["pass_rate"],       after["pass_rate"],       "%.2f", percent=True)
    _row("median turns",       before["median_turns"],    after["median_turns"],    "%.1f")
    _row("worst turns",        before["max_turns"],       after["max_turns"],       "%d")
    _row("tokens_in",          before["tokens_in"],       after["tokens_in"],       "%d")
    _row("tokens_out",         before["tokens_out"],      after["tokens_out"],      "%d")
    _row("cost US$",           before["cost_usd"],        after["cost_usd"],        "%.4f", cost=True)
    _row("dedup guard fires",  before["dedup_guard_fires"], after["dedup_guard_fires"], "%d")
    _row("step_cap hits",      before["step_cap_hits"],   after["step_cap_hits"],   "%d")
    _row("recorded errors",    before["total_recorded_errors"], after["total_recorded_errors"], "%d")
    print("    " + "-" * 62)
    print()

    qd = (after_q["max_turns"] or 0) - (before_q["max_turns"] or 0)
    qc = after_q["cost_usd"] - before_q["cost_usd"]
    if qd > 0 or qc > 0:
        print("  Qualitative (quick %s): Guard removed -> turns +%d, cost +$%.6f."
              % (FAIL_CASE_QUICK, qd, qc))
    else:
        print("  Qualitative: Guard removed -> see table above for full-set delta.")

    return {
        "failure": "D7 F1 loop-control (dedup guard removed)",
        "layer": "loop-control (guardrails.py check_duplicate)",
        "quick_case": FAIL_CASE_QUICK,
        "before": before,
        "after": after,
        "quick_before": before_q,
        "quick_after": after_q,
    }


# =====================================================================
# FAILURE 2  —  Tool descriptor v0 (broken) replaces v2
# =====================================================================
def _install_failure_2(active: bool):
    """
    D7 Failure 2 · tool-interface layer.

    Working version:
        book_slot returns the complete booking confirmation.

    Broken version:
        remove clinic/date/time from the return shape.
        The action still executes, but the observation no longer carries
        enough evidence to produce a correct booking record.
    """
    import tools

    if active:
        def broken_book_slot(clinic, date, time, referral_id):
            return {
                "booked": True,
                "clinic": "WRONG-" + clinic,
                "date": "1999-01-01",
                "time": "00:00",
                "referral_id": referral_id,
        }

        tools.REGISTRY["B"]["book_slot"] = broken_book_slot

    else:
        # Restore working interface
        tools.REGISTRY["B"]["book_slot"] = tools.book_slot

def run_failure_2(verbose=False):
    """Failure 2: tool-interface return-shape corruption."""
    import agent, prompt, prompt_sequential, tools

    key = load_key()
    all_cases = [c for c in load_cases() if c in SCRIPTS and c in key]

    def _run_one(label, interface_active, quick_case=None):

        # 先恢复干净 tools
        importlib.reload(tools)

        # interface_active=True  -> 正常
        # interface_active=False -> 删除 book_slot 返回字段
        _install_failure_2(not interface_active)

        importlib.reload(prompt)
        importlib.reload(prompt_sequential)
        importlib.reload(agent)

        cases = [quick_case] if quick_case else all_cases

        
        results, _ = run_set(
            cases,
            verbose=(verbose and quick_case),
            parallel_tools=True
        )

        # D7 F2: tool-interface failure must be checked at the tool-observation layer.
        # Scripted backend has a fixed final answer, so a corrupted book_slot return
        # would otherwise be hidden by the correct scripted final.
        for r in results:
            exp = key.get(r["case_id"]) or {}
            expected_booked = exp.get("booked")

            # Only booking cases have a book_slot observation to validate
            if not expected_booked:
                continue

            trace = r["record"].get("tool_trace", []) or []
            booking_rows = [
                row for row in trace
                if row.get("tool") == "book_slot"
            ]

            if not booking_rows:
                continue

            row = booking_rows[-1]

            # tolerate different trace field names
            actual = (
                row.get("result")
                or row.get("observation")
                or row.get("output")
                or row.get("data")
                or {}
            )

            # unwrap {"data": {...}} if necessary
            if isinstance(actual, dict) and isinstance(actual.get("data"), dict):
                actual = actual["data"]

            mismatch = (
                not isinstance(actual, dict)
                or actual.get("clinic") != expected_booked.get("clinic")
                or actual.get("date") != expected_booked.get("date")
                or actual.get("time") != expected_booked.get("time")
            )

            if mismatch:
                r["passed"] = False
                r.setdefault("fails", []).append(
                    "booked.tool_return_mismatch"
                )

        total = len(results)

        passed = sum(1 for r in results if r["passed"])

        turns = [r["record"]["turns"] for r in results]

        cost = sum(
            r["record"]["cost_usd"]
            for r in results
        )

        tin = sum(
            r["record"]["tokens_in"]
            for r in results
        )

        tout = sum(
            r["record"]["tokens_out"]
            for r in results
        )

        booked_wrong = sum(
            1 for r in results
            if not r["passed"]
            and any("booked." in f for f in r["fails"])
        )

        band_mismatch = sum(
            1 for r in results
            if not r["passed"]
            and any("decision" in f for f in r["fails"])
        )

        return {
            "label": label,
            "interface_intact": interface_active,
            "cases_run": len(cases),
            "trials": total,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "median_turns": statistics.median(turns) if turns else None,
            "max_turns": max(turns) if turns else None,
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd": round(cost, 6),
            "codecheck_fails_booked_field": booked_wrong,
            "codecheck_fails_decision": band_mismatch,
        }

    print()
    print("=" * 68)
    print("  D7 FAILURE 2 - tool-interface layer: corrupted booking output")
    print("=" * 68)

    before_q = _run_one(
        "BEFORE (interface intact)",
        True,
        quick_case=FAIL_CASE_F2
    )

    after_q = _run_one(
        "AFTER (interface broken)",
        False,
        quick_case=FAIL_CASE_F2
    )

    print()
    print("    Quick %s:" % FAIL_CASE_F2)

    print(
        "      BEFORE intact -> passes=%d/%d, turns=%d, cost=$%.6f"
        % (
            before_q["passed"],
            before_q["trials"],
            before_q["max_turns"] or 0,
            before_q["cost_usd"]
        )
    )

    print(
        "      AFTER broken  -> passes=%d/%d, turns=%d, cost=$%.6f"
        % (
            after_q["passed"],
            after_q["trials"],
            after_q["max_turns"] or 0,
            after_q["cost_usd"]
        )
    )

    before = _run_one(
        "BEFORE (interface intact)",
        True
    )

    after = _run_one(
        "AFTER (interface broken)",
        False
    )

    # 恢复正常 tools
    importlib.reload(tools)
    _install_failure_2(False)

    importlib.reload(prompt)
    importlib.reload(prompt_sequential)
    importlib.reload(agent)

    print()
    print("    " + "-" * 62)

    hdr = "%-22s  %12s  %12s  %12s" % (
        "metric",
        "BEFORE",
        "AFTER(broken)",
        "DELTA"
    )

    print("    " + hdr)
    print("    " + "-" * 62)

    def _row(name, b, a, fmt="%s", cost=False, percent=False):
        try:
            d = None if (b is None or a is None) else a - b
        except TypeError:
            d = None

        ds = "-"

        if d is not None:
            if cost:
                ds = "%+.4f $" % d
            elif percent:
                ds = "%+.2f pp" % (d * 100.0)
            else:
                ds = (
                    ("%+d" % d)
                    if isinstance(d, int)
                    else ("%+.2f" % d)
                )

        def F(v):
            return "-" if v is None else (fmt % v)

        print(
            "    %-22s  %12s  %12s  %12s"
            % (name, F(b), F(a), ds)
        )

    _row(
        "trials",
        before["trials"],
        after["trials"],
        "%d"
    )

    _row(
        "passed trials",
        before["passed"],
        after["passed"],
        "%d"
    )

    _row(
        "pass_rate",
        before["pass_rate"],
        after["pass_rate"],
        "%.2f",
        percent=True
    )

    _row(
        "median turns",
        before["median_turns"],
        after["median_turns"],
        "%.1f"
    )

    _row(
        "worst turns",
        before["max_turns"],
        after["max_turns"],
        "%d"
    )

    _row(
        "tokens_in",
        before["tokens_in"],
        after["tokens_in"],
        "%d"
    )

    _row(
        "tokens_out",
        before["tokens_out"],
        after["tokens_out"],
        "%d"
    )

    _row(
        "cost US$",
        before["cost_usd"],
        after["cost_usd"],
        "%.4f",
        cost=True
    )

    _row(
        "fails: booked.*",
        before["codecheck_fails_booked_field"],
        after["codecheck_fails_booked_field"],
        "%d"
    )

    _row(
        "fails: decision",
        before["codecheck_fails_decision"],
        after["codecheck_fails_decision"],
        "%d"
    )

    print("    " + "-" * 62)
    print()

    return {
        "failure": "D7 F2 tool-interface corrupted booking output",
        "layer": "tool interface (book_slot return shape)",
        "quick_case": FAIL_CASE_F2,
        "before": before,
        "after": after,
        "quick_before": before_q,
        "quick_after": after_q,
    }


# =====================================================================
def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8')
    print()
    print(config.summary())
    print("data:", config.data_root())

    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}
    verbose = "--verbose" in flags
    want = set(args) or {"1", "2"}

    out = {"config": config.summary(),
           "backend": "scripted (always for D7)",
           "failures": {}}

    # make sure baseline environment is clean before starting
    _install_failure_1(False)
    _install_failure_2(False)

    if "1" in want:
        out["failures"]["F1"] = run_failure_1(verbose=verbose)
    if "2" in want:
        out["failures"]["F2"] = run_failure_2(verbose=verbose)

    path = os.path.join(OUT_DIR, "failure_results.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    print()
    print("  D7 failure reproductions complete. wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
