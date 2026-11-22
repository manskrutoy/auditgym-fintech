"""Optional Gymnasium adapter.  The core contract (AuditEnv) does not depend on Gymnasium;
this wrapper subclasses gymnasium.Env when the package is installed and otherwise falls back
to a plain object with the same methods.  Observations/actions are JSON strings (Text spaces).

    from auditgym.gym_adapter import AuditGymEnv
    env = AuditGymEnv(mode="train", config={"preset": "mixed"})
    obs, info = env.reset(seed=1)              # obs: JSON string
    obs, r, term, trunc, info = env.step('{"action":"list_records","table":"ledger"}')
"""

import json

from .env import AuditEnv

try:                                   # pragma: no cover - depends on optional package
    import gymnasium as _gym
    from gymnasium import spaces as _spaces
    _Base = _gym.Env
except Exception:                      # gymnasium not installed: keep the same interface
    _gym = None
    _spaces = None
    _Base = object

_MAX_TEXT = 2_000_000


class AuditGymEnv(_Base):
    metadata = {"render_modes": []}

    def __init__(self, mode="train", config=None, **kw):
        self.core = AuditEnv(mode=mode, **kw)
        self.config = config
        if _spaces is not None:
            self.observation_space = _spaces.Text(max_length=_MAX_TEXT)
            self.action_space = _spaces.Text(max_length=_MAX_TEXT)

    def reset(self, *, seed=None, options=None):
        if _gym is not None:
            super().reset(seed=seed)
        cfg = (options or {}).get("config", self.config)
        obs, info = self.core.reset(seed=seed, config=cfg)
        return json.dumps(obs), info

    def step(self, action):
        if isinstance(action, str):
            try:
                action = json.loads(action)
            except ValueError:
                action = {"action": None}
        obs, r, te, tr, info = self.core.step(action)
        return json.dumps(obs), float(r), bool(te), bool(tr), info
