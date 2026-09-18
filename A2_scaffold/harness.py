"""
PE6201 · A2 scaffold — THE HARNESS  (D4, D5)
====================================================================
Load the answer key, run cases, grade them, report.

--------------------------------------------------------------------
THE TWO KINDS OF CHECK, AND WHY YOU NEED BOTH

A CODE CHECK compares the answer with your answer key.
    decision == expected_decision
    No model, no person, no opinion. Deterministic, free, instant.
    It is what produces the number.

A JUDGEMENT CHECK has someone read the record and decide.
    "Does the reason actually name the band and the window?"
    A PERSON can do it. A SECOND MODEL can do it. Same kind of check -
    the only difference is who grades. (This is what A1 called L1/L2.
    The names never mattered; the difference does.)

Why both: with three possible outcomes, a coin-flip scores 33% on the
code check alone. An agent can reach the right decision for the wrong
reason and the code check will not notice. `must_record` and `trigger`
are what stop a lucky run counting as a good one.

`prepare_judgement_check` below does NOT grade. It builds the queue a
human or a second model works through. Automating the judgement is
your design decision - and if you use a model, say so, because a model
grading a model is a claim that needs defending.
====================================================================
"""
import json
import os
import statistics

import config
from agent import run_case


# =====================================================================
# LOADING
# =====================================================================
def load_key(problem=None):
    """The answer key. YOURS, not ours, once you have extended it.

    Starts as 15 rows and grows by one per case you write. Same file
    throughout - the harness joins on case_id and does not care which
    rows we shipped and which you added.
    """
    problem = problem or config.PROBLEM
    path = os.path.join(config.data_root(),
                        "expected_outcomes_%s.json" % problem)
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    return {r["case_id"]: r for r in rows}


def load_cases(problem=None):
    """Every case id in the work queue, in file order."""
    problem = problem or config.PROBLEM
    table, field = (("referrals", "referral_id") if problem == "B"
                    else ("claims", "claim_id"))
    path = os.path.join(config.data_root(), "data_%s" % problem,
                        "%s.json" % table)
    with open(path, encoding="utf-8") as fh:
        return [r[field] for r in json.load(fh)]


# =====================================================================
# THE CODE CHECK
# =====================================================================
def code_check(record, expected):
    """Deterministic comparison. Returns (passed, [reasons it failed]).

    Note what is compared and what is NOT. The DECISION and its single
    TRIGGER are compared. The wording is not, the turn count is not, the
    cost is not - two agents can both be right and cost very different
    amounts, which is the subject of D6.
    """
    fails = []

    if record.get("decision") != expected.get("expected_decision"):
        fails.append("decision %r, expected %r"
                     % (record.get("decision"), expected.get("expected_decision")))

    # An escalation must escalate FOR THE RIGHT REASON. A run that
    # reaches the right outcome by the wrong trigger is not a pass - it
    # got there by luck and it will not get there next time.
    if expected.get("trigger"):
        if record.get("trigger") != expected["trigger"]:
            fails.append("trigger %r, expected %r"
                         % (record.get("trigger"), expected["trigger"]))

    # A booking must book the RIGHT slot. Problem B only.
    if expected.get("booked"):
        got = record.get("booked") or {}
        for field in ("clinic", "date", "time"):
            if got.get(field) != expected["booked"][field]:
                fails.append("booked.%s %r, expected %r"
                             % (field, got.get(field), expected["booked"][field]))
    # Request-information cases must name the EXACT missing test.
    if expected.get("missing"):
        if record.get("missing") != expected["missing"]:
            fails.append(
                "missing %r, expected %r"
                % (record.get("missing"), expected["missing"])
            )

    # Check the irreversible gated action in the tool trace.
    tools_called = [
        item.get("tool")
        for item in record.get("tool_trace", [])
    ]

    # Every valid Problem B decision must be grounded in the referral row.
    # The FAQ explicitly lists "a required tool appears in the trace" as a
    # code check. Custom labels may provide a stricter required_tools list;
    # otherwise get_referral is the minimum common evidence requirement.
    required_tools = expected.get("required_tools", ["get_referral"])
    for required_tool in required_tools:
        if required_tool not in tools_called:
            fails.append("required tool %s missing from trace" % required_tool)

    book_count = tools_called.count("book_slot")

    if expected.get("expected_decision") == "book":
        if book_count != 1:
            fails.append(
                "book_slot called %d times, expected exactly 1"
                % book_count
            )
    else:
        if book_count != 0:
            fails.append(
                "book_slot called %d times, expected 0"
                % book_count
            )

    return (not fails), fails


# =====================================================================
# THE JUDGEMENT CHECK
# =====================================================================
def prepare_judgement_check(record, expected):
    """Build ONE item for a human - or a second model - to rule on.

    This deliberately does not decide anything. `must_record` items are
    written in English and a substring match would be theatre, not a
    check. Someone reads the reason and answers yes or no per item.
    """
    return {
        "case_id": record["case_id"],
        "decision": record.get("decision"),
        "reason": record.get("reason", ""),
        "must_record": expected.get("must_record", []),
        "verdict": None,          # <- a person or a second model fills this
        "review_method": None,     # filled as "human" by run_eval --judge
    }


# =====================================================================
# RUNNING THE SET
# =====================================================================
def run_set(case_ids=None, problem=None, trials_for=None, verbose=False):
    """Run cases and grade them.

    `trials_for(case_id) -> int` decides how many trials each case gets.
    D4: ordinary cases get ONE trial; NEGATIVE cases get THREE, because
    negatives are the ones that flip between runs and a single trial
    cannot tell a real refusal from a lucky one.
    """
    problem = problem or config.PROBLEM
    key = load_key(problem)
    case_ids = case_ids or load_cases(problem)
    trials_for = trials_for or (lambda cid: 3 if _is_negative(key.get(cid)) else 1)

    results, judgement_queue = [], []

    for cid in case_ids:
        expected = key.get(cid)
        if expected is None:
            # check_my_data.py catches this before you get here. If you
            # are seeing it, run the checker.
            print("  SKIP %s - no label in the answer key" % cid)
            continue

        for trial in range(1, trials_for(cid) + 1):
            # The evaluation harness explicitly simulates recorded human
            # approval so booking cases can be scored deterministically.
            # Outside this harness, a live agent without approval remains
            # blocked by the confirm gate immediately before book_slot.
            record = run_case(
                cid,
                problem=problem,
                approve=lambda action, payload: True,
                verbose=verbose,
            )
            passed, fails = code_check(record, expected)
            results.append({"case_id": cid, "trial": trial, "passed": passed,
                            "fails": fails, "record": record,
                            "family": expected.get("family")})
            if trial == 1 and cid in config.JUDGEMENT_CASES:
                judgement_queue.append(prepare_judgement_check(record, expected))

    return results, judgement_queue


def _is_negative(expected):
    """A negative case is one whose correct outcome is anything except
    the act - so, an ask or an escalate."""
    if not expected:
        return False
    return expected.get("expected_decision") in (
        "escalate", "request_document", "request_information")


# =====================================================================
# REPORTING
# =====================================================================
def report(results):
    """The result table. EVERY pass rate is printed with its trial count,
    because a pass rate without one is not a measurement."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    turns = [r["record"]["turns"] for r in results]
    cost = sum(r["record"]["cost_usd"] for r in results)
    key = load_key()
    negative_results = [
        r for r in results if _is_negative(key.get(r["case_id"]))
    ]
    ordinary_results = [
        r for r in results if not _is_negative(key.get(r["case_id"]))
    ]
    negative_passed = sum(1 for r in negative_results if r["passed"])
    ordinary_passed = sum(1 for r in ordinary_results if r["passed"])

    print()
    print("=" * 68)
    print("  RESULTS   %d of %d trials passed   (%.0f%%)"
          % (passed, total, 100.0 * passed / total if total else 0))
    print("=" * 68)
    print("  trials              %d" % total)
    print("  cases               %d" % len({r["case_id"] for r in results}))
    print("  negative trials     %d/%d passed" %
          (negative_passed, len(negative_results)))
    print("  median turns        %s" % (statistics.median(turns) if turns else "-"))
    print("  worst case turns    %s" % (max(turns) if turns else "-"))
    print("  hit the step cap    %d"
          % sum(1 for r in results if r["record"]["stopped_by"] == "step_cap"))
    print("  total cost          US$%.4f   (%s backend)"
          % (cost, results[0]["record"]["backend"] if results else "-"))
    print()

    failures = [r for r in results if not r["passed"]]
    if failures:
        print("  FAILED TRIALS - each one is either a bug or a wrong label:")
        for r in failures:
            print("    %-12s trial %d  [%s]" % (r["case_id"], r["trial"],
                                                r["family"]))
            for f in r["fails"]:
                print("        %s" % f)
        print()
        print("  Before you fix the agent, ask whether the LABEL is right.")
        print("  Test: could you justify the label to someone who had never")
        print("  seen your agent's output, using only Appendix A's routing")
        print("  table? If yes, the agent is wrong. If no, the label is.")
    else:
        print("  Every trial passed the code check.")
        print("  That is HALF the check. Work through the judgement queue")
        print("  before you believe this number.")
    print()

    # ============================================================
    # D6 · ECONOMICS
    # ============================================================

    pass_rate = passed / total if total else 0.0

    # Layer 1: measured live API token cost per referral. On the scripted
    # backend this remains an explicitly labelled estimate in each record.
    token_cost_per_case = cost / total if total else 0.0

    # Human cost when the agent fails
    failure_cost = round((
        config.HUMAN_HOURLY_RATE
        * config.MINUTES_PER_ESCALATION
        / 60
    ), 2)

    # Layer 2: expected variable cost of one referral.
    expected_variable_cost_per_case = (
        token_cost_per_case
        + (1 - pass_rate) * failure_cost
    )

    # Layer 3: defensible fixed monthly operating assumption.
    variable_monthly_cost = (
        expected_variable_cost_per_case * config.MONTHLY_VOLUME)
    total_monthly_cost = config.FIXED_MONTHLY_COST + variable_monthly_cost
    average_full_cost_per_case = (
        total_monthly_cost / config.MONTHLY_VOLUME
        if config.MONTHLY_VOLUME else None)

    # Sensitivity: vary measured pass rate +/-10 percentage points. Keep the
    # table in JSON so the report can cite it without hand arithmetic.
    sensitivity = []
    for delta_pp in range(-config.SENSITIVITY_RANGE_PP,
                          config.SENSITIVITY_RANGE_PP + 1,
                          config.SENSITIVITY_STEP_PP):
        p = max(0.0, min(1.0, pass_rate + delta_pp / 100.0))
        variable = token_cost_per_case + (1 - p) * failure_cost
        monthly = config.FIXED_MONTHLY_COST + config.MONTHLY_VOLUME * variable
        sensitivity.append({
            "delta_percentage_points": delta_pp,
            "pass_rate": p,
            "expected_variable_cost_per_case": variable,
            "total_monthly_cost": monthly,
            "average_full_cost_per_case": (
                monthly / config.MONTHLY_VOLUME
                if config.MONTHLY_VOLUME else None),
        })

    # Human-only handling costs failure_cost per referral. This is the pass
    # rate at which the agent's all-in monthly cost equals that baseline.
    break_even_pass_rate_vs_human = None
    if failure_cost > 0 and config.MONTHLY_VOLUME:
        break_even_pass_rate_vs_human = (
            token_cost_per_case
            + config.FIXED_MONTHLY_COST / config.MONTHLY_VOLUME
        ) / failure_cost

    # Also solve the monthly volume at which fixed cost is recovered at the
    # measured pass rate. None means no finite break-even at that quality.
    saving_per_case_vs_human = (
        failure_cost - expected_variable_cost_per_case)
    break_even_monthly_volume = (
        config.FIXED_MONTHLY_COST / saving_per_case_vs_human
        if saving_per_case_vs_human > 0 else None)

    # Per-step reliability diagnostic
    median_turns = statistics.median(turns) if turns else None

    step_reliability = (
        pass_rate ** (1 / median_turns)
        if median_turns and pass_rate > 0
        else None
    )
    return {
        "cases": len({r["case_id"] for r in results}),
        "trials": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "ordinary_cases": len({r["case_id"] for r in ordinary_results}),
        "ordinary_trials": len(ordinary_results),
        "ordinary_passed": ordinary_passed,
        "ordinary_pass_rate": (
            ordinary_passed / len(ordinary_results)
            if ordinary_results else None),
        "negative_cases": len({r["case_id"] for r in negative_results}),
        "negative_trials": len(negative_results),
        "negative_passed": negative_passed,
        "negative_pass_rate": (
            negative_passed / len(negative_results)
            if negative_results else None),
        "median_turns": median_turns,
        "worst_case_turns": max(turns) if turns else None,
        "cost_usd": cost,
        "economics": {
            "formula": "token_cost + (1-pass_rate)*failure_cost",
            "token_cost_per_case": token_cost_per_case,
            "failure_cost_usd": failure_cost,
            "expected_failure_cost_per_case": (
                (1 - pass_rate) * failure_cost),
            "expected_variable_cost_per_case": (
                expected_variable_cost_per_case),
            "monthly_volume": config.MONTHLY_VOLUME,
            "variable_monthly_cost": variable_monthly_cost,
            "fixed_monthly_cost": config.FIXED_MONTHLY_COST,
            "total_monthly_cost": total_monthly_cost,
            "average_full_cost_per_case": average_full_cost_per_case,
            "break_even_pass_rate_vs_human": (
                break_even_pass_rate_vs_human),
            "break_even_monthly_volume": break_even_monthly_volume,
            "sensitivity": sensitivity,
        },
        "step_reliability": step_reliability,
    }
