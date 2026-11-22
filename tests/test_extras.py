"""Optional adapters: Gymnasium-style wrapper and the HTML demo viewer."""

import json
import unittest

from auditgym.gym_adapter import AuditGymEnv
from auditgym.viewer import build

from tests.helpers import episode


class TestExtras(unittest.TestCase):
    def test_gym_adapter_roundtrip(self):
        env = AuditGymEnv(mode="train", config={"preset": "single"})
        obs, info = env.reset(seed=3)
        o = json.loads(obs)
        self.assertEqual(o["remaining_steps"], 100)
        obs, r, te, tr, info = env.step('{"action":"list_records","table":"fx","limit":3}')
        self.assertEqual(len(json.loads(obs)["result"]["records"]), 3)
        obs, r, te, tr, info = env.step("not json")
        self.assertEqual(json.loads(obs)["error"]["code"], "invalid_action")
        sub = json.dumps({"action": "submit", "findings": {"episode_id": o["episode_id"], "findings": []}})
        obs, r, te, tr, info = env.step(sub)
        self.assertTrue(te)
        self.assertIsInstance(r, float)

    def test_viewer_builds(self):
        doc = build(episode(seed=61, preset="interacting"), "expert")
        self.assertTrue(doc.startswith("<!DOCTYPE html>"))
        self.assertIn("AuditGym", doc)
