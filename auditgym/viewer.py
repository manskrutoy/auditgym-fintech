"""Self-contained HTML audit workpaper: replays an episode for one or more policies
(demo aid; no effect on scoring).

    python -m auditgym viewer --episode dev/dev_09 --out reports/demo_dev_09.html

Design: a cool slate review console (navy ink, one ultramarine accent for selection), the reward as one
huge number with its formula spelled out, a 100-tick budget strip, an action tape beside the
environment's answer, and findings marked with rubber stamps (ВЕРНО / ЛОЖНО / ПРОПУСК) — the one
bold element, taken from audit practice. Fonts (Inter, Geist Mono; OFL) are embedded.
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
@font-face{font-family:'UI';src:url(data:font/ttf;base64,__INTER__) format('truetype');font-weight:100 900}
@font-face{font-family:'Mono';src:url(data:font/ttf;base64,__MONO__) format('truetype');font-weight:100 900}
:root{
  --ground:#E9EDF3; --card:#FFFFFF; --ink:#0F1B2D; --mute:#5B6678; --line:#D5DCE6; --soft:#F4F6FA;
  --accent:#2F45D8; --ok:#12804F; --bad:#C4291C; --miss:#A86A12;
  --ui:'UI',"Segoe UI",system-ui,sans-serif; --mono:'Mono',ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html{background:var(--ground)}
body{margin:0;color:var(--ink);font:15px/1.5 var(--ui);-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:0 28px}
header{position:sticky;top:0;z-index:5;background:rgba(233,237,243,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
header .wrap{display:flex;align-items:center;gap:14px 20px;flex-wrap:wrap;padding-top:12px;padding-bottom:12px}
.brand{font:700 19px var(--ui);letter-spacing:-.02em}
.brand i{font-style:normal;color:var(--accent)}
.meta{order:3;flex-basis:100%;display:flex;gap:8px;flex-wrap:wrap;color:var(--mute);font-size:13px}
.meta span{background:var(--card);border:1px solid var(--line);border-radius:7px;padding:3px 9px;white-space:nowrap}
.meta b{color:var(--ink);font-weight:600}
.seg{margin-left:auto;display:flex;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:3px}
.seg button{white-space:nowrap;font:600 14px var(--ui);border:0;background:transparent;color:var(--mute);padding:8px 14px;border-radius:7px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:#fff}
.seg button:focus-visible,.step:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.hero{display:grid;grid-template-columns:1.25fr 1fr;gap:28px;padding:44px 0 26px;align-items:end}
.kicker{color:var(--mute);font-size:14px;margin-bottom:6px}
.reward{font:600 132px/0.9 var(--ui);letter-spacing:-.055em;font-variant-numeric:tabular-nums}
.reward.neg{color:var(--bad)}
.eq{margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;color:var(--mute);font-size:15px}
.eq .t{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:5px 10px;color:var(--ink);font-variant-numeric:tabular-nums}
.counts{display:grid;grid-template-columns:repeat(4,1fr);background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden}
.counts div{padding:18px 18px 16px;border-right:1px solid var(--line)}
.counts div:last-child{border-right:0}
.counts span{display:block;color:var(--mute);font-size:13px}
.counts strong{font:600 44px/1.1 var(--ui);letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.c-ok strong{color:var(--ok)}.c-bad strong{color:var(--bad)}.c-miss strong{color:var(--miss)}
.budget{margin:6px 0 34px}
.budget .lab{display:flex;justify-content:space-between;color:var(--mute);font-size:13px;margin-bottom:8px}
.ticks{display:grid;grid-template-columns:repeat(100,1fr);gap:2px;height:30px}
.ticks i{border-radius:2px;background:#D9DFE8}
.ticks i.u{background:var(--ink)}.ticks i.e{background:var(--bad)}.ticks i.s{background:var(--ok)}
.ticks i.sel{outline:2px solid var(--accent);outline-offset:1px}
h2{font:650 22px var(--ui);letter-spacing:-.02em;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 16px;max-width:70ch}
.console{display:grid;grid-template-columns:330px minmax(0,1fr);gap:20px;margin-bottom:46px}
.tape{background:var(--card);border:1px solid var(--line);border-radius:16px;max-height:520px;overflow:auto;padding:6px}
.step{display:grid;grid-template-columns:34px 26px 1fr;gap:8px;align-items:center;width:100%;border:0;background:transparent;text-align:left;
  padding:9px 10px;border-radius:9px;cursor:pointer;font:14px var(--ui);color:var(--ink)}
.step:hover{background:var(--soft)}
.step[aria-selected="true"]{background:#E7EAFB;box-shadow:inset 3px 0 0 var(--accent)}
.step .n{font:500 13px var(--mono);color:var(--mute);font-variant-numeric:tabular-nums}
.step .k{width:24px;height:24px;border-radius:6px;display:grid;place-items:center;font:700 12px var(--mono);background:var(--soft);color:var(--ink)}
.step.err .k{background:#F8E1DE;color:var(--bad)}.step.sub .k{background:var(--ok);color:#fff}
.step .d{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.panel{min-width:0;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;min-height:300px}
.panel h3{font:650 17px var(--ui);margin:0 0 4px}
.req{font:13px/1.5 var(--mono);color:var(--mute);background:var(--soft);border-radius:8px;padding:8px 10px;word-break:break-all;margin:8px 0 12px}
.scroll{max-height:390px;overflow:auto;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font:13px var(--mono);font-variant-numeric:tabular-nums}
th{position:sticky;top:0;background:var(--soft);text-align:left;color:var(--mute);font:600 12px var(--ui);padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td.n{text-align:right}
tr:last-child td{border-bottom:0}
.err-msg{color:var(--bad);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;margin-bottom:56px}
.fc{position:relative;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px 16px;overflow:hidden}
.fc .ty{font:650 17px var(--ui);letter-spacing:-.01em}
.fc .ids{font:13px var(--mono);color:var(--mute);margin:4px 0 10px;overflow-wrap:anywhere;padding-right:96px}
.fc .amt{font:600 26px var(--ui);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.fc .why{color:var(--mute);font-size:14px;margin-top:8px}
.stamp{position:absolute;right:22px;top:20px;transform:rotate(-9deg);border:3px solid currentColor;border-radius:8px;padding:3px 10px 2px;
  font:800 17px var(--ui);letter-spacing:.06em;opacity:.9}
.stamp.ok{color:var(--ok)}.stamp.bad{color:var(--bad)}.stamp.miss{color:var(--miss);border-style:dashed}
.fc.bad{background:linear-gradient(#fff,#fff) padding-box}
footer{color:var(--mute);font-size:13px;padding:0 0 40px}
@media (prefers-reduced-motion:no-preference){
  .stamp{animation:press .32s cubic-bezier(.2,1.4,.4,1) both}
  @keyframes press{from{transform:rotate(-9deg) scale(1.8);opacity:0}to{transform:rotate(-9deg) scale(1);opacity:.9}}
}
@media (max-width:900px){.hero{grid-template-columns:1fr}.console{grid-template-columns:1fr}.reward{font-size:96px}.counts strong{font-size:34px}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const T = {duplicate_invoice:'Дубль счёта',unallocated_payment:'Нераспределённый платёж',fx_misconversion:'Неверный курс',period_cutoff:'Не тот период'};
const el=(t,a={},...c)=>{const e=document.createElement(t);for(const[k,v]of Object.entries(a)){if(k==='class')e.className=v;else if(k==='text')e.textContent=v;else e.setAttribute(k,v)}for(const x of c)e.append(x);return e};
const fmt=n=>typeof n==='number'?n.toLocaleString('ru-RU'):(n===null?'—':String(n));
const ru=(x,d)=>x.toFixed(d).replace('.',',');
const H=new URLSearchParams(location.hash.slice(1));
let run=Object.keys(D.runs)[0]; if(H.get('run') in D.runs) run=H.get('run');
let sel=+H.get('step')||1;
function renderSeg(){const b=document.getElementById('seg');b.innerHTML='';
  for(const k of Object.keys(D.runs)){const x=el('button',{type:'button','aria-pressed':String(k===run),text:D.runs[k].label});
    x.onclick=()=>{run=k;sel=1;render()};b.append(x);}}
function renderHero(){const g=D.runs[run].grade;const r=document.getElementById('reward');
  r.textContent=(g.reward>=0?'+':'−')+ru(Math.abs(g.reward),3); r.classList.toggle('neg',g.reward<0);
  document.getElementById('eq').innerHTML=`<span class="t">2 × F1 ${ru(g.f1,2)}</span> − <span class="t">1</span> − <span class="t">0,002 × ${g.inspection_steps} шагов</span>`;
  const set=(id,v)=>document.querySelector(id+' strong').textContent=v;
  set('.c-ok',g.tp);set('.c-bad',g.fp);set('.c-miss',g.fn);set('.c-f1',ru(g.f1,2));}
function renderBudget(){const s=D.runs[run].steps;const box=document.getElementById('ticks');box.innerHTML='';
  for(let i=1;i<=100;i++){const st=s[i-1];box.append(el('i',{class:(st?'u'+(st.cls==='err'?' e':st.cls==='sub'?' s':''):'')+(i===sel?' sel':''),title:st?`Шаг ${i}: ${st.label}`:''}));}
  document.getElementById('bud').textContent=`использовано ${s.length} из 100`;}
function renderTape(){const s=D.runs[run].steps;const box=document.getElementById('tape');box.innerHTML='';
  s.forEach((st,i)=>{const b=el('button',{type:'button',class:'step'+(st.cls?' '+st.cls:''),'aria-selected':String(i+1===sel)},
      el('span',{class:'n',text:String(i+1).padStart(2,'0')}),el('span',{class:'k',text:st.short}),el('span',{class:'d',text:st.label}));
    b.onclick=()=>{sel=i+1;renderTape();renderBudget();renderPanel()};box.append(b);});}
function table(rows){if(!rows.length)return el('p',{class:'sub',text:'Пустая страница.'});
  const cols=Object.keys(rows[0]).filter(k=>k!=='line_items');const t=el('table'),h=el('tr');cols.forEach(c=>h.append(el('th',{text:c})));t.append(el('thead',{},h));
  const b=el('tbody');rows.forEach(r=>{const tr=el('tr');cols.forEach(c=>{const v=r[c];tr.append(el('td',{class:typeof v==='number'?'n':'',text:Array.isArray(v)?v.map(x=>x.invoice_id+': '+fmt(x.amount_minor)).join(', '):fmt(v)}))});b.append(tr)});
  t.append(b);return el('div',{class:'scroll'},t);}
function renderPanel(){const box=document.getElementById('panel');box.innerHTML='';const s=D.runs[run].steps[sel-1];
  if(!s){box.append(el('p',{class:'sub',text:'Выберите шаг слева.'}));return}
  const o=s.obs;box.append(el('h3',{text:`Шаг ${sel}: ${s.label}`}),el('div',{class:'req',text:JSON.stringify(s.action).slice(0,500)}));
  if(o.error){box.append(el('p',{class:'err-msg',text:`${o.error.code}: ${o.error.message}`}));return}
  const r=o.result||{};
  if(r.records){box.append(el('p',{class:'sub',text:`Таблица ${r.table}: ${r.records.length} из ${r.total_records} записей · следующий курсор: ${r.next_cursor||'конец таблицы'}`}),table(r.records))}
  else if(r.record)box.append(table([r.record]));else if(r.document)box.append(table([r.document]));
  else box.append(el('p',{class:'sub',text:JSON.stringify(r)}));}
function renderCards(){const box=document.getElementById('cards');box.innerHTML='';const R=D.runs[run];const items=[];
  R.findings.forEach(f=>items.push({st:f.tp?'ok':'bad',lab:f.tp?'ВЕРНО':'ЛОЖНО',t:f.type,ids:f.affected_ids.join(', '),amt:fmt(f.claimed_amount_minor)+' '+f.currency,
    why:f.tp?'Совпало с эталоном: тип, ID, сумма, валюта и доказательства.':(f.why||'В эталоне такой ошибки нет.')}));
  D.truth.forEach(t=>{if(!R.found.includes(t.issue_id))items.push({st:'miss',lab:'ПРОПУСК',t:t.type,ids:t.affected_ids.join(', '),amt:fmt(t.expected_amount_minor)+' '+t.currency,why:'Ошибка есть, агент её не заявил. '+(t.cause||'')})});
  const ord={ok:0,bad:1,miss:2}; items.sort((a,b)=>ord[a.st]-ord[b.st]);
  if(!items.length){box.append(el('p',{class:'sub',text:'Книги чистые, и агент правильно ничего не заявил.'}));return}
  items.forEach((x,i)=>{const c=el('div',{class:'fc '+x.st},el('div',{class:'stamp '+x.st,text:x.lab}),el('div',{class:'ty',text:T[x.t]||x.t}),el('div',{class:'ids',text:x.ids}),
    el('div',{class:'amt',text:x.amt}),el('div',{class:'why',text:x.why}));c.querySelector('.stamp').style.animationDelay=Math.min(i*40,320)+'ms';box.append(c)});}
function render(){renderSeg();renderHero();renderBudget();renderTape();renderPanel();renderCards()}
render();
"""


def _font(name):
    import base64, os
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name), "rb") as f:
        return base64.b64encode(f.read()).decode()


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
    meta = [("Компания", m["company_name"]), ("Период", "%s — %s" % (m["period_start"], m["period_end"])),
            ("Пояс", "UTC" + m["timezone"]), ("Валюта", m["base_currency"]),
            ("Проводки", "%d" % c["ledger_rows"]), ("Документы", "%d" % c["documents"]),
            ("Ошибок в эталоне", "%d" % len(ep.truth["issues"]))]
    meta_html = "".join("<span>%s <b>%s</b></span>" % (_e(k), _e(v)) for k, v in meta)
    css = CSS.replace("__INTER__", _font("Inter-sub.ttf")).replace("__MONO__", _font("GeistMono-sub.ttf"))
    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AuditGym — разбор эпизода %(eid)s</title><style>%(css)s</style></head>
<body>
<header><div class="wrap"><div class="brand">Audit<i>Gym</i></div><div class="meta">%(meta)s</div>
<div class="seg" id="seg" role="group" aria-label="Агент"></div></div></header>
<main class="wrap">
<section class="hero">
  <div><div class="kicker">Награда агента за эпизод <span style="font-family:var(--mono)">%(eid)s</span></div>
  <div class="reward" id="reward"></div><div class="eq" id="eq"></div></div>
  <div class="counts"><div class="c-ok"><span>Верно</span><strong></strong></div><div class="c-bad"><span>Ложно</span><strong></strong></div>
  <div class="c-miss"><span>Пропущено</span><strong></strong></div><div class="c-f1"><span>F1</span><strong></strong></div></div>
</section>
<section class="budget"><div class="lab"><span>Бюджет: 100 действий, каждое — даже ошибочное — тратит одно</span><span id="bud"></span></div><div class="ticks" id="ticks"></div></section>
<h2>Что делал агент</h2><p class="sub">Слева — каждое действие по порядку, справа — что агент запросил и что ему вернула среда.</p>
<section class="console"><div class="tape" id="tape" role="listbox" aria-label="Действия агента"></div><div class="panel" id="panel" aria-live="polite"></div></section>
<h2>Сверка выводов с эталоном</h2><p class="sub">Эталон закрыт от агента и показан только в этом разборе. У каждого ложного вывода указана ловушка, на которую попался агент.</p>
<section class="cards" id="cards"></section>
<footer>Все компании, документы и суммы вымышлены. Файл создан командой <span style="font-family:var(--mono)">python -m auditgym viewer</span> и работает без интернета.</footer>
</main>
<script type="application/json" id="data">%(blob)s</script>
<script>%(js)s</script>
</body></html>""" % {"eid": _e(m["episode_id"]), "css": css, "meta": meta_html, "blob": blob, "js": JS}
