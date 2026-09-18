#!/usr/bin/env python3
"""
PE6201 · A2 — run_all_scripted.py  (总入口，一键完成所有 scripted 实验)
====================================================================
    python3 run_all_scripted.py            运行全部：数据检查 → eval(并行)
                                           → guardrails → D2c 串行/并行
                                           → D7 failures → cost model
    python3 run_all_scripted.py --skip-eval      跳过重复的 eval(并行)
                                           (D2c 里本来就会跑一遍并行 + 串行)
    python3 run_all_scripted.py --failures-only 只跑 D7 failure reproductions

一键跑完后，报告里需要的表全部来自 outputs/ 目录下的 CSV / JSON，
不需要手抄任何数字。

脚本流程：
  1. check_my_data.py        — 确认 fixture 数据没有破损
  2. run_eval.py (parallel)  — scripted evaluation (D5 marker-run entry)
  3. run_guardrails.py       — D3b 的 10 个 guardrail 测试
  4. run_d2c_compare.py      — D2(c) 串行 vs 并行 控制实验
  5. run_failures.py         — D7 两个 failure reproductions
  6. cost_model.py           — D6 三层成本模型 + 敏感性 + break-even

每一步把 stdout 追加到 outputs/all_scripted.log；
最终写一份 outputs/all_scripted_summary.json 作为结果索引。

注意：本文件只使用 SCRIPTED backend，不花钱，没有网络调用。
LIVE battery 请用独立的 run_live.py，不要混在一起，防止误烧 API 钱。
====================================================================
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

DATA_CHECK_PATH = os.path.join(HERE, "..", "A2_reference_data", "check_my_data.py")

STEPS = [
    ("1_data_check",        ["check_my_data"],      "check reference fixtures"),
    ("2_eval_parallel",     ["run_eval"],           "scripted eval (parallel, D5 marker entry)"),
    ("3_guardrails",        ["run_guardrails"],     "D3b guardrail suite"),
    ("4_d2c_compare",       ["run_d2c_compare", "--csv"], "D2(c) sequential vs parallel"),
    ("5_d7_failures",       ["run_failures"],       "D7 both failure reproductions"),
    ("6_cost_model",        ["cost_model"],         "D6 3-layer cost + sensitivity + break-even"),
]


def _runner_script_path(name):
    if name == "check_my_data":
        return DATA_CHECK_PATH
    return os.path.join(HERE, name + ".py")


def _run(step_id, script_names, description, log_fh):
    script_path = _runner_script_path(script_names[0])
    if not os.path.exists(script_path):
        msg = "SKIP %s — %s not found at %s" % (step_id, script_names[0], script_path)
        print(msg)
        log_fh.write(msg + "\n")
        return False, msg, None

    argv_extra = script_names[1:] if len(script_names) > 1 else []
    cwd = HERE if script_names[0] != "check_my_data" else os.path.dirname(DATA_CHECK_PATH)

    banner = "\n" + "=" * 72 + "\n"
    banner += "  %s — %s\n" % (step_id, description)
    banner += "  script: %s %s\n" % (os.path.basename(script_path), " ".join(argv_extra))
    banner += "  started at %s\n" % datetime.datetime.now().isoformat(timespec="seconds")
    banner += "=" * 72 + "\n"
    print(banner)
    log_fh.write(banner)
    log_fh.flush()

    try:
        proc = subprocess.run(
            [sys.executable, script_path] + argv_extra,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        out = proc.stdout or ""
        sys.stdout.write(out)
        sys.stdout.flush()
        log_fh.write(out)
        log_fh.flush()
        rc = proc.returncode
    except Exception as exc:
        rc = 99
        err_txt = "EXCEPTION: %s\n%s" % (exc, traceback.format_exc())
        print(err_txt)
        log_fh.write(err_txt)
        log_fh.flush()

    footer = "\n  %s finished with exit code %d at %s\n" % (
        step_id, rc, datetime.datetime.now().isoformat(timespec="seconds"))
    print(footer)
    log_fh.write(footer)
    log_fh.flush()

    ok = (rc == 0)
    status_txt = "PASS" if ok else "FAIL (exit %d)" % rc
    return ok, status_txt, rc


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(
        description="A2 master scripted entry: every deterministic test in order")
    p.add_argument("--skip-eval", action="store_true",
                   help="skip run_eval.py (run_d2c_compare.py already runs parallel)")
    p.add_argument("--failures-only", action="store_true",
                   help="only run D7 failures (useful after first run)")
    p.add_argument("--guardrails-only", action="store_true",
                   help="only run D3b guardrails")
    a = p.parse_args(argv[1:])

    import config
    print()
    print("=" * 72)
    print("  PE6201 A2 — RUN_ALL_SCRIPTED (no API cost, no network)")
    print("=" * 72)
    print("  backend      :", config.BACKEND)
    print("  problem      :", config.PROBLEM)
    print("  data root    :", config.data_root())
    print("  output dir   :", OUT_DIR)
    print("  started at   :", datetime.datetime.now().isoformat(timespec="seconds"))
    print()
    print("  [!] This file uses ONLY the SCRIPTED backend.")
    print("      LIVE battery → run_live.py (separate file, costs money).")
    print("=" * 72)
    print()

    log_path = os.path.join(OUT_DIR, "all_scripted.log")
    summary = {
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "config_summary": config.summary(),
        "data_root": config.data_root(),
        "output_dir": OUT_DIR,
        "steps": {},
    }
    overall_ok = True

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write("all_scripted.py log — started %s\n\n"
                     % summary["started_at"])
        log_fh.write(summary["config_summary"] + "\n\n")

        plan = STEPS[:]
        if a.failures_only:
            plan = [s for s in STEPS if s[0] == "5_d7_failures"]
        elif a.guardrails_only:
            plan = [s for s in STEPS if s[0] == "3_guardrails"]
        if a.skip_eval:
            plan = [s for s in plan if s[0] != "2_eval_parallel"]

        for step_id, script_names, description in plan:
            ok, status_txt, rc = _run(step_id, script_names, description, log_fh)
            if not ok:
                overall_ok = False
            summary["steps"][step_id] = {
                "description": description,
                "script": script_names,
                "passed": bool(ok),
                "status": status_txt,
                "exit_code": rc,
                "ran_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }

    summary["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    summary["all_passed"] = overall_ok

    summary_path = os.path.join(OUT_DIR, "all_scripted_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    print()
    print("=" * 72)
    print("  RUN_ALL_SCRIPTED  —  SUMMARY")
    print("=" * 72)
    for step_id, info in summary["steps"].items():
        mark = "PASS" if info["passed"] else "FAIL"
        print("    [%-4s]  %-18s  %s" % (mark, step_id, info["description"]))
    print()
    print("  overall  :", "ALL PASSED" if overall_ok else "SOME STEPS FAILED — check log above")
    print("  log      :", log_path)
    print("  summary  :", summary_path)
    print("  outputs/ :")
    for n in sorted(os.listdir(OUT_DIR)):
        fp = os.path.join(OUT_DIR, n)
        if os.path.isfile(fp):
            print("    - %s (%d bytes)" % (n, os.path.getsize(fp)))
    print()

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
