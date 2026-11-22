"""Metrics and the shared terminal reward (section 05)."""

from .constants import STEP_COST
from .matcher import SchemaError, match, validate_submission


def metrics(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    if tp + fp + fn == 0:
        f1 = 1.0                       # empty truth, empty findings
    else:
        f1 = 2 * tp / (2 * tp + fp + fn)
    return p, r, f1


def clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def shared_reward(f1: float, inspection_steps: int) -> float:
    return clip(2.0 * f1 - 1.0 - STEP_COST * inspection_steps)


def experimental_reward(tp, fp, fn, n_truth, inspection_steps):
    """Optional experimental variant (reported separately, never replaces the shared one):
    F-beta with beta=0.5 (penalises false accusations more than misses)."""
    b2 = 0.25
    denom = (1 + b2) * tp + b2 * fn + fp
    fb = 1.0 if (tp + fp + fn) == 0 else ((1 + b2) * tp / denom if denom else 0.0)
    return clip(2.0 * fb - 1.0 - STEP_COST * inspection_steps)


def grade(submission, truth, inspection_steps: int, no_answer: bool = False, known_ids=None):
    """Grade a submission.  no_answer=True means the episode was truncated (empty answer).  Returns a full report dict
    that stays with the evaluator; only `reward` may be returned to a policy in train mode."""
    issues = truth["issues"]
    if no_answer:
        findings = []
    else:
        try:
            findings = validate_submission(submission, truth.get("episode_id"))
        except SchemaError as e:
            return {"valid": False, "error": str(e), "reward": -1.0, "experimental_reward": -1.0,
                    "tp": 0, "fp": 0, "fn": len(issues), "precision": 0.0, "recall": 0.0, "f1": 0.0,
                    "inspection_steps": inspection_steps, "matches": [], "n_findings": None}
    pairs, fps, fns = match(findings, issues, known_ids)
    tp, fp, fn = len(pairs), len(fps), len(fns)
    p, r, f1 = metrics(tp, fp, fn)
    return {
        "valid": True, "error": None,
        "reward": shared_reward(f1, inspection_steps),
        "experimental_reward": experimental_reward(tp, fp, fn, len(issues), inspection_steps),
        "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1,
        "inspection_steps": inspection_steps,
        "n_findings": len(findings),
        "matches": [{"finding": i, "issue_id": issues[j].get("issue_id")} for i, j in pairs],
        "false_positive_findings": fps,
        "fp_types": [findings[i]["type"] for i in fps],
        "missed_issue_ids": [issues[j].get("issue_id") for j in fns],
        "missed_types": [issues[j]["type"] for j in fns],
    }
