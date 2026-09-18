"""
PE6201 · A2 scaffold — THE AGENT LOOP  (D1)
====================================================================
    thought -> action -> observation -> repeat -> final

That is the whole of ReAct, and it is hand-rolled here on purpose. No
framework owns your loop: when it misbehaves you need to be able to
read the twelve lines that did it.

WHAT MAKES THIS AN AGENT RATHER THAN A WORKFLOW: the number of steps is
decided by the DATA, not by you. A one-line claim with a live policy is
a short run. A four-line claim with a pre-authorisation to chase is a
long one. You did not write that branch - the record did.

--------------------------------------------------------------------
INSTRUMENTATION IS NOT OPTIONAL

Every run records turns, tokens, cost, every tool call and every
guardrail event. D6's cost model and D7's loop failure both need
numbers that were captured WHILE THE RUN HAPPENED. A team that adds
instrumentation afterwards has to run the whole battery again.

You cannot report a failure you had no way of noticing.
====================================================================
"""
import time

import config
import prompt
import tools
from backends import make_backend
from guardrails import Guardrails, GuardrailStop


def run_case(case_id, problem=None, approve=None, verbose=False):
    """Run ONE case from a clean state and return the decision record.

    ISOLATION (D4): everything this function needs is created inside it.
    No case may depend on a previous one having run - so no module-level
    counters, no shared guardrail object, no leftover transcript.
    """
    problem = problem or config.PROBLEM
    call_mode = config.CALL_MODE
    parallel_tools = call_mode == "parallel"
    started = time.time()

    guards = Guardrails(config.MAX_TURNS, config.MAX_TOKENS_PER_RUN,
                        config.AUTONOMY)
    # WHAT THE MODEL IS TOLD. On the scripted backend these are ignored -
    # the moves are pre-written, so no prompt is ever sent. On the live
    # backend this IS the experiment D2(b) measures: the descriptors and
    # the routing rules, assembled by prompt.build_system_prompt().
    #     python3 run_eval.py --prompt      to see the exact text
    descriptor_table = tools.DESCRIPTOR_SETS[config.DESCRIPTOR_VERSION]
    backend = make_backend(
        case_id,
        tool_descriptors=[descriptor_table[n] for n in tools.REGISTRY[problem]
                          if n in descriptor_table],
        system_prompt=prompt.build_system_prompt(
            problem, config.DESCRIPTOR_VERSION))

    transcript = []      # what the model would see
    evidence = []        # every tool actually called, in order

    #---------------新增（保存调用参数以及返回||专门保存异常，不和正常tooltrace搞混---------------
    tool_trace = []  # full evidence for every tool call
    errors = []

    # TURNS ARE TOOL-CALLING TURNS. The concluding move - where the agent
    # writes its decision record - is bookkeeping, not a turn. This is the
    # same convention Appendix A uses: CLM-8842 is "turns": 4 with EIGHT
    # tool calls, because the gated action is a turn like any other and
    # the write-up afterwards is not. Count them any other way and your
    # D2(c) arithmetic stops agreeing with the brief.
    turns = 0
    iterations = 0       # loop-safety only; never reported
    tokens_in = tokens_out = 0
    stopped_by = None

    # On the scripted backend the gate auto-approves so the run stays
    # deterministic. The RECORD still shows the gate was reached and
    # passed, which is what a marker looks for.
    if approve is None:
        approve = lambda action, payload: True

    try:
        while True:
            iterations += 1
            if iterations > config.MAX_TURNS + 2:
                raise GuardrailStop("step_cap", "loop did not terminate")

            move = backend.next_move(transcript)
            ti, to = backend.token_estimate(transcript)
            tokens_in, tokens_out = tokens_in + ti, tokens_out + to
            guards.check_budget(tokens_in + tokens_out)

            if verbose:
                label = ("conclude" if "final" in move else "turn %d" % (turns + 1))
                print("  %-9s | %s" % (label, move.get("thought", "")[:88]))

            # ---- conclude +记录JSON parse error-------------------------------------------
            if "final" in move:
                record = dict(move["final"])

                if record.get("reason") == "model did not return parseable JSON":
                    errors.append({
                        "after_turn": turns,
                        "type": "json_parse_error",
                        "detail": move.get("thought", "")
                    })

                break
            # ---- act: one turn may carry SEVERAL calls ---------------
            turns += 1
            guards.check_turns(turns)

            # Only calls INDEPENDENT of each other belong in one turn.
            # A dependency chain cannot be shortened by running things at
            # once - that is why Problem B saves less than Problem A.

            #从python直接报错，变成程序记录正常结束留下证据-----------
            if move.get("calls"):
                raw_calls = move["calls"]

            elif "tool" in move and "args" in move:
                raw_calls = [(move["tool"], move["args"])]

            else:
                errors.append({
                    "after_turn": turns,
                    "type": "invalid_model_move",
                    "detail": "missing calls or tool/args",
                    "move": move
                })

                record = {
                    "decision": "escalate",
                    "reason": "invalid model move: missing calls or tool/args"
                }
                stopped_by = "invalid_model_move"
                break

            # In parallel mode every independent call returned by the model
            # shares one tool-calling turn. In sequential mode the same calls
            # are executed one per turn. The prompt asks the live model to
            # follow the selected mode; this split is a deterministic safety
            # net and also makes scripted comparisons use the same loop.
            call_groups = [raw_calls] if parallel_tools else [
                [call] for call in raw_calls
            ]

            broken = False
            for group_index, calls in enumerate(call_groups):
                if group_index > 0:
                    turns += 1
                    guards.check_turns(turns)
                    if verbose:
                        print("  turn %-4d | (sequential continuation)" % turns)

                observations = []

                for name, args in calls:
                    guards.check_duplicate(name, args)

                    if name == tools.GATED_ACTION.get(problem):
                        if not guards.gate(name, args, approve):
                            raise GuardrailStop(
                                "gate_held",
                                "%s awaits human approval (autonomy=%s)"
                                % (name, config.AUTONOMY))

                    try:
                        result = tools.call(problem, name, args)
                    except Exception as exc:
                        # Tool/interface failures are part of the run evidence,
                        # not reasons for the evaluator itself to crash. Keep
                        # the stop loud and machine-readable for D7.
                        evidence.append(name)
                        error = {
                            "turn": turns,
                            "type": "tool_error",
                            "tool": name,
                            "args": args,
                            "exception": type(exc).__name__,
                            "detail": str(exc),
                        }
                        errors.append(error)
                        tool_trace.append({
                            "turn": turns,
                            "tool": name,
                            "args": args,
                            "observation": None,
                            "error": error,
                        })
                        record = {
                            "decision": "escalate",
                            "reason": "tool unavailable or invalid: %s" % name,
                        }
                        stopped_by = "tool_error"
                        broken = True
                        if verbose:
                            print("       %-26s -> ERROR %s: %s" % (
                                name, type(exc).__name__, str(exc)))
                        break

                    evidence.append(name)

                    tool_trace.append({
                        "turn": turns,
                        "tool": name,
                        "args": args,
                        "observation": result,
                    })

                    if verbose:
                        print("       %-26s -> %s" % (name, _short(result)))

                    if result is None:
                        errors.append({
                            "turn": turns,
                            "type": "tool_returned_none",
                            "tool": name,
                            "args": args,
                            "detail": "broken case or missing reference data"
                        })

                        record = {
                            "decision": "escalate",
                            "reason": "broken case: %s returned None" % name
                        }
                        stopped_by = "broken_case"
                        broken = True
                        break

                    observations.append({
                        "tool": name,
                        "args": args,
                        "observation": result
                    })

                if broken:
                    break

                transcript.append({
                    "role": "assistant",
                    "content": (move.get("thought", "") if group_index == 0
                                else "(sequential continuation)")
                })

                transcript.append({
                    "role": "user",
                    "content": repr(observations)
                })

            if broken or stopped_by == "broken_case":
                break

    except GuardrailStop as stop:
        # A LOUD STOP. The record says what halted the run and where, so
        # this never looks like a quiet wrong answer.
        stopped_by = stop.reason

        errors.append({
            "turn": turns,
            "type": "guardrail_stop",
            "reason": stop.reason,
            "detail": stop.detail
        })

        record = {"decision": "escalate",
                  "reason": "halted by the %s guardrail - %s"
                            % (stop.reason, stop.detail)}

    cost = (tokens_in / 1e6) * config.PRICE_IN + (tokens_out / 1e6) * config.PRICE_OUT

    record.update({
        "case_id": case_id,
        "evidence": evidence,
        #---------把tool trace和errors放进最终结果----------
        "tool_trace": tool_trace,
        "errors": errors,
        "turns": turns,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "seconds": round(time.time() - started, 3),
        "guardrails_fired": guards.fired,
        "stopped_by": stopped_by,
        "backend": backend.name,
        "descriptor_version": config.DESCRIPTOR_VERSION,
        "call_mode": call_mode,
    })
    return record


def _short(value, n=64):
    s = repr(value)
    return s if len(s) <= n else s[:n - 1] + "…"
