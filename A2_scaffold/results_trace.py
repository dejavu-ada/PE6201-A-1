"""
PE6201 · A2 — UNIFIED TRACE / RESULTS OUTPUT  (D4, D5, D6, D7)
====================================================================
Every run produces a STANDARD row of columns per trial so every table
in the report is generated from the same JSON/CSV file — no hand-copying.

Standard row schema (exactly what the report tables need):
    case_id
    backend             scripted | live
    model               "" for scripted, e.g. "openai/gpt-4o-mini" for live
    prompt_version      descriptor version: v1 | v2
    execution_mode      sequential | parallel
    decision            book | escalate | request_information | request_document | approve_in_principle
    trigger             "" unless decision==escalate
    missing             "" unless decision is request_*
    booked_clinic       "" unless decision==book
    booked_date         "" unless decision==book
    booked_time         "" unless decision==book
    passed              True | False (code check)
    turns               int
    tool_calls          int  (len of tool_trace)
    tokens_in           int
    tokens_out          int
    cost_usd            float
    cap_fired           step_cap | budget_ceiling | duplicate_action | gate_held | ""
    evidence            list[str]   (just the tool names, same order)
    gate                gate_passed | gate_held | ""   (autonomy gate status)
    family              from expected_outcomes, for report group-bys
    trial_number        1..N (negatives get 3)
    guardrails_fired    list of guardrail names (compact)
    fails               list of code-check failure reasons, if any

Usage:
    from results_trace import standardize_record, standardize_results, write_standard_csv

    flat_row = standardize_record(result_dict, expected_dict, trial_number)
    all_rows = standardize_results(results_list, key_dict)
    write_standard_csv(all_rows, "outputs/unified_results.csv")
====================================================================
"""
import csv
import json
import os

import config


STANDARD_COLUMNS = [
    "case_id",
    "backend",
    "model",
    "prompt_version",
    "execution_mode",
    "decision",
    "trigger",
    "missing",
    "booked_clinic",
    "booked_date",
    "booked_time",
    "passed",
    "turns",
    "tool_calls",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "cap_fired",
    "evidence",
    "gate",
    "family",
    "trial_number",
    "guardrails_fired",
    "fails",
]


def _booked_fields(rec):
    b = rec.get("booked") or {}
    if not isinstance(b, dict):
        return "", "", ""
    return (b.get("clinic", "") or "",
            b.get("date", "") or "",
            b.get("time", "") or "")


def _cap_fired(rec):
    sb = rec.get("stopped_by")
    if sb and sb in ("step_cap", "budget_ceiling", "duplicate_action",
                     "gate_held", "broken_case", "invalid_model_move",
                     "json_parse_error"):
        return sb
    for g in rec.get("guardrails_fired", []) or []:
        name = g.get("guardrail", "") if isinstance(g, dict) else str(g)
        if name in ("step_cap", "budget_ceiling", "duplicate_action"):
            return name
    return ""


def _gate_status(rec):
    for g in rec.get("guardrails_fired", []) or []:
        name = g.get("guardrail", "") if isinstance(g, dict) else str(g)
        if name == "gate_passed":
            return "gate_passed"
        if name == "gate_held":
            return "gate_held"
    return ""


def _guard_names(rec):
    out = []
    for g in rec.get("guardrails_fired", []) or []:
        if isinstance(g, dict):
            out.append(g.get("guardrail", str(g)))
        else:
            out.append(str(g))
    return out


def standardize_record(result_row, expected=None, trial_number=None):
    """Convert one harness `result` dict (with nested `record`) into the
    standard flat row."""
    rec = result_row.get("record") or {}
    expected = expected or {}
    bc, bd, bt = _booked_fields(rec)

    execution_mode = rec.get("execution_mode",
                             "parallel" if rec.get("parallel_tools", True)
                             else "sequential")
    backend = rec.get("backend", config.BACKEND)
    model = "" if backend == "scripted" else config.MODEL

    return {
        "case_id": rec.get("case_id", result_row.get("case_id", "")),
        "backend": backend,
        "model": model,
        "prompt_version": rec.get("descriptor_version",
                                  config.DESCRIPTOR_VERSION),
        "execution_mode": execution_mode,
        "decision": rec.get("decision", ""),
        "trigger": rec.get("trigger", ""),
        "missing": rec.get("missing", ""),
        "booked_clinic": bc,
        "booked_date": bd,
        "booked_time": bt,
        "passed": bool(result_row.get("passed", False)),
        "turns": int(rec.get("turns", 0) or 0),
        "tool_calls": len(rec.get("tool_trace", []) or []),
        "tokens_in": int(rec.get("tokens_in", 0) or 0),
        "tokens_out": int(rec.get("tokens_out", 0) or 0),
        "cost_usd": float(rec.get("cost_usd", 0.0) or 0.0),
        "cap_fired": _cap_fired(rec),
        "evidence": list(rec.get("evidence", []) or []),
        "gate": _gate_status(rec),
        "family": expected.get("family", result_row.get("family", "")),
        "trial_number": trial_number if trial_number is not None
                        else result_row.get("trial", 1),
        "guardrails_fired": _guard_names(rec),
        "fails": list(result_row.get("fails", []) or []),
    }


def standardize_results(results, key=None):
    """Convert a list of harness results into a list of standard rows.
    `key` = {case_id: expected_outcomes row} (from harness.load_key)."""
    key = key or {}
    rows = []
    for r in results:
        expected = key.get(r.get("case_id", ""), {})
        rows.append(standardize_record(r, expected))
    return rows


def summarize(rows, label=""):
    """Aggregate a list of standard rows into a summary dict (useful for
    cost model input and final reports)."""
    if not rows:
        return {"label": label, "trials": 0, "passed": 0,
                "pass_rate": None, "median_turns": None,
                "tokens_in_per_case": 0, "tokens_out_per_case": 0}
    trials = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    turns = sorted(r["turns"] for r in rows)
    med_turns = turns[len(turns) // 2] if len(turns) % 2 else 0.5 * (
        turns[len(turns) // 2 - 1] + turns[len(turns) // 2])
    total_in = sum(r["tokens_in"] for r in rows)
    total_out = sum(r["tokens_out"] for r in rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    return {
        "label": label,
        "trials": trials,
        "passed": passed,
        "pass_rate": passed / trials if trials else None,
        "median_turns": med_turns,
        "cost_usd": total_cost,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "tokens_in_per_case": total_in / trials if trials else 0,
        "tokens_out_per_case": total_out / trials if trials else 0,
    }


def write_standard_csv(rows, path):
    """Write the unified flat rows to a CSV (arrays become |-joined strings
    so a spreadsheet can read them directly)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=STANDARD_COLUMNS)
        w.writeheader()
        for r in rows:
            row_out = dict(r)
            for k in ("evidence", "guardrails_fired", "fails"):
                v = row_out.get(k, [])
                if isinstance(v, list):
                    row_out[k] = " | ".join(str(x) for x in v)
                else:
                    row_out[k] = str(v)
            w.writerow({k: (row_out.get(k, "") if k in STANDARD_COLUMNS
                            else "") for k in STANDARD_COLUMNS})


def write_standard_json(rows, path, extra_meta=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "config_summary": config.summary(),
        "columns": STANDARD_COLUMNS,
        "summary": summarize(rows),
        "rows": rows,
    }
    if extra_meta:
        payload.update(extra_meta)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
