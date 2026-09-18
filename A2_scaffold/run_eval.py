#!/usr/bin/env python3
"""Main PE6201 A2 evaluation runner.

Edit config.py and run ``python run_eval.py``. Results are separated by
experimental purpose under ``results/``:

* one complete result file per live model;
* one scripted D4/D5(a) baseline file;
* dedicated D2(b), D2(c), D3, D5, D6 and D7 evidence files.
"""
from datetime import datetime, timezone
import glob
import json
import os
import re
import sys

import config
import prompt
from backends import SCRIPTS
from harness import load_cases, load_key, report, run_set


HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
LEGACY_RESULTS_PATH = os.path.join(HERE, "results.json")
EXPECTED_LIVE_MODELS = 6
os.makedirs(RESULTS_DIR, exist_ok=True)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value):
    """Stable filesystem-safe model label, including provider when present."""
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").lower()
    return value or "unnamed"


def _model_family(model):
    """Derive a stable family label from the configured model slug."""
    known = {
        "qwen/qwen3-30b-a3b-instruct-2507": "qwen3",
        "deepseek/deepseek-v4-flash-0731": "deepseek-v4",
        "mistralai/mistral-small-3.2-24b-instruct": "mistral-small-3",
        "anthropic/claude-haiku-4.5": "claude-haiku-4",
        "google/gemini-3.1-flash-lite": "gemini-3",
        "openai/gpt-5-mini": "gpt-5",
    }
    value = str(model or "").strip().lower()
    return known.get(value, value or "unknown")


def _price_metadata(metadata):
    """Keep only non-personal cost metadata in generated evidence."""
    metadata = metadata if isinstance(metadata, dict) else {}
    fields = (
        "price_tier", "price_in_per_million", "price_out_per_million",
        "last_updated_utc",
    )
    return {field: metadata.get(field) for field in fields
            if metadata.get(field) is not None}


def _strip_person_metadata(model_file):
    """Remove legacy grader-name fields while preserving verdict evidence."""
    for version in model_file.get("descriptor_versions", {}).values():
        for run in version.get("runs", {}).values():
            for item in run.get("judgement_queue", []):
                item.pop("graded_by", None)
            summary = run.get("judgement_summary")
            if isinstance(summary, dict):
                summary.pop("graded_by", None)
    return model_file


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def _model_identity():
    return {
        "backend": config.BACKEND,
        "model": config.MODEL if config.BACKEND == "live" else "scripted",
        "problem": config.PROBLEM,
    }


def _model_results_path(identity=None):
    identity = identity or _model_identity()
    if identity.get("backend") == "scripted":
        name = "d4_d5a_scripted_results.json"
    else:
        name = "results_%s.json" % _safe_name(identity.get("model"))
    return os.path.join(RESULTS_DIR, name)


def _new_model_file(identity=None):
    return {
        "schema_version": "model-results-1.0",
        "file_purpose": "complete evaluation evidence for one model",
        "identity": identity or _model_identity(),
        "generated_at_utc": _now(),
        "run_metadata": {},
        "descriptor_versions": {},
    }


def _load_model_file(path=None, identity=None):
    path = path or _model_results_path(identity)
    data = _read_json(path)
    if (isinstance(data, dict)
            and data.get("schema_version") == "model-results-1.0"
            and isinstance(data.get("descriptor_versions"), dict)):
        data["run_metadata"] = _price_metadata(data.get("run_metadata"))
        return _strip_person_metadata(data)
    return _new_model_file(identity)


def _prompt_metrics(version=None):
    version = version or config.DESCRIPTOR_VERSION
    text = prompt.build_system_prompt(config.PROBLEM, version)
    return {
        "characters": len(text),
        "rough_tokens_chars_div_4": len(text) // 4,
        "note": "Static estimate only; live usage fields are measured.",
    }


def _enrich_summary(summary, results):
    enriched = dict(summary)
    enriched.update({
        "call_mode": config.CALL_MODE,
        "tokens_in": sum(r["record"].get("tokens_in", 0) for r in results),
        "tokens_out": sum(r["record"].get("tokens_out", 0) for r in results),
        "seconds": round(sum(
            r["record"].get("seconds", 0) for r in results), 3),
        "step_cap_hits": sum(
            r["record"].get("stopped_by") == "step_cap" for r in results),
        "token_source": (
            "measured_api_usage" if config.BACKEND == "live"
            else "scripted_estimate_not_for_live_cost_claims"),
    })
    return enriched


def _metric_delta(left, right, name):
    a, b = left.get(name), right.get(name)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(b - a, 12)
    return None


def _summary_projection(summary):
    fields = (
        "cases", "trials", "passed", "pass_rate", "ordinary_trials",
        "ordinary_passed", "ordinary_pass_rate", "negative_cases",
        "negative_trials", "negative_passed", "negative_pass_rate",
        "median_turns", "worst_case_turns", "tokens_in", "tokens_out",
        "cost_usd", "seconds", "step_cap_hits", "token_source",
        "economics", "step_reliability",
    )
    return {field: summary.get(field) for field in fields}


def _d2c_comparison(model_file, version):
    entry = model_file.get("descriptor_versions", {}).get(version, {})
    runs = entry.get("runs", {})
    if not {"sequential", "parallel"}.issubset(runs):
        return None
    sequential = runs["sequential"]["summary"]
    parallel = runs["parallel"]["summary"]
    metrics = (
        "trials", "passed", "pass_rate", "negative_pass_rate",
        "median_turns", "worst_case_turns", "tokens_in", "tokens_out",
        "cost_usd", "seconds", "step_cap_hits",
    )
    return {
        "schema_version": "experiment-result-1.0",
        "experiment": "D2(c) sequential versus parallel tool calling",
        "generated_at_utc": _now(),
        "identity": model_file["identity"],
        "descriptor_version": version,
        "controlled_variables": {
            "same_model": True,
            "same_evaluation_set": True,
            "same_prompt_and_descriptor": True,
            "only_changed_variable": "call_mode",
        },
        "sequential": _summary_projection(sequential),
        "parallel": _summary_projection(parallel),
        "delta_parallel_minus_sequential": {
            metric: _metric_delta(sequential, parallel, metric)
            for metric in metrics
        },
        "correctness_changed": (
            sequential.get("pass_rate") != parallel.get("pass_rate")),
        "negative_correctness_changed": (
            sequential.get("negative_pass_rate")
            != parallel.get("negative_pass_rate")),
        "source_result_file": os.path.basename(
            _model_results_path(model_file["identity"])),
    }


def _d2b_comparison(model_file):
    versions = model_file.get("descriptor_versions", {})
    if not {"v1", "v2"}.issubset(versions):
        return None
    common_modes = sorted(
        set(versions["v1"].get("runs", {}))
        & set(versions["v2"].get("runs", {})))
    comparisons = []
    metrics = (
        "passed", "pass_rate", "negative_pass_rate", "median_turns",
        "tokens_in", "tokens_out", "cost_usd", "seconds",
    )
    for mode in common_modes:
        v1 = versions["v1"]["runs"][mode]["summary"]
        v2 = versions["v2"]["runs"][mode]["summary"]
        comparisons.append({
            "call_mode": mode,
            "v1": _summary_projection(v1),
            "v2": _summary_projection(v2),
            "delta_v2_minus_v1": {
                metric: _metric_delta(v1, v2, metric)
                for metric in metrics
            },
            "correctness_changed": (
                v1.get("pass_rate") != v2.get("pass_rate")),
        })
    if not comparisons:
        return None
    return {
        "schema_version": "experiment-result-1.0",
        "experiment": "D2(b) descriptor v1 versus v2",
        "generated_at_utc": _now(),
        "identity": model_file["identity"],
        "controlled_variables": {
            "same_model": True,
            "same_evaluation_set": True,
            "same_call_mode_within_each_comparison": True,
            "only_changed_variable": "descriptor_version",
        },
        "comparisons": comparisons,
        "source_result_file": os.path.basename(
            _model_results_path(model_file["identity"])),
    }


def _d6_cost_analysis(model_file):
    rows = []
    for version, entry in sorted(
            model_file.get("descriptor_versions", {}).items()):
        for mode, run in sorted(entry.get("runs", {}).items()):
            summary = run.get("summary", {})
            rows.append({
                "descriptor_version": version,
                "call_mode": mode,
                "trials": summary.get("trials"),
                "pass_rate": summary.get("pass_rate"),
                "negative_pass_rate": summary.get("negative_pass_rate"),
                "tokens_in": summary.get("tokens_in"),
                "tokens_out": summary.get("tokens_out"),
                "token_source": summary.get("token_source"),
                "economics": summary.get("economics"),
            })
    if not rows:
        return None
    return {
        "schema_version": "experiment-result-1.0",
        "experiment": "D6 economics, sensitivity and break-even",
        "generated_at_utc": _now(),
        "identity": model_file["identity"],
        "run_metadata": _price_metadata(model_file.get("run_metadata")),
        "runs": rows,
        "source_result_file": os.path.basename(
            _model_results_path(model_file["identity"])),
        "warning": (
            "Only rows labelled measured_api_usage may support live D6 claims."),
    }


def _refresh_model_experiment_files(model_file):
    identity = model_file["identity"]
    slug = _safe_name(identity.get("model"))
    for version in sorted(model_file.get("descriptor_versions", {})):
        comparison = _d2c_comparison(model_file, version)
        if comparison:
            path = os.path.join(
                RESULTS_DIR,
                "d2c_sequential_parallel_%s_%s.json" % (slug, version))
            _write_json(path, comparison)

    descriptor = _d2b_comparison(model_file)
    if descriptor:
        _write_json(os.path.join(
            RESULTS_DIR,
            "d2b_descriptor_comparison_%s.json" % slug), descriptor)

    cost = _d6_cost_analysis(model_file)
    if cost:
        _write_json(os.path.join(
            RESULTS_DIR, "d6_cost_analysis_%s.json" % slug), cost)


def _model_result_paths():
    paths = [os.path.join(RESULTS_DIR, "d4_d5a_scripted_results.json")]
    paths.extend(glob.glob(os.path.join(RESULTS_DIR, "results_*.json")))
    return [path for path in paths if os.path.exists(path)]


def _refresh_d5_model_battery():
    by_mode = {}
    v1_models = set()
    source_files = []
    for path in _model_result_paths():
        model_file = _read_json(path, {})
        identity = model_file.get("identity", {})
        if identity.get("backend") != "live":
            continue
        source_files.append(os.path.basename(path))
        versions = model_file.get("descriptor_versions", {})
        if versions.get("v1", {}).get("runs"):
            v1_models.add(identity.get("model"))
        metadata = _price_metadata(model_file.get("run_metadata", {}))
        for mode, run in versions.get("v2", {}).get("runs", {}).items():
            by_mode.setdefault(mode, []).append({
                "model": identity.get("model"),
                "model_family": _model_family(identity.get("model")),
                "price_tier": metadata.get("price_tier"),
                "price_in_per_million": metadata.get("price_in_per_million"),
                "price_out_per_million": metadata.get("price_out_per_million"),
                "summary": _summary_projection(run.get("summary", {})),
                "source_result_file": os.path.basename(path),
            })

    expected = EXPECTED_LIVE_MODELS
    comparisons = {}
    for mode, rows in by_mode.items():
        rows.sort(key=lambda row: str(row.get("model")))
        families = [row.get("model_family") for row in rows]
        tiers = [row.get("price_tier") for row in rows]
        comparisons[mode] = {
            "controlled_variables": (
                "same v2 prompt, cases and call mode; model only"),
            "models_recorded": len(rows),
            "checks": {
                "minimum_three_models": len(rows) >= 3,
                "expected_n_minus_one_models": len(rows) >= expected,
                "at_least_two_price_tiers": len(set(tiers)) >= 2,
                "no_duplicate_model_family": (
                    len(families) == len(set(families))),
                "separate_v1_pass_present": bool(v1_models),
            },
            "runs": rows,
        }

    output = {
        "schema_version": "experiment-result-1.0",
        "experiment": "D5(b) live model battery",
        "generated_at_utc": _now(),
        "expected_live_models": expected,
        "v1_models_recorded": sorted(v1_models),
        "comparisons_by_call_mode": comparisons,
        "source_result_files": sorted(source_files),
    }
    _write_json(os.path.join(
        RESULTS_DIR, "d5_model_battery_summary.json"), output)


def _refresh_all_derived_files():
    for path in _model_result_paths():
        model_file = _read_json(path)
        if isinstance(model_file, dict):
            _refresh_model_experiment_files(model_file)
    _refresh_d5_model_battery()


def _migrate_legacy_results():
    """Split the former unified results.json without deleting it here."""
    legacy = _read_json(LEGACY_RESULTS_PATH)
    if not isinstance(legacy, dict):
        return False
    if legacy.get("schema_version") != "3.0":
        return False

    for experiment in legacy.get("experiments", {}).values():
        identity = dict(experiment.get("identity", {}))
        version = identity.pop("descriptor_version", "v2")
        path = _model_results_path(identity)
        model_file = _load_model_file(path, identity)
        model_file["identity"] = identity
        model_file["run_metadata"] = _price_metadata(
            experiment.get("run_metadata", {}))
        model_file["descriptor_versions"][version] = {
            "prompt_metrics": experiment.get("prompt_metrics", {}),
            "runs": experiment.get("runs", {}),
        }
        model_file["generated_at_utc"] = _now()
        model_file["migrated_from"] = "../results.json schema 3.0"
        _write_json(path, model_file)

    if "guardrails" in legacy:
        _write_json(os.path.join(
            RESULTS_DIR, "d3_guardrail_results.json"), legacy["guardrails"])
    if "d7_failures" in legacy:
        _write_json(os.path.join(
            RESULTS_DIR, "d7_failure_results.json"), legacy["d7_failures"])
    descriptor = legacy.get("descriptor_experiment")
    if descriptor:
        name = (
            "d2b_descriptor_prompt_only.json"
            if descriptor.get("backend") == "prompt_only"
            else "d2b_descriptor_experiment_%s.json"
                 % _safe_name(descriptor.get("model")))
        _write_json(os.path.join(RESULTS_DIR, name), descriptor)
    _refresh_all_derived_files()
    return True


def _judge_current_mode():
    path = _model_results_path()
    model_file = _load_model_file(path)
    run = (model_file.get("descriptor_versions", {})
           .get(config.DESCRIPTOR_VERSION, {}).get("runs", {})
           .get(config.CALL_MODE))
    if not run:
        print("No matching model/version/mode run exists in %s."
              % os.path.basename(path))
        return 1
    queue = run.get("judgement_queue", [])
    if not queue:
        print("No judgement queue exists for the current run.")
        return 1

    passed = 0
    for index, item in enumerate(queue, 1):
        print("\n" + "=" * 68)
        print("JUDGEMENT %d/%d - %s" % (
            index, len(queue), config.CALL_MODE))
        print("Case:", item["case_id"])
        print("Decision:", item["decision"])
        print("Reason:\n" + item.get("reason", ""))
        checks = []
        for requirement in item.get("must_record", []):
            print("\nRequirement:\n ", requirement)
            while True:
                answer = input("Satisfied? [y/n]: ").strip().lower()
                if answer in ("y", "n"):
                    break
            checks.append({
                "requirement": requirement,
                "passed": answer == "y",
            })
        verdict = all(check["passed"] for check in checks)
        item["item_checks"] = checks
        item["verdict"] = "PASS" if verdict else "FAIL"
        item["review_method"] = "human"
        passed += int(verdict)

    run["judgement_summary"] = {
        "total": len(queue),
        "passed": passed,
        "failed": len(queue) - passed,
        "review_method": "human",
    }
    model_file["generated_at_utc"] = _now()
    _write_json(path, model_file)
    _refresh_all_derived_files()
    print("Judgement complete: %d/%d passed" % (passed, len(queue)))
    print("Updated", os.path.relpath(path, HERE))
    return 0


def main(argv):
    migrated = _migrate_legacy_results()
    if migrated:
        print("Migrated legacy results.json into purpose-specific files.")

    print()
    print(config.summary())
    print("data: %s" % config.data_root())
    args = [arg for arg in argv[1:] if not arg.startswith("-")]
    flags = {arg for arg in argv[1:] if arg.startswith("-")}

    if "--judge" in flags:
        return _judge_current_mode()
    if "--refresh" in flags:
        _refresh_all_derived_files()
        print("Refreshed D2/D5/D6 derived result files without model calls.")
        return 0
    if "--prompt" in flags:
        print()
        prompt.audit()
        return 0

    if args:
        case_id = args[0]
        print("\n" + "-" * 68)
        print("  %s - every turn (%s)" % (case_id, config.CALL_MODE))
        print("-" * 68)
        results, queue = run_set([case_id], verbose=True)
        if not results:
            return 1
        print("\n  DECISION RECORD")
        print(json.dumps(results[0]["record"], indent=2,
                         ensure_ascii=False, default=str))
        print("\n  CODE CHECK   %s"
              % ("PASS" if results[0]["passed"] else "FAIL"))
        for failure in results[0]["fails"]:
            print("      %s" % failure)
        print("\n  JUDGEMENT CHECK")
        if queue:
            for item in queue[0]["must_record"]:
                print("      [ ] %s" % item)
        else:
            print("      not in the representative judgement sample")
        return 0 if results[0]["passed"] else 1

    key = load_key()
    cases = [case for case in load_cases() if case in key]
    if config.BACKEND == "scripted":
        cases = [case for case in cases if case in SCRIPTS]
    if not cases:
        print("Nothing to run for Problem %s." % config.PROBLEM)
        return 1

    print("\nRunning %d cases in %s mode." % (len(cases), config.CALL_MODE))
    results, queue = run_set(cases)
    summary = _enrich_summary(report(results), results)

    path = _model_results_path()
    model_file = _load_model_file(path)
    model_file["identity"] = _model_identity()
    model_file["run_metadata"] = {
        "price_tier": config.PRICE_TIER,
        "price_in_per_million": config.PRICE_IN,
        "price_out_per_million": config.PRICE_OUT,
        "last_updated_utc": _now(),
    }
    version_entry = model_file["descriptor_versions"].setdefault(
        config.DESCRIPTOR_VERSION, {"prompt_metrics": {}, "runs": {}})
    version_entry["prompt_metrics"] = _prompt_metrics()
    version_entry["runs"][config.CALL_MODE] = {
        "config": config.summary(),
        "summary": summary,
        "results": results,
        "judgement_queue": queue,
    }
    model_file["generated_at_utc"] = _now()
    _write_json(path, model_file)
    _refresh_all_derived_files()

    relative = os.path.relpath(path, HERE)
    modes = sorted(version_entry["runs"])
    print("Wrote %s" % relative)
    print("Stored %s modes: %s" % (
        config.DESCRIPTOR_VERSION, ", ".join(modes)))

    d2c = _d2c_comparison(model_file, config.DESCRIPTOR_VERSION)
    if d2c:
        print("Updated the dedicated D2(c) comparison file.")
    if _d2b_comparison(model_file):
        print("Updated the dedicated D2(b) comparison file.")
    print("Updated D5 battery summary and D6 cost file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
