"""
PE6201 · A2 scaffold — THE AGENT LOOP · SEQUENTIAL VERSION  (D1)
====================================================================
    thought -> action (ONE TOOL) -> observation -> repeat -> final

SEQUENTIAL MODE: Each turn executes EXACTLY ONE tool call.
Even if the backend returns multiple calls in one move, they are split
into separate turns, one per call.

This is the serial version for comparison against the parallel version.
====================================================================
"""
import time

import config
import prompt_sequential as prompt
import tools
from backends import make_backend
from guardrails import Guardrails, GuardrailStop


def run_case(case_id, problem=None, approve=None, verbose=False):
    problem = problem or config.PROBLEM
    started = time.time()

    guards = Guardrails(config.MAX_TURNS * 2, config.MAX_TOKENS_PER_RUN,
                        config.AUTONOMY)
    descriptor_table = tools.DESCRIPTOR_SETS[config.DESCRIPTOR_VERSION]
    backend = make_backend(
        case_id,
        tool_descriptors=[descriptor_table[n] for n in tools.REGISTRY[problem]
                          if n in descriptor_table],
        system_prompt=prompt.build_system_prompt(
            problem, config.DESCRIPTOR_VERSION))

    transcript = []
    evidence = []
    tool_trace = []
    errors = []

    turns = 0
    iterations = 0
    tokens_in = tokens_out = 0
    stopped_by = None

    if approve is None:
        approve = lambda action, payload: True

    pending_calls = []
    pending_thought = None

    try:
        while True:
            iterations += 1
            if iterations > (config.MAX_TURNS * 2) + 5:
                raise GuardrailStop("step_cap", "loop did not terminate")

            if not pending_calls:
                move = backend.next_move(transcript)
                ti, to = backend.token_estimate(transcript)
                tokens_in, tokens_out = tokens_in + ti, tokens_out + to
                guards.check_budget(tokens_in + tokens_out)

                if verbose:
                    label = ("conclude" if "final" in move else "move %d" % (turns + 1))
                    print("  %-9s · %s" % (label, move.get("thought", "")[:88]))

                if "final" in move:
                    record = dict(move["final"])

                    if record.get("reason") == "model did not return parseable JSON":
                        errors.append({
                            "after_turn": turns,
                            "type": "json_parse_error",
                            "detail": move.get("thought", "")
                        })

                    break

                if move.get("calls"):
                    pending_calls = list(move["calls"])
                elif "tool" in move and "args" in move:
                    pending_calls = [(move["tool"], move["args"])]
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

                pending_thought = move.get("thought", "")

                if len(pending_calls) > 1 and verbose:
                    print("    [sequential] splitting %d calls into individual turns"
                          % len(pending_calls))

            name, args = pending_calls.pop(0)
            turns += 1
            guards.check_turns(turns)

            guards.check_duplicate(name, args)

            if name == tools.GATED_ACTION.get(problem):
                if not guards.gate(name, args, approve):
                    raise GuardrailStop(
                        "gate_held",
                        "%s awaits human approval (autonomy=%s)"
                        % (name, config.AUTONOMY))

            result = tools.call(problem, name, args)

            evidence.append(name)

            tool_trace.append({
                "turn": turns,
                "tool": name,
                "args": args,
                "observation": result,
            })

            if verbose:
                print("       turn %-3d %-22s -> %s"
                      % (turns, name, _short(result)))

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
                break

            single_observation = [{
                "tool": name,
                "args": args,
                "observation": result
            }]

            transcript.append({
                "role": "assistant",
                "content": pending_thought if pending_thought is not None else ""
            })

            transcript.append({
                "role": "user",
                "content": repr(single_observation)
            })

            pending_thought = None

    except GuardrailStop as stop:
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
        "execution_mode": "sequential",
    })
    return record


def _short(value, n=64):
    s = repr(value)
    return s if len(s) <= n else s[:n - 1] + "…"
