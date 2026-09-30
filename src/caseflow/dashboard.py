"""Self-contained HTML dashboard for one run (no server, no external assets).

Built from the files in the run folder (manifest, CSV, validated JSON). When the
original input files are still reachable, their text is embedded too so the page can
show exactly where each extracted fact came from. Regenerate for any past run with
`caseflow dashboard`. All document-derived values are inserted with textContent in
the browser - never as HTML.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .ingestion import SUPPORTED_FORMATS, IngestionError, SourceDocument, extract_text
from .output_writer import FORMULA_PREFIXES, atomic_write_text


def _unescape(value: str) -> str:
    # Reverse the CSV formula guard for display ('+1-555 -> +1-555).
    if value.startswith("'") and value[1:2] and value[1:].startswith(FORMULA_PREFIXES):
        return value[1:]
    return value


def _load_json(run_dir: Path, rel: str) -> Any:
    if not rel:
        return None
    path = run_dir / Path(rel).with_suffix(".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _source_text(input_dir: Path, rel: str, settings: dict[str, Any]) -> str | None:
    path = input_dir / rel
    if path.suffix.lower() not in SUPPORTED_FORMATS or not path.is_file():
        return None
    doc = SourceDocument(path, rel, SUPPORTED_FORMATS[path.suffix.lower()], True, path.stat().st_size, "")
    try:
        return extract_text(doc, settings.get("max_file_bytes", 10**7), settings.get("max_document_chars", 60_000))
    except (IngestionError, OSError):
        return None


def collect_run_data(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    with (run_dir / "final_report.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = [{k: _unescape(v) for k, v in row.items()} for row in csv.DictReader(fh)]
    tasks_by_id = {d["document_id"]: d["tasks"] for d in manifest.get("documents", [])}
    settings = manifest.get("settings", {})
    input_dir = Path(settings.get("input_dir", "data"))
    documents = []
    for row in rows:
        extraction = _load_json(run_dir, row.get("structured_output_path", ""))
        documents.append({
            "row": row,
            "extraction": extraction,
            "email": _load_json(run_dir, row.get("email_output_path", "")),
            "summary": _load_json(run_dir, row.get("summary_output_path", "")),
            "tasks": tasks_by_id.get(row["document_id"], {}),
            "source_text": _source_text(input_dir, row["source_file"], settings) if extraction else None,
        })
    manifest = {k: v for k, v in manifest.items() if k != "documents"}
    return {"manifest": manifest, "documents": documents}


def render_dashboard(run_dir: Path) -> str:
    payload = json.dumps(collect_run_data(run_dir), ensure_ascii=False)
    # Prevent the data block from closing the <script> element early.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _TEMPLATE.replace("__DATA__", payload)


def write_dashboard(run_dir: Path) -> Path:
    path = run_dir / "dashboard.html"
    atomic_write_text(path, render_dashboard(run_dir))
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CaseFlow Results</title>
<style>
:root{
  --bg:#f4f5f7;--panel:#fff;--ink:#17191c;--muted:#5f6873;--faint:#8b939c;--line:#e2e5e9;
  --accent:#2e5bdb;--accent-soft:#e8eefc;
  --green:#18794e;--green-soft:#e2f4ea;--amber:#94600a;--amber-soft:#fdf0d5;
  --red:#b42318;--red-soft:#fde7e5;--grey:#4b5563;--grey-soft:#eceef1;--mark:#fff1a8;
  --mock:#6b3fa0;--mock-soft:#f2eafc;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#101215;--panel:#191c21;--ink:#e8ebef;--muted:#a1a9b3;--faint:#78818c;--line:#2a3038;
  --accent:#86a6ff;--accent-soft:#1e2842;
  --green:#71d39f;--green-soft:#14301f;--amber:#f1c56d;--amber-soft:#35280d;
  --red:#ff8d84;--red-soft:#3b1613;--grey:#c3c9d1;--grey-soft:#252a31;--mark:#5a4a0c;
  --mock:#cbabf6;--mock-soft:#2b2140;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:28px 20px 40px}
h1{font-size:26px;line-height:1.25;margin:0 0 6px}
h2{font-size:18px;margin:0 0 12px}
.lead{color:var(--muted);font-size:16px;margin:0;max-width:760px}
.small{font-size:13px;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px}
section{margin-top:26px}

.mock{display:flex;gap:10px;align-items:flex-start;background:var(--mock-soft);color:var(--mock);border-radius:12px;padding:12px 16px;margin-top:18px}
.mock b{display:block}
.mock.real{background:var(--accent-soft);color:var(--accent)}

/* how it works */
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media (max-width:860px){.steps{grid-template-columns:1fr 1fr}}
@media (max-width:520px){.steps{grid-template-columns:1fr}}
.step{padding:16px;position:relative}
.step .num{width:30px;height:30px;border-radius:50%;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-weight:700;margin-bottom:8px}
.step h3{margin:0 0 4px;font-size:15px}
.step p{margin:0;color:var(--muted);font-size:13.5px}

/* outcome tiles */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media (max-width:860px){.tiles{grid-template-columns:1fr 1fr}}
.tile{padding:16px;text-align:left;border:2px solid transparent;cursor:pointer;font:inherit;color:inherit}
.tile:hover{border-color:var(--line)}
.tile.on{border-color:var(--accent)}
.tile .n{font-size:32px;font-weight:700;line-height:1}
.tile .t{font-weight:600;margin-top:6px}
.tile .d{font-size:13px;color:var(--muted)}
.tile.green .n{color:var(--green)}.tile.amber .n{color:var(--amber)}.tile.red .n{color:var(--red)}.tile.grey .n{color:var(--grey)}

/* layout */
.split{display:grid;grid-template-columns:360px minmax(0,1fr);gap:16px;align-items:start}
.split>*{min-width:0}
@media (max-width:940px){.split{grid-template-columns:minmax(0,1fr)}}
.list{overflow:hidden}
.listhead{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
.item{display:block;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid var(--line);padding:12px 14px;cursor:pointer;font:inherit;color:inherit}
.item:last-child{border-bottom:0}
.item:hover{background:var(--bg)}
.item.sel{background:var(--accent-soft)}
.item .top{display:flex;gap:8px;align-items:center}
.item .title{font-weight:600}
.item .file{font-size:12.5px;color:var(--faint);word-break:break-all}
.dot{width:10px;height:10px;border-radius:50%;flex:none}
.dot.green{background:var(--green)}.dot.amber{background:var(--amber)}.dot.red{background:var(--red)}.dot.grey{background:var(--faint)}

.pill{display:inline-flex;align-items:center;gap:4px;border-radius:999px;padding:2px 10px;font-size:12.5px;font-weight:600;white-space:nowrap}
.pill.green{background:var(--green-soft);color:var(--green)}.pill.amber{background:var(--amber-soft);color:var(--amber)}
.pill.red{background:var(--red-soft);color:var(--red)}.pill.grey{background:var(--grey-soft);color:var(--grey)}
.pill.blue{background:var(--accent-soft);color:var(--accent)}

/* detail */
.detail{padding:22px}
.verdict{display:flex;gap:12px;align-items:flex-start;padding:14px 16px;border-radius:12px;margin:14px 0}
.verdict.green{background:var(--green-soft)}.verdict.amber{background:var(--amber-soft)}.verdict.red{background:var(--red-soft)}.verdict.grey{background:var(--grey-soft)}
.verdict .icon{font-size:22px;line-height:1}
.verdict b{display:block}
.journey{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:6px 0 4px}
@media (max-width:640px){.journey{grid-template-columns:1fr 1fr}}
.jstep{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.jstep .h{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.jstep .s{font-weight:600;margin-top:2px}
.jstep .x{font-size:12.5px;color:var(--muted)}
.jstep.green{border-color:color-mix(in srgb,var(--green) 40%,var(--line))}
.jstep.amber{border-color:color-mix(in srgb,var(--amber) 40%,var(--line))}
.jstep.red{border-color:color-mix(in srgb,var(--red) 40%,var(--line))}

.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-top:20px;overflow-x:auto}
.tab{background:none;border:0;border-bottom:2px solid transparent;padding:10px 12px;font:inherit;font-weight:600;color:var(--muted);cursor:pointer;white-space:nowrap}
.tab.on{color:var(--accent);border-bottom-color:var(--accent)}
.pane{padding-top:16px}
.explain{background:var(--bg);border-radius:10px;padding:10px 14px;color:var(--muted);font-size:13.5px;margin-bottom:14px}

.facts{width:100%;border-collapse:collapse}
.facts td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.facts td:first-child{color:var(--muted);width:30%}
.facts .q{display:block;font-size:12.5px;color:var(--faint);margin-top:3px}
.unk{color:var(--faint);font-style:italic}
ul.clean{margin:0;padding-left:18px}

.doc{white-space:pre-wrap;font:13.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--bg);border-radius:10px;padding:14px;max-height:520px;overflow:auto}
mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 1px}

.mail{border:1px solid var(--line);border-radius:12px;overflow:hidden}
.mail .row{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--bg);flex-wrap:wrap}
.mail pre{margin:0;padding:16px;white-space:pre-wrap;font:inherit}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:4px 12px;cursor:pointer;font:inherit;font-size:13px}
.btn:hover{border-color:var(--accent)}

.sumgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:640px){.sumgrid{grid-template-columns:1fr}}
.sumbox{border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.sumbox .h{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
.sumbox.wide{grid-column:1/-1}

.tech{width:100%;border-collapse:collapse;font-size:13.5px}
.tech th,.tech td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
.tech th{color:var(--muted);font-weight:600}
.empty{color:var(--muted);padding:40px;text-align:center}
footer{margin-top:28px;color:var(--faint);font-size:12.5px}
details.glossary summary{cursor:pointer;font-weight:600}
details.glossary dl{display:grid;grid-template-columns:180px 1fr;gap:6px 14px;margin:12px 0 0}
details.glossary dt{font-weight:600}
details.glossary dd{margin:0;color:var(--muted)}
@media (max-width:600px){details.glossary dl{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="headline"></h1>
    <p class="lead" id="lead"></p>
    <div class="mock" id="mode"></div>
  </header>

  <section>
    <h2>How it works</h2>
    <div class="steps">
      <div class="card step"><div class="num">1</div><h3>Read the document</h3><p>Opens each TXT, PDF or Word file and pulls out its text. Files it can't read are reported, not guessed at.</p></div>
      <div class="card step"><div class="num">2</div><h3>Pull out the facts</h3><p>AI fills in a case form: who, what product, what went wrong, what was done. Every fact must quote the document as proof.</p></div>
      <div class="card step"><div class="num">3</div><h3>Draft a reply</h3><p>For real complaints only, AI writes a polite email draft. It is never sent automatically.</p></div>
      <div class="card step"><div class="num">4</div><h3>Brief the manager</h3><p>AI writes a short internal summary and flags cases a person should check.</p></div>
    </div>
  </section>

  <section>
    <h2>Results at a glance <span class="small">— click a box to filter</span></h2>
    <div class="tiles" id="tiles"></div>
  </section>

  <section class="split">
    <div class="card list">
      <div class="listhead"><b id="listtitle">All documents</b><span class="small" id="listcount"></span></div>
      <div id="items"></div>
    </div>
    <div class="card detail" id="detail"><div class="empty">Choose a document on the left</div></div>
  </section>

  <section class="card" style="padding:16px 18px">
    <details class="glossary">
      <summary>What do these words mean?</summary>
      <dl>
        <dt>Unknown</dt><dd>The document doesn't say. The system never guesses or fills gaps.</dd>
        <dt>Evidence / quote</dt><dd>The exact words in the document that support a fact. The system checks every quote really exists; made-up quotes are rejected.</dd>
        <dt>Needs review</dt><dd>A person should look before acting: e.g. conflicting notes, missing contact details, unclear request, or suspicious instructions in the text.</dd>
        <dt>Draft reply</dt><dd>A suggested email. Nothing is ever sent by this system.</dd>
        <dt>No reply needed</dt><dd>The document is praise or a question, not a complaint.</dd>
        <dt>Reply on hold</dt><dd>It's unclear whether this is a complaint, so a person decides.</dd>
        <dt>Couldn't read</dt><dd>The file was empty, damaged, password-protected, a scanned image (needs OCR), or too large.</dd>
      </dl>
    </details>
  </section>

  <footer id="foot"></footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const M = DATA.manifest, DOCS = DATA.documents;
const $ = s => document.querySelector(s);
function el(tag, attrs, ...kids){
  const e = document.createElement(tag);
  for (const [k,v] of Object.entries(attrs||{})){
    if (k==='class') e.className=v; else if (k.startsWith('on')) e.addEventListener(k.slice(2),v); else e.setAttribute(k,v);
  }
  for (const k of kids.flat()) if (k!=null && k!==false) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
const pill = (text, tone) => el('span',{class:'pill '+tone}, text);
const words = s => String(s||'').replace(/_/g,' ');
const cap = s => { s = words(s); return s.charAt(0).toUpperCase()+s.slice(1); };

// ---------- plain-language interpretation ----------
const ERR = {
  unsupported_format:'This file type isn\u2019t supported. Only TXT, PDF and Word (.docx) files are processed.',
  empty_document:'The file is empty \u2014 there was no text to read.',
  encoding_error:'The text file uses an unusual character encoding. Re-save it as UTF-8 and try again.',
  corrupted_file:'The file is damaged and couldn\u2019t be opened.',
  encrypted_pdf:'The PDF is password-protected. Provide an unlocked copy.',
  ocr_required:'This PDF is a scanned image with no text inside. It needs OCR (text recognition) first.',
  document_too_large:'The document is larger than the configured limit. Nothing was cut off \u2014 it was skipped instead.',
  read_error:'The file couldn\u2019t be read from disk.',
  mock_fixture_missing:'Demo (mock) mode only knows the bundled sample documents. Run in real AI mode to process this file.',
  validation_failed:'The AI\u2019s answer failed our checks twice (for example, it quoted text that isn\u2019t in the document), so it was not saved.',
  retries_exhausted:'The AI service didn\u2019t respond after several tries.',
  authentication_failed:'The API key was rejected, so processing stopped.',
  run_aborted:'Not processed because the run stopped early.',
};
function outcome(d){
  const r=d.row, s=r.processing_status;
  if (s==='skipped') return {tone:'grey', group:'skipped', icon:'\u23ED', title:'Not supported', text:ERR[r.error_code]||'Skipped.'};
  if (s==='failed'||s==='aborted'||s==='interrupted')
    return {tone:'red', group:'failed', icon:'\u2716', title: r.error_stage==='ingestion' ? 'Couldn\u2019t read this file' : 'Processing failed',
            text: ERR[r.error_code] || r.error_message || 'Something went wrong.'};
  const reasons = (d.summary && d.summary.review_reasons) || [];
  const extra = [];
  if (r.complaint==='Unknown') extra.push('It\u2019s unclear whether this is a complaint.');
  if (d.extraction && d.extraction.ambiguities.length) extra.push(...d.extraction.ambiguities);
  if (s==='partial_success') extra.push('One of the AI steps failed: ' + (ERR[r.error_code]||r.error_message));
  if (r.review_required==='Yes')
    return {tone:'amber', group:'review', icon:'\u26A0', title:'Needs a person to check', text:[...new Set([...reasons, ...extra])]};
  return {tone:'green', group:'ready', icon:'\u2714', title:'Ready \u2014 no issues found', text:'All steps completed and nothing needs special attention.'};
}
function headline(d){
  const e=d.extraction, r=d.row;
  if (!e) return r.source_file;
  if (e.complaint===false) return 'Not a complaint' + (e.product_or_service ? ` \u00b7 ${e.product_or_service}` : '');
  const kind = e.complaint_category && e.complaint_category!=='unknown' ? cap(e.complaint_category)+' complaint' :
               (e.complaint===null ? 'Unclear request' : 'Complaint');
  return kind + (e.customer_name ? ` from ${e.customer_name}` : ' (customer unknown)');
}
const STATUS = {open:['Open','amber'],in_progress:['In progress','blue'],resolved:['Resolved','green'],closed:['Closed','green'],
  escalated:['Escalated','red'],not_a_complaint:['Not a complaint','grey'],unknown:['Status unclear','grey']};
function emailStep(r){
  if (r.email_status==='succeeded') return ['green','Reply drafted', r.recipient_missing==='Yes' ? 'No email address in the document' : 'Ready to review and send'];
  if (r.email_skip_reason==='not_a_complaint') return ['grey','No reply needed','Not a complaint'];
  if (r.email_skip_reason==='complaint_unconfirmed') return ['amber','Reply on hold','Unclear if it\u2019s a complaint'];
  if (r.email_status==='failed') return ['red','Failed', ERR[r.error_code]||''];
  return ['grey','Not done','Earlier step didn\u2019t finish'];
}

// ---------- header ----------
const groups = {ready:[],review:[],failed:[],skipped:[]};
DOCS.forEach(d => { d.o = outcome(d); groups[d.o.group].push(d); });
const complaints = DOCS.filter(d=>d.row.complaint==='Yes').length;
const drafts = DOCS.filter(d=>d.row.email_status==='succeeded').length;
$('#headline').textContent = `We processed ${DOCS.length} customer documents`;
$('#lead').textContent = `Found ${complaints} complaint${complaints===1?'':'s'}, drafted ${drafts} repl${drafts===1?'y':'ies'}, and flagged ${groups.review.length} case${groups.review.length===1?'':'s'} for a person to check. ` +
  `${groups.failed.length ? groups.failed.length+' file'+(groups.failed.length===1?'':'s')+' couldn\u2019t be processed. ' : ''}Took ${M.elapsed_seconds.toFixed(1)} seconds.`;
const mode = $('#mode');
if (M.provider.is_mock){
  mode.append(el('span',{},'\u{1F9EA}'), el('div',{}, el('b',{},'Demo mode'),
    'These results are pre-written examples for the sample documents, used to demonstrate the workflow without calling the AI service. Run with ', el('code',{},'--provider openai'),' for real AI results.'));
} else {
  mode.className='mock real';
  mode.append(el('span',{},'\u{1F916}'), el('div',{}, el('b',{},`Real AI mode (${M.provider.model})`),
    'Results were generated by the AI and checked automatically. Email drafts should still be reviewed by a person before sending.'));
}

// ---------- tiles ----------
const TILES = [
  ['ready','green','Ready','Processed, no issues'],
  ['review','amber','Needs review','A person should check'],
  ['failed','red','Couldn\u2019t process','Damaged, empty, or unreadable'],
  ['skipped','grey','Not supported','Wrong file type'],
];
let filter = null, selected = null, tab = 'overview';
function renderTiles(){
  const t=$('#tiles'); t.replaceChildren();
  for (const [key,tone,title,desc] of TILES)
    t.append(el('button',{class:`card tile ${tone}${filter===key?' on':''}`,onclick:()=>{filter = filter===key?null:key; renderTiles(); renderList();}},
      el('div',{class:'n'},groups[key].length), el('div',{class:'t'},title), el('div',{class:'d'},desc)));
}

// ---------- list ----------
function renderList(){
  const shown = filter ? groups[filter] : DOCS;
  $('#listtitle').textContent = filter ? TILES.find(t=>t[0]===filter)[2] : 'All documents';
  $('#listcount').textContent = `${shown.length} of ${DOCS.length}`;
  const box=$('#items'); box.replaceChildren();
  if (!shown.length) box.append(el('div',{class:'empty'},'Nothing here'));
  for (const d of shown){
    box.append(el('button',{class:'item'+(selected===d?' sel':''),onclick:()=>{selected=d; tab='overview'; const y=scrollY; renderList(); renderDetail(); scrollTo(0,y); if (innerWidth<=940) $('#detail').scrollIntoView({behavior:'smooth',block:'start'});}},
      el('div',{class:'top'}, el('span',{class:'dot '+d.o.tone}), el('span',{class:'title'},headline(d))),
      el('div',{class:'file'}, `${d.row.source_file}`)));
  }
}

// ---------- detail ----------
function highlight(text, quotes){
  const ranges=[];
  for (const q of quotes){
    const pat = q.trim().replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/\s+/g,'\\s+').replace(/["\u201c\u201d]/g,'["\u201c\u201d]');
    try { const m = new RegExp(pat,'i').exec(text); if (m) ranges.push([m.index, m.index+m[0].length]); } catch(_){}
  }
  ranges.sort((a,b)=>a[0]-b[0]);
  const merged=[]; for (const r of ranges){ const l=merged[merged.length-1]; if (l && r[0]<=l[1]) l[1]=Math.max(l[1],r[1]); else merged.push([...r]); }
  const out=[]; let i=0;
  for (const [a,b] of merged){ out.push(text.slice(i,a)); out.push(el('mark',{},text.slice(a,b))); i=b; }
  out.push(text.slice(i)); return out;
}
const unk = () => el('span',{class:'unk'},'Unknown \u2014 not stated in the document');
function show(v){ if (v===null||v===undefined||v==='') return unk(); if (v===true) return 'Yes'; if (v===false) return 'No'; return String(v); }
function bullets(items, empty){ return items && items.length ? el('ul',{class:'clean'},items.map(x=>el('li',{},x))) : el('span',{class:'unk'},empty||'None'); }
function copyBtn(text,label){ const b=el('button',{class:'btn',onclick:()=>navigator.clipboard.writeText(text).then(()=>{b.textContent='\u2713 Copied';setTimeout(()=>b.textContent=label,1400);})},label); return b; }

function renderDetail(){
  const d=selected, r=d.row, e=d.extraction, box=$('#detail'); box.replaceChildren();
  const [stText, stTone] = e ? STATUS[e.overall_case_status] : ['',''];
  box.append(el('div',{class:'small'}, r.source_file), el('h2',{style:'margin:2px 0 0;font-size:21px'}, headline(d)));
  if (e) box.append(el('div',{style:'display:flex;gap:6px;flex-wrap:wrap;margin-top:8px'},
    pill(stText, stTone), e.escalation_required ? pill('Escalation required','red') : null,
    e.supporting_document_available ? pill('Mentions an attachment','blue') : null));

  const o=d.o;
  box.append(el('div',{class:'verdict '+o.tone}, el('span',{class:'icon'},o.icon),
    el('div',{}, el('b',{},o.title), Array.isArray(o.text) ? bullets(o.text) : el('div',{},o.text))));

  // journey through the 4 steps
  const ing = d.tasks.ingestion?.status;
  const j = [
    ['1 \u00b7 Read', ing==='succeeded'?['green','Done','Text extracted']:(r.processing_status==='skipped'?['grey','Skipped','Unsupported type']:['red','Failed','See above'])],
    ['2 \u00b7 Facts', r.extraction_status==='succeeded'?['green','Done',`${e.evidence.length} facts backed by quotes`]:(r.extraction_status==='failed'?['red','Failed','See above']:['grey','Not done','Previous step didn\u2019t finish'])],
    ['3 \u00b7 Reply', emailStep(r)],
    ['4 \u00b7 Manager', r.summary_status==='succeeded'?['green','Done', d.summary.review_required?'Flagged for review':'No concerns']:(r.summary_status==='failed'?['red','Failed','']:['grey','Not done','Previous step didn\u2019t finish'])],
  ];
  box.append(el('div',{class:'journey'}, j.map(([h,[tone,s,x]])=>el('div',{class:'jstep '+tone}, el('div',{class:'h'},h), el('div',{class:'s'},s), el('div',{class:'x'},x)))));

  if (!e) return;
  const tabs = [['overview','Overview'],['source','Original document'],['facts','Extracted facts'],
    ['email', d.email ? 'Reply draft' : 'Reply (none)'],['summary','Manager summary'],['tech','Technical details']];
  const bar = el('div',{class:'tabs'}, tabs.map(([k,label])=>el('button',{class:'tab'+(tab===k?' on':''),onclick:()=>{tab=k; const y=scrollY; renderDetail(); scrollTo(0,y);}},label)));
  box.append(bar);
  const pane = el('div',{class:'pane'}); box.append(pane);
  const byField = {}; for (const ev of e.evidence) (byField[ev.field_name] ||= []).push(ev.source_quote);

  if (tab==='overview'){
    pane.append(el('div',{class:'sumgrid'},
      el('div',{class:'sumbox wide'}, el('div',{class:'h'},'What happened'), show(e.issue_description)),
      el('div',{class:'sumbox'}, el('div',{class:'h'},'Customer'), show(e.customer_name),
        el('div',{class:'small'}, e.email || 'No email address', ' \u00b7 ', e.phone_number || 'No phone')),
      el('div',{class:'sumbox'}, el('div',{class:'h'},'Product or service'), show(e.product_or_service)),
      el('div',{class:'sumbox'}, el('div',{class:'h'},'What has been done'), show(e.resolution_provided)),
      el('div',{class:'sumbox'}, el('div',{class:'h'},'Suggested next step'), d.summary ? d.summary.recommended_next_action : unk()),
      el('div',{class:'sumbox wide'}, el('div',{class:'h'},'Missing information'), bullets(e.missing_information,'Nothing important missing')),
    ));
  }
  if (tab==='source'){
    pane.append(el('div',{class:'explain'},'This is the text the system read. ', el('mark',{},'Highlighted'),
      ' parts are the exact quotes it used as proof for the extracted facts.'));
    pane.append(d.source_text ? el('div',{class:'doc'}, highlight(d.source_text, e.evidence.map(x=>x.source_quote)))
      : el('div',{class:'empty'},'The original file isn\u2019t available from this location.'));
  }
  if (tab==='facts'){
    pane.append(el('div',{class:'explain'},'The case form the AI filled in. Under each fact is the quote from the document that proves it. \u201cUnknown\u201d means the document doesn\u2019t say \u2014 the system never guesses.'));
    const F = [['customer_name','Customer name'],['email','Email'],['phone_number','Phone'],['product_or_service','Product / service'],
      ['complaint_category','Type of issue'],['complaint','Is it a complaint?'],['issue_description','The problem'],
      ['resolution_provided','What has been done'],['overall_case_status','Case status'],['escalation_required','Needs escalation?'],
      ['supporting_document_available','Says something is attached?']];
    pane.append(el('table',{class:'facts'}, F.map(([k,label])=>{
      let v = e[k]; if (k==='complaint_category'||k==='overall_case_status') v = v==='unknown'?null:cap(v);
      return el('tr',{}, el('td',{},label), el('td',{}, show(v), (byField[k]||[]).map(q=>el('span',{class:'q'},`\u201c${q}\u201d`))));
    }),
      el('tr',{}, el('td',{},'Missing information'), el('td',{}, bullets(e.missing_information))),
      el('tr',{}, el('td',{},'Unclear or conflicting'), el('td',{}, bullets(e.ambiguities)))));
    if (e.supporting_document_available) pane.append(el('p',{class:'small'},'Note: \u201cattached\u201d only means the document says so \u2014 attachments are not opened or checked.'));
  }
  if (tab==='email'){
    if (!d.email){
      const [,s,x]=emailStep(r);
      pane.append(el('div',{class:'empty'}, el('b',{},s), el('div',{},
        r.email_skip_reason==='not_a_complaint' ? 'This document is feedback or a question, not a complaint, so no complaint reply was written.' :
        r.email_skip_reason==='complaint_unconfirmed' ? 'The document doesn\u2019t make clear whether this is a complaint. A person should decide before anyone replies.' : x)));
    } else {
      const m=d.email, body=`${m.greeting}\n\n${m.body}\n\n${m.closing}`;
      pane.append(el('div',{class:'explain'},'A suggested reply. It only states facts from the document and never promises refunds, amounts or deadlines that aren\u2019t there. ', el('b',{},'Nothing has been sent.')));
      pane.append(el('div',{class:'mail'},
        el('div',{class:'row'}, el('div',{}, el('b',{},'To: '), e.email || el('span',{class:'pill amber'},'No email address in document')), el('span',{})),
        el('div',{class:'row'}, el('div',{}, el('b',{},'Subject: '), m.subject), copyBtn(m.subject,'Copy subject')),
        el('div',{class:'row'}, el('span',{class:'small'},'Message'), copyBtn(body,'Copy message')),
        el('pre',{}, body)));
    }
  }
  if (tab==='summary'){
    const s=d.summary;
    if (!s){ pane.append(el('div',{class:'empty'},'No summary was produced.')); }
    else {
      pane.append(el('div',{class:'explain'},'Internal note for managers. \u201cDone so far\u201d only lists actions the document shows actually happened; the next step is a suggestion.'));
      pane.append(el('div',{class:'sumgrid'},
        el('div',{class:'sumbox wide'}, el('div',{class:'h'},'In one line'), s.case_overview),
        el('div',{class:'sumbox'}, el('div',{class:'h'},'Key issue'), s.key_issue),
        el('div',{class:'sumbox'}, el('div',{class:'h'},'Current status'), s.current_status),
        el('div',{class:'sumbox'}, el('div',{class:'h'},'Done so far'), s.action_taken),
        el('div',{class:'sumbox'}, el('div',{class:'h'},'Suggested next step'), s.recommended_next_action),
        el('div',{class:'sumbox wide'}, el('div',{class:'h'},'Needs review?'),
          s.review_required ? [pill('Yes','amber'), bullets(s.review_reasons)] : pill('No','green'))));
    }
  }
  if (tab==='tech'){
    pane.append(el('div',{class:'explain'},'Timing and retry details for each step, as recorded in run_manifest.json.'));
    const NAMES={ingestion:'1 \u00b7 Read document',extraction:'2 \u00b7 Extract facts (AI)',customer_email:'3 \u00b7 Draft reply (AI)',case_summary:'4 \u00b7 Manager summary (AI)'};
    pane.append(el('table',{class:'tech'}, el('tr',{},['Step','Result','AI calls','Time','Note'].map(h=>el('th',{},h))),
      Object.values(d.tasks).map(t=>el('tr',{}, el('td',{},NAMES[t.name]||t.name), el('td',{},cap(t.status)),
        el('td',{},t.name==='ingestion'?'\u2013':(t.attempts||'\u2013')), el('td',{},t.duration_seconds!=null?t.duration_seconds.toFixed(2)+'s':'\u2013'),
        el('td',{},t.skip_reason?cap(t.skip_reason):(t.error_code||(t.corrected?'Fixed after one correction':'')))))));
    pane.append(el('p',{class:'small'},`Document ID: ${r.document_id}`));
  }
}

$('#foot').textContent = `Run ${M.run_id} \u00b7 ${new Date(M.started_at).toLocaleString()} \u00b7 ${M.provider.is_mock?'demo mode':M.provider.model} \u00b7 ` +
  `${M.llm.total_provider_calls} AI calls, at most ${M.llm.peak_in_flight} at once (limit ${M.llm.concurrency_limit}) \u00b7 Files: final_report.csv, run_manifest.json`;
renderTiles(); renderList();
selected = groups.review[0] || groups.ready[0] || DOCS[0];
if (selected){ renderList(); renderDetail(); }
</script>
</body>
</html>
"""
