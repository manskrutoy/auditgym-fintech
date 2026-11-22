"""Shared matcher: findings schema, normalisation, tolerances, one-to-one matching.

Published as required by section 05 of the challenge.  The matcher depends only
on structured fields; `explanation` is length-checked but never scored.

Normalisation
  * type: exact string from ISSUE_TYPES (case-sensitive).
  * affected_ids / evidence_ids: each id is stripped of surrounding whitespace;
    order and repeats are ignored (compared as sets).
  * currency: stripped and upper-cased; must equal the truth currency exactly.
  * amount: integer minor units; |claimed - expected| <= amount_tolerance_minor
    (1 minor unit for fx_misconversion because of rounding, 0 otherwise).
A finding can match a truth issue ("compatible pair") only if type, the canonical
affected-id set, currency and amount all agree AND its evidence ids contain at
least one complete admissible evidence set.  Extra evidence is allowed (<= 10).

Ambiguity
  Each truth issue is matched to at most one finding and vice versa.  We compute a
  maximum-cardinality bipartite matching over compatible pairs (augmenting paths),
  visiting findings in submission order and truth issues in issue_id order, so the
  result is deterministic and maximal.  Because all compatible pairs are equally
  correct, maximising the number of matches is the only objective.  Unmatched and
  repeated findings are false positives; unmatched truth issues are false negatives.
"""

from .constants import (
    ISSUE_TYPES, MAX_AFFECTED, MAX_EVIDENCE, MAX_EXPLANATION, MAX_FINDINGS, MAX_ID_LEN,
)

FINDING_KEYS = {"type", "affected_ids", "claimed_amount_minor", "currency", "evidence_ids", "explanation"}
SUBMISSION_KEYS = {"episode_id", "findings"}


class SchemaError(ValueError):
    pass


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _id_list(v, name, max_len, allow_empty):
    if not isinstance(v, list):
        raise SchemaError("%s must be a list" % name)
    if len(v) > max_len:
        raise SchemaError("%s has more than %d entries" % (name, max_len))
    if not v and not allow_empty:
        raise SchemaError("%s must not be empty" % name)
    out = []
    for x in v:
        if not isinstance(x, str):
            raise SchemaError("%s entries must be strings" % name)
        s = x.strip()
        if not s or len(s) > MAX_ID_LEN:
            raise SchemaError("%s entry has invalid length" % name)
        out.append(s)
    return out


def validate_submission(sub, episode_id):
    """Return the normalised findings list or raise SchemaError."""
    if not isinstance(sub, dict):
        raise SchemaError("submission must be an object")
    if set(sub) != SUBMISSION_KEYS:
        raise SchemaError("submission keys must be exactly %s" % sorted(SUBMISSION_KEYS))
    if sub["episode_id"] != episode_id:
        raise SchemaError("episode_id does not match the current episode")
    fs = sub["findings"]
    if not isinstance(fs, list):
        raise SchemaError("findings must be a list")
    if len(fs) > MAX_FINDINGS:
        raise SchemaError("more than %d findings" % MAX_FINDINGS)
    out = []
    for i, f in enumerate(fs):
        if not isinstance(f, dict):
            raise SchemaError("finding %d must be an object" % i)
        if set(f) != FINDING_KEYS:
            raise SchemaError("finding %d keys must be exactly %s" % (i, sorted(FINDING_KEYS)))
        if f["type"] not in ISSUE_TYPES:
            raise SchemaError("finding %d has unknown type" % i)
        aff = _id_list(f["affected_ids"], "affected_ids", MAX_AFFECTED, False)
        evi = _id_list(f["evidence_ids"], "evidence_ids", MAX_EVIDENCE, True)
        amt = f["claimed_amount_minor"]
        if not _is_int(amt) or amt < 0 or amt > 10 ** 15:
            raise SchemaError("finding %d claimed_amount_minor must be a non-negative integer" % i)
        cur = f["currency"]
        if not isinstance(cur, str) or len(cur.strip()) != 3 or not cur.strip().isalpha():
            raise SchemaError("finding %d currency must be a 3-letter code" % i)
        exp = f["explanation"]
        if not isinstance(exp, str) or len(exp) > MAX_EXPLANATION:
            raise SchemaError("finding %d explanation must be a string of <= %d chars" % (i, MAX_EXPLANATION))
        out.append({
            "type": f["type"],
            "affected": frozenset(aff),
            "amount": amt,
            "currency": cur.strip().upper(),
            "evidence": frozenset(evi),
        })
    return out


def compatible(finding, issue) -> bool:
    if finding["type"] != issue["type"]:
        return False
    if finding["affected"] != frozenset(issue["affected_ids"]):
        return False
    if finding["currency"] != issue["currency"]:
        return False
    if abs(finding["amount"] - issue["expected_amount_minor"]) > issue.get("amount_tolerance_minor", 0):
        return False
    return any(set(s) <= finding["evidence"] for s in issue["evidence_sets"])


def match(findings, issues):
    """Maximum one-to-one matching. Returns (pairs, unmatched_finding_idx, unmatched_issue_idx)."""
    issues_order = sorted(range(len(issues)), key=lambda j: issues[j].get("issue_id", ""))
    adj = [[j for j in issues_order if compatible(f, issues[j])] for f in findings]
    owner = {}                                   # issue index -> finding index

    def augment(i, seen):
        for j in adj[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(findings)):
        augment(i, set())
    pairs = sorted((i, j) for j, i in owner.items())
    matched_f = {i for i, _ in pairs}
    matched_t = {j for _, j in pairs}
    return (pairs,
            [i for i in range(len(findings)) if i not in matched_f],
            [j for j in range(len(issues)) if j not in matched_t])
