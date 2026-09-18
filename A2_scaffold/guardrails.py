"""
PE6201 · A2 scaffold — THE GUARDRAIL LAYER  (D3a)
====================================================================
Seven controls, and NONE of them depend on the model behaving well.

    1. STEP CAP            stop after N turns
    2. BUDGET CEILING      stop after N tokens
    3. ACTION DE-DUPLICATION   stop repeating an action already taken
    4. AUTONOMY GATE       hold the irreversible step for a human
    5. TOOL ALLOWLIST      reject tools outside the problem registry
    6. STRICT ARGUMENTS    reject malformed calls before execution
    7. UNTRUSTED OUTPUT    stop instructions embedded in tool data

A model cannot influence whether these fire, which is why D3(b)'s ten
guardrail cases run on the SCRIPTED backend. They test your code.

MAKE THE STOP LOUD. A cap that silently returns an empty answer is
worse than the loop it prevented: it turns a visible cost problem into
an invisible correctness problem. Every stop below records WHY.
====================================================================
"""
import json


class GuardrailStop(Exception):
    """Raised when the code layer halts a run. Carries the reason so the
    decision record can say what stopped it and at which turn."""

    def __init__(self, reason, detail="", blocked_action=None):
        self.reason = reason
        self.detail = detail
        self.blocked_action = blocked_action
        super().__init__("%s: %s" % (reason, detail) if detail else reason)


class Guardrails:
    """One instance per run. Never share one between cases - a shared
    instance leaks state and D4 requires every case to start clean."""

    def __init__(self, max_turns, max_tokens, autonomy):
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if autonomy not in ("suggest", "confirm", "act"):
            raise ValueError(
                "autonomy must be 'suggest', 'confirm' or 'act', not %r"
                % autonomy)
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.autonomy = autonomy
        self.seen_actions = set()     # for de-duplication
        self.fired = []               # every guardrail event, for the record

    # ---- 1 · step cap -----------------------------------------------
    def check_turns(self, turn):
        if turn > self.max_turns:
            self._fire("step_cap", "reached %d turns" % self.max_turns)
            raise GuardrailStop("step_cap",
                                "hit the %d-turn cap without a conclusion"
                                % self.max_turns)

    # ---- 2 · budget ceiling -----------------------------------------
    def check_budget(self, tokens_so_far):
        if tokens_so_far > self.max_tokens:
            self._fire("budget_ceiling", "%d tokens" % tokens_so_far)
            raise GuardrailStop("budget_ceiling",
                                "spent %d tokens, ceiling is %d"
                                % (tokens_so_far, self.max_tokens))

    # ---- 3 · action de-duplication ----------------------------------
    def check_duplicate(self, tool, args):
        """A loop has no memory of its own actions unless you give it one.

        This IS that memory. Class 4's loop failure was exactly this
        guard deleted: 8 turns, no answer, 1.6x the cost, and NO
        exception raised. It did not crash. It burned money in a circle.
        """
        # Booking is idempotent by referral, not by the full payload.
        # A changed clinic/date/time must not create a second appointment.
        if tool == "book_slot" and isinstance(args, dict):
            signature = (tool, args.get("referral_id"))
            stop_reason = "idempotency_block"
            detail = "%s already attempted for referral %r" % (
                tool, args.get("referral_id"))
        else:
            canonical_args = json.dumps(
                args, sort_keys=True, separators=(",", ":"), default=repr)
            signature = (tool, canonical_args)
            stop_reason = "duplicate_action"
            detail = "%s called again with identical arguments" % tool
        if signature in self.seen_actions:
            self.halt(stop_reason, detail, blocked_action=tool)
        self.seen_actions.add(signature)

    # ---- 5 · tool allowlist ----------------------------------------
    def check_tool_allowed(self, tool, allowed_tools):
        if tool not in allowed_tools:
            self.halt(
                "unauthorized_tool",
                "%r is not in the allowlist: %s"
                % (tool, ", ".join(sorted(allowed_tools))),
                blocked_action=tool,
            )

    # ---- 6 · strict arguments --------------------------------------
    def invalid_arguments(self, tool, detail):
        self.halt("invalid_arguments", "%s: %s" % (tool, detail),
                  blocked_action=tool)

    # ---- 7 · untrusted tool output ---------------------------------
    def untrusted_output(self, tool, marker, blocked_action=None):
        self.halt(
            "prompt_injection",
            "%s returned instruction-like untrusted text (%s)"
            % (tool, marker),
            blocked_action=blocked_action or tool,
        )

    # ---- 4 · autonomy gate ------------------------------------------
    def gate(self, action_name, payload, approve=None):
        """Called ONLY in front of the irreversible step.

        Note where this sits: in front of the ACTION, not in front of the
        agent. An agent gated as a whole is not an agent, it is a form.

        `approve` is a callable the harness supplies. On the scripted
        backend it auto-approves so the run is deterministic - and the
        record still shows the gate was passed, which is what a marker
        checks for.
        """
        if self.autonomy == "act":
            self._fire("gate_passed", "%s (autonomy=act)" % action_name)
            return True
        if self.autonomy == "suggest":
            self._fire("gate_held", "%s (autonomy=suggest)" % action_name)
            return False
        # confirm
        ok = bool(approve and approve(action_name, payload))
        self._fire("gate_%s" % ("passed" if ok else "held"),
                   "%s (autonomy=confirm)" % action_name)
        return ok

    # ---- bookkeeping ------------------------------------------------
    def _fire(self, kind, detail):
        self.fired.append({"guardrail": kind, "detail": detail})

    def halt(self, reason, detail, blocked_action=None):
        """Record and raise one structured, fail-closed stop."""
        self._fire(reason, detail)
        raise GuardrailStop(reason, detail, blocked_action=blocked_action)
