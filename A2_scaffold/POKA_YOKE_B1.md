# Problem B Poka-Yoke designs

These checks make invalid tool calls fail before the agent can act on an
incorrect result. They supplement the descriptors; they do not change the
routing rules or the irreversible action.

## 1. Referral-specialty consistency

`check_referral_criteria(specialty, referral_id)` now enforces both invariants:

- `specialty` must be one of the codes in `data_B/specialties.json`.
- It must equal the specialty stored on the selected referral.

Previously, a typo could look like a missing specialty and a different valid
specialty could run the referral through the wrong department protocol. Both
mistakes now raise a clear `TypeError` or `ValueError`.

## 2. Closed slot-query contract

`get_clinic_slots(specialty, band, **window)` now enforces:

- recognised specialty and urgency-band values;
- exactly the `from` and `to` window fields;
- string dates in valid `YYYY-MM-DD` form; and
- `from <= to`.

Previously, a missing boundary silently became `0000-00-00` or `9999-99-99`,
which could widen the legal booking window without the caller noticing. The
tool now rejects missing, extra, malformed, or reversed window values before
reading any slot data.

## Verification

Run from `A2_scaffold/`:

```bash
python -m unittest -v test_poka_yoke.py
python run_eval.py
```

The unit tests cover valid calls plus unknown/mismatched specialties, missing
windows, invented bands, malformed dates, and reversed windows. The scripted
regression confirms that the existing REF-5602 booking flow still passes.
