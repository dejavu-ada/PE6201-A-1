#!/usr/bin/env python3
"""Reproduce and recover two deterministic D7 failures.

Both failures are deletions from the working single agent and always use the
scripted backend. Results are saved into the shared results.json.
"""
import copy
import os

import backends
import config
import tools
from agent import run_case
from guardrails import Guardrails
from harness import code_check, load_key
from run_eval import RESULTS_DIR, _write_json


CASE_ID = "REF-5602"


def _metrics(record, expected):
    passed, failures = code_check(record, expected)
    return {
        "turns": record.get("turns"),
        "tool_calls": len(record.get("tool_trace", [])),
        "tools_in_order": [
            row.get("tool") for row in record.get("tool_trace", [])],
        "tokens_in": record.get("tokens_in"),
        "tokens_out": record.get("tokens_out"),
        "cost_usd": record.get("cost_usd"),
        "decision": record.get("decision"),
        "stopped_by": record.get("stopped_by"),
        "code_check_pass": passed,
        "code_check_failures": failures,
    }


def _same_trajectory(left, right):
    return (
        left.get("decision") == right.get("decision")
        and left.get("turns") == right.get("turns")
        and left.get("evidence") == right.get("evidence")
    )


def _looping_script(case_id):
    steps = copy.deepcopy(backends.SCRIPTS[case_id])
    repeat = copy.deepcopy(steps[1])
    repeat["thought"] = "Repeat completed checks instead of progressing."
    return steps[:2] + [repeat, copy.deepcopy(repeat)] + steps[2:]


def reproduce_dedup_failure(expected):
    """Delete loop-layer action de-duplication, then restore it."""
    original_script = backends.SCRIPTS[CASE_ID]
    before = run_case(CASE_ID, problem="B")
    real_check = Guardrails.check_duplicate
    try:
        backends.SCRIPTS[CASE_ID] = _looping_script(CASE_ID)
        Guardrails.check_duplicate = lambda self, tool, args: None
        broken = run_case(CASE_ID, problem="B")
    finally:
        Guardrails.check_duplicate = real_check
        backends.SCRIPTS[CASE_ID] = original_script
    recovered = run_case(CASE_ID, problem="B")
    return {
        "failure": "action de-duplication deleted",
        "layer": "code / loop control",
        "case_id": CASE_ID,
        "expected_observation": (
            "redundant calls increase turns, tokens and cost; pass rate may hide it"),
        "before": _metrics(before, expected),
        "broken": _metrics(broken, expected),
        "recovered": _metrics(recovered, expected),
        "recovery_pass": _same_trajectory(before, recovered),
        "diagnosis": (
            "Prompt advice cannot guarantee memory of completed actions; "
            "deterministic code-layer de-duplication is the correct fix."),
    }


def reproduce_missing_tool_failure(expected):
    """Delete a required tool-interface capability, then restore it."""
    before = run_case(CASE_ID, problem="B")
    real_tool = tools.REGISTRY["B"].pop("get_clinic_slots")
    broken = None
    broken_error = None
    try:
        try:
            broken = run_case(CASE_ID, problem="B")
        except Exception as exc:  # the reproduced failure is the evidence
            broken_error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
    finally:
        tools.REGISTRY["B"]["get_clinic_slots"] = real_tool
    recovered = run_case(CASE_ID, problem="B")
    return {
        "failure": "get_clinic_slots deleted from tool registry",
        "layer": "tool interface / capability availability",
        "case_id": CASE_ID,
        "expected_observation": (
            "the booking trajectory cannot continue because the required "
            "capability is out of reach"),
        "before": _metrics(before, expected),
        "broken": (
            _metrics(broken, expected) if broken is not None
            else {"unhandled_tool_error": broken_error}),
        "recovered": _metrics(recovered, expected),
        "recovery_pass": _same_trajectory(before, recovered),
        "diagnosis": (
            "A prompt or guardrail cannot execute a missing capability; "
            "restoring the tool interface is the correct fix."),
    }


def _print_failure(label, result):
    print("\n" + "=" * 68)
    print(label, "-", result["failure"])
    print("=" * 68)
    for stage in ("before", "broken", "recovered"):
        row = result[stage]
        if "unhandled_tool_error" in row:
            err = row["unhandled_tool_error"]
            print("  %-9s ERROR %s: %s" % (
                stage.upper(), err["type"], err["message"]))
        else:
            print(
                "  %-9s turns=%s tools=%s tokens=%s cost=$%.6f pass=%s"
                % (stage.upper(), row["turns"], row["tool_calls"],
                   (row["tokens_in"] or 0) + (row["tokens_out"] or 0),
                   row["cost_usd"] or 0, row["code_check_pass"]))
    print("  recovery:", "PASS" if result["recovery_pass"] else "FAIL")


def main():
    original_backend = config.BACKEND
    original_mode = config.CALL_MODE
    try:
        config.BACKEND = "scripted"
        config.CALL_MODE = "parallel"
        expected = load_key("B")[CASE_ID]
        failures = {
            "F1": reproduce_dedup_failure(expected),
            "F2": reproduce_missing_tool_failure(expected),
        }
    finally:
        config.BACKEND = original_backend
        config.CALL_MODE = original_mode

    _print_failure("D7 FAILURE 1", failures["F1"])
    _print_failure("D7 FAILURE 2", failures["F2"])

    output = {
        "backend": "scripted",
        "problem": "B",
        "call_mode": "parallel",
        "method": "working agent -> delete one component -> restore it",
        "all_recoveries_passed": all(
            item["recovery_pass"] for item in failures.values()),
        "failures": failures,
    }
    path = os.path.join(RESULTS_DIR, "d7_failure_results.json")
    _write_json(path, output)
    print("\nWrote results/d7_failure_results.json")
    return 0 if output["all_recoveries_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
