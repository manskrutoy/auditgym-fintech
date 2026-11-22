"""AuditGym environment: Gymnasium-style JSON contract for an AI financial auditor.

    obs, info = env.reset(seed=..., config=...)
    obs, reward, terminated, truncated, info = env.step(action)

Actions are JSON objects: {"action": <name>, ...arguments}.
  list_records(table, cursor=None, limit=50)   table in ledger|invoices|payments|fx
  get_record(table, id)
  get_document(doc_id)
  calculator(expression)
  submit(findings)       findings = {"episode_id": ..., "findings": [...]}

Modes
  train: the terminal reward and grading summary are returned to the policy.
  eval:  the policy always receives reward 0.0 and no diagnostics; the grade is kept
         in `evaluator_log` (read by the evaluator process, never sent to the policy).
"""

import copy
import json
import os
import time

from .calculator import CalcError, evaluate
from .constants import (
    ACTIONS, ENV_VERSION, MAX_ID_LEN, MAX_STEPS, PAGE_LIMIT, SCHEMA_VERSION, TABLE_KEYS, TABLES,
    TIME_LIMIT_S,
)
from .generator import generate_episode
from .reward import grade

TASK = (
    "You are auditing the books of one fictional company for one reporting period. "
    "Inspect the records with the tools, then call submit once with findings. Each finding: "
    "type (duplicate_invoice | unallocated_payment | fx_misconversion | period_cutoff), "
    "affected_ids, claimed_amount_minor (integer minor units), currency, evidence_ids "
    "(doc_id / row_id / fx_id, max 10) and a short explanation (max 1000 chars). "
    "The books may be clean: false accusations are penalised. Every action, including errors, "
    "uses one of the step budget; submit ends the episode."
)

TOOLS = {
    "list_records": {"args": {"table": "ledger|invoices|payments|fx", "cursor": "string|null",
                              "limit": "int 1..%d" % PAGE_LIMIT}},
    "get_record": {"args": {"table": "ledger|invoices|payments|fx", "id": "primary key (%s)" %
                            ", ".join("%s:%s" % kv for kv in TABLE_KEYS.items())}},
    "get_document": {"args": {"doc_id": "doc_id of an invoice or payment"}},
    "calculator": {"args": {"expression": "arithmetic on decimal numbers: + - * / // % ** ( )"}},
    "submit": {"args": {"findings": "{episode_id, findings:[{type, affected_ids, claimed_amount_minor, "
                                    "currency, evidence_ids, explanation}]}"}},
}

_ARGS = {
    "list_records": ({"table"}, {"cursor", "limit"}),
    "get_record": ({"table", "id"}, set()),
    "get_document": ({"doc_id"}, set()),
    "calculator": ({"expression"}, set()),
    "submit": ({"findings"}, set()),
}


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _short(x):
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= 40 else s[:37] + "..."


def _copy(x):
    return json.loads(json.dumps(x))


class AuditEnv:
    metadata = {"render_modes": [], "env_version": ENV_VERSION}

    def __init__(self, mode="train", max_steps=MAX_STEPS, time_limit_s=TIME_LIMIT_S,
                 record_trajectory=False, clock=time.monotonic):
        if mode not in ("train", "eval"):
            raise ValueError("mode must be 'train' or 'eval'")
        if not (1 <= int(max_steps) <= MAX_STEPS):
            raise ValueError("max_steps must be within 1..%d" % MAX_STEPS)
        self.mode = mode
        self.max_steps = int(max_steps)
        self.time_limit_s = time_limit_s
        self.record_trajectory = record_trajectory
        self._clock = clock
        self._ep = None
        self.evaluator_log = []        # grades; never part of observations
        self.trajectory = []

    # ------------------------------------------------------------------ reset
    def reset(self, seed=None, config=None, options=None, episode=None):
        if options:
            config = options.get("config", config)
            episode = options.get("episode", episode)
        if episode is None:
            if seed is None:
                seed = int.from_bytes(os.urandom(8), "big")
            episode = generate_episode(seed, config)
        self._ep = episode
        self._truth = episode.truth
        self._index = {}
        for t in TABLES:
            key = TABLE_KEYS[t]
            self._index[t] = {r[key]: r for r in episode.tables[t]}
        self._docs = {}
        for r in episode.tables["invoices"]:
            self._docs[r["doc_id"]] = ("invoice", r)
        for r in episode.tables["payments"]:
            self._docs[r["doc_id"]] = ("payment", r)
        self.steps_used = 0
        self.inspection_steps = 0
        self.done = False
        self._terminated = False
        self._truncated = False
        self.last_grade = None
        self._t0 = self._clock()
        obs = {
            "task": TASK,
            "episode_id": episode.episode_id,
            "manifest": _copy(episode.manifest),
            "policy": _copy(episode.policy),
            "tools": TOOLS,
            "step": 0,
            "remaining_steps": self.max_steps,
        }
        info = {"env_version": ENV_VERSION, "schema_version": SCHEMA_VERSION, "mode": self.mode}
        self.trajectory = []
        if self.record_trajectory:
            self._record(None, obs, 0.0, False, False)
        return obs, info

    # ------------------------------------------------------------------ step
    def step(self, action):
        if self._ep is None:
            raise RuntimeError("reset() must be called before step()")
        if self.done:
            obs = self._obs(None, None, ToolError("episode_finished", "episode already finished; call reset()"))
            return obs, 0.0, self._terminated, self._truncated, self._info()
        self.steps_used += 1
        name = action.get("action") if isinstance(action, dict) else None

        if self.time_limit_s is not None and self._clock() - self._t0 > self.time_limit_s:
            self.inspection_steps = self.steps_used
            return self._finish(None, truncated=True, action=action, reason="time_limit")

        if name == "submit":
            findings = action.get("findings") if isinstance(action, dict) else None
            extra = set(action) - {"action", "findings"}
            self.inspection_steps = self.steps_used - 1
            if "findings" not in action or extra:
                findings = {"__invalid__": "submit requires exactly one argument 'findings'"}
            return self._finish(findings, truncated=False, action=action)

        self.inspection_steps = self.steps_used
        try:
            result = self._dispatch(action)
            err = None
        except ToolError as e:
            result, err = None, e
        if self.steps_used >= self.max_steps:
            return self._finish(None, truncated=True, action=action, result=result, err=err, reason="step_limit")
        obs = self._obs(name if isinstance(name, str) else None, result, err)
        self._record(action, obs, 0.0, False, False)
        return obs, 0.0, False, False, self._info()

    # ------------------------------------------------------------------ internals
    def _finish(self, submission, truncated, action, result=None, err=None, reason=None):
        g = grade(None if truncated else submission, self._truth, self.inspection_steps)
        g["episode_id"] = self._ep.episode_id
        g["terminated_by"] = reason or "submit"
        g["steps_used"] = self.steps_used
        g["wall_time_s"] = round(self._clock() - self._t0, 4)
        self.last_grade = g
        self.evaluator_log.append(g)
        self.done = True
        self._terminated = not truncated
        self._truncated = truncated
        if truncated:
            if err is None and reason == "time_limit":
                err = ToolError("time_limit", "episode time limit reached; empty answer recorded")
            out = {"truncated": reason}
            if result is not None:
                out["last_result"] = result
            obs = self._obs(action.get("action") if isinstance(action, dict) else None, out, err)
        else:
            res = {"submitted": True}
            if self.mode == "train":
                res.update({"valid": g["valid"], "reward": g["reward"]})
                if not g["valid"]:
                    res["error"] = g["error"]
            obs = self._obs("submit", res, None)
        reward = g["reward"] if self.mode == "train" else 0.0
        info = self._info()
        if self.mode == "train":
            info["grade"] = {k: g[k] for k in ("valid", "tp", "fp", "fn", "precision", "recall", "f1",
                                                "reward", "experimental_reward", "inspection_steps")}
        else:
            info["reward_withheld"] = True
        self._record(action, obs, reward, self._terminated, self._truncated)
        return obs, reward, self._terminated, self._truncated, info

    def _info(self):
        return {"env_version": ENV_VERSION, "mode": self.mode, "steps_used": self.steps_used,
                "inspection_steps": self.inspection_steps}

    def _obs(self, name, result, err):
        return {
            "step": self.steps_used,
            "remaining_steps": max(0, self.max_steps - self.steps_used),
            "action": name if name in ACTIONS else None,
            "result": result,
            "error": None if err is None else {"code": err.code, "message": err.message},
        }

    def _record(self, action, obs, reward, terminated, truncated):
        if self.record_trajectory:
            self.trajectory.append({
                "episode_id": self._ep.episode_id, "step": self.steps_used,
                "action": _copy(action) if action is not None else None,
                "observation": _copy(obs), "reward": reward,
                "terminated": terminated, "truncated": truncated,
            })

    def _dispatch(self, action):
        if not isinstance(action, dict):
            raise ToolError("invalid_action", "action must be a JSON object with an 'action' field")
        name = action.get("action")
        if not isinstance(name, str):
            raise ToolError("invalid_action", "missing 'action' field")
        if name not in _ARGS:
            raise ToolError("unknown_action", "unknown action %r" % _short(name))
        req, opt = _ARGS[name]
        args = {k: v for k, v in action.items() if k != "action"}
        missing = req - set(args)
        extra = set(args) - req - opt
        if missing or extra:
            raise ToolError("invalid_arguments", "missing %s / unexpected %s" % (sorted(missing), sorted(extra)))
        return getattr(self, "_t_" + name)(**args)

    def _table(self, table):
        if not isinstance(table, str) or table not in TABLES:
            raise ToolError("unknown_table", "table must be one of %s" % list(TABLES))
        return table

    def _t_list_records(self, table, cursor=None, limit=PAGE_LIMIT):
        table = self._table(table)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ToolError("invalid_arguments", "limit must be an integer >= 1")
        limit = min(limit, PAGE_LIMIT)
        rows = self._ep.tables[table]
        if cursor is None:
            offset = 0
        else:
            if not isinstance(cursor, str):
                raise ToolError("invalid_cursor", "cursor must be a string or null")
            parts = cursor.split(":")
            if len(parts) != 3 or parts[0] != "c1" or parts[1] != table or not parts[2].isdigit():
                raise ToolError("invalid_cursor", "invalid cursor for table %s" % table)
            offset = int(parts[2])
            if offset > len(rows):
                raise ToolError("invalid_cursor", "cursor out of range")
        page = rows[offset:offset + limit]
        nxt = offset + len(page)
        return {
            "table": table,
            "records": _copy(page),
            "next_cursor": "c1:%s:%d" % (table, nxt) if nxt < len(rows) else None,
            "total_records": len(rows),
        }

    def _t_get_record(self, table, id):
        table = self._table(table)
        if not isinstance(id, str) or len(id) > MAX_ID_LEN:
            raise ToolError("invalid_arguments", "id must be a string")
        rec = self._index[table].get(id)
        if rec is None:
            raise ToolError("not_found", "no record %r in table %s" % (_short(id), table))
        return {"table": table, "record": _copy(rec)}

    def _t_get_document(self, doc_id):
        if not isinstance(doc_id, str) or len(doc_id) > MAX_ID_LEN:
            raise ToolError("invalid_arguments", "doc_id must be a string")
        hit = self._docs.get(doc_id)
        if hit is None:
            raise ToolError("not_found", "no document %r" % _short(doc_id))
        return {"doc_type": hit[0], "document": _copy(hit[1])}

    def _t_calculator(self, expression):
        try:
            return {"value": evaluate(expression)}
        except CalcError as e:
            raise ToolError("calc_error", str(e))
