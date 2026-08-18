"""render_arch.py — architecture graph -> self-contained Miller-columns HTML.

Pure renderer: embeds the graph as JSON and ships a small vanilla-JS Miller-columns
UI (Finder-style click-through). No CDN, no build step. Palette matches
validators/framework_health so the explorer reads as a sibling of the health dashboard.
"""
from __future__ import annotations

import html
import json


def render_html(graph: dict) -> str:
    data_json = json.dumps(graph, separators=(",", ":"))
    s = graph["summary"]
    ov = graph.get("health_overlay_at")
    ov_note = (f'· health status overlaid ({html.escape(str(ov)[:10])})' if ov
               else '· no health overlay (status dots hidden)')
    subtitle = (f'{s["n_skills"]} skills · {s["n_cards"]} cards '
                f'({s["n_verdict_bearing_cards"]} verdict-bearing) · '
                f'{s["n_datasets"]} datasets ({s["n_datasets_in_catalog"]} in catalog) · '
                f'{s["n_resolvers"]} resolvers / {s["n_verdicts"]} verdicts {ov_note}')
    shas = graph.get("root_shas", {})
    sha_note = " · ".join(f'{k}@{v}' for k, v in shas.items() if v)
    return (
        _HTML_HEAD
        .replace("__SUBTITLE__", html.escape(subtitle))
        .replace("__GEN__", html.escape(str(graph.get("generated_at", ""))[:19]))
        .replace("__SHAS__", html.escape(sha_note))
        + "<script>\nconst DATA = " + data_json + ";\n" + _JS + "\n</script>\n</body></html>"
    )


_HTML_HEAD = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Framework Architecture Explorer</title>
<style>
:root{--bg:#f7f6f1;--card:#fff;--ink:#0b0b0b;--muted:#52514e;--line:#e1e0d9;--zebra:#faf9f5;
 --green:#0ca30c;--amber:#fab219;--red:#c0392b;--grey:#898781;--purple:#6c5aa8;--teal:#199e70;--ink2:#52514e}
*{box-sizing:border-box}
body{margin:0;font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#0b0b0b;color:#fff;padding:11px 22px}
header h1{margin:0;font-size:16px;display:inline}
header .meta{color:#b9b8b1;font-size:11px;margin-left:10px}
header .orient{color:#9b9a93;font-size:11px;margin-top:4px}
.toolbar{display:flex;align-items:center;gap:14px;padding:8px 22px;background:var(--card);
 border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10;flex-wrap:wrap}
.modebtns{display:flex;gap:0;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.modebtn{padding:5px 13px;cursor:pointer;font-weight:600;font-size:12px;background:#fff;color:var(--muted);border:none}
.modebtn.active{background:#0b0b0b;color:#fff}
.search{flex:1;min-width:160px;max-width:340px;padding:5px 10px;border:1px solid var(--line);border-radius:6px;font-size:12px}
.crumbs{font-size:11px;color:var(--muted)}
.crumbs b{color:var(--ink)}
.legend{font-size:11px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.legend .dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle}
#miller{display:flex;height:calc(100vh - 118px);overflow-x:auto;background:var(--bg)}
.col{min-width:270px;max-width:270px;border-right:1px solid var(--line);overflow-y:auto;background:var(--card);flex:0 0 auto}
.col.detail{min-width:430px;max-width:460px;background:#fffdf8}
.col.wide{min-width:340px;max-width:360px}
.colhdr{position:sticky;top:0;background:#52514e;color:#fff;font-size:11px;font-weight:600;
 padding:6px 12px;z-index:2;letter-spacing:.02em}
.colhdr .sub{color:#cfcec7;font-weight:400}
.grp{background:#e1e0d9;font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;
 color:#4a4945;padding:4px 12px;position:sticky;top:24px}
.item{padding:6px 12px;border-bottom:1px solid #f0efe9;cursor:pointer;display:flex;align-items:center;gap:6px;justify-content:space-between}
.item:hover{background:#eef0f5}
.item.sel{background:#e7ecf7;box-shadow:inset 3px 0 0 var(--purple)}
.item .nm{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .rt{display:flex;gap:4px;align-items:center;flex:0 0 auto}
.item .arrow{color:#c0bfb8;font-size:11px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:0 0 auto}
.chip{display:inline-block;padding:1px 6px;border-radius:9px;color:#fff;font-size:9.5px;font-weight:600;white-space:nowrap}
.chip.sm{font-size:9px;padding:0 5px}
.chip.out{background:transparent;border:1px solid var(--line);color:var(--muted)}
/* detail panel */
.det{padding:12px 16px}
.det h2{font-size:14px;margin:0 0 2px}
.det .q{color:var(--ink2);font-style:italic;margin:0 0 10px;font-size:12.5px;line-height:1.5}
.det .metarow{font-size:11px;color:var(--muted);margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap}
.sect{margin:12px 0 4px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:#4a4945;
 border-bottom:1px solid var(--line);padding-bottom:3px}
.dschip{display:inline-flex;align-items:center;gap:5px;background:#f2f1ea;border:1px solid var(--line);
 border-radius:6px;padding:3px 8px;margin:2px 4px 2px 0;font-size:11.5px;cursor:pointer}
.dschip:hover{background:#e7ecf7}
.dschip.bad{border-color:var(--red)}
.kv{font-size:11.5px;margin:2px 0}.kv b{color:#4a4945}
.enumbox{margin:3px 0 8px}
.enumbox .fld{font-weight:600;font-size:11.5px;color:#333}
.fldlist{margin:2px 0 8px;padding:0;list-style:none;font-size:11.5px;column-count:2;column-gap:14px}
.fldlist li{margin:1px 0;break-inside:avoid}
.rule{border:1px solid var(--line);border-radius:6px;padding:6px 9px;margin:5px 0;background:#fff}
.rule .rid{font-weight:600;font-size:11.5px;font-family:ui-monospace,Menlo,monospace}
.rule .cond{font-size:11px;color:var(--muted);margin:2px 0}
.rule .verdicts{margin-top:3px}
.caveat{font-size:11px;color:var(--muted);margin:3px 0;padding-left:12px;position:relative}
.caveat:before{content:"•";position:absolute;left:0;color:#b0afa8}
details{margin:4px 0}details>summary{cursor:pointer;font-size:11px;color:var(--purple);font-weight:600}
code{background:#eceae2;padding:0 4px;border-radius:3px;font-family:ui-monospace,Menlo,monospace;font-size:10.5px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;word-break:break-all}
.empty{padding:20px 14px;color:#b0afa8;font-size:12px;font-style:italic}
.pill{display:inline-block;background:#eef0f5;border:1px solid var(--line);border-radius:9px;
 padding:1px 8px;font-size:10.5px;margin:2px 3px 2px 0;cursor:pointer;color:#3a3a3a}
.pill:hover{background:#e7ecf7}
</style></head><body>
<header><h1>Framework Architecture Explorer</h1><span class="meta">__SUBTITLE__</span>
<div class="orient">Click through the wiring: <b>skill → cards → datasets · methods · outputs · rules → verdict</b>. Companion to the health dashboard (this shows what's <i>wired</i>, not what's <i>live</i>). Generated __GEN__ · __SHAS__</div>
</header>
<div class="toolbar">
  <div class="modebtns">
    <button class="modebtn active" id="mode-skill" onclick="setMode('skill')">Skill-first</button>
    <button class="modebtn" id="mode-dataset" onclick="setMode('dataset')">Dataset-first</button>
  </div>
  <input class="search" id="search" placeholder="filter first column…" oninput="onSearch()">
  <div class="crumbs" id="crumbs"></div>
  <div class="legend" id="legend"></div>
</div>
<div id="miller"></div>
"""


_JS = r"""
// ---- palette + helpers ---------------------------------------------------
const C={green:'#0ca30c',amber:'#fab219',red:'#c0392b',grey:'#898781',purple:'#6c5aa8',teal:'#199e70',dark:'#52514e'};
const HEALTH={production_ready:C.green,ready_unproven:C.teal,partial:C.amber,placeholder:C.grey,
  broken_or_drift:C.red,live:C.green,blocked:'#b8860b',broken:C.red};
const STATUS={wired:C.green,partial:C.amber,placeholder:C.grey,not_wired:C.grey,unknown:C.grey};
function esc(x){return (x==null?'':String(x)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function dot(color,t){return '<span class="dot" style="background:'+color+'" title="'+esc(t||'')+'"></span>';}
function chip(t,color,cls){return '<span class="chip '+(cls||'')+'" style="background:'+color+'">'+esc(t)+'</span>';}
function healthDot(v){if(!v)return '';return dot(HEALTH[v]||C.grey,'health: '+v);}
function fmtBytes(n){if(!n)return '—';const u=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++;}return n.toFixed(n<10&&i>0?1:0)+' '+u[i];}

let MODE='skill';
const miller=document.getElementById('miller');
let path=[];  // array of {level, key} describing current selection chain

// ---- column primitives ---------------------------------------------------
function clearFrom(level){ // remove columns at >= level
  [...miller.children].forEach(c=>{if(+c.dataset.level>=level)c.remove();});
  path=path.filter(p=>p.level<level);
}
function addCol(level,cls,hdr,bodyHTML){
  clearFrom(level);
  const col=document.createElement('div');
  col.className='col '+(cls||''); col.dataset.level=level;
  col.innerHTML='<div class="colhdr">'+hdr+'</div>'+bodyHTML;
  miller.appendChild(col);
  col.scrollIntoView({behavior:'smooth',inline:'end',block:'nearest'});
  return col;
}
function markSel(level,key){
  const col=[...miller.children].find(c=>+c.dataset.level===level);
  if(!col)return;
  col.querySelectorAll('.item').forEach(el=>el.classList.toggle('sel',el.dataset.key===key));
}
function item(key,name,left,right,onclick){
  return '<div class="item" data-key="'+esc(key)+'" onclick="'+onclick+'">'+
    '<span class="nm">'+left+esc(name)+'</span><span class="rt">'+(right||'')+'<span class="arrow">›</span></span></div>';
}

// ---- SKILL-FIRST ----------------------------------------------------------
function skillRight(s){
  let r='';
  (s.gates||[]).slice(0,2).forEach(g=>{r+=chip(g,C.dark,'sm');});
  r+=chip(s.status,STATUS[s.status]||C.grey,'sm');
  r+=healthDot(s.health);
  return r;
}
function renderSkills(filter){
  const names=Object.keys(DATA.skills).sort();
  const root=DATA.skills['target-profile'];
  const fan=DATA.fanout||[];
  const others=names.filter(n=>n!=='target-profile'&&!fan.includes(n));
  const f=(filter||'').toLowerCase();
  const match=n=>!f||n.toLowerCase().includes(f);
  let b='';
  if(root&&match('target-profile')){
    b+='<div class="grp">Composed root</div>';
    b+=item('target-profile','target-profile',dot(C.purple,'composed'),skillRight(root),"selSkill('target-profile')");
  }
  const fanM=fan.filter(match);
  if(fanM.length){b+='<div class="grp">Fan-out skills ('+fan.length+')</div>';
    fanM.forEach(n=>{const s=DATA.skills[n];if(s)b+=item(n,n,'',skillRight(s),"selSkill('"+n+"')");});}
  const othM=others.filter(match);
  if(othM.length){b+='<div class="grp">Other skills ('+others.length+')</div>';
    othM.forEach(n=>{const s=DATA.skills[n];if(s)b+=item(n,n,'',skillRight(s),"selSkill('"+n+"')");});}
  addCol(0,'','Skills <span class="sub">— click to open its cards</span>',b||'<div class="empty">no match</div>');
}
function selSkill(name){
  markSel(0,name);
  const s=DATA.skills[name];
  path=[{level:0,key:name}];
  let b='';
  if(s.is_composed_root&&s.fanout.length){
    b+='<div class="grp">Composes '+s.fanout.length+' sub-skills</div><div style="padding:6px 12px">';
    s.fanout.forEach(n=>{b+='<span class="pill" onclick="selSkill(\''+n+'\')">'+esc(n)+'</span>';});
    b+='</div>';
  }
  const vb=s.verdict_bearing_cards||[], disp=s.display_cards||[];
  if(vb.length){b+='<div class="grp">Verdict-bearing cards ('+vb.length+')</div>';
    vb.forEach(cid=>b+=cardItem(cid));}
  if(disp.length){b+='<div class="grp">Display / additive cards ('+disp.length+')</div>';
    disp.forEach(cid=>b+=cardItem(cid));}
  if(!vb.length&&!disp.length)b+='<div class="empty">no cards declared</div>';
  const sub='v'+esc(s.version||'?')+' · '+esc(s.status)+(s.gates.length?' · gate: '+esc(s.gates.join(', ')):'');
  addCol(1,'wide',esc(name)+' <span class="sub">'+sub+'</span>',b);
}
function cardItem(cid){
  const c=DATA.cards[cid];
  if(!c)return item(cid,cid,dot(C.red,'no card yaml'),chip('missing',C.red,'sm'),"void(0)");
  let right='';
  if(c.verdicts&&c.verdicts.length)right+=chip(c.verdicts.length+'▸verdict',C.purple,'sm');
  right+=healthDot(c.health);
  return item(cid,cid,'',right,"selCard('"+cid+"',1)");
}

// ---- CARD DETAIL ----------------------------------------------------------
function selCard(cid,fromLevel){
  markSel(fromLevel,cid);
  const c=DATA.cards[cid];
  const lvl=fromLevel+1;
  if(!c){addCol(lvl,'detail','card','<div class="empty">no card yaml on disk</div>');return;}
  let b='<div class="det">';
  b+='<h2>'+esc(c.card_id)+' '+(c.health?healthDot(c.health):'')+'</h2>';
  b+='<p class="q">'+esc(c.question||'—')+'</p>';
  b+='<div class="metarow">'+
     'v'+esc(c.version||'?')+
     (c.measurement_type?' · <b>'+esc(c.measurement_type)+'</b>':'')+
     (c.measurement?' · '+esc(c.measurement):'')+
     (c.sample_context?' · '+esc(c.sample_context):'')+
     (c.entity_grains&&c.entity_grains.length?' · grains: '+esc(c.entity_grains.join(', ')):'')+
     '</div>';
  // DATASETS
  b+='<div class="sect">Input datasets ('+c.datasets.length+')</div>';
  if(c.datasets.length){c.datasets.forEach(d=>{
    const ok=d.in_catalog; const mk=ok?'✓':'✗';
    const fam=d.family&&d.family.is_family;
    let extra='';
    if(fam)extra+=' '+chip('▦ '+d.family.count+' indications',C.teal,'sm');
    else if(d.kind)extra+=' '+chip(d.kind,C.grey,'sm');
    if(d.resolution==='non-manifest resource')extra+=' '+chip('non-manifest',C.amber,'sm');
    if(!ok&&d.gap_category)extra+=' '+chip(d.gap_category,C.red,'sm');
    b+='<span class="dschip'+(ok?'':' bad')+'" onclick="selDataset(\''+esc(d.product_id)+'\','+lvl+')">'+
       '<span style="color:'+(ok?C.green:C.red)+'">'+mk+'</span> '+esc(d.product_id)+extra+'</span>';
  });}else b+='<div class="empty">no required_inputs declared</div>';
  // METHODS
  b+='<div class="sect">Methods</div>';
  if(c.methods.length){c.methods.forEach(m=>{
    b+='<div class="kv"><code>'+esc(m.call)+'</code>';
    const ak=Object.keys(m.args||{});
    if(ak.length)b+=' <span style="color:#999">('+esc(ak.join(', '))+')</span>';
    b+='</div>';});}else b+='<div class="empty">—</div>';
  // OUTPUTS
  b+='<div class="sect">Outputs — summary fields ('+c.summary_fields.length+')</div>';
  if(c.summary_fields.length){b+='<ul class="fldlist">';
    c.summary_fields.forEach(f=>b+='<li>'+esc(f)+'</li>');b+='</ul>';}
  else b+='<div class="empty">—</div>';
  const vk=Object.keys(c.vocabulary||{});
  if(vk.length){b+='<div class="sect">Controlled vocabularies</div>';
    vk.forEach(fld=>{b+='<div class="enumbox"><span class="fld">'+esc(fld)+':</span> ';
      (c.vocabulary[fld]||[]).forEach(v=>b+=chip(v,C.dark,'sm')+' ');b+='</div>';});}
  if(c.figures.length){b+='<div class="sect">Figures ('+c.figures.length+')</div>';
    c.figures.forEach(f=>b+='<div class="kv">'+(f.primary?'★ ':'')+'<b>'+esc(f.id)+'</b> <code>'+esc(f.type)+'</code><br><span style="color:#777">'+esc(f.description)+'</span></div>');}
  // RULES -> VERDICT
  b+='<div class="sect">Rules → verdict</div>';
  if(c.rules&&c.rules.length){
    c.rules.forEach(r=>{
      b+='<div class="rule"><span class="rid">'+esc(r.rule_id)+'</span> '+chip(r.axis,C.grey,'sm')+(r.is_killer?' '+chip('killer',C.red,'sm'):'');
      let cond=esc(r.field||'');
      const ck=Object.keys(r.condition||{});
      if(ck.length)cond+=' '+ck.map(k=>esc(k)+' '+esc(JSON.stringify(r.condition[k]))).join(', ');
      b+='<div class="cond">when '+cond+'</div>';
      const sg=r.signals||{};const sk=Object.keys(sg);
      if(sk.length)b+='<div class="cond">signals: '+sk.map(k=>esc(k)+'='+esc(sg[k])).join(' · ')+'</div>';
      if(r.verdicts&&r.verdicts.length){b+='<div class="verdicts">→ ';
        r.verdicts.forEach(v=>b+=chip(v.gate+': '+v.verdict,C.purple,'sm')+' ');b+='</div>';}
      b+='</div>';
    });
  }else b+='<div class="empty">verdict-inert — no rule reads this card (display / additive context only)</div>';
  // thresholds / warnings / caveats
  const tk=Object.keys(c.thresholds||{});
  if(tk.length){b+='<details><summary>Thresholds ('+tk.length+')</summary>';
    tk.forEach(k=>b+='<div class="kv"><b>'+esc(k)+':</b> '+esc(JSON.stringify(c.thresholds[k]))+'</div>');b+='</details>';}
  if(c.warning_predicates&&c.warning_predicates.length){b+='<details><summary>Warning predicates ('+c.warning_predicates.length+')</summary>';
    c.warning_predicates.forEach(w=>b+='<div class="kv"><b>'+esc(w.warning_id)+'</b> — <code>'+esc(w['if'])+'</code></div>');b+='</details>';}
  if(c.caveats&&c.caveats.length){b+='<details><summary>Caveats ('+c.caveats.length+')</summary>';
    c.caveats.forEach(cv=>b+='<div class="caveat">'+esc(cv)+'</div>');b+='</details>';}
  // consumers
  if(c.consumers&&c.consumers.length){b+='<div class="sect">Consumed by skills ('+c.consumers.length+')</div>';
    c.consumers.forEach(n=>b+='<span class="pill" onclick="setMode(\'skill\');selSkill(\''+n+'\')">'+esc(n)+'</span>');}
  b+='</div>';
  addCol(lvl,'detail','Card detail',b);
}

// ---- DATASET DETAIL -------------------------------------------------------
function selDataset(pid,fromLevel){
  const d=DATA.datasets[pid];
  const lvl=fromLevel+1;
  if(!d){addCol(lvl,'detail','dataset','<div class="empty">unknown product_id</div>');return;}
  let b='<div class="det"><h2>'+esc(pid)+'</h2>';
  const resColor={'manifest':C.green,'non-manifest resource':C.amber,'uncataloged':C.red}[d.resolution]||C.grey;
  b+='<div class="metarow">'+(d.in_catalog?chip('in catalog',C.green):chip('NOT in catalog',C.red))+
     ' '+chip(d.resolution||'?',resColor,'sm')+
     (d.kind?' '+chip(d.kind,C.grey):'')+(d.matched_by==='prefix'?' '+chip('prefix→'+esc(d.resolved_id),C.amber,'sm'):'')+'</div>';
  if(d.family&&d.family.is_family){
    b+='<div class="sect">Indication family — reader resolves <code>{indication}-'+esc(d.family.stem)+'</code></div>';
    b+='<div class="kv">This card pins <b>'+esc(pid)+'</b> as one example; the catalog has <b>'+d.family.count+
       '</b> indication siblings (reader substitutes <code>{indication}</code> at runtime — NOT single-indication):</div>';
    b+='<div style="margin:4px 0">';d.family.members.forEach(m=>b+=chip(m,C.teal,'sm')+' ');b+='</div>';
  }
  if(!d.in_catalog&&d.gap_note){
    b+='<div class="sect">Why uncataloged'+(d.gap_category?' · '+esc(d.gap_category):'')+'</div>';
    b+='<p class="q">'+esc(d.gap_note)+'</p>';
  }
  if(d.description)b+='<p class="q">'+esc(d.description)+'</p>';
  const row=(k,v)=>v?('<div class="kv"><b>'+k+':</b> '+v+'</div>'):'';
  b+=row('resolved id',esc(d.resolved_id));
  b+=row('provider',esc(d.provider));
  b+=row('version',esc(d.version));
  b+=row('format',esc(d.format));
  b+=row('size',fmtBytes(d.size_bytes));
  b+=row('sort key',d.sort_key?('<code>'+esc(JSON.stringify(d.sort_key))+'</code>'):'');
  b+=row('S3 URI',d.s3_uri?('<span class="mono">'+esc(d.s3_uri)+'</span>'):'');
  b+=row('license',d.license?('<span style="font-size:11px">'+esc(String(d.license).slice(0,240))+'</span>'):'');
  b+=row('manifest',d.manifest_path?('<code>'+esc(d.manifest_path)+'</code>'):'');
  if(d.derived_from&&d.derived_from.length){b+='<div class="sect">Lineage — derived from</div>';
    d.derived_from.forEach(x=>b+='<span class="pill" onclick="setMode(\'dataset\');selDatasetList();selDataset(\''+esc(x)+'\',0)">'+esc(x)+'</span>');}
  if(d.consumed_by_cards&&d.consumed_by_cards.length){b+='<div class="sect">Consumed by cards ('+d.consumed_by_cards.length+')</div>';
    d.consumed_by_cards.forEach(cid=>b+='<span class="pill" onclick="selCard(\''+esc(cid)+'\','+lvl+')">'+esc(cid)+'</span>');}
  if(d.consumed_by_skills&&d.consumed_by_skills.length){b+='<div class="sect">…reaching skills ('+d.consumed_by_skills.length+')</div>';
    d.consumed_by_skills.forEach(n=>b+='<span class="pill" onclick="setMode(\'skill\');selSkill(\''+esc(n)+'\')">'+esc(n)+'</span>');}
  b+='</div>';
  addCol(lvl,'detail','Dataset detail',b);
}

// ---- DATASET-FIRST --------------------------------------------------------
function renderDatasetList(filter){
  const ds=Object.values(DATA.datasets);
  const f=(filter||'').toLowerCase();
  const match=d=>!f||d.product_id.toLowerCase().includes(f);
  const consumed=ds.filter(d=>d.in_catalog&&d.consumed_by_cards.length).filter(match)
                   .sort((a,b)=>(b.size_bytes||0)-(a.size_bytes||0));
  const broken=ds.filter(d=>!d.in_catalog).filter(match).sort((a,b)=>a.product_id<b.product_id?-1:1);
  let b='';
  if(broken.length){b+='<div class="grp">Referenced, not in catalog ('+broken.length+')</div>';
    broken.forEach(d=>b+=dsItem(d));}
  b+='<div class="grp">In catalog · consumed ('+consumed.length+') — heaviest first</div>';
  consumed.forEach(d=>b+=dsItem(d));
  addCol(0,'wide','Datasets <span class="sub">— click to see cards it feeds</span>',b||'<div class="empty">no match</div>');
}
function dsItem(d){
  let r='';
  if(d.family&&d.family.is_family)r+=chip('▦'+d.family.count,C.teal,'sm');
  if(d.resolution==='non-manifest resource')r+=chip('non-manifest',C.amber,'sm');
  if(!d.in_catalog&&d.gap_category)r+=chip(d.gap_category,C.red,'sm');
  if(d.size_bytes)r+=chip(fmtBytes(d.size_bytes),C.grey,'sm');
  r+=chip(d.consumed_by_cards.length+' cards',C.dark,'sm');
  const left=d.in_catalog?'<span style="color:'+C.green+'">✓</span> ':'<span style="color:'+C.red+'">✗</span> ';
  return item(d.product_id,d.product_id,left,r,"selDatasetCards('"+d.product_id.replace(/'/g,"")+"')");
}
function selDatasetCards(pid){
  markSel(0,pid);
  const d=DATA.datasets[pid];
  let b='';
  b+='<div class="grp">Cards reading this dataset ('+d.consumed_by_cards.length+')</div>';
  if(d.consumed_by_cards.length)d.consumed_by_cards.forEach(cid=>b+=cardItem(cid));
  else b+='<div class="empty">no card consumes this</div>';
  addCol(1,'wide',esc(pid),b);
  // also show dataset detail immediately at level 2 for convenience
  selDataset(pid,1);
}

// ---- mode / search / boot -------------------------------------------------
function setMode(m){
  if(m===MODE&&miller.children.length)return;
  MODE=m;
  document.getElementById('mode-skill').classList.toggle('active',m==='skill');
  document.getElementById('mode-dataset').classList.toggle('active',m==='dataset');
  document.getElementById('search').value='';
  clearFrom(0);
  if(m==='skill')renderSkills();else renderDatasetList();
}
function onSearch(){
  const v=document.getElementById('search').value;
  if(MODE==='skill')renderSkills(v);else renderDatasetList(v);
}
function renderLegend(){
  const L=document.getElementById('legend');
  L.innerHTML=
    '<span>'+dot(C.green)+'wired/live</span>'+
    '<span>'+dot(C.amber)+'partial</span>'+
    '<span>'+dot(C.grey)+'placeholder</span>'+
    '<span>'+dot(C.red)+'broken/drift</span>'+
    '<span>'+chip('verdict',C.purple,'sm')+'</span>';
}
renderLegend();
setMode('skill');
"""
