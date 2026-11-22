"""Shared matcher: findings schema, normalisation, tolerances, one-to-one matching.

Published as required by section 05 of the challenge.  The matcher depends only
on structured fields; `explanation` is length-checked but never scored.

Normalisation (jury conventions, genesis-exe.com/fintech-checks.html)
  * type: exact string; an unknown type is wrong content (false positive), not a structural error.
  * affected_ids / evidence_ids: exact strings (case-sensitive, NO trimming), compared as sets.
  * currency: exact string, no normalisation.
  * amount: JSON integer minor units; |claimed - expected| <= amount_tolerance_minor
    (published per type in policy.json: 1 for fx_misconversion because of rounding, 0 otherwise).
  * evidence: may contain extra ids, but every cited id must exist in the public records.
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


def _str_list(v, name, max_len=None):
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise SchemaError("%s must be a list of strings" % name)
    if max_len is not None and len(v) > max_len:
        raise SchemaError("%s has more than %d entries" % (name, max_len))
    return v


def validate_submission(sub, episode_id=None):
    """Return the normalised findings list or raise SchemaError (= structural error, reward -1).

    Conventions published by the jury (genesis-exe.com/fintech-checks.html):
      * limits first: <= 30 findings, <= 10 evidence ids, explanation <= 1000 code points;
      * structural errors (wrong JSON types, missing fields, limits) invalidate the whole submit;
      * wrong CONTENT (unknown type, wrong currency, wrong ids/amount) is just a false positive;
      * ids compared exactly (case-sensitive, no trimming); currency exact (no normalisation);
      * claimed_amount_minor must be a JSON integer (not bool/str/float).
    """
    if isinstance(sub, str):                     # accept findings.json passed as a JSON string
        try:
            import json
            sub = json.loads(sub)
        except ValueError:
            raise SchemaError("submission string is not valid JSON")
    if isinstance(sub, list):                    # bare findings list
        sub = {"findings": sub}
    if not isinstance(sub, dict) or "findings" not in sub:
        raise SchemaError("submission must be an object with 'findings'")
    if episode_id is not None and "episode_id" in sub and sub["episode_id"] != episode_id:
        raise SchemaError("episode_id does not match the current episode")
    fs = sub["findings"]
    if not isinstance(fs, list):
        raise SchemaError("findings must be a list")
    if len(fs) > MAX_FINDINGS:
        raise SchemaError("more than %d findings" % MAX_FINDINGS)
    for i, f in enumerate(fs):                   # limits are checked first
        if isinstance(f, dict):
            if isinstance(f.get("evidence_ids"), list) and len(f["evidence_ids"]) > MAX_EVIDENCE:
                raise SchemaError("finding %d has more than %d evidence ids" % (i, MAX_EVIDENCE))
            if isinstance(f.get("explanation"), str) and len(f["explanation"]) > MAX_EXPLANATION:
                raise SchemaError("finding %d explanation longer than %d" % (i, MAX_EXPLANATION))
    out = []
    for i, f in enumerate(fs):
        if not isinstance(f, dict):
            raise SchemaError("finding %d must be an object" % i)
        missing = (FINDING_KEYS - {"explanation"}) - set(f)
        if missing:
            raise SchemaError("finding %d misses %s" % (i, sorted(missing)))
        if not isinstance(f["type"], str):
            raise SchemaError("finding %d type must be a string" % i)
        aff = _str_list(f["affected_ids"], "affected_ids")
        evi = _str_list(f["evidence_ids"], "evidence_ids", MAX_EVIDENCE)
        amt = f["claimed_amount_minor"]
        if not _is_int(amt):
            raise SchemaError("finding %d claimed_amount_minor must be a JSON integer" % i)
        if not isinstance(f["currency"], str):
            raise SchemaError("finding %d currency must be a string" % i)
        exp = f.get("explanation", "")
        if not isinstance(exp, str) or len(exp) > MAX_EXPLANATION:
            raise SchemaError("finding %d explanation must be a string of <= %d code points" % (i, MAX_EXPLANATION))
        out.append({
            "type": f["type"],
            "affected": frozenset(aff),
            "amount": amt,
            "currency": f["currency"],
            "evidence": frozenset(evi),
        })
    return out


def _evidence_sets(issue):
    for k in ("evidence_sets", "valid_evidence_sets", "evidence"):
        if k in issue:
            v = issue[k]
            return v if v and isinstance(v[0], list) else [v]
    return []


def compatible(finding, issue, known_ids=None) -> bool:
    if finding["type"] not in ISSUE_TYPES and finding["type"] != issue["type"]:
        return False
    if finding["type"] != issue["type"]:
        return False
    if finding["affected"] != frozenset(issue["affected_ids"]):
        return False
    if finding["currency"] != issue["currency"]:
        return False
    tol = issue.get("amount_tolerance_minor", issue.get("tolerance", 0)) or 0
    if abs(finding["amount"] - issue["expected_amount_minor"]) > tol:
        return False
    if known_ids is not None and not finding["evidence"] <= known_ids:
        return False                                  # cites records that do not exist
    return any(set(s) <= finding["evidence"] for s in _evidence_sets(issue))


def match(findings, issues, known_ids=None):
    """Maximum one-to-one matching. Returns (pairs, unmatched_finding_idx, unmatched_issue_idx)."""
    issues_order = sorted(range(len(issues)), key=lambda j: str(issues[j].get("issue_id", j)))
    adj = [[j for j in issues_order if compatible(f, issues[j], known_ids)] for f in findings]
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
