#!/usr/bin/env python3
"""
PE6201 · A2 — D6 COST MODEL (Section 7)
====================================================================
    python3 cost_model.py                read outputs/comparison.json first,
                                         plus optional outputs/results_parallel.json

    python3 cost_model.py results.json   read a specific live results file

    python3 cost_model.py --live         pull prices from config (default
                                         scripted estimates also works)
    python3 cost_model.py --csv          also emit sensitivity + monthly CSVs

Three cost layers — all three required by Section 7:

  LAYER 1 — Token cost
         = tokens_in  * price_in_per_million
         + tokens_out * price_out_per_million
         Reported "per referral processed".

  LAYER 2 — Expected failure cost
         = (1 - success_rate) * FAILURE_COST_PER_BAD_BOOKING
         Problem B default failure cost = US$ 9.17 per bad referral
         (this number comes from the brief - VERIFY AGAINST CURRENT VERSION).

  LAYER 3 — Fixed monthly cost
         Defensible per-month standing charges. Default values match a low-volume
         shared-ops deployment:
              agent-owner time / on-call overhead / observability / SRE
              ≈ 0.20 FTE   @ blended US$40/hr → US$ 2880/month.
         Plus two cheap monitoring + logging services → US$ 2880 + 40 = 2920.

         You MUST justify these numbers in your report (the numbers are
         assumptions, not facts). The program just computes from the formulas
         so the sensitivities auto-update.

The model also produces:
   * Monthly cost at a range of monthly volumes
   * Sensitivity table: success rate ±10 percentage points in 2 pp steps
   * Break-even success rate: at what % success does Model A cost
     (price model start beating Model B at the same volume)
   * cost_model.csv         — per-model 3-layer breakdown for the report
   * cost_sensitivity.csv   — ±10 pp table (paste directly into Appendix)
   * cost_monthly_volume.csv— monthly cost curve across volume tiers
====================================================================
"""
import argparse
import csv
import json
import math
import os
import sys

import config

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

FAILURE_COST_B = 9.17
MONTHLY_FIXED_DOLLARS = 2920.0
VOLUME_PER_MONTH = 4000


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _extract_metrics(obj, label=""):
    if "summary" in obj and isinstance(obj["summary"], dict):
        s = obj["summary"]
        trials = s.get("trials") or len(obj.get("results", []))
        passed = s.get("passed")
        pass_rate = s.get("pass_rate")
        median_turns = s.get("median_turns")
        total_cost = s.get("cost_usd")
    else:
        trials = obj.get("trials")
        passed = obj.get("passed")
        pass_rate = obj.get("pass_rate")
        median_turns = obj.get("median_turns")
        total_cost = obj.get("cost_usd")

    results = obj.get("results") or obj.get("rows") or []
    if results:
        def _ti(r):
            rec = r.get("record", r)
            return rec.get("tokens_in", r.get("tokens_in", 0))
        def _to(r):
            rec = r.get("record", r)
            return rec.get("tokens_out", r.get("tokens_out", 0))
        t_in = sum(_ti(r) for r in results)
        t_out = sum(_to(r) for r in results)
        n = len(results)
        per_in = t_in / n if n else 0
        per_out = t_out / n if n else 0
    else:
        per_in = obj.get("tokens_in_per_case", 0)
        per_out = obj.get("tokens_out_per_case", 0)

    return {
        "label": label,
        "trials": trials,
        "passed": passed,
        "pass_rate": pass_rate if pass_rate is not None else (
            (passed / trials) if (trials and passed is not None) else None),
        "median_turns": median_turns,
        "total_cost_usd_measured": total_cost,
        "tokens_in_per_case": per_in,
        "tokens_out_per_case": per_out,
    }


def layer1_token_cost_per_case(m):
    return (m["tokens_in_per_case"] * config.PRICE_IN / 1e6
          + m["tokens_out_per_case"] * config.PRICE_OUT / 1e6)


def layer2_expected_failure_cost_per_case(m, failure_cost=FAILURE_COST_B):
    if m["pass_rate"] is None:
        return None
    return (1.0 - m["pass_rate"]) * failure_cost


def total_monthly_cost(m, volume=VOLUME_PER_MONTH, fixed=MONTHLY_FIXED_DOLLARS,
                       failure_cost=FAILURE_COST_B):
    l1 = layer1_token_cost_per_case(m)
    l2 = layer2_expected_failure_cost_per_case(m, failure_cost)
    if l2 is None:
        l2 = 0.0
    variable_per = l1 + l2
    total = fixed + (volume * variable_per)
    return {
        "volume": volume,
        "L1_per_case": l1,
        "L2_per_case": l2,
        "L3_fixed_monthly": fixed,
        "variable_per_case": variable_per,
        "total_monthly": total,
        "cost_per_case_average": total / volume if volume else None,
    }


def sensitivity(m, label=""):
    if m["pass_rate"] is None:
        return []
    base = m["pass_rate"]
    rows = []
    for pp in range(-10, 11, 2):
        p = max(0.0, min(1.0, base + pp / 100.0))
        m2 = dict(m)
        m2["pass_rate"] = p
        mc = total_monthly_cost(
            m2,
            volume=VOLUME_PER_MONTH,
            fixed=MONTHLY_FIXED_DOLLARS,
            failure_cost=FAILURE_COST_B,
        )
        rows.append({
            "model_label": m.get("label", label),
            "delta_pp": pp,
            "success_rate": p,
            "failure_rate": 1.0 - p,
            "L2_per_case": (1.0 - p) * FAILURE_COST_B,
            "total_monthly": mc["total_monthly"],
            "avg_cost_per_case": mc["cost_per_case_average"],
        })
    return rows


def monthly_volume_table(m, volumes=(200, 500, 1000, 2000, 5000, 10000)):
    out = []
    for v in volumes:
        mc = total_monthly_cost(m, volume=v)
        out.append({
            "model_label": m.get("label", ""),
            "monthly_volume": v,
            "L1_monthly": mc["L1_per_case"] * v,
            "L2_monthly": mc["L2_per_case"] * v,
            "L3_fixed_monthly": mc["L3_fixed_monthly"],
            "total_monthly": mc["total_monthly"],
            "avg_cost_per_case": mc["cost_per_case_average"],
        })
    return out


def break_even_success_rate(m_cheap, mexpensive,
                        volume=VOLUME_PER_MONTH, fixed=MONTHLY_FIXED_DOLLARS):
    l1_c = layer1_token_cost_per_case(m_cheap)
    l1_e = layer1_token_cost_per_case(mexpensive)

    pass_c = m_cheap.get("pass_rate")
    pass_e = mexpensive.get("pass_rate")

    if pass_e is None or FAILURE_COST_B <= 0:
        return None

    # Expensive model all-in variable cost at its measured pass rate.
    E = l1_e + (1.0 - pass_e) * FAILURE_COST_B

    # Cheap model token-only cost; solve for the cheap pass rate p where
    # C + (1-p)F = E  ->  p = 1 - (E-C)/F.
    C = l1_c
    break_even_p_for_cheap = 1.0 - (E - C) / FAILURE_COST_B

    return {
        "cheap_model_label": m_cheap.get("label", "cheap"),
        "expensive_model_label": mexpensive.get("label", "expensive"),
        "L1_per_case_cheap": l1_c,
        "L1_per_case_expensive": l1_e,
        "expensive_measured_pass_rate": pass_e,
        "cheap_model_measured_pass_rate": pass_c,
        "break_even_pass_rate_cheap_model_would_need": break_even_p_for_cheap,
        "interpretation": (
            "The cheap model needs a success rate of %.4f%% to match "
            "the expensive model's total variable cost per referral "
            "at a failure cost of US$%.2f."
            % (break_even_p_for_cheap * 100.0, FAILURE_COST_B)
        )
    }


def _write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main(argv):
    global FAILURE_COST_B, VOLUME_PER_MONTH, MONTHLY_FIXED_DOLLARS
    p = argparse.ArgumentParser(description="A2 D6 cost model")
    p.add_argument("files", nargs="*",
                   help="results.json files (default: outputs/results_parallel.json + results_sequential.json)")
    p.add_argument("--volume", type=int, default=VOLUME_PER_MONTH)
    p.add_argument("--fixed", type=float, default=MONTHLY_FIXED_DOLLARS)
    p.add_argument("--failure-cost", type=float, default=FAILURE_COST_B)
    p.add_argument("--csv", action="store_true", default=True,
                   help="also emit CSV tables (default True)")
    a = p.parse_args(argv[1:])

    FAILURE_COST_B = a.failure_cost
    VOLUME_PER_MONTH = a.volume
    MONTHLY_FIXED_DOLLARS = a.fixed

    if a.files:
        files = a.files
    else:
        files = [os.path.join(OUT_DIR, f) for f in
                 ("results_parallel.json", "results_sequential.json")
                 if os.path.exists(os.path.join(OUT_DIR, f))]
        if not files and os.path.exists(os.path.join(HERE, "results.json")):
            files = [os.path.join(HERE, "results.json")]

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print()
    print("PE6201 A2 - D6 COST MODEL")
    print("=" * 68)
    print("config prices in : $%.4f / 1M tokens" % config.PRICE_IN)
    print("config prices out: $%.4f / 1M tokens" % config.PRICE_OUT)
    print("failure cost  : $%.2f per bad booking (Problem B, brief §7)"
          % FAILURE_COST_B)
    print("fixed / month: $%.2f   (assumption: 0.20 FTE + monitoring)"
          % MONTHLY_FIXED_DOLLARS)
    print("monthly vol : %d referrals processed" % VOLUME_PER_MONTH)
    print("data       :", config.data_root())
    print()

    if not files:
        print("(!) no input files. Run `python run_d2c_compare.py` first, or")
        print("    pass a results.json path on the command line.")
        print("    Falling back to hard-coded demo numbers.")
        print()
        demo_metrics = [
            _extract_metrics({
                "trials": 70, "passed": 70, "pass_rate": 1.0,
                "median_turns": 4.0, "cost_usd": 0.1267,
                "tokens_in_per_case": 1126200 / 70,
                "tokens_out_per_case": 35160 / 70,
            }, label="parallel-scripted-estimate")
        ]
    else:
        demo_metrics = []
        for path in files:
            try:
                obj = _load(path)
            except (OSError, json.JSONDecodeError) as e:
                print("  skip %s: %s" % (path, e))
                continue
            label = os.path.basename(path)
            if "comparison" in label.lower():
                for k in ("sequential", "parallel"):
                    r = obj.get(k)
                    if isinstance(r, dict):
                        demo_metrics.append(_extract_metrics(r, label=label + "::" + k))
            elif isinstance(obj, dict) and "rows" in obj:
                summ = obj.get("summary", {}) if isinstance(obj.get("summary"), dict) else {}
                demo_metrics.append(_extract_metrics({
                    **summ,
                    "results": obj.get("rows", [])
                }, label=label))
            else:
                demo_metrics.append(_extract_metrics(obj, label=label))

    cost_rows_csv = []
    sens_rows_csv = []
    monthly_rows_csv = []
    rows_out = []

    for m in demo_metrics:
        print("-" * 68)
        print("MODEL / RUN :", m["label"])
        print("-" * 68)
        l1 = layer1_token_cost_per_case(m)
        l2 = layer2_expected_failure_cost_per_case(m)
        mc = total_monthly_cost(m, volume=VOLUME_PER_MONTH,
                               fixed=MONTHLY_FIXED_DOLLARS)
        print("  trials            :", m["trials"])
        if m["pass_rate"] is not None:
            print("  success rate      : %.2f %%" % (100.0 * m["pass_rate"]))
        print("  median turns      :", m["median_turns"])
        print("  tok_in / case      : %d" % round(m["tokens_in_per_case"]))
        print("  tok_out / case     : %d" % round(m["tokens_out_per_case"]))
        print()
        print("  L1  token cost / case         : $%.6f" % l1)
        if l2 is not None:
            print("  L2  expected failure / case   : $%.6f   (= (1-p)*%.2f)"
                  % (l2, FAILURE_COST_B))
        else:
            print("  L2  expected failure / case   : n/a (no success rate)")
        print("  L3  fixed monthly            : $%.2f" % MONTHLY_FIXED_DOLLARS)
        print()
        print("  Total / month @ %d referrals  : $%.2f"
              % (VOLUME_PER_MONTH, mc["total_monthly"]))
        print("  Avg cost / referral             : $%.6f"
              % (mc["cost_per_case_average"] or float("nan")))
        print()

        cost_rows_csv.append({
            "model_label": m["label"],
            "trials": m["trials"],
            "success_rate_pct": (None if m["pass_rate"] is None
                                 else 100.0 * m["pass_rate"]),
            "median_turns": m["median_turns"],
            "tokens_in_per_case": round(m["tokens_in_per_case"]),
            "tokens_out_per_case": round(m["tokens_out_per_case"]),
            "L1_token_cost_per_case_usd": l1,
            "L2_failure_cost_per_case_usd": l2,
            "L3_fixed_monthly_usd": mc["L3_fixed_monthly"],
            "total_variable_per_case_usd": mc["variable_per_case"],
            "total_monthly_usd": mc["total_monthly"],
            "avg_cost_per_case_usd": mc["cost_per_case_average"],
            "failure_cost_per_bad_booking_usd": FAILURE_COST_B,
            "monthly_volume": VOLUME_PER_MONTH,
        })

        sens = sensitivity(m)
        if sens:
            print("  Sensitivity  success ±10 pp (2 pp steps):")
            print("    %8s  %8s  %12s  %14s  %16s" %
                  ("Δpp", "p_success", "L2 $/case", "total $/mo", "avg $/case"))
            for r in sens:
                print("    %+7d   %6.2f%%   %10.4f   %14.2f   %16.6f" % (
                    r["delta_pp"], 100.0 * r["success_rate"],
                    r["L2_per_case"], r["total_monthly"],
                    r["avg_cost_per_case"]))
            print()
            sens_rows_csv.extend(sens)

        mv = monthly_volume_table(m)
        print("  Monthly volume curve:")
        print("    %8s  %12s  %14s" % ("volume", "total $/mo", "avg $/case"))
        for row in mv:
            print("    %7d   $%11.2f   $%14.6f" % (
                row["monthly_volume"],
                row["total_monthly"],
                row["avg_cost_per_case"] or float("nan")))
        print()
        monthly_rows_csv.extend(mv)

        m_out = dict(m); m_out["layer_breakdown"] = {
            "L1_per_case": l1,
            "L2_per_case": l2,
            "L3_fixed_monthly": mc["L3_fixed_monthly"],
        }
        m_out["monthly_totals"] = mc
        m_out["sensitivity"] = sens
        m_out["monthly_volume_table"] = mv
        rows_out.append(m_out)

    be = None
    be_row_csv = None
    if len(demo_metrics) >= 2:
        print("=" * 68)
        print("Break-even analysis between the first two models:")
        print("=" * 68)
        be = break_even_success_rate(demo_metrics[0], demo_metrics[1],
                                    volume=VOLUME_PER_MONTH,
                                    fixed=MONTHLY_FIXED_DOLLARS)
        for k, v in be.items():
            if k == "interpretation":
                print()
                print("  ", v)
            else:
                if isinstance(v, float):
                    print("  %-48s: %.6f" % (k, v))
                else:
                    print("  %-48s: %r" % (k, v))
        print()
        be_row_csv = be

    out_path = os.path.join(OUT_DIR, "cost_model.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "config": {
                "price_in_per_million": config.PRICE_IN,
                "price_out_per_million": config.PRICE_OUT,
                "failure_cost_per_bad_booking_usd": FAILURE_COST_B,
                "monthly_fixed_usd": MONTHLY_FIXED_DOLLARS,
                "volume_per_month": VOLUME_PER_MONTH,
            },
            "models": rows_out,
            "break_even": be,
        }, fh, indent=2, default=str)
    print("wrote", out_path)

    csv_cost = os.path.join(OUT_DIR, "cost_model.csv")
    _write_csv(csv_cost, cost_rows_csv, list(cost_rows_csv[0].keys()))
    print("wrote", csv_cost)

    if sens_rows_csv:
        csv_sens = os.path.join(OUT_DIR, "cost_sensitivity.csv")
        _write_csv(csv_sens, sens_rows_csv, list(sens_rows_csv[0].keys()))
        print("wrote", csv_sens)

    if monthly_rows_csv:
        csv_mv = os.path.join(OUT_DIR, "cost_monthly_volume.csv")
        _write_csv(csv_mv, monthly_rows_csv, list(monthly_rows_csv[0].keys()))
        print("wrote", csv_mv)

    if be_row_csv:
        csv_be = os.path.join(OUT_DIR, "cost_break_even.csv")
        with open(csv_be, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            for k, v in be_row_csv.items():
                w.writerow([k, v])
        print("wrote", csv_be)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
