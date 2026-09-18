# -*- coding: utf-8 -*-
"""
====================================================================
 PE6201 A2 — COLAB/INTERACTIVE MASTER  (a2_master.py)
====================================================================
 这是一块一块运行的「总主控文件」，不用再记住 run_eval.py /
 run_d2c_compare.py / run_live.py 等一堆文件名。Colab 里每格
 （cell）就是下面的一个 SECTION，改最上面的 CONFIG 然后按
 SECTION 0 → 1 → 2 … 逐格跑就行。

 Windows 本地命令行运行：
     python a2_master.py                 走默认 section1（scripted 全套）
     python a2_master.py section2        只跑串行 vs 并行
     python a2_master.py section7        只跑 LIVE（先改 CONFIG 里的 KEY）
     python a2_master.py all             1..6 全跑（scripted 不花钱）

 Colab 使用步骤：
     1. 上传整个 A2_scaffold/ + A2_reference_data/ 到 Colab Drive
     2. 把此文件里的每个 SECTION 分别粘到一个代码格
     3. 在 CONFIG SECTION 填入 API KEY（跑 LIVE 才需要），然后逐格运行

 每个 SECTION 都有独立的 `run_section_N(...)` 函数 —— 在 Colab
 里也可以直接调函数，省得粘大段代码。
====================================================================
"""
from __future__ import annotations

import argparse
import csv
import datetime
import importlib
import json
import os
import statistics
import subprocess
import sys
import textwrap
from typing import Any, Iterable

# ----------------------------------------------------------------
# 0. CONFIG SECTION  ——  所有你需要改的参数都在这里
#     Colab 用户：只改这一格，下面的 SECTION 都不用改
# ----------------------------------------------------------------
# (live 跑的时候再填，scripted 不需要)
class CFG:
    # ========= LIVE 才需要，scripted 留空就行 =========
    OPENROUTER_API_KEY: str = ""   # 例 "sk-or-xxx…"
    MODEL:           str = ""      # 例 "openai/gpt-4o-mini" / "anthropic/claude-sonnet-4" / "google/gemini-2.5-pro"
    # ========= 始终生效 =========
    BACKEND:         str = "scripted"       # scripted (free, default) | live (costs $$)
    DESCRIPTOR:      str = "v2"             # v1 | v2   (D2b 实验)
    PARALLEL_TOOLS:  bool = True            # True=并行 | False=串行
    TRIALS_REPEAT:   int | None = None      # None→ordinary×1 negative×3；给数字就每 case 跑 N 次
    MONTHLY_VOLUME:  int = 4000             # Cost model 里的默认月单量
    FAILURE_COST_B:  float = 9.17           # Problem B 每次 bad booking = $9.17
    FIXED_COST_MONTH: float = 2920.0        # 每月固定运维成本假设
    # ========= D7 failure 快捷开关 =========
    F1_DEDUP_DISABLE: bool = False          # True = 跑 Failure 1（loop-control）
    F2_DESCRIPTOR_BROKEN: bool = False      # True = 跑 Failure 2（prompt/descriptor）


HERE = os.path.dirname(os.path.abspath(__file__))
A2_ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(A2_ROOT, "A2_reference_data")
OUT_DIR = os.path.join(HERE, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)


def _apply_cfg_env(cfg: type[CFG]) -> None:
    """把 CFG 里的值写回环境变量 + importlib.reload config.py，
    让所有子模块立刻用新配置。"""
    if cfg.BACKEND: os.environ["A2_BACKEND"] = cfg.BACKEND
    if cfg.MODEL:   os.environ["A2_MODEL"]   = cfg.MODEL
    if cfg.OPENROUTER_API_KEY:
        os.environ["OPENROUTER_API_KEY"] = cfg.OPENROUTER_API_KEY
    os.environ["DESCRIPTOR_VERSION"] = cfg.DESCRIPTOR
    os.environ["PARALLEL_TOOLS"] = "true" if cfg.PARALLEL_TOOLS else "false"
    sys.path.insert(0, HERE)
    sys.path.insert(0, DATA_DIR)
    import config as _cfg_mod
    importlib.reload(_cfg_mod)


_apply_cfg_env(CFG)

import config
from harness import (load_cases, load_key, code_check, report, run_set,
                     _is_negative, prepare_judgement_check)
from backends import SCRIPTS
import guardrails as G
import results_trace as RT


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _print_hdr(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}\n")


# ================================================================
# SECTION 0 — 数据检查 (check_my_data.py 等价)
#          Colab:  %run -i a2_master.py section0
# ================================================================
def run_section_0(cfg: type[CFG] = CFG, verbose: bool = True) -> dict[str, Any]:
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 0 · Data consistency check (Problem B)")
    check_path = os.path.join(DATA_DIR, "check_my_data.py")
    result: dict[str, Any] = {"path": check_path}
    try:
        proc = subprocess.run(
            [sys.executable, check_path],
            cwd=DATA_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if verbose:
            sys.stdout.write(proc.stdout)
            if proc.stderr: sys.stdout.write(proc.stderr)
        result["returncode"] = proc.returncode
        result["ok"] = (proc.returncode == 0)
    except Exception as e:
        result["ok"] = False
        result["exception"] = repr(e)
    # 额外打印 fixture 统计
    key = load_key()
    exp_count = len(key)
    neg_count = sum(1 for v in key.values() if _is_negative(v))
    ord_count = exp_count - neg_count
    scripted_count = len(SCRIPTS)
    missing_scripted = [c for c in key if c not in SCRIPTS]
    total_trials = sum(3 if _is_negative(key[c]) else 1 for c in SCRIPTS if c in key)
    result.update({
        "expected_cases": exp_count,
        "ordinary": ord_count,
        "negative": neg_count,
        "scripted_cases": scripted_count,
        "missing_scripted": len(missing_scripted),
        "planned_trials": total_trials,
    })
    if verbose:
        print()
        print("  [expected_outcomes_B.json]  cases:", exp_count)
        print("    ordinary (book ×1)    :", ord_count)
        print("    negative (not-book ×3):", neg_count)
        print("  [backends.py scripted]        :", scripted_count)
        print("  没有 scripted 的 expected     :", len(missing_scripted), missing_scripted or "(无)")
        print("  计划总 trials 数              :", total_trials)
    return result


# ================================================================
# SECTION 1 — Scripted 全套 (eval并行 + guardrails + D2c + D7 failures + cost model)
# ================================================================
def run_section_1(cfg: type[CFG] = CFG) -> dict[str, Any]:
    _print_hdr("SECTION 1 · SCRIPTED SUITE (不花钱，默认就是跑这个)")
    t0 = _timestamp()
    r0 = run_section_0(cfg, verbose=False)
    r3 = run_section_3(cfg, verbose=False)
    r2 = run_section_2(cfg, verbose=False)
    r5 = run_section_5(cfg, verbose=False)
    r6 = run_section_6(cfg, verbose=False)
    return {
        "started_at": t0,
        "finished_at": _timestamp(),
        "section0_data_check": r0,
        "section2_seq_par":    r2,
        "section3_guardrails": r3,
        "section5_failures":   r5,
        "section6_cost_model": r6,
    }

# ================================================================
# SECTION 2 — 串行 vs 并行 控制实验 (D2c)
# ================================================================
def run_section_2(cfg: type[CFG] = CFG, verbose: bool = True) -> dict[str, Any]:
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 2 · Sequential vs Parallel (D2c control experiment)")

    key = load_key()
    cases = [c for c in load_cases() if c in SCRIPTS and c in key]

    def _run(parallel: bool, label: str):
        results, queue = run_set(
            cases,
            parallel_tools=parallel,
            verbose=False,
        )
        summ = report(results)
        std = RT.standardize_results(results, key)
        return {
            "label": label,
            "summary": summ,
            "results": results,
            "judgement_queue": queue,
            "trace_rows": std,
        }

    seq_res = _run(False, "sequential")
    par_res = _run(True, "parallel")

    # Write per-mode traces.
    for mode, obj in (("sequential", seq_res), ("parallel", par_res)):
        RT.write_standard_json(
            obj["trace_rows"],
            os.path.join(OUT_DIR, f"master_d2c_{mode}_trace.json"),
            extra_meta={
                "experiment": "master_d2c",
                "execution_mode": mode,
            },
        )
        RT.write_standard_csv(
            obj["trace_rows"],
            os.path.join(OUT_DIR, f"master_d2c_{mode}_trace.csv"),
        )

    # Combined trace.
    combined = []
    for mode, obj in (("sequential", seq_res), ("parallel", par_res)):
        for row in obj["trace_rows"]:
            rr = dict(row)
            rr["execution_mode"] = mode
            combined.append(rr)

    combined_path = os.path.join(OUT_DIR, "master_d2c_combined_trace.csv")
    combined_cols = ["execution_mode"] + list(RT.STANDARD_COLUMNS)

    with open(combined_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=combined_cols,
            extrasaction="ignore",
        )
        writer.writeheader()

        for row in combined:
            out = dict(row)
            for field in ("evidence", "guardrails_fired", "fails"):
                value = out.get(field, [])
                if isinstance(value, list):
                    out[field] = " | ".join(str(x) for x in value)
            writer.writerow({col: out.get(col, "") for col in combined_cols})

    # harness.report() returns only:
    # trials, passed, pass_rate, median_turns, cost_usd.
    # Derive the extra metrics needed by this master wrapper here.
    def _token_from_record(record: dict[str, Any], kind: str):
        aliases = {
            "tokens_in": ("tokens_in", "input_tokens", "prompt_tokens"),
            "tokens_out": ("tokens_out", "output_tokens", "completion_tokens"),
        }

        for name in aliases[kind]:
            value = record.get(name)
            if value is not None:
                return value

        usage = record.get("usage")
        if isinstance(usage, dict):
            for name in aliases[kind]:
                value = usage.get(name)
                if value is not None:
                    return value

        return None

    def _add_extra_metrics(summary: dict[str, Any], obj: dict[str, Any]):
        summary = dict(summary)
        results = obj["results"]

        turns = [
            r["record"].get("turns")
            for r in results
            if r.get("record", {}).get("turns") is not None
        ]
        summary["worst_turns"] = max(turns) if turns else None

        summary["step_cap_hits"] = sum(
            1
            for r in results
            if r.get("record", {}).get("stopped_by") == "step_cap"
        )

        tokens_in_values = []
        tokens_out_values = []

        for result in results:
            record = result.get("record", {})
            tin = _token_from_record(record, "tokens_in")
            tout = _token_from_record(record, "tokens_out")

            if tin is not None:
                tokens_in_values.append(tin)
            if tout is not None:
                tokens_out_values.append(tout)

        summary["tokens_in"] = (
            sum(tokens_in_values) if tokens_in_values else None
        )
        summary["tokens_out"] = (
            sum(tokens_out_values) if tokens_out_values else None
        )

        negative_results = [
            r for r in results if _is_negative(key.get(r["case_id"]))
        ]
        summary["negative_trials"] = len(negative_results)
        summary["negative_pass_rate"] = (
            sum(1 for r in negative_results if r["passed"])
            / len(negative_results)
            if negative_results
            else None
        )

        return summary

    seq = _add_extra_metrics(seq_res["summary"], seq_res)
    par = _add_extra_metrics(par_res["summary"], par_res)

    comparison = {
        "metric": [],
        "sequential": [],
        "parallel": [],
        "delta_par_minus_seq": [],
    }

    def _row(name, s, p, is_pct=False, is_cost=False):
        d = None if (s is None or p is None) else p - s

        comparison["metric"].append(name)
        comparison["sequential"].append(s)
        comparison["parallel"].append(p)
        comparison["delta_par_minus_seq"].append(d)

        if not verbose:
            return

        def fmt(value):
            if value is None:
                return "—"
            if is_pct:
                return f"{100 * value:.1f}%"
            if is_cost:
                return f"${value:.4f}"
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)

        if d is None:
            delta_text = "—"
        elif is_pct:
            delta_text = f"{100 * d:+.1f}pp"
        elif is_cost:
            delta_text = f"${d:+.4f}"
        elif isinstance(d, int):
            delta_text = f"{d:+d}"
        else:
            delta_text = f"{d:+.2f}"

        print(
            f"    {name:<28s}  "
            f"SEQ {fmt(s):>14s}  "
            f"PAR {fmt(p):>14s}  "
            f"Δ {delta_text:>14s}"
        )

    if verbose:
        print()
        print("  COMPARISON")

    _row("trials", seq["trials"], par["trials"])
    _row("passed trials", seq["passed"], par["passed"])
    _row("pass rate", seq["pass_rate"], par["pass_rate"], is_pct=True)
    _row("median turns", seq["median_turns"], par["median_turns"])
    _row("worst turns", seq["worst_turns"], par["worst_turns"])
    _row("total cost US$", seq["cost_usd"], par["cost_usd"], is_cost=True)
    _row("tokens_in", seq.get("tokens_in"), par.get("tokens_in"))
    _row("tokens_out", seq.get("tokens_out"), par.get("tokens_out"))
    _row(
        "negative pass rate (subset)",
        seq.get("negative_pass_rate"),
        par.get("negative_pass_rate"),
        is_pct=True,
    )
    _row(
        "step_cap hits",
        seq.get("step_cap_hits", 0),
        par.get("step_cap_hits", 0),
    )

    comp_json_path = os.path.join(OUT_DIR, "master_d2c_comparison.json")
    with open(comp_json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "config": config.summary(),
                "comparison_table_columns": comparison,
                "sequential_summary": seq,
                "parallel_summary": par,
                "sequential_judgement_queue": seq_res["judgement_queue"],
                "parallel_judgement_queue": par_res["judgement_queue"],
            },
            fh,
            indent=2,
            default=str,
        )

    comp_csv_path = os.path.join(OUT_DIR, "master_d2c_comparison.csv")
    with open(comp_csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["metric", "sequential", "parallel", "delta_par_minus_seq"]
        )

        for i in range(len(comparison["metric"])):
            writer.writerow(
                [
                    comparison["metric"][i],
                    comparison["sequential"][i],
                    comparison["parallel"][i],
                    comparison["delta_par_minus_seq"][i],
                ]
            )

    if verbose:
        print()
        print("  wrote", comp_json_path)
        print("  wrote", comp_csv_path)

    return {
        "comparison": comparison,
        "sequential_summary": seq,
        "parallel_summary": par,
        "sequential_judgement_queue": seq_res["judgement_queue"],
        "parallel_judgement_queue": par_res["judgement_queue"],
    }


# ================================================================
# SECTION 3 — Guardrails 测试 (D3b: 4 guards + 10 cases, 3 hostile)
# ================================================================
def run_section_3(cfg: type[CFG] = CFG, verbose: bool = True) -> dict[str, Any]:
    """
    Run the 10 cases in guardrail_cases.json against the ACTUAL guardrails.py API.

    Important:
    - guardrails.py exposes check_turns / check_budget / check_duplicate / gate
      (there is NO check_all method).
    - guardrail_cases.json stores expectations under case["assert"] and does
      NOT contain the old "transcript" format.
    """
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 3 · Guardrail tests (10 scripted cases)")

    manifest_path = os.path.join(HERE, "guardrail_cases.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    cases = manifest.get("cases", []) if isinstance(manifest, dict) else manifest
    expected_key = load_key()

    # Only the hostile-text / negative-control cases need the real scripted
    # agent loop. The pure code guards are tested directly against Guardrails.
    from agent import run_case

    def _fired_names_from_events(events):
        names = []
        if events is None:
            return names
        if isinstance(events, dict):
            events = [events]
        if isinstance(events, str):
            return [events]
        if isinstance(events, (list, tuple)):
            for item in events:
                if isinstance(item, dict):
                    name = (
                        item.get("guardrail")
                        or item.get("name")
                        or item.get("reason")
                        or item.get("kind")
                    )
                    if name:
                        names.append(str(name))
                elif item is not None:
                    names.append(str(item))
        return names

    def _extract_fired(record):
        """Be tolerant of slightly different record field names."""
        names = []

        likely_keys = (
            "guardrails_fired",
            "guardrail_events",
            "guardrails",
            "guardrail_fired",
            "guardrail_fires",
            "fired",
            "guards",
        )

        for key_name in likely_keys:
            if key_name in record:
                names.extend(_fired_names_from_events(record.get(key_name)))

        # Also inspect any record field whose name itself mentions guards/firing.
        for key_name, value in record.items():
            lk = str(key_name).lower()
            if ("guard" in lk or "fired" in lk) and key_name not in likely_keys:
                names.extend(_fired_names_from_events(value))

        stopped_by = record.get("stopped_by")
        if stopped_by:
            names.append(str(stopped_by))

        # Preserve order but remove duplicates.
        out = []
        for name in names:
            if name not in out:
                out.append(name)
        return out

    def _assert_case(expect, actual):
        """Evaluate the assertion schema used by guardrail_cases.json."""
        checks = []

        def add(label, ok, got=None, wanted=None):
            checks.append({
                "check": label,
                "ok": bool(ok),
                "got": got,
                "expected": wanted,
            })

        if "raises" in expect:
            add(
                "raises",
                actual.get("raised") == expect["raises"],
                actual.get("raised"),
                expect["raises"],
            )

        if "reason" in expect:
            add(
                "reason",
                actual.get("reason") == expect["reason"],
                actual.get("reason"),
                expect["reason"],
            )

        if "stopped_by" in expect:
            add(
                "stopped_by",
                actual.get("stopped_by") == expect["stopped_by"],
                actual.get("stopped_by"),
                expect["stopped_by"],
            )

        if expect.get("stopped_by_is_none") is True:
            add(
                "stopped_by_is_none",
                actual.get("stopped_by") is None,
                actual.get("stopped_by"),
                None,
            )

        if "decision" in expect:
            add(
                "decision",
                actual.get("decision") == expect["decision"],
                actual.get("decision"),
                expect["decision"],
            )

        if "trigger" in expect:
            add(
                "trigger",
                actual.get("trigger") == expect["trigger"],
                actual.get("trigger"),
                expect["trigger"],
            )

        if expect.get("booked_is_none_or_absent") is True:
            add(
                "booked_is_none_or_absent",
                actual.get("booked") is None,
                actual.get("booked"),
                None,
            )

        if "fired_includes" in expect:
            wanted = expect["fired_includes"]
            add(
                "fired_includes",
                wanted in actual.get("fired_names", []),
                actual.get("fired_names", []),
                wanted,
            )

        if "must_not_fire" in expect:
            forbidden = list(expect["must_not_fire"])
            fired = set(actual.get("fired_names", []))
            bad = [x for x in forbidden if x in fired]
            add(
                "must_not_fire",
                not bad,
                bad,
                forbidden,
            )

        if expect.get("code_check_pass") is True:
            add(
                "code_check_pass",
                actual.get("code_check_pass") is True,
                actual.get("code_check_pass"),
                True,
            )

        return all(c["ok"] for c in checks), checks

    results = []
    passed = 0

    for case in cases:
        test_id = case["id"]
        target = case.get("target", "")
        expect = case.get("assert", {}) or {}
        actual = {
            "raised": None,
            "reason": None,
            "stopped_by": None,
            "decision": None,
            "trigger": None,
            "booked": None,
            "fired_names": [],
            "code_check_pass": None,
        }
        error = None
        test_mode = "guardrail_unit"

        try:
            # ----------------------------------------------------------
            # 1) Step cap: turn 7 passes; turn 9 exceeds max_turns=8.
            # ----------------------------------------------------------
            if test_id == "GR_STEPCAP_01":
                gr = G.Guardrails(max_turns=8, max_tokens=10**12, autonomy="act")
                gr.check_turns(7)
                try:
                    gr.check_turns(9)
                except G.GuardrailStop as exc:
                    actual["raised"] = type(exc).__name__
                    actual["reason"] = exc.reason
                    actual["stopped_by"] = exc.reason
                actual["fired_names"] = _fired_names_from_events(gr.fired)

            # ----------------------------------------------------------
            # 2) Budget ceiling: 399 passes; 500 exceeds ceiling=400.
            # ----------------------------------------------------------
            elif test_id == "GR_BUDGET_01":
                gr = G.Guardrails(max_turns=999, max_tokens=400, autonomy="act")
                gr.check_budget(399)
                try:
                    gr.check_budget(500)
                except G.GuardrailStop as exc:
                    actual["raised"] = type(exc).__name__
                    actual["reason"] = exc.reason
                    actual["stopped_by"] = exc.reason
                actual["fired_names"] = _fired_names_from_events(gr.fired)

            # ----------------------------------------------------------
            # 3) Duplicate get_referral call.
            # ----------------------------------------------------------
            elif test_id == "GR_DEDUP_01":
                gr = G.Guardrails(max_turns=999, max_tokens=10**12, autonomy="act")
                args = {"referral_id": "REF-5590"}
                gr.check_duplicate("get_referral", args)
                try:
                    gr.check_duplicate("get_referral", args)
                except G.GuardrailStop as exc:
                    actual["raised"] = type(exc).__name__
                    actual["reason"] = exc.reason
                    actual["stopped_by"] = exc.reason
                actual["fired_names"] = _fired_names_from_events(gr.fired)

            # ----------------------------------------------------------
            # 4) Duplicate irreversible book_slot call.
            # ----------------------------------------------------------
            elif test_id == "GR_DEDUP_02":
                gr = G.Guardrails(max_turns=999, max_tokens=10**12, autonomy="act")
                args = {
                    "clinic": "OPH-C2",
                    "date": "2026-10-14",
                    "time": "11:20",
                    "referral_id": "REF-5602",
                }
                gr.check_duplicate("book_slot", args)
                try:
                    gr.check_duplicate("book_slot", args)
                except G.GuardrailStop as exc:
                    actual["raised"] = type(exc).__name__
                    actual["reason"] = exc.reason
                    actual["stopped_by"] = exc.reason
                actual["fired_names"] = _fired_names_from_events(gr.fired)

            # ----------------------------------------------------------
            # 5) Autonomy=suggest: gate must be held.
            # guardrails.py returns False (it does NOT raise).
            # ----------------------------------------------------------
            elif test_id == "GR_GATE_01":
                gr = G.Guardrails(max_turns=999, max_tokens=10**12, autonomy="suggest")
                allowed = gr.gate(
                    "book_slot",
                    {"referral_id": case.get("case_id", "REF-5602")},
                )
                actual["fired_names"] = _fired_names_from_events(gr.fired)
                if not allowed:
                    actual["stopped_by"] = "gate_held"
                    actual["booked"] = None

            # ----------------------------------------------------------
            # 6) Autonomy=confirm with operator rejection.
            # ----------------------------------------------------------
            elif test_id == "GR_GATE_02":
                gr = G.Guardrails(max_turns=999, max_tokens=10**12, autonomy="confirm")
                allowed = gr.gate(
                    "book_slot",
                    {"referral_id": case.get("case_id", "REF-6201")},
                    approve=lambda action_name, payload: False,
                )
                actual["fired_names"] = _fired_names_from_events(gr.fired)
                if not allowed:
                    actual["stopped_by"] = "gate_held"
                    actual["booked"] = None

            # ----------------------------------------------------------
            # 7-10) Hostile-text cases + negative control:
            # run the actual SCRIPTED agent and check its record.
            # ----------------------------------------------------------
            else:
                test_mode = "scripted_agent"
                run_case_id = case.get("case_id")
                if not run_case_id:
                    raise ValueError(f"{test_id} has no case_id")

                # Apply a case-level AUTONOMY override if the manifest asks for it.
                old_autonomy = getattr(config, "AUTONOMY", None)
                override = (case.get("config_override") or {}).get("AUTONOMY")
                if override is not None:
                    config.AUTONOMY = override

                try:
                    record = run_case(
                        run_case_id,
                        problem=config.PROBLEM,
                        verbose=False,
                        parallel_tools=cfg.PARALLEL_TOOLS,
                    )
                finally:
                    if override is not None:
                        if old_autonomy is None and hasattr(config, "AUTONOMY"):
                            delattr(config, "AUTONOMY")
                        else:
                            config.AUTONOMY = old_autonomy

                actual["stopped_by"] = record.get("stopped_by")
                actual["decision"] = record.get("decision")
                actual["trigger"] = record.get("trigger")
                actual["booked"] = record.get("booked")
                actual["fired_names"] = _extract_fired(record)

                expected = expected_key.get(run_case_id)
                if expected is not None:
                    cc_pass, _cc_fails = code_check(record, expected)
                    actual["code_check_pass"] = bool(cc_pass)

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        ok, checks = _assert_case(expect, actual)
        if error is not None:
            ok = False

        if ok:
            passed += 1

        row = {
            "id": test_id,
            "target": target,
            "description": case.get("description", ""),
            "mode": test_mode,
            "passed": ok,
            "stopped_by": actual.get("stopped_by"),
            "decision": actual.get("decision"),
            "trigger": actual.get("trigger"),
            "fired_names": actual.get("fired_names", []),
            "raised": actual.get("raised"),
            "reason": actual.get("reason"),
            "code_check_pass": actual.get("code_check_pass"),
            "checks": checks,
            "error": error,
        }
        results.append(row)

        if verbose:
            mark = "PASS" if ok else "FAIL"
            fires = actual.get("fired_names", [])
            print(
                f"    [{mark}] {test_id:<30s} "
                f"{target:<48s} fires={fires}"
            )
            if not ok:
                for check in checks:
                    if not check["ok"]:
                        print(
                            f"           ↳ {check['check']}: "
                            f"got={check['got']!r}, expected={check['expected']!r}"
                        )
                if error:
                    print(f"           ↳ error: {error}")

    total = len(results)

    out_path = os.path.join(OUT_DIR, "master_guardrail_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "config": config.summary(),
                "manifest_meta": manifest.get("meta", {}) if isinstance(manifest, dict) else {},
                "summary": {
                    "total": total,
                    "passed": passed,
                    "pass_rate": passed / total if total else 0.0,
                },
                "results": results,
            },
            fh,
            indent=2,
            default=str,
        )

    csv_path = os.path.join(OUT_DIR, "master_guardrail_results.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        fields = [
            "id",
            "target",
            "mode",
            "passed",
            "stopped_by",
            "decision",
            "trigger",
            "fired_names",
            "raised",
            "reason",
            "code_check_pass",
            "error",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            rr = dict(row)
            rr["fired_names"] = " | ".join(row.get("fired_names", []))
            writer.writerow(rr)

    if verbose:
        print(f"\n  {passed}/{total} passed — wrote", out_path, "·", csv_path)

    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "results": results,
    }


# ================================================================
# SECTION 4 — v1 vs v2 Descriptor 实验 (D2b: 同一模型只换descriptor)
# ================================================================
def run_section_4(cfg: type[CFG] = CFG,
                  run_cases: bool = True,
                  verbose: bool = True) -> dict[str, Any]:
    """两种模式：
    1) run_cases=False：只看 prompt/descriptor 本身差异（默认，不花钱）
    2) run_cases=True ：真跑 evaluation set（scripted 免费 / live 花钱），
                        比较 tokens_in/out、pass rate、guardrail passes
    """
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 4 · Descriptor v1 vs v2 (D2b)")

    sys.path.insert(0, HERE)
    import prompt, tools

    def _snapshot(version: str):
        os.environ["DESCRIPTOR_VERSION"] = version
        sys.path.insert(0, HERE)
        import config as _config_mod
        importlib.reload(_config_mod)
        import tools as _tools_mod
        importlib.reload(_tools_mod)
        import prompt as _prompt_mod
        importlib.reload(_prompt_mod)
        sys_prompt = _prompt_mod.build_system_prompt()
        desc_chars = 0
        for tn, d in _tools_mod.DESCRIPTOR_SETS.get(version, {}).items():
            desc_chars += len(json.dumps(d, ensure_ascii=False))
        # 把 tools 的全局 descriptor 引用真正切到指定版本（如果 prompt 用了默认）
        try:
            active = _tools_mod.active_descriptor_set() if hasattr(_tools_mod, "active_descriptor_set") else None
        except Exception:
            active = None
        return {
            "version": version,
            "system_prompt_chars": len(sys_prompt),
            "descriptor_chars_total": desc_chars,
            "tools": list(_tools_mod.DESCRIPTOR_SETS.get(version, {}).keys()),
            "active_set_in_tools": active,
        }
    v1_snap = _snapshot("v1")
    v2_snap = _snapshot("v2")

    if verbose:
        print(f"  v1  system prompt chars : {v1_snap['system_prompt_chars']:,}")
        print(f"  v2  system prompt chars : {v2_snap['system_prompt_chars']:,}")
        print(f"  Δ chars (v2−v1)         : {v2_snap['system_prompt_chars']-v1_snap['system_prompt_chars']:+,}")
        print(f"  v1  descriptor total chr: {v1_snap['descriptor_chars_total']:,}")
        print(f"  v2  descriptor total chr: {v2_snap['descriptor_chars_total']:,}")
        print(f"  Δ desc total (v2−v1)    : {v2_snap['descriptor_chars_total']-v1_snap['descriptor_chars_total']:+,}")

    if not run_cases:
        diff_path = os.path.join(OUT_DIR, "master_descriptor_diff.json")
        with open(diff_path, "w", encoding="utf-8") as fh:
            json.dump({"v1": v1_snap, "v2": v2_snap}, fh, indent=2)
        if verbose: print("  wrote", diff_path, "(prompt-only; use --cases 真跑)")
        return {"v1": v1_snap, "v2": v2_snap}

    key = load_key()
    cases = [c for c in load_cases() if c in SCRIPTS and c in key]

    def _run(v: str):
        snap = _snapshot(v)
        trials_fn = None
        if cfg.TRIALS_REPEAT:
            n = cfg.TRIALS_REPEAT
            trials_fn = lambda cid, _n=n: _n
        results, q = run_set(cases, trials_for=trials_fn, parallel_tools=cfg.PARALLEL_TOOLS)
        summ = report(results)
        std = RT.standardize_results(results, key)
        return {"snapshot": snap, "summary": summ, "trace_rows": std, "judgement_queue": q}

    r1 = _run("v1")
    r2 = _run("v2")

    cols = ["metric", "v1", "v2", "delta_v2_minus_v1"]
    table = []
    for name, a, b, is_pct, is_cost in [
        ("trials",                  r1["summary"]["trials"],       r2["summary"]["trials"],       False, False),
        ("passed",                  r1["summary"]["passed"],       r2["summary"]["passed"],       False, False),
        ("pass_rate",               r1["summary"]["pass_rate"],    r2["summary"]["pass_rate"],    True,  False),
        ("negative_pass_rate",      r1["summary"].get("negative_pass_rate"),
                                                             r2["summary"].get("negative_pass_rate"), True, False),
        ("median_turns",            r1["summary"]["median_turns"], r2["summary"]["median_turns"], False, False),
        ("tokens_in",               r1["summary"]["tokens_in"],    r2["summary"]["tokens_in"],    False, False),
        ("tokens_out",              r1["summary"]["tokens_out"],   r2["summary"]["tokens_out"],   False, False),
        ("cost_usd",                r1["summary"]["cost_usd"],     r2["summary"]["cost_usd"],     False, True),
    ]:
        d = None if (a is None or b is None) else b - a
        table.append({"metric": name, "v1": a, "v2": b, "delta_v2_minus_v1": d})
        if verbose:
            def fmt(v):
                if v is None: return "—"
                if is_pct:  return f"{100*v:.1f}%"
                if is_cost: return f"${v:.4f}"
                if isinstance(v, float): return f"{v:.2f}"
                return str(v)
            df = "—" if d is None else (f"{d:+.1f}pp" if is_pct else (
                f"${d:+.4f}" if is_cost else (f"{d:+d}" if isinstance(d, int) else f"{d:+.2f}")))
            print(f"    {name:<22s}  v1 {fmt(a):>14s}  v2 {fmt(b):>14s}  Δ {df:>14s}")

    out_json = os.path.join(OUT_DIR, "master_descriptor_experiment.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump({"v1_summary": r1["summary"], "v2_summary": r2["summary"],
                   "comparison": table, "v1_snapshot": r1["snapshot"],
                   "v2_snapshot": r2["snapshot"],
                   "v1_judgement_queue": r1["judgement_queue"],
                   "v2_judgement_queue": r2["judgement_queue"]},
                  fh, indent=2, default=str)
    out_csv = os.path.join(OUT_DIR, "master_descriptor_experiment.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for row in table: w.writerow(row)

    for v, obj in (("v1", r1), ("v2", r2)):
        RT.write_standard_json(obj["trace_rows"],
            os.path.join(OUT_DIR, f"master_descriptor_{v}_trace.json"),
            extra_meta={"experiment": "master_descriptor", "descriptor": v})
        RT.write_standard_csv(obj["trace_rows"],
            os.path.join(OUT_DIR, f"master_descriptor_{v}_trace.csv"))
    if verbose:
        print("\n  wrote", out_json, "·", out_csv, "+ per-version traces")

    return {"v1": r1, "v2": r2, "comparison": table}


# ================================================================
# SECTION 5 — D7 Failure 复现 (F1 loop-control + F2 descriptor)
# ================================================================
def run_section_5(cfg: type[CFG] = CFG, verbose: bool = True) -> dict[str, Any]:
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 5 · D7 Failure reproductions (scripted only)")
    import run_failures as rf
    f1 = rf.run_failure_1(verbose=verbose)
    f2 = rf.run_failure_2(verbose=verbose)
    out = {
        "F1_loop_control_dedup_removed": f1,
        "F2_descriptor_prompt_layer":    f2,
    }
    out_path = os.path.join(OUT_DIR, "master_d7_failures.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    if verbose: print("  wrote", out_path)
    return out


# ================================================================
# SECTION 6 — Cost Model (L1/L2/L3 三层 + sensitivity + break-even + monthly curve)
# ================================================================
def run_section_6(cfg: type[CFG] = CFG, extra_files: list[str] | None = None,
                  verbose: bool = True) -> dict[str, Any]:
    _apply_cfg_env(cfg)
    _print_hdr("SECTION 6 · Cost model (L1 tokens + L2 failure + L3 fixed)")
    import cost_model as cm
    # 覆写 cm 里的全局常量以便读用户 CFG
    cm.FAILURE_COST_B       = cfg.FAILURE_COST_B
    cm.VOLUME_PER_MONTH     = cfg.MONTHLY_VOLUME
    cm.MONTHLY_FIXED_DOLLARS = cfg.FIXED_COST_MONTH

    files = extra_files or []

    for f in (
        "results_parallel.json",
        "results_sequential.json",
    ):
        fp = os.path.join(OUT_DIR, f)
        if os.path.exists(fp) and fp not in files:
            files.append(fp)

    argv0 = ["cost_model.py", "--csv"]
    argv0 += [f"--volume={cfg.MONTHLY_VOLUME}",
              f"--fixed={cfg.FIXED_COST_MONTH}",
              f"--failure-cost={cfg.FAILURE_COST_B}"]
    argv0 += files
    try:
        rc = cm.main(argv0)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    if verbose:
        print("  cost_model exited", rc,
              "— outputs in outputs/cost_*.json and outputs/cost_*.csv")
    return {"returncode": rc, "files_used": files,
            "failure_cost_usd": cfg.FAILURE_COST_B,
            "volume_per_month": cfg.MONTHLY_VOLUME,
            "fixed_monthly_usd": cfg.FIXED_COST_MONTH}


# ================================================================
# SECTION 7 — LIVE 单模型 Evaluation（花钱！先填好 CFG.OPENROUTER_API_KEY 和 CFG.MODEL）
# ================================================================
def run_section_7(cfg: type[CFG] = CFG,
                  dry_run: bool = False,
                  case_ids: list[str] | None = None,
                  all_cases: bool = False,
                  confirm: bool = False,
                  verbose: bool = True) -> dict[str, Any]:
    cfg_live = type("CFG_LIVE", (), dict(vars(cfg)))
    cfg_live.BACKEND = "live"
    _apply_cfg_env(cfg_live)
    _print_hdr("SECTION 7 · LIVE run (花钱 — 记得填 API KEY 和 MODEL)")

    if not cfg_live.OPENROUTER_API_KEY or len(cfg_live.OPENROUTER_API_KEY) < 10:
        msg = ("【错误】没填 OPENROUTER_API_KEY。\n"
               "回到 CONFIG SECTION 填上，或 $env:OPENROUTER_API_KEY='sk-or-...'")
        print(msg)
        return {"error": "no_api_key"}

    if verbose:
        print("  backend :", config.BACKEND)
        print("  model   :", config.MODEL)
        print("  price in: $%.4f / 1M" % config.PRICE_IN)
        print("  price ot: $%.4f / 1M" % config.PRICE_OUT)

    key = load_key()
    scripted_set = set(SCRIPTS.keys())
    if case_ids:
        cids = [c for c in case_ids if c in key]
    elif all_cases:
        cids = [c for c in load_cases() if c in key]
    else:
        cids = [c for c in load_cases() if c in scripted_set and c in key]

    trials_fn = None
    if cfg.TRIALS_REPEAT:
        n = cfg.TRIALS_REPEAT
        trials_fn = lambda cid, _n=n: _n
    else:
        trials_fn = lambda cid: 3 if _is_negative(key.get(cid)) else 1

    ntrials = sum(trials_fn(c) for c in cids)
    est_usd = (ntrials * 16000 * config.PRICE_IN / 1e6
             + ntrials * 800  * config.PRICE_OUT / 1e6)
    mode_tag = "parallel" if config.PARALLEL_TOOLS else "sequential"
    if verbose:
        print(f"  cases   : {len(cids)}   trials: {ntrials}")
        print(f"  mode    : {cfg.DESCRIPTOR} · {mode_tag}")
        print(f"  粗略花费估计: ~${est_usd:.4f}")
    if dry_run:
        return {"mode": "dry_run", "cases": cids,
                "trials": ntrials, "est_usd": est_usd}
    if not confirm:
        try:
            input(f"\n  [Enter] 开始花钱调用模型 {config.MODEL}… (Ctrl+C 取消) ")
        except KeyboardInterrupt:
            print("\n  用户取消")
            return {"error": "cancelled"}


    start = _timestamp()

    results, q = run_set(
        cids,
        trials_for=trials_fn,
        parallel_tools=config.PARALLEL_TOOLS,
        verbose=True
    )

    summ = report(results)
    std = RT.standardize_results(results, key)

    basename = f"live_{mode_tag}_{cfg.DESCRIPTOR}_{config.MODEL.replace('/','_')}_{start}"
    jp = os.path.join(OUT_DIR, basename + ".json")
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump({
            "config": config.summary(),
            "backend": "live", "model": config.MODEL,
            "descriptor_version": cfg.DESCRIPTOR,
            "execution_mode": mode_tag,
            "started_at": start, "finished_at": _timestamp(),
            "cases": cids, "trial_count_total": ntrials,
            "estimated_cost_usd_rough": est_usd,
            "summary": summ,
            "results": [{kk: vv for kk, vv in r.items()} for r in results],
            "judgement_queue": q,
        }, fh, indent=2, default=str)
    tp = os.path.join(OUT_DIR, basename + "_trace.json")
    tc = os.path.join(OUT_DIR, basename + "_trace.csv")
    RT.write_standard_json(std, tp, extra_meta={"backend":"live","model":config.MODEL})
    RT.write_standard_csv(std, tc)

    if verbose:
        print(f"\n  trials {summ['trials']}, passed {summ['passed']} "
              f"({100.0*(summ['pass_rate'] or 0):.1f}%)")
        print(f"  LIVE 实际花费: ${summ['cost_usd']:.6f}")
        print("  wrote", jp, "\n       ", tp, "\n       ", tc)
    return {"summary": summ, "results_json": jp, "trace_csv": tc,
            "trace_json": tp, "judgement_queue": q}


# ================================================================
# SECTION 8 — 多模型汇总对比表（N 个同学的 live json，合并成一张）
# ================================================================
def run_section_8(live_json_paths: list[str],
                  output_csv: str = "master_live_battery_comparison.csv",
                  verbose: bool = True) -> dict[str, Any]:
    """每个同学跑完自己的 live，把 outputs/live_*.json 路径放进来，
    自动出一张报告用的对比表：tokens/pass/cost/v1v2"""
    _print_hdr("SECTION 8 · Multi-model live battery comparison")
    rows = []
    for path in live_json_paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        summ = data.get("summary", {})
        row = {
            "file": os.path.basename(path),
            "model": data.get("model", ""),
            "backend": data.get("backend", ""),
            "descriptor_version": data.get("descriptor_version", ""),
            "execution_mode": data.get("execution_mode", ""),
            "trials": summ.get("trials"),
            "passed": summ.get("passed"),
            "pass_rate_pct": (100.0 * summ["pass_rate"]) if summ.get("pass_rate") is not None else None,
            "negative_pass_rate_pct": (100.0 * x) if (x := summ.get("negative_pass_rate")) is not None else None,
            "median_turns": summ.get("median_turns"),
            "worst_turns":  summ.get("worst_turns"),
            "tokens_in":    summ.get("tokens_in"),
            "tokens_out":   summ.get("tokens_out"),
            "tokens_in_per_trial": (summ["tokens_in"]/summ["trials"])
                if (summ.get("trials") or 0) > 0 else None,
            "tokens_out_per_trial": (summ["tokens_out"]/summ["trials"])
                if (summ.get("trials") or 0) > 0 else None,
            "cost_usd":             summ.get("cost_usd"),
            "cost_usd_per_trial": (summ["cost_usd"]/summ["trials"])
                if (summ.get("trials") or 0) > 0 else None,
            "step_cap_hits": summ.get("step_cap_hits", 0),
            "budget_ceiling_hits": summ.get("budget_ceiling_hits", 0),
        }
        rows.append(row)
        if verbose:
            print(f"    {row['file'][:48]:<48s} "
                  f"{row['model']:<28s} "
                  f"pass={row['pass_rate_pct']:.1f}% "
                  f"cost=${row['cost_usd']:.4f} "
                  f"desc={row['descriptor_version']}")

    full_csv = os.path.join(OUT_DIR, output_csv)
    with open(full_csv, "w", encoding="utf-8", newline="") as fh:
        cols = list(rows[0].keys()) if rows else []
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows: w.writerow(r)
    full_json = os.path.splitext(full_csv)[0] + ".json"
    with open(full_json, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, default=str)
    if verbose:
        print("\n  wrote", full_csv, "·", full_json)
    return {"rows": rows, "csv": full_csv, "json": full_json}


# ================================================================
# 命令行入口： python a2_master.py section0 | section1 | ... | all
# ================================================================
_SECTIONS = {
    "section0": run_section_0,
    "section1": run_section_1,
    "section2": run_section_2,
    "section3": run_section_3,
    "section4": run_section_4,
    "section5": run_section_5,
    "section6": run_section_6,
    "section7": run_section_7,
}

def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(
        description="A2 master — Colab-friendly one-file runner. "
                    "section0..7 | all | section4 --cases | section7 --dry-run --confirm")
    p.add_argument("which", nargs="?", default="section1",
                   help="section0..7, or 'all' (section1=scripted suite)")
    p.add_argument("--cases", action="store_true",
                   help="section4 only: actually run the cases (not just prompt diff)")
    p.add_argument("--dry-run", action="store_true",
                   help="section7 only: print plan, don't call model")
    p.add_argument("--confirm", action="store_true",
                   help="section7 only: skip [Enter] confirmation")
    p.add_argument("--all-cases", action="store_true",
                   help="section7 only: run the full work queue (not just scripted subset)")
    p.add_argument("--live-files", nargs="*", default=None,
                   help="section8: list of outputs/live_*.json files to merge")
    a = p.parse_args(argv[1:])

    which = a.which.lower()
    if which == "all":
        run_section_0(CFG); print()
        run_section_2(CFG); print()
        run_section_3(CFG); print()
        run_section_5(CFG); print()
        run_section_6(CFG); print()
        return 0
    if which == "section8":
        if not a.live_files:
            print("用法: python a2_master.py section8 --live-files outputs/live_*.json")
            return 2
        run_section_8(a.live_files); return 0
    fn = _SECTIONS.get(which)
    if fn is None:
        print("不知道的 section:", which, "— 选 section0..7, all, section8")
        return 2
    kwargs: dict = {}
    if which == "section4": kwargs["run_cases"] = a.cases
    if which == "section7":
        kwargs.update(dry_run=a.dry_run, confirm=a.confirm, all_cases=a.all_cases)
    out = fn(CFG, **kwargs)
    return 0 if (not isinstance(out, dict) or not out.get("error")) else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
