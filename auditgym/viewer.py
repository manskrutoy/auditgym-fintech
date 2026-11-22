"""Self-contained HTML audit workpaper: replays an episode for one or more policies
(demo aid; no effect on scoring).

    python -m auditgym viewer --episode dev/dev_09 --out reports/demo_dev_09.html

Design: an auditor's columnar workpaper — pad-green ruled paper, graphite ink, green tick
marks for agreed findings, red pencil for false accusations, blue reviewer pencil for misses.
The 100-cell step budget is the one bold element.
"""

import html
import json

from .env import AuditEnv
from .analysis import fp_cause
from .matcher import validate_submission
from .policies.scripted import POLICIES

CAUSE_RU = {
    "trap: legitimate recurring / repeated amount": "Ловушка: законно повторяющаяся сумма (подписка или вторая услуга), строки счетов разные.",
    "trap: same customer and amount, different line items": "Ловушка: тот же клиент и сумма, но разные позиции в счетах.",
    "trap: printed/UTC date differs from company-local date": "Ловушка: напечатанная/UTC-дата не совпадает с датой в поясе компании, курс на самом деле верный.",
    "trap: no rate that day (weekend/holiday) -> previous business day": "Ловушка: в этот день курс не публиковался, политика берёт прошлый рабочий день.",
    "trap: period boundary in another time zone": "Ловушка: документ на границе периода в другом часовом поясе, по времени компании период верный.",
    "trap: legitimate unapplied receipt / advance / refund": "Ловушка: аванс, неопознанное поступление или возврат законно не распределены.",
    "right documents, wrong type": "Документы верные, но тип ошибки другой.",
    "right issue, wrong amount": "Ошибка найдена, но сумма неверная.",
    "right issue, wrong currency": "Ошибка найдена, но валюта неверная.",
    "right issue, incomplete evidence": "Ошибка найдена, но доказательств недостаточно.",
}

TYPE_RU = {
    "duplicate_invoice": "Дубль счёта",
    "unallocated_payment": "Нераспределённый платёж",
    "fx_misconversion": "Неверный курс",
    "period_cutoff": "Не тот период",
}

CSS = r"""
:root{
  --paper:#F3F7F1; --rule:#D3E3CF; --rule-strong:#A9C7A3; --ink:#23302A; --mute:#5E6F66;
  --tick:#1E7B4F; --red:#B3261E; --blue:#2856A6; --card:#FBFDFA;
  --serif:"Iowan Old Style","Charter","Palatino Linotype","Book Antiqua",Georgia,serif;
  --sans:"Avenir Next","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;color:var(--ink);font:15px/1.55 var(--sans);
  background-image:repeating-linear-gradient(to bottom,transparent 0 27px,var(--rule) 27px 28px);
  background-attachment:local}
main{max-width:1120px;margin:0 auto;padding:40px 28px 80px;border-left:2px solid #E7B9B4;
  background:linear-gradient(to right,transparent 0,transparent 100%)}
a{color:var(--blue)}
h1{font:600 34px/1.15 var(--serif);margin:0;letter-spacing:-.01em}
h2{font:600 21px/1.3 var(--serif);margin:44px 0 6px}
p.lead{margin:6px 0 0;color:var(--mute);max-width:72ch}
.hint{color:var(--mute);font-size:13px;margin:0 0 14px;max-width:72ch}
.head{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;flex-wrap:wrap}
.sign{font-size:13px;color:var(--mute);text-align:right;line-height:1.7}
.sign b{color:var(--ink);font-weight:600}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;margin-top:22px;
  border-top:1.5px solid var(--ink);border-bottom:1.5px solid var(--ink)}
.fact{padding:10px 14px 12px;border-right:1px solid var(--rule-strong)}
.fact:last-child{border-right:none}
.fact span{display:block;font-size:12.5px;color:var(--mute)}
.fact strong{font:600 19px/1.3 var(--serif);font-variant-numeric:tabular-nums lining-nums}
.tabs{display:flex;gap:8px;margin:28px 0 0;flex-wrap:wrap}
.tabs button{font:600 14px var(--sans);padding:8px 14px;border-radius:6px;border:1.5px solid var(--ink);
  background:transparent;color:var(--ink);cursor:pointer}
.tabs button[aria-pressed="true"]{background:var(--ink);color:var(--paper)}
.tabs button:focus-visible,.cell:focus-visible{outline:3px solid var(--blue);outline-offset:2px}
.score{margin-top:18px;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.reward{font:600 54px/1 var(--serif);font-variant-numeric:tabular-nums lining-nums}
.formula{font-size:15px;color:var(--mute);font-variant-numeric:tabular-nums}
.formula b{color:var(--ink)}
.budget{display:grid;grid-template-columns:repeat(20,1fr);gap:4px;margin-top:6px;max-width:640px}
.cell{aspect-ratio:1;border-radius:3px;border:1px solid var(--rule-strong);background:transparent;
  font:600 11px var(--sans);color:var(--ink);display:grid;place-items:center;padding:0;cursor:default}
.cell.used{cursor:pointer;background:#E3EEE0;border-color:#8DB287}
.cell.err{background:#F6DEDB;border-color:var(--red);color:var(--red)}
.cell.sub{background:var(--tick);border-color:var(--tick);color:#fff}
.cell.sel{box-shadow:0 0 0 2px var(--ink)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--mute);margin-top:10px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px;border:1px solid var(--rule-strong)}
.detail{margin-top:16px;background:var(--card);border:1px solid var(--rule-strong);border-radius:4px;padding:14px 16px}
.detail h3{font:600 16px var(--serif);margin:0 0 8px}
.detail .act{font-variant-numeric:tabular-nums;color:var(--mute);font-size:13.5px;word-break:break-all}
.scroll{max-height:340px;overflow:auto;margin-top:10px;border-top:1px solid var(--rule-strong)}
table{width:100%;border-collapse:collapse;font-size:13.5px;font-variant-numeric:tabular-nums}
th{font-weight:600;text-align:left;color:var(--mute);padding:7px 10px;border-bottom:1.5px solid var(--ink);background:var(--card);position:sticky;top:0}
td{padding:6px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
td.n{text-align:right;white-space:nowrap}
.ws{border-top:1.5px solid var(--ink);margin-top:6px}
.mark{font:700 18px/1 var(--serif);width:34px;text-align:center}
.m-ok{color:var(--tick)}.m-bad{color:var(--red)}.m-miss{color:var(--blue)}
.why{color:var(--mute);font-size:13px}
.ids span{white-space:nowrap}
.err-msg{color:var(--red)}
.foot{margin-top:48px;font-size:13px;color:var(--mute);max-width:72ch}
@media (max-width:640px){.budget{grid-template-columns:repeat(10,1fr)}.reward{font-size:42px}main{padding:28px 16px 60px}}
@media (prefers-reduced-motion:no-preference){.cell.used{transition:transform .12s}.cell.used:hover{transform:translateY(-1px)}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const T = {duplicate_invoice:'Дубль счёта',unallocated_payment:'Нераспределённый платёж',fx_misconversion:'Неверный курс',period_cutoff:'Не тот период'};
const el = (t,a={},...c)=>{const e=document.createElement(t);for(const[k,v]of Object.entries(a)){if(k==='class')e.className=v;else if(k==='text')e.textContent=v;else e.setAttribute(k,v)}for(const x of c)e.append(x);return e};
const fmt = n => typeof n==='number' ? n.toLocaleString('ru-RU') : (n===null?'—':String(n));
let run = Object.keys(D.runs)[0], sel = null;
const H = new URLSearchParams(location.hash.slice(1));
if (H.get('run') in D.runs) run = H.get('run');
if (+H.get('step') > 0 && +H.get('step') <= D.runs[run].steps.length) sel = +H.get('step');

function renderTabs(){
  const box=document.getElementById('tabs');box.innerHTML='';
  for(const k of Object.keys(D.runs)){
    const b=el('button',{type:'button','aria-pressed':String(k===run),text:D.runs[k].label});
    b.onclick=()=>{run=k;sel=null;render()};box.append(b);
  }
}
function renderScore(){
  const g=D.runs[run].grade;
  const ru=(x,d)=>x.toFixed(d).replace('.',',');
  document.getElementById('reward').textContent=(g.reward>=0?'+':'−')+ru(Math.abs(g.reward),3);
  document.getElementById('formula').innerHTML=
    `= 2 × F1 <b>${ru(g.f1,2)}</b> − 1 − 0,002 × <b>${g.inspection_steps}</b> шагов. Верно ${g.tp}, ложно ${g.fp}, пропущено ${g.fn}.`;
}
function renderBudget(){
  const box=document.getElementById('budget');box.innerHTML='';
  const steps=D.runs[run].steps;
  for(let i=1;i<=100;i++){
    const s=steps[i-1];
    const c=el('button',{type:'button',class:'cell'+(s?(' used'+(s.cls?' '+s.cls:'')):''),'aria-label':s?`Шаг ${i}: ${s.label}`:`Шаг ${i} не использован`});
    if(s){c.textContent=s.short;c.onclick=()=>{sel=i;renderBudget();renderDetail()};if(sel===i)c.classList.add('sel')}
    else c.disabled=true;
    box.append(c);
  }
}
function table(rows){
  if(!rows.length)return el('p',{class:'hint',text:'Пустая страница.'});
  const cols=Object.keys(rows[0]).filter(k=>k!=='line_items');
  const t=el('table'),h=el('tr');cols.forEach(c=>h.append(el('th',{text:c})));t.append(el('thead',{},h));
  const b=el('tbody');
  rows.forEach(r=>{const tr=el('tr');cols.forEach(c=>{const v=r[c];const td=el('td',{class:typeof v==='number'?'n':'',text:Array.isArray(v)?v.map(x=>x.invoice_id+': '+fmt(x.amount_minor)).join(', '):fmt(v)});tr.append(td)});b.append(tr)});
  t.append(b);return el('div',{class:'scroll'},t);
}
function renderDetail(){
  const box=document.getElementById('detail');box.innerHTML='';
  if(!sel){box.append(el('p',{class:'hint',text:'Нажмите на любой использованный шаг, чтобы увидеть, что агент запросил и что ему вернула среда.'}));return}
  const s=D.runs[run].steps[sel-1],o=s.obs;
  box.append(el('h3',{text:`Шаг ${sel} из 100 — ${s.label}`}));
  box.append(el('div',{class:'act',text:JSON.stringify(s.action).slice(0,600)}));
  if(o.error){box.append(el('p',{class:'err-msg',text:`Ошибка ${o.error.code}: ${o.error.message}`}));return}
  const r=o.result||{};
  if(r.records){box.append(el('p',{class:'hint',text:`Таблица ${r.table}: получено ${r.records.length} из ${r.total_records}. Следующий курсор: ${r.next_cursor||'конец таблицы'}.`}));box.append(table(r.records))}
  else if(r.record){box.append(table([r.record]))}
  else if(r.document){box.append(table([r.document]))}
  else box.append(el('p',{class:'hint',text:JSON.stringify(r)}));
}
function renderFindings(){
  const tb=document.getElementById('findings');tb.innerHTML='';
  const R=D.runs[run];
  const rows=[];
  R.findings.forEach(f=>rows.push({m:f.tp?'✓':'✗',cls:f.tp?'m-ok':'m-bad',t:f.type,ids:f.affected_ids.join(', '),amt:fmt(f.claimed_amount_minor)+' '+f.currency,why:f.tp?'Совпало с эталоном: тип, ID, сумма, валюта и доказательства.':(f.why||'Ложное обвинение: в эталоне такой ошибки нет.')}));
  D.truth.forEach(t=>{if(!R.found.includes(t.issue_id))rows.push({m:'○',cls:'m-miss',t:t.type,ids:t.affected_ids.join(', '),amt:fmt(t.expected_amount_minor)+' '+t.currency,why:'Пропущено: ошибка есть, агент её не заявил. '+(t.cause||'')})});
  if(!rows.length){tb.append(el('tr',{},el('td',{colspan:'5',class:'why',text:'Книги чистые, и агент правильно ничего не заявил.'})));return}
  rows.forEach(r=>{const tr=el('tr');tr.append(el('td',{class:'mark '+r.cls,text:r.m}),el('td',{text:T[r.t]||r.t}),(()=>{const td=el('td',{class:'ids'});r.ids.split(', ').forEach((x,i)=>{if(i)td.append(', ');td.append(el('span',{text:x}))});return td})(),el('td',{class:'n',text:r.amt}),el('td',{class:'why',text:r.why}));tb.append(tr)});
}
function render(){renderTabs();renderScore();renderBudget();renderDetail();renderFindings()}
render();
"""


def _e(x):
    return html.escape(str(x))


def _run(ep, policy):
    env = AuditEnv(mode="train", record_trajectory=True)
    obs, _ = env.reset(episode=ep)
    pol = POLICIES[policy]()
    pol.reset(obs)
    while True:
        obs, r, te, tr, info = env.step(pol.act(obs))
        if te or tr:
            break
    g = env.last_grade
    sub = g.get("submission") or {"findings": []}
    matched = {m["finding"]: m["issue_id"] for m in g["matches"]}
    steps = []
    for t in env.trajectory[1:]:
        a = t["action"] or {}
        name = a.get("action")
        o = t["observation"]
        short = {"list_records": "L", "get_record": "R", "get_document": "D", "calculator": "C", "submit": "✓"}.get(name, "?")
        label = {"list_records": "просмотр таблицы %s" % a.get("table"), "get_record": "запись %s" % a.get("id"),
                 "get_document": "документ %s" % a.get("doc_id"), "calculator": "калькулятор",
                 "submit": "отправка выводов"}.get(name, "неизвестное действие")
        steps.append({"short": short, "label": label, "cls": "sub" if name == "submit" else ("err" if o["error"] else ""),
                      "action": a, "obs": o})
    findings = []
    raw = sub.get("findings", []) if isinstance(sub, dict) else []
    try:
        norm = validate_submission(sub, ep.episode_id) if raw else []
    except Exception:
        norm = []
    inv = {d["invoice_id"]: d for d in ep.tables["invoices"]}
    pay = {d["payment_id"]: d for d in ep.tables["payments"]}
    idx = (inv, pay, ep.provenance.get("document_tags", {}))
    for i, f in enumerate(raw):
        why = None
        if i not in matched and i < len(norm):
            c = fp_cause(ep, norm[i], idx)
            why = CAUSE_RU.get(c, "Ложное обвинение: в эталоне такой ошибки нет (%s)." % c)
        findings.append(dict(f, tp=i in matched, why=why))
    labels = {"expert": "Скриптовый эксперт", "reconciler": "Простая сверка", "random": "Случайный агент",
              "flag_all": "Атака «пометить всё»"}
    return {"label": labels.get(policy, policy), "steps": steps, "findings": findings,
            "found": sorted(matched.values()),
            "grade": {k: g[k] for k in ("reward", "f1", "tp", "fp", "fn", "inspection_steps")}}


def build(ep, policies=("expert", "reconciler")):
    if isinstance(policies, str):
        policies = (policies,)
    m = ep.manifest
    muts = {mu["issue_id"]: mu for mu in ep.provenance.get("mutations", [])}
    cause_ru = {
        "duplicate_document_posted": "Копия счёта с новыми номерами проведена второй раз.",
        "allocation_not_applied": "Платёж по remittance относится к счёту, но в книге лежит в 1190.",
        "wrong_rate_date": "Курс взят не на ту дату (%s).",
        "wrong_posting_period": "Счёт проведён не в своём периоде (%s).",
    }
    truth = []
    for iss in ep.truth["issues"]:
        mu = muts.get(iss["issue_id"], {})
        c = cause_ru.get(mu.get("mutation"), "")
        if "%s" in c:
            c = c % (mu.get("wrong_date_rule") or mu.get("variant") or "")
        truth.append(dict(iss, cause=c))
    data = {"runs": {p: _run(ep, p) for p in policies}, "truth": truth}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    c = m["counts"]
    facts = [("Компания", m["company_name"]), ("Период", "%s — %s" % (m["period_start"], m["period_end"])),
             ("Пояс компании", "UTC" + m["timezone"]), ("Базовая валюта", m["base_currency"]),
             ("Проводки", "%d" % c["ledger_rows"]), ("Документы", "%d" % c["documents"]),
             ("Ошибок в эталоне", "%d" % len(ep.truth["issues"]))]
    facts_html = "".join('<div class="fact"><span>%s</span><strong>%s</strong></div>' % (_e(k), _e(v)) for k, v in facts)
    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AuditGym — рабочий документ %(eid)s</title><style>%(css)s</style></head>
<body><main>
<div class="head">
  <div><h1>Рабочий документ аудита</h1>
  <p class="lead">Эпизод AuditGym: вымышленная компания за один отчётный период. Агент расследует книги через инструменты среды,
  отправляет выводы с доказательствами, а закрытый оценщик сверяет их с эталоном.</p></div>
  <div class="sign">Эпизод <b>%(eid)s</b><br>Подготовил: агент<br>Проверил: закрытый оценщик</div>
</div>
<div class="facts">%(facts)s</div>

<h2>Итог проверки</h2>
<div class="tabs" id="tabs" role="group" aria-label="Политика"></div>
<div class="score"><div class="reward" id="reward"></div><div class="formula" id="formula"></div></div>

<h2>Бюджет шагов</h2>
<p class="hint">Сто клеток — это весь бюджет эпизода. Каждый вызов инструмента, включая ошибочный, тратит одну клетку; отправка выводов — последняя.</p>
<div class="budget" id="budget"></div>
<div class="legend"><span><i style="background:#E3EEE0;border-color:#8DB287"></i>чтение (L — таблица, R — запись, D — документ)</span>
<span><i style="background:#F6DEDB;border-color:#B3261E"></i>ошибка вызова</span><span><i style="background:#1E7B4F;border-color:#1E7B4F"></i>отправка</span></div>
<div class="detail" id="detail" aria-live="polite"></div>

<h2>Сверка выводов с эталоном</h2>
<p class="hint">✓ — вывод совпал с эталоном, ✗ — ложное обвинение, ○ — пропущенная ошибка. Эталон закрыт от агента и показан здесь только для демонстрации.</p>
<table class="ws"><thead><tr><th></th><th>Тип</th><th>Затронутые ID</th><th>Сумма</th><th>Пояснение</th></tr></thead><tbody id="findings"></tbody></table>

<p class="foot">Все компании, документы и суммы вымышлены. Файл создан командой <code>python -m auditgym viewer</code> и открывается без интернета.</p>
</main>
<script type="application/json" id="data">%(blob)s</script>
<script>%(js)s</script>
</body></html>""" % {"eid": _e(m["episode_id"]), "css": CSS, "facts": facts_html, "blob": blob, "js": JS}
