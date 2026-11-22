import copy

from auditgym.env import AuditEnv
from auditgym.generator import generate_episode
from auditgym.policies.scripted import ExpertAuditor, Oracle

_CACHE = {}


def episode(seed=4242, preset="all_types", **cfg):
    key = (seed, preset, tuple(sorted(cfg.items())))
    if key not in _CACHE:
        c = {"preset": preset}
        c.update(cfg)
        _CACHE[key] = generate_episode(seed, c)
    return _CACHE[key]


def oracle_findings(ep):
    return Oracle(ep.truth).act({"episode_id": ep.episode_id})["findings"]


def submit(env, findings):
    return env.step({"action": "submit", "findings": findings})


def run_policy(ep, pol, mode="train", **kw):
    env = AuditEnv(mode=mode, record_trajectory=True, **kw)
    obs, _ = env.reset(episode=ep)
    pol.reset(obs)
    while True:
        obs, r, te, tr, info = env.step(pol.act(obs))
        if te or tr:
            return env, r, info


def finding_from_issue(issue, **over):
    f = {"type": issue["type"], "affected_ids": list(issue["affected_ids"]),
         "claimed_amount_minor": issue["expected_amount_minor"], "currency": issue["currency"],
         "evidence_ids": list(issue["evidence_sets"][0]), "explanation": "test"}
    f.update(over)
    return f


def sub(ep, findings):
    return {"episode_id": ep.episode_id, "findings": copy.deepcopy(findings)}
