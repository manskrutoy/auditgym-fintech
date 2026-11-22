"""Self-contained HTML replay of one episode (demo aid; no scoring impact).

    python -m auditgym viewer --episode dev/dev_09 --policy expert --out reports/demo_dev_09.html
"""

import html
import json

from .env import AuditEnv
from .matcher import compatible, validate_submission
from .policies.scripted import POLICIES

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--text:#e6e8ee;--mute:#8b93a7;--ok:#3ecf8e;--bad:#ff6b6b;--warn:#f5b94a;--acc:#7aa2ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:32px 0 12px;color:var(--mute);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--mute)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.k{color:var(--mute);font-size:12px}.v{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:500;font-size:12px}td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:#c9d1e6}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600}
.tp{background:rgba(62,207,142,.15);color:var(--ok)}.fp{background:rgba(255,107,107,.15);color:var(--bad)}.fn{background:rgba(245,185,74,.15);color:var(--warn)}
.steps{display:flex;flex-wrap:wrap;gap:4px}.s{width:26px;height:26px;border-radius:6px;display:grid;place-items:center;font-size:11px;background:#1f2430;color:var(--mute)}
.s.l{background:rgba(122,162,255,.18);color:var(--acc)}.s.sub{background:rgba(62,207,142,.25);color:var(--ok)}.s.err{background:rgba(255,107,107,.2);color:var(--bad)}
.note{color:var(--mute);font-size:12px;margin-top:8px}
"""


def _e(x):
    return html.escape(str(x))


def build(ep, policy="expert"):
    env = AuditEnv(mode="train", record_trajectory=True)
    obs, _ = env.reset(episode=ep)
    pol = POLICIES[policy]()
    pol.reset(obs)
    sub = None
    while True:
        act = pol.act(obs)
        if act.get("action") == "submit":
            sub = act["findings"]
        obs, r, te, tr, info = env.step(act)
        if te or tr:
            break
    g = env.last_grade
    m = ep.manifest
    issues = ep.truth["issues"]
    findings = sub["findings"] if sub else []
    norm = validate_submission(sub, ep.episode_id) if sub else []
    matched_issue = {mm["finding"]: mm["issue_id"] for mm in g["matches"]}

    steps = []
    for t in env.trajectory[1:]:
        a = (t["action"] or {}).get("action")
        cls = "sub" if a == "submit" else ("err" if t["observation"]["error"] else "l")
        label = {"list_records": "L", "get_record": "R", "get_document": "D", "calculator": "C", "submit": "✓"}.get(a, "?")
        title = json.dumps(t["action"])[:160]
        steps.append('<div class="s %s" title="%s">%s</div>' % (cls, _e(title), label))

    frows = []
    for i, f in enumerate(findings):
        tag = '<span class="tag tp">TP</span>' if i in matched_issue else '<span class="tag fp">FP</span>'
        frows.append("<tr><td>%s</td><td><code>%s</code></td><td><code>%s</code></td><td class=num>%s %s</td><td><code>%s</code></td><td>%s</td></tr>" % (
            tag, _e(f["type"]), _e(", ".join(f["affected_ids"])), _e(f["claimed_amount_minor"]), _e(f["currency"]),
            _e(", ".join(f["evidence_ids"])), _e(f["explanation"])))
    found = set(matched_issue.values())
    trows = []
    for iss in issues:
        tag = '<span class="tag tp">найдено</span>' if iss["issue_id"] in found else '<span class="tag fn">пропуск</span>'
        trows.append("<tr><td>%s</td><td><code>%s</code></td><td><code>%s</code></td><td class=num>%s %s</td><td>%s</td></tr>" % (
            tag, _e(iss["type"]), _e(", ".join(iss["affected_ids"])), _e(iss["expected_amount_minor"]), _e(iss["currency"]),
            _e(iss["interaction_group"] or "—")))
    muts = "".join("<tr><td><code>%s</code></td><td>%s</td></tr>" % (
        _e(mu["mutation"]), _e(", ".join("%s=%s" % (k, v) for k, v in mu.items() if k not in ("mutation", "issue_id"))))
        for mu in ep.provenance.get("mutations", []))

    cards = [("Награда", "%+.3f" % g["reward"]), ("F1", "%.2f" % g["f1"]), ("TP / FP / FN", "%d / %d / %d" % (g["tp"], g["fp"], g["fn"])),
             ("Шаги проверки", g["inspection_steps"]), ("Проводки", m["counts"]["ledger_rows"]), ("Документы", m["counts"]["documents"])]
    doc = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AuditGym — демо %(eid)s</title><style>%(css)s</style></head><body><main>
<h1>AuditGym · %(company)s</h1>
<div class="sub">Эпизод <code>%(eid)s</code> · период %(ps)s … %(pe)s (UTC%(tz)s) · базовая валюта %(base)s · политика <code>%(pol)s</code></div>
<div class="grid">%(cards)s</div>
<h2>Траектория агента</h2><div class="card"><div class="steps">%(steps)s</div>
<div class="note">L — list_records, R — get_record, D — get_document, C — calculator, ✓ — submit. Наведите курсор, чтобы увидеть действие.</div></div>
<h2>Выводы агента</h2><table><tr><th></th><th>тип</th><th>affected_ids</th><th>сумма</th><th>доказательства</th><th>объяснение</th></tr>%(frows)s</table>
<h2>Закрытый эталон (показан только в демо)</h2><table><tr><th></th><th>тип</th><th>affected_ids</th><th>сумма</th><th>взаимодействие</th></tr>%(trows)s</table>
<h2>Записанные причины ошибок (provenance)</h2><table><tr><th>мутация</th><th>детали</th></tr>%(muts)s</table>
<div class="note">Данные полностью вымышлены. Сгенерировано командой python -m auditgym viewer.</div>
</main></body></html>""" % {
        "eid": _e(m["episode_id"]), "css": CSS, "company": _e(m["company_name"]), "ps": _e(m["period_start"]),
        "pe": _e(m["period_end"]), "tz": _e(m["timezone"]), "base": _e(m["base_currency"]), "pol": _e(policy),
        "cards": "".join('<div class="card"><div class="k">%s</div><div class="v">%s</div></div>' % (_e(k), _e(v)) for k, v in cards),
        "steps": "".join(steps), "frows": "".join(frows) or '<tr><td colspan=6 class="sub">нет выводов</td></tr>',
        "trows": "".join(trows) or '<tr><td colspan=5 class="sub">чистая компания — ошибок нет</td></tr>',
        "muts": muts or '<tr><td colspan=2 class="sub">нет</td></tr>',
    }
    return doc
