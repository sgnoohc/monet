"""Grading page: scoring controls, full-screen viewer, keyboard navigation."""
from .ui_style import TOKENS

CSS = TOKENS + """
.bar{position:sticky;top:0;z-index:40;background:var(--card);
 border-bottom:1px solid var(--line)}
.bar .in{max-width:1500px;margin:0 auto;padding:9px 16px;display:flex;gap:10px;
 align-items:center;flex-wrap:wrap}
.stat{color:var(--mut);font-variant-numeric:tabular-nums}
.stat b{color:var(--ink)}
.layout{max-width:1500px;margin:0 auto;display:grid;grid-template-columns:230px 1fr;
 gap:18px;padding:16px}
.nav{position:sticky;top:56px;height:calc(100vh - 72px);overflow:auto;
 background:var(--card);border:1px solid var(--line);border-radius:10px;padding:7px}
.nav ol{list-style:none;margin:0;padding:0;counter-reset:n}
.navsort{display:flex;gap:5px;margin:0 0 6px;position:sticky;top:-7px;z-index:2;
 background:var(--card);padding:0 0 6px;border-bottom:1px solid var(--line2)}
.navsort select{flex:1;min-width:0;font-size:12px;padding:3px 6px}
.navsort button{padding:2px 8px;font-size:13px}
.nav li{display:flex;justify-content:space-between;gap:6px;padding:5px 8px;
 border-radius:6px;cursor:pointer;font-size:12.5px;align-items:center}
.nav li:hover{background:var(--bg)}
.nav li.on{background:var(--sel);color:#fff}
.nav li .s{font-variant-numeric:tabular-nums;color:var(--mut);white-space:nowrap}
.nav li.on .s{color:#dbe8f7}
.nav li.flag{outline:1px solid var(--bl)}
.nav li.done .s{color:var(--ok)}
.nav li.on.done .s{color:#bff0d5}
.stu{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px 16px;margin-bottom:14px;display:none}
.stu.cur{display:block}
.pager{display:flex;gap:10px;align-items:center;margin-bottom:12px}
.pager .pos{color:var(--mut);font-variant-numeric:tabular-nums}
.nav li.hide{display:none}
.shd{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.nm{font-size:17px;font-weight:650}
.badge{font-size:11.5px;color:var(--mut)}
.badge.flag{color:var(--bl);background:var(--blbg);border-radius:99px;padding:1px 8px}
.tot{margin-left:auto;font-variant-numeric:tabular-nums;font-size:15px}
.tot .pct{color:var(--mut);margin-left:6px}
.tot b{font-size:20px}
.tot.edited{color:var(--acc)}
.idrow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:9px 0 3px}
.idrow img{height:34px;width:auto;border:1px solid var(--line);border-radius:6px;
 background:#fff;cursor:zoom-in}
.idrow input{width:210px}
.pagelinks{display:flex;gap:8px;align-items:center;margin-left:auto}
.pagelinks a.paper{color:var(--acc);text-decoration:none;font-size:12.5px;white-space:nowrap}
.pagelinks a.paper:hover{text-decoration:underline}
.part{display:grid;grid-template-columns:220px 1fr 260px;gap:14px;align-items:start;
 padding:11px 0;border-top:1px solid var(--line2)}
.part.focus{background:var(--bg);border-radius:8px;
 box-shadow:inset 3px 0 0 var(--acc);padding-left:9px}
.part.v-correct .pl .t::before{content:"";display:inline-block;width:9px;height:9px;
 border-radius:50%;background:var(--ok);margin-right:7px;vertical-align:middle}
.part.v-wrong .pl .t::before{content:"";display:inline-block;width:9px;height:9px;
 border-radius:50%;background:var(--no);margin-right:7px;vertical-align:middle}
.part.v-unsure .pl .t::before{content:"";display:inline-block;width:9px;height:9px;
 border-radius:50%;background:var(--bl);margin-right:7px;vertical-align:middle}
.part.v-correct{background:linear-gradient(90deg,var(--okbg),transparent 38%)}
.part.v-wrong{background:linear-gradient(90deg,var(--nobg),transparent 38%)}
.part.v-unsure{background:linear-gradient(90deg,var(--blbg),transparent 38%)}
.read{font-size:11.5px;color:var(--mut);margin-top:3px;overflow-wrap:anywhere}
.read b{font-weight:600;color:var(--ink)}
.vtag{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;font-weight:700}
.v-correct .vtag{color:var(--ok)}.v-wrong .vtag{color:var(--no)}
.v-unsure .vtag{color:var(--bl)}
.pl .t{font-weight:600;font-size:13px}
.pl .k{color:var(--mut);font-size:11.5px;margin-top:2px}
.shots{display:flex;flex-wrap:wrap;gap:8px;min-width:0}
.shots img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;
 background:#fff;cursor:zoom-in}
.sc{display:flex;flex-direction:column;gap:6px;align-items:flex-end}
.spin{display:flex;align-items:center}
.spin button{border-radius:0;width:30px;padding:5px 0}
.spin button:first-child{border-radius:7px 0 0 7px}
.spin button:last-child{border-radius:0 7px 7px 0;border-left:none}
.spin input{width:60px;border-radius:0;border-left:none;border-right:none;padding:5px 2px}
.spin .of{color:var(--mut);font-size:12px;margin-left:7px;white-space:nowrap}
.chips{display:flex;gap:4px}
.chips button{padding:3px 9px;font-size:12px;border-radius:99px}
.chips button.on{background:var(--sel);border-color:var(--sel);color:#fff}
.foot{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
.foot input[type=text]{flex:1;min-width:220px}
details.pts{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:10px 14px;margin-bottom:14px}
details.pts summary{cursor:pointer;font-weight:600}
.ptsgrid{display:grid;gap:6px;margin-top:10px}
.ptrow{display:grid;grid-template-columns:minmax(110px,160px) auto 1fr;gap:14px;
 align-items:center;font-size:12.5px;padding:5px 0;border-top:1px solid var(--line2)}
.ptrow.all{border-top:none;padding-bottom:8px}
.ptrow .pn{font-weight:600}
.ptrow label{display:flex;gap:6px;align-items:center;color:var(--mut)}
.ptrow input[type=number]{width:64px}
.qm{display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-width:0}
.qm .mode{display:flex}
.qm .mode button{padding:2px 9px;font-size:11.5px;border-radius:0}
.qm .mode button:first-child{border-radius:6px 0 0 6px}
.qm .mode button:last-child{border-radius:0 6px 6px 0;border-left:none}
.qm .mode button.on{background:var(--ink);border-color:var(--ink);color:var(--card)}
.qm .pcts{display:flex;gap:3px;flex-wrap:wrap}
.qm .pcts button{padding:2px 0;width:44px;font-size:11.5px;border-radius:99px;
 font-variant-numeric:tabular-nums;color:var(--mut)}
.qm .pcts button.on{background:var(--sel);border-color:var(--sel);color:#fff}
.qm .pcts button.some{border-color:var(--sel);color:var(--sel)}
.qm input[type=text]{flex:1;min-width:160px}
.qm input.bad{border-color:var(--no)}
.chips{flex-wrap:wrap;justify-content:flex-end;max-width:320px}
#viewer{position:fixed;inset:0;z-index:100;background:rgba(12,12,14,.93);
 display:none;flex-direction:column}
#viewer.on{display:flex}
#viewer .vbar{display:flex;gap:10px;align-items:center;padding:9px 14px;color:#eee;
 font-size:13px;background:rgba(0,0,0,.35)}
#viewer .vbar button{background:#2a2a30;border-color:#44444c;color:#eee}
#viewer .vbar button:hover{background:#36363e}
#viewer .vstage{flex:1;overflow:hidden;position:relative;cursor:grab}
#viewer .vstage.drag{cursor:grabbing}
#vbox{position:absolute;left:0;top:0;transform-origin:0 0;display:flex;
 align-items:flex-start;gap:24px}
#viewer img{display:block;background:#fff;image-rendering:-webkit-optimize-contrast}
#viewer #vkey{display:none;outline:6px solid var(--ok)}
#viewer.key #vkey{display:block}
#vkeybtn.on{background:var(--ok)!important;border-color:var(--ok)!important;color:#fff!important}
.vhint{color:#9a9aa2;font-size:12px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .shots img,
 :root:not([data-theme="light"]) .idrow img{filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"] .shots img,:root[data-theme="dark"] .idrow img{
 filter:invert(1) hue-rotate(180deg)}
.simbtn{padding:1px 9px;font-size:11.5px;border-radius:99px;color:var(--mut);
 background:none;border:1px dashed var(--line)}
.simbtn.open{border-color:var(--sel);color:var(--sel);border-style:solid}
body.simon .layout,body.simon .bar .in{margin-right:460px}
#sim{position:fixed;top:0;right:0;bottom:0;width:450px;z-index:60;display:none;
 flex-direction:column;background:var(--card);border-left:1px solid var(--line);
 box-shadow:-6px 0 18px rgba(0,0,0,.08)}
#sim.on{display:flex}
.simhd{display:flex;gap:8px;align-items:center;padding:10px 12px 4px}
.simhd strong{font-size:14px}
.simhint{padding:0 12px 8px;border-bottom:1px solid var(--line)}
#simbody{flex:1;overflow:auto;padding:10px 12px 30px}
.sanc{background:var(--bg);border-radius:8px;padding:8px 10px;margin-bottom:10px}
.sanc .who{font-weight:600}
.sread{font-size:12px;color:var(--mut);overflow-wrap:anywhere}
.sread b{color:var(--ink);font-weight:600}
.sgrp{display:flex;align-items:center;gap:8px;margin:14px 0 6px;font-size:11.5px;
 text-transform:uppercase;letter-spacing:.04em;color:var(--mut);font-weight:650}
.sgrp button{text-transform:none;letter-spacing:0;font-weight:400;padding:2px 8px;
 font-size:11.5px;margin-left:auto}
.sit{border:1px solid var(--line);border-radius:8px;padding:7px 9px;margin-bottom:7px}
.sit.here{border-color:var(--sel);box-shadow:inset 3px 0 0 var(--sel)}
.sit .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.sit .who{font-weight:600;font-size:13px;cursor:pointer}
.sit .who:hover{color:var(--acc)}
.sit .sc2{margin-left:auto;font-variant-numeric:tabular-nums;font-size:12.5px}
.sit .sc2.diff{color:var(--bl);font-weight:650}
.sit .sim{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
.sit img{max-width:100%;max-height:70px;display:block;margin-top:5px;background:#fff;
 border:1px solid var(--line2);border-radius:4px;cursor:zoom-in}
.sit button{padding:1px 8px;font-size:11.5px;border-radius:99px}
details.srest summary{cursor:pointer;font-size:11.5px;color:var(--mut);margin:14px 0 6px;
 text-transform:uppercase;letter-spacing:.04em;font-weight:650}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .sit img{
 filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"] .sit img{filter:invert(1) hue-rotate(180deg)}
@media (max-width:1100px){body.simon .layout,body.simon .bar .in{margin-right:0}
 #sim{width:min(450px,100vw)}}
.notebtn{padding:1px 9px;font-size:11.5px;border-radius:99px;color:var(--mut);
 background:none;border:1px dashed var(--line)}
.notebtn.has{border-style:solid;color:var(--ink)}
.notebtn.open{border-color:var(--sel);color:var(--sel)}
.mist{display:flex;flex-direction:column;gap:5px;align-items:flex-end;width:100%}
.mist.hide{display:none}
.mist .tags{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end}
.mist .tag{display:inline-flex;align-items:center;background:var(--line2);
 border:1px solid var(--line);border-radius:99px;padding:1px 2px 1px 9px;font-size:12px}
.mist .tag button{border:none;background:none;padding:0 6px;color:var(--mut);cursor:pointer;
 font-size:13px;line-height:1}
.mist .tag button:hover{color:var(--no)}
.mistin{width:100%;min-width:0;font-size:12px;padding:3px 8px}
.mrow{display:grid;grid-template-columns:minmax(160px,1fr) 64px 2fr;gap:10px;
 padding:6px 0;border-top:1px solid var(--line2);font-size:12.5px;align-items:start}
.mrow .n{text-align:right;font-variant-numeric:tabular-nums;color:var(--mut)}
.mrow button{padding:2px 8px;font-size:12px;border-radius:99px;margin:0 4px 4px 0}
.mpart{font-weight:600;font-size:12.5px;margin:12px 0 2px}
.mpart:first-child{margin-top:0}
#cdlg{position:fixed;inset:0;z-index:92;background:rgba(0,0,0,.28);display:none;
 align-items:flex-start;justify-content:center;padding:80px 16px}
#cdlg.on{display:flex}
#cdlg .box{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:16px 18px;width:100%;max-width:460px;box-shadow:0 10px 40px rgba(0,0,0,.18)}
#cdlg h3{margin:0 0 4px;font-size:15px}
#cdlg .crow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:10px;font-size:12.5px}
#cdlg label{display:flex;gap:6px;align-items:center;color:var(--mut)}
#cdlg input{width:80px}
.cprev{margin-top:8px;font-size:12.5px;font-variant-numeric:tabular-nums;color:var(--mut)}
.cprev b{color:var(--ink);font-weight:600}
/* ---- stats ---- */
:root{--sq0:#c9dbef;--sq1:#6f9fd6;--sq2:#1e5fa8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --sq0:#2a4262;--sq1:#4a82c0;--sq2:#8cc0f5}}
:root[data-theme="dark"]{--sq0:#2a4262;--sq1:#4a82c0;--sq2:#8cc0f5}
#stats{position:fixed;inset:0;z-index:90;background:var(--bg);overflow:auto;display:none}
#stats.on{display:block}
#stats .in{max-width:980px;margin:0 auto;padding:18px 16px 40px}
#stats .hd{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
#stats .hd h2{font-size:18px;margin:0}
.binset{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--mut)}
.binset label{display:flex;gap:5px;align-items:center}
.binset input{width:68px}
#stfit.on{background:var(--sel);border-color:var(--sel);color:#fff}
.curve{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:10px 12px;margin:0 0 14px}
.curve.on{border-color:var(--sel)}
.curve .crow2{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}
.curve .ck{display:flex;gap:6px;align-items:center;font-weight:600}
.curve .hint{flex-basis:100%}
.cvtab table{border-collapse:collapse;margin-top:8px;font-size:12.5px;
 font-variant-numeric:tabular-nums}
.cvtab td,.cvtab th{padding:3px 12px 3px 0;text-align:right}
.cvtab th{color:var(--mut);font-weight:500}
.cvtab td:first-child,.cvtab th:first-child{text-align:left}
.tot .cv{color:var(--sel);margin-left:8px;font-size:13px}
#stats .sub{color:var(--mut);font-size:12.5px;margin:-8px 0 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:10px;
 margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px}
.tile .k{font-size:11.5px;color:var(--mut)}
.tile .v{font-size:20px;font-weight:600;margin-top:2px}
.tile .v small{font-size:12px;font-weight:400;color:var(--mut);margin-left:4px}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:12px 12px 6px;position:relative}
.chartbox h3,.parts h3{font-size:13.5px;margin:0 0 2px}
.chartbox .cap{font-size:12px;color:var(--mut);margin-bottom:6px}
.chartbox svg{display:block;width:100%;overflow:visible}
.chartbox svg text{font-size:11px;fill:var(--mut);font-variant-numeric:tabular-nums}
.chartbox svg .grid{stroke:var(--line2);stroke-width:1}
.chartbox svg .axis{stroke:var(--line);stroke-width:1}
.chartbox svg .col{fill:var(--acc)}
.chartbox svg .col.dim{opacity:.35}
.chartbox svg .hit{fill:transparent;cursor:pointer}
.chartbox svg text.capn{paint-order:stroke;stroke:var(--card);stroke-width:4px;
 stroke-linejoin:round;pointer-events:none}
.chartbox svg .ref{stroke:var(--ink);stroke-width:1.5}
.chartbox svg .ref.med{stroke:var(--mut)}
.chartbox svg text.reft{fill:var(--ink);font-weight:600}
.chartbox svg text.reft.med{fill:var(--mut)}
.binlist{margin-top:8px;font-size:12.5px;min-height:18px}
.binlist button{padding:2px 8px;font-size:12px;border-radius:99px;margin:3px 4px 0 0}
#tip{position:fixed;z-index:95;pointer-events:none;background:var(--card);
 border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;
 box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;max-width:260px}
#tip b{font-variant-numeric:tabular-nums}
.parts{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:12px;margin-top:16px}
.legend{display:flex;gap:14px;font-size:12px;color:var(--mut);margin:4px 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;
 vertical-align:-1px}
.parts table{width:100%;border-collapse:collapse}
.parts th,.parts td{padding:6px 8px;border-top:1px solid var(--line2);font-size:12.5px;
 text-align:left}
.parts th{color:var(--mut);font-weight:500;font-size:11.5px;border-top:none}
.parts td.n,.parts th.n{text-align:right;font-variant-numeric:tabular-nums}
.stack{display:flex;gap:2px;height:12px;width:100%;min-width:120px}
.stack span{display:block;height:100%;min-width:0}
.stack span:first-child{border-radius:4px 0 0 4px}
.stack span:last-child{border-radius:0 4px 4px 0}
.stack span:only-child{border-radius:4px}
.stack .z{background:var(--sq0)}.stack .p{background:var(--sq1)}.stack .f{background:var(--sq2)}
details.tbl{margin-top:8px;font-size:12.5px}
details.tbl summary{cursor:pointer;color:var(--mut)}
details.tbl table{border-collapse:collapse;margin-top:6px}
details.tbl td,details.tbl th{padding:3px 10px;border-top:1px solid var(--line2);
 font-variant-numeric:tabular-nums;text-align:right}
@media (max-width:1100px){.layout{grid-template-columns:1fr}
 .nav{position:static;height:auto}.part{grid-template-columns:1fr}
 .sc{align-items:flex-start}.tot{margin-left:0;width:100%}}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
let S={max:{},score:{},note:{},name:{},sid:{},touched:{}};
try{const r=localStorage.getItem(STORE);if(r)S=Object.assign(S,JSON.parse(r));}catch(e){}
PARTS.forEach(p=>{if(S.max[p.id]==null)S.max[p.id]=p.points;});
if(!S.chips)S.chips={};        // pid -> typed marks, for "custom"
if(!S.pcts)S.pcts={};          // pid -> percentages switched on
if(!S.qmode)S.qmode={};        // pid -> 'pct' | 'text'
const PCTS=[100,90,80,70,60,50,40,30,20,10,0], PCT_DEFAULT=[0,50,100];
// Marks typed before the percentage picker existed stay as they were.
PARTS.forEach(p=>{if(!S.qmode[p.id])S.qmode[p.id]=(S.chips[p.id]||'').trim()?'text':'pct';});
const half=x=>Math.round(x*2)/2;          // scores move in half points
const pctsOf=pid=>S.pcts[pid]||PCT_DEFAULT;
function typed(pid){
  const mx=+S.max[pid]||0, raw=(S.chips[pid]||'').trim();
  return raw?raw.split(/[\s,;]+/).map(x=>/^full$/i.test(x)?mx:/^half$/i.test(x)?Math.round(mx)/2:+x)
            .filter(x=>isFinite(x)&&x>=0&&x<=mx):[];
}
// The quick-mark buttons for one part.  Anything above the part's points is
// dropped, not clipped, so lowering the points never invents a value nobody
// typed; percentages land on the nearest half point.
function chipVals(pid){
  const mx=+S.max[pid]||0;
  let v=S.qmode[pid]==='text'?typed(pid):pctsOf(pid).map(p=>mx*p/100);
  if(!v.length)v=[0,Math.round(mx)/2,mx];
  return [...new Set(v.map(half))].sort((a,b)=>a-b);
}
function paintPicker(pid){
  const box=$('.qm[data-pid="'+pid+'"]'), mx=+S.max[pid]||0, on=pctsOf(pid);
  const mode=S.qmode[pid];
  box.innerHTML=`<span class="mode"><button data-mode="pct" class="${mode==='pct'?'on':''}">%</button>`
    +`<button data-mode="text" class="${mode==='text'?'on':''}">custom</button></span>`
    +(mode==='pct'
      ? '<span class="pcts">'+PCTS.map(p=>`<button data-pct="${p}" class="${on.includes(p)?'on':''}"`
          +` title="${p}% = ${half(mx*p/100)} of ${mx}">${p}%</button>`).join('')+'</span>'
      : `<input type="text" placeholder="0, 5, 10, 12, ${mx}" value="${String(S.chips[pid]||'').replace(/"/g,'&quot;')}">`);
  const inp=$('input',box); if(inp)markBad(pid,inp);
}
function markBad(pid,inp){
  // Red when nothing typed is usable, so a typo does not silently fall back.
  inp.classList.toggle('bad',!!inp.value.trim()&&!typed(pid).length);
}
function paintAll(){
  // "All parts": on where every part has it, outlined where only some do.
  const box=$('#qmall');
  box.innerHTML='<span class="pcts">'+PCTS.map(p=>{
    const ps=PARTS.filter(q=>S.qmode[q.id]==='pct');
    const n=ps.filter(q=>pctsOf(q.id).includes(p)).length;
    return `<button data-allpct="${p}" class="${ps.length&&n===ps.length?'on':n?'some':''}">${p}%</button>`;
  }).join('')+'</span>';
}
function setPcts(pid,list){
  S.pcts[pid]=[...new Set(list)].sort((a,b)=>b-a); S.qmode[pid]='pct';
  paintPicker(pid); paintChips(pid);
}
function paintChips(pid){
  const vals=chipVals(pid), mx=+S.max[pid]||0;
  $$('.chips[data-pid="'+pid+'"]').forEach(c=>{
    const k=c.closest('.stu').dataset.k, cur=+S.score[k][pid];
    c.innerHTML=vals.map(v=>`<button data-pid="${pid}" data-v="${v}"`
      +` class="${Math.abs(v-cur)<1e-9?'on':''}">${v===mx&&mx>0?'full':v}</button>`).join('');
  });
}
// Mistake notes: S.tags[sheet][part] = ["forgot the sign", ...].  Kept per
// answer so the aggregate can always lead back to the paper it came from.
if(!S.tags)S.tags={};
const tagsOf=(k,pid)=>((S.tags[k]||{})[pid]||[]);
const tkey=t=>t.trim().toLowerCase().replace(/\s+/g,' ');
function allTags(pid,sheets=DATA){
  const m=new Map();
  sheets.forEach(s=>tagsOf(s.k,pid).forEach(t=>{
    const key=tkey(t); if(!m.has(key))m.set(key,{label:t,who:[]});
    m.get(key).who.push(s);
  }));
  return [...m.values()].sort((a,b)=>b.who.length-a.who.length||a.label.localeCompare(b.label));
}
function paintTags(k,pid){
  const box=$('#p_'+k+'_'+pid+' .mist .tags'); if(!box)return;
  const n=tagsOf(k,pid).length, btn=$('#p_'+k+'_'+pid+' .notebtn');
  btn.textContent=n?'notes · '+n:'note'; btn.classList.toggle('has',!!n);
  box.innerHTML=tagsOf(k,pid).map((t,i)=>`<span class="tag">${esc(t)}`
    +`<button data-rm="${i}" title="remove this note" aria-label="remove">×</button></span>`).join('');
}
// The notes stay folded away until asked for, so the card reads as before.
function toggleNotes(k,pid,open){
  const part=$('#p_'+k+'_'+pid), box=$('.mist',part);
  open=open==null?box.classList.contains('hide'):open;
  box.classList.toggle('hide',!open); $('.notebtn',part).classList.toggle('open',open);
  if(open)$('.mistin',part).focus();
}
function refreshList(pid){
  $('#ml_'+pid).innerHTML=allTags(pid).map(x=>`<option value="${esc(x.label)}">`).join('');
}
function addTag(k,pid,t){
  t=t.trim().replace(/\s+/g,' '); if(!t)return;
  // Same wording as an earlier note, whatever the case, so the two group.
  const seen=allTags(pid).find(x=>tkey(x.label)===tkey(t)); if(seen)t=seen.label;
  S.tags[k]=S.tags[k]||{}; const l=S.tags[k][pid]=S.tags[k][pid]||[];
  if(!l.some(x=>tkey(x)===tkey(t)))l.push(t);
  S.touched[k]=true; paintTags(k,pid); refreshList(pid); paint(k); save();
}
function rmTag(k,pid,i){
  tagsOf(k,pid).splice(i,1); paintTags(k,pid); refreshList(pid); save();
}
// AUTO is keyed by the sheet's folder (Name__sheet004 when flagged), DATA by k
const STEM={}; DATA.forEach(s=>STEM[s.k]=s.stem);
const autoOf=(k,pid)=>(AUTO[STEM[k]]||{})[pid]||null;
function suggested(k,pid){
  const v=autoOf(k,pid);
  if(v&&v.verdict==='wrong')return 0;          // red -> zero
  return S.max[pid];                            // green / amber -> full
}
// A fresh autograde run supersedes suggestions stored from an earlier build,
// but never overwrites a sheet the grader has already worked on.
const STALE = (typeof AUTO_STAMP!=='undefined') && AUTO_STAMP && S.autoStamp!==AUTO_STAMP;
DATA.forEach(s=>{
  if(!S.score[s.k])S.score[s.k]={};
  PARTS.forEach(p=>{
    if(S.score[s.k][p.id]==null || (STALE && !S.touched[s.k]))
      S.score[s.k][p.id]=suggested(s.k,p.id);
  });
  if(S.name[s.k]==null)S.name[s.k]=s.name;
  if(S.sid[s.k]==null)S.sid[s.k]=s.id;
  if(S.note[s.k]==null)S.note[s.k]='';
});
let cur=0, focusPart=0, T=null, SIM=null;   // SIM: the similar-answers drawer
const maxTotal=()=>PARTS.reduce((a,p)=>a+(+S.max[p.id]||0),0);
const total=k=>PARTS.reduce((a,p)=>a+(+S.score[k][p.id]||0),0);
const touched=k=>!!S.touched[k];
/* ---- final curve -------------------------------------------------------
   A squeeze toward full marks: every total keeps the same fraction K of its
   distance from full marks, with K picked so the class mean lands on the
   target.  Full marks stay full, the order never changes, and the lowest
   scores gain the most.  Computed over every sheet (every sheet is exported)
   from the marks as they stand, so it keeps hitting the target as you grade.
   Only raises: a target at or below the mean leaves the marks alone.  The
   parts are never touched; the curve applies to totals and exports. */
const curveOn=()=>!!(S.curve&&S.curve.on&&isFinite(+S.curve.target));
function curveK(){
  if(!curveOn())return 1;
  const F=maxTotal(); if(!(F>0)||!DATA.length)return 1;
  const m=DATA.reduce((a,s)=>a+total(s.k),0)/DATA.length;
  const T=Math.min(100,Math.max(0,+S.curve.target))/100*F;
  if(T<=m||m>=F)return 1;
  return (F-T)/(F-m);
}
// Rounded to the chosen step (S.curve.step, 0 = two decimals), to the nearest
// one or always up (S.curve.mode) -- but never below the raw total: the curve
// must not cost anyone a mark.
const curveStep=()=>+((S.curve||{}).step)||0;
const curveUp=()=>(S.curve||{}).mode==='up';
const curveOf=(t,K)=>{
  const F=maxTotal(), x=F-(F-t)*K, st=curveStep();
  if(!st)return Math.round(x*100)/100;
  // the nudges: a true half rounds up, and a total already on a step (75.5
  // stored as 75.50000001) is not pushed to the next one
  let r=curveUp()?Math.ceil(x/st-1e-9)*st:Math.round(x/st+1e-9)*st;
  if(r<t-1e-9)r=Math.ceil(t/st-1e-9)*st;
  return Math.round(r*1e4)/1e4;
};
// the total that is reported: curved when the curve is on, else the raw total
const finalTotal=(k,K=curveK())=>curveOn()?curveOf(total(k),K):total(k);
// whole percent of the paper's current total; blank while it has no points
const pct=k=>{const m=maxTotal();return m>0?Math.round(100*total(k)/m)+'%':'';};
function saveNow(){
  clearTimeout(T); T=null;
  try{localStorage.setItem(STORE,JSON.stringify(S));$('#saved').textContent='saved locally';}
  catch(e){$('#saved').textContent='browser storage unavailable — use Save progress';}
}
function save(){clearTimeout(T);T=setTimeout(saveNow,250);}
// A reload inside the app (Grade again, another step) must not drop the last
// quarter-second of edits still waiting on the timer.
window.addEventListener('pagehide',()=>{if(T)saveNow();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&T)saveNow();});

function setScore(k,pid,v,flag=true){
  const mx=+S.max[pid]||0;
  v=Math.max(0,Math.min(mx,Math.round((+v||0)*2)/2));
  S.score[k][pid]=v; if(flag)S.touched[k]=true;
  const card=$('#s_'+k);
  const inp=$('#in_'+k+'_'+pid,card); if(inp)inp.value=v;
  $$('.chips button',$('#p_'+k+'_'+pid,card)).forEach(b=>
    b.classList.toggle('on',Math.abs((+b.dataset.v)-v)<1e-9));
  paint(k); save();
  if(SIM)renderSim();
}
function paint(k){
  const el=$('#t_'+k);
  el.innerHTML='<b>'+total(k)+'</b> / '+maxTotal()+' <span class="pct">'+pct(k)+'</span>'
    +(curveOn()&&curveK()<1?'<span class="cv" title="after the final curve">curved '
      +fmt(finalTotal(k),2)+' ('+Math.round(100*finalTotal(k)/(maxTotal()||1))+'%)</span>':'');
  el.classList.toggle('edited',touched(k));
  const li=$('#n_'+k);
  if(curveOn()&&curveK()<1){
    const c=finalTotal(k);
    li.querySelector('.s').textContent=total(k)+' → '+fmt(c,2)+' · '
      +Math.round(100*c/(maxTotal()||1))+'%';
    li.title='raw '+total(k)+' ('+pct(k)+'), after the final curve '+fmt(c,2);
  }else{
    li.querySelector('.s').textContent=total(k)+(pct(k)?' · '+pct(k):'');
    li.title='';
  }
  li.classList.toggle('done',touched(k));
  li.querySelector('.who').textContent=S.name[k]||k;
  $('#nm_'+k).textContent=S.name[k]||k;
  $('#prog').innerHTML='<b>'+DATA.filter(s=>touched(s.k)).length+'</b> of '+DATA.length+' reviewed';
}
function applyMax(){
  PARTS.forEach(p=>{
    const v=Math.max(0,+$('#mx_'+p.id).value||0); S.max[p.id]=v;
    $$('.of_'+p.id).forEach(e=>e.textContent='/ '+v);
    DATA.forEach(s=>{
      if(S.score[s.k][p.id]>v)S.score[s.k][p.id]=v;
      const i=$('#in_'+s.k+'_'+p.id); if(i){i.max=v;i.value=S.score[s.k][p.id];}
    });
    paintChips(p.id); paintPicker(p.id);
  });
  $('#mxtot').textContent=maxTotal(); paintAll();
  DATA.forEach(s=>paint(s.k)); save();
}
/* ---- list order --------------------------------------------------------
   Sorted when chosen, on load, and on the refresh button: re-sorting on every
   mark would move the sheet you are grading out from under next/previous. */
function nameParts(k){
  const n=(S.name[k]||DATA.find(s=>s.k===k).name||k).trim();
  if(n.includes(','))return {last:n.split(',')[0].trim(),first:n.split(',').slice(1).join(',').trim()};
  const w=n.split(/\s+/); return {last:w[w.length-1]||'',first:w.slice(0,-1).join(' ')};
}
function sortList(scroll=true){
  const how=$('#sortby').value, desc=how.startsWith('-'), key=how.replace(/^-/,'');
  const cmpName=f=>(a,b)=>nameParts(DATA[a].k)[f].localeCompare(nameParts(DATA[b].k)[f],
    undefined,{sensitivity:'base'})||nameParts(DATA[a].k)[f==='last'?'first':'last']
    .localeCompare(nameParts(DATA[b].k)[f==='last'?'first':'last'],undefined,{sensitivity:'base'});
  const by={sheet:()=>0, last:cmpName('last'), first:cmpName('first'),
    score:(a,b)=>total(DATA[a].k)-total(DATA[b].k),
    todo:(a,b)=>touched(DATA[a].k)-touched(DATA[b].k)}[key]||(()=>0);
  ORDER=DATA.map((s,i)=>i).sort((a,b)=>(desc?-by(a,b):by(a,b))||a-b);   // ties: sheet order
  const ol=$('.nav ol'); ORDER.forEach(i=>ol.appendChild($('#n_'+DATA[i].k)));
  $('#resort').style.display=key==='score'||key==='todo'?'':'none';
  go(cur,false);
  if(scroll){const li=$('#n_'+DATA[cur].k); if(li)li.scrollIntoView({block:'nearest'});}
}
/* ---- navigation ------------------------------------------------------- */
function go(i,scroll=true){
  const vis=visible();
  if(!vis.length)return;
  if(!vis.includes(i)){                     // hidden: the next shown after it
    const at=ORDER.indexOf(i);
    i=vis.find(n=>ORDER.indexOf(n)>=at); if(i==null)i=vis[vis.length-1];
  }
  cur=Math.max(0,Math.min(DATA.length-1,i)); focusPart=0;
  if(curveOn())paint(DATA[cur].k);      // its curved total moves with everyone's marks
  $$('.stu').forEach((c,n)=>c.classList.toggle('cur',n===cur));
  DATA.forEach((s,n)=>$('#n_'+s.k).classList.toggle('on',n===cur));
  const pos=vis.indexOf(cur)+1;
  $$('.pos').forEach(e=>e.textContent=pos+' of '+vis.length);
  markFocus();
  const li=$('#n_'+DATA[cur].k);
  if(li)li.scrollIntoView({block:'nearest'});
  if(scroll)window.scrollTo({top:0,behavior:'instant'});
}
// Sheet indices in the order the list shows them: next/previous follow it.
let ORDER=DATA.map((s,i)=>i);
function visible(){
  return ORDER.filter(i=>!$('#n_'+DATA[i].k).classList.contains('hide'));
}
function step(d){
  const vis=visible(), at=vis.indexOf(cur);
  if(at<0)return go(cur);
  const next=vis[Math.max(0,Math.min(vis.length-1,at+d))];
  go(next);
}
function markFocus(scroll=false){
  $$('.part').forEach(p=>p.classList.remove('focus'));
  const card=$('#s_'+DATA[cur].k);
  const ps=$$('.part',card);
  if(ps[focusPart]){ps[focusPart].classList.add('focus');
    if(scroll)ps[focusPart].scrollIntoView({block:'nearest'});}
}
/* ---- similar answers: everyone whose read answer looks like this one --- */
// Anchored on one sheet's part; hopping to a student in the list keeps the
// list, so you can walk the whole group and give it the same mark.
const simNorm=t=>String(t||'').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'')
  .replace(/[−–—]/g,'-').replace(/[×✕]/g,'x').replace(/\s+/g,'');
const simNums=t=>(String(t||'').replace(/(\d),(\d{3})(?!\d)/g,'$1$2')
  .match(/-?\d*\.?\d+(?:e-?\d+)?/gi)||[]).map(Number).filter(isFinite);
function dice(a,b){
  if(a===b)return 1; if(a.length<2||b.length<2)return 0;
  const A=new Map(); for(let i=0;i<a.length-1;i++){const g=a.slice(i,i+2);A.set(g,(A.get(g)||0)+1);}
  let n=0; for(let i=0;i<b.length-1;i++){const g=b.slice(i,i+2),c=A.get(g);if(c){n++;A.set(g,c-1);}}
  return 2*n/(a.length+b.length-2);
}
function numMatch(a,b){
  if(!a.length||!b.length)return null;
  const hit=(x,l)=>l.some(y=>Math.abs(x-y)<=1e-3*Math.max(1,Math.abs(x),Math.abs(y)));
  return (a.filter(x=>hit(x,b)).length/a.length+b.filter(y=>hit(y,a)).length/b.length)/2;
}
// Numbers compare by value and the words/units around them separately, so
// "15 s" and "15.0s" are the same read while "15.0 m" (wrong unit) and
// "7.5 s" (wrong value) are not even similar, however alike the strings look.
const NUM=/-?\d*\.?\d+(?:e-?\d+)?/gi;
const canon=t=>simNorm(t).replace(/(\d),(\d{3})(?!\d)/g,'$1$2').replace(NUM,m=>'#'+Number(m));
const words=t=>simNorm(t).replace(/(\d),(\d{3})(?!\d)/g,'$1$2').replace(NUM,'');
function similarity(a,b){
  const na=simNorm(a), nb=simNorm(b);
  if(!na||!nb)return 0; if(canon(a)===canon(b))return 1;
  const n=numMatch(simNums(a),simNums(b));
  if(n==null)return Math.min(.99,dice(na,nb));
  const wa=words(a), wb=words(b);
  const w=wa===wb?1:(!wa||!wb)?.5:dice(wa,wb);
  return Math.min(.99,.55*n+.45*w);
}
const ocrOf=(k,pid)=>(autoOf(k,pid)||{}).ocr||'';
const shotsSrc=(k,pid)=>$$('#p_'+k+'_'+pid+' .shots img').map(im=>im.getAttribute('src'));
function openSim(k,pid){
  const anchor=ocrOf(k,pid);
  const list=DATA.filter(s=>s.k!==k).map(s=>({k:s.k,sim:similarity(anchor,ocrOf(s.k,pid))}))
    .sort((x,y)=>y.sim-x.sim);
  SIM={k,pid,list,anchor};
  document.body.classList.add('simon'); $('#sim').classList.add('on');
  $('#simbody').scrollTop=0; renderSim();
}
function closeSim(){
  SIM=null; document.body.classList.remove('simon'); $('#sim').classList.remove('on');
  $$('.simbtn.open').forEach(b=>b.classList.remove('open'));
}
function simItem(s,pid,ref){
  const v=+S.score[s.k][pid]||0, d=DATA.find(x=>x.k===s.k), here=DATA[cur].k===s.k;
  const txt=ocrOf(s.k,pid);
  return `<div class="sit${here?' here':''}" data-k="${esc(s.k)}"><div class="row">`
    +`<span class="who" data-act="go">${esc(S.name[s.k]||d.name||s.k)}</span>`
    +`<span class="sim">${s.sim>=1?'same':Math.round(s.sim*100)+'%'}</span>`
    +`<span class="sc2${Math.abs(v-ref)>1e-9?' diff':''}" title="their mark for this part">`
    +`${fmt(v,2)} / ${fmt(S.max[pid],2)}</span></div>`
    +`<div class="sread">read: <b>${esc(txt||'—')}</b></div>`
    +shotsSrc(s.k,pid).map(src=>`<img src="${esc(src)}" alt="" data-act="zoom">`).join('')
    +`<div class="row" style="margin-top:5px"><button data-act="go">go</button>`
    +`<button data-act="page" title="See their whole page">page</button>`
    +(Math.abs(v-ref)>1e-9?`<button data-act="match" title="Give them the same mark">`
      +`give ${fmt(ref,2)}</button>`:'')+`</div></div>`;
}
function renderSim(){
  if(!SIM)return;
  const {k,pid,list,anchor}=SIM, part=PARTS.find(p=>p.id===pid);
  const ref=+S.score[k][pid]||0, d=DATA.find(x=>x.k===k);
  $('#simtitle').textContent='Similar answers · '+part.label;
  $$('.simbtn').forEach(b=>b.classList.toggle('open',
    b.dataset.pid===pid&&b.closest('.stu').dataset.k===k));
  const body=$('#simbody'), top=body.scrollTop;
  let h=`<div class="sanc"><div class="row" style="display:flex;gap:8px">`
    +`<span class="who">${esc(S.name[k]||d.name||k)}</span><span class="grow"></span>`
    +`<b style="font-variant-numeric:tabular-nums">${fmt(ref,2)} / ${fmt(S.max[pid],2)}</b></div>`
    +`<div class="sread">read: <b>${esc(anchor||'—')}</b></div></div>`;
  if(!anchor){
    body.innerHTML=h+'<p class="hint">Nothing was read from this answer, so there is '
      +'nothing to match it against. Run Autograde to read the answers.</p>';
    return;
  }
  const same=list.filter(s=>s.sim>=1), near=list.filter(s=>s.sim<1&&s.sim>=.6),
        rest=list.filter(s=>s.sim<.6);
  const grp=(title,l)=>{
    const off=l.filter(s=>Math.abs((+S.score[s.k][pid]||0)-ref)>1e-9).length;
    return `<div class="sgrp">${title} (${l.length})`
      +(off?`<button data-act="matchall" data-g="${title}" title="Give every one of `
        +`these the same mark as ${esc(S.name[k]||k)}">give all ${fmt(ref,2)}</button>`:'')
      +`</div>`+l.map(s=>simItem(s,pid,ref)).join('');
  };
  if(same.length)h+=grp('Same read',same);
  if(near.length)h+=grp('Similar',near);
  if(!same.length&&!near.length)h+='<p class="hint">No one else has a read like this one.</p>';
  if(rest.length)h+=`<details class="srest"${SIM.restOpen?' open':''}><summary>Everyone else (${rest.length})`
    +`</summary>${rest.map(s=>simItem(s,pid,ref)).join('')}</details>`;
  body.innerHTML=h; body.scrollTop=top;
  const det=$('details.srest',body);
  if(det)det.addEventListener('toggle',()=>{if(SIM)SIM.restOpen=det.open;});
}
function simGo(k){
  const i=DATA.findIndex(s=>s.k===k); if(i<0||!SIM)return;
  if(!visible().includes(i)){$('#filt').value='all';filt();}
  go(i); focusPart=PARTS.findIndex(p=>p.id===SIM.pid); markFocus(true); renderSim();
}
// [ and ]: walk the groups in order, skipping "everyone else" unless it is open
function simHop(d){
  if(!SIM)return;
  const pool=SIM.list.filter(s=>s.sim>=.6||SIM.restOpen).map(s=>s.k);
  if(!pool.length)return;
  const at=pool.indexOf(DATA[cur].k);
  const n=at<0?(d>0?0:pool.length-1):at+d;
  if(n<0||n>=pool.length)return;
  simGo(pool[n]);
  const el=$(`#simbody .sit[data-k="${CSS.escape(pool[n])}"]`);
  if(el)el.scrollIntoView({block:'nearest'});
}
function pageAt(k,pid){
  const pl=pagesOf(k), part=PARTS.find(p=>p.id===pid);
  openViewer(pl,Math.max(0,Math.min(pl.length-1,((part&&part.page)||1)-1)));
}
/* ---- full-screen viewer ----------------------------------------------- */
let V={list:[],at:0,zoom:1,x:0,y:0,nat:[0,0],key:false};
try{V.key=localStorage.getItem(STORE+':viewkey')==='1';}catch(e){}
function openViewer(list,at){
  V.list=list; V.at=at; $('#viewer').classList.add('on'); showShot();
}
// The key's page for what is on screen: only full pages have one.
const keyFor=it=>it&&it.page&&KEY[it.page-1]||'';
function showShot(){
  const it=V.list[V.at], img=$('#vimg'), kimg=$('#vkey');
  const ksrc=keyFor(it), withKey=V.key&&!!ksrc;
  $('#vkeybtn').style.display=KEY.length&&it.page?'':'none';
  $('#vkeybtn').classList.toggle('on',V.key);
  $('#viewer').classList.toggle('key',withKey);
  // fit once everything shown has loaded, so the pair is framed as one
  let wait=withKey?2:1;
  const done=()=>{if(--wait)return;
    img.style.width=img.naturalWidth+'px';
    kimg.style.width=kimg.naturalWidth+'px';
    const box=$('#vbox');
    V.nat=[box.scrollWidth,box.scrollHeight];fit();};
  img.onload=done; kimg.onload=withKey?done:null;
  img.src=it.src;
  if(withKey)kimg.src=ksrc;
  $('#vlabel').textContent=it.label+(withKey?' · answer key beside it':'');
  $('#vcount').textContent=(V.at+1)+' / '+V.list.length;
}
function toggleKey(){
  V.key=!V.key;
  try{localStorage.setItem(STORE+':viewkey',V.key?'1':'0');}catch(e){}
  showShot();
}
function fit(){
  const st=$('#vstage').getBoundingClientRect();
  const [w,h]=V.nat;
  V.zoom=Math.min(st.width/w,st.height/h)*0.96;
  V.x=(st.width-w*V.zoom)/2; V.y=(st.height-h*V.zoom)/2; apply();
}
function apply(){
  const img=$('#vbox');
  img.style.transform=`translate(${V.x}px,${V.y}px) scale(${V.zoom})`;
  $('#vzoom').textContent=Math.round(V.zoom*100)+'%';
}
function zoomAt(f,cx,cy){
  const st=$('#vstage').getBoundingClientRect();
  cx=cx==null?st.width/2:cx-st.left; cy=cy==null?st.height/2:cy-st.top;
  const z=Math.max(.05,Math.min(12,V.zoom*f));
  V.x=cx-(cx-V.x)*(z/V.zoom); V.y=cy-(cy-V.y)*(z/V.zoom); V.zoom=z; apply();
}
function closeViewer(){$('#viewer').classList.remove('on');}
function shotsOf(k){
  return $$('#s_'+k+' .shots img, #s_'+k+' .idrow img')
    .map(im=>({src:im.getAttribute('src'),label:im.dataset.label||''}));
}
function pagesOf(k){
  const s=DATA.find(d=>d.k===k);
  return s.pages.map((p,i)=>({src:p,label:'full page '+(i+1),page:i+1}));
}
/* ---- progress file ---------------------------------------------------- */
function saveFile(){
  const blob=new Blob([JSON.stringify({quiz:STORE,saved:new Date().toISOString(),state:S},null,1)],
                      {type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download=STORE+'_progress.json';document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
}
function loadFile(ev){
  const f=ev.target.files[0]; if(!f)return;
  const rd=new FileReader();
  rd.onload=()=>{try{
    const j=JSON.parse(rd.result);
    if(!j.state)throw new Error('not a progress file');
    S=Object.assign(S,j.state); save();
    $('#sortby').value=S.sort||'sheet'; if(!$('#sortby').value)$('#sortby').value='sheet';
    sortList(false);
    DATA.forEach(s=>{
      PARTS.forEach(p=>setScore(s.k,p.id,S.score[s.k][p.id],false));
      const nm=$('#f_name_'+s.k),sd=$('#f_sid_'+s.k),cm=$('#cmt_'+s.k);
      if(nm)nm.value=S.name[s.k]||'';if(sd)sd.value=S.sid[s.k]||'';
      if(cm)cm.value=S.note[s.k]||'';
      PARTS.forEach(p=>paintTags(s.k,p.id));
      paint(s.k);
    });
    PARTS.forEach(p=>{if(!S.qmode[p.id])S.qmode[p.id]=(S.chips[p.id]||'').trim()?'text':'pct';
                      paintPicker(p.id);paintChips(p.id);}); paintAll();
    PARTS.forEach(p=>refreshList(p.id));
    $('#saved').textContent='progress loaded';
  }catch(e){alert('Could not load: '+e.message);}};
  rd.readAsText(f); ev.target.value='';
}
function exportCSV(){
  const head=['Sheet','Name','ID'].concat(PARTS.map(p=>p.label+' /'+S.max[p.id]))
             .concat(['Total /'+maxTotal()])
             .concat(curveOn()?['Curved total /'+maxTotal()]:[])
             .concat(['Reviewed','Comment','Flags','Mistakes']);
  const K=curveK();
  const q=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
  const out=[head.map(q).join(',')];
  DATA.forEach(s=>out.push([s.sheet,S.name[s.k],S.sid[s.k]]
    .concat(PARTS.map(p=>S.score[s.k][p.id]))
    .concat([total(s.k)]).concat(curveOn()?[curveOf(total(s.k),K)]:[])
    .concat([touched(s.k)?'yes':'no',S.note[s.k],s.flags||'',
             PARTS.flatMap(p=>tagsOf(s.k,p.id).map(t=>p.id+': '+t)).join('; ')]).map(q).join(',')));
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([out.join('\n')],{type:'text/csv'}));
  a.download=STORE+'_grades.csv';document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
}
/* ---- Canvas upload ------------------------------------------------------
   Canvas matches a row by its own ID, so every identity column is copied from
   the roster and only the score comes from this page.  A sheet whose student
   cannot be placed on the roster is left out rather than guessed at. */
const cfold=s=>(s||'').normalize('NFKD').replace(/[^A-Za-z]/g,'').toLowerCase();
function canvasIndex(){
  const byId={},byName={};
  CANVAS.roster.forEach(r=>{
    [r.i,r.s,r.l].forEach(k=>{k=(k||'').trim().toLowerCase();
                              if(k&&!(k in byId))byId[k]=r;});
    const c=r.n.indexOf(',');
    const forms=[r.n];
    if(c>0)forms.push(r.n.slice(c+1)+' '+r.n.slice(0,c));   // "First Last" too
    forms.forEach(f=>{const k=cfold(f);if(k&&!(k in byName))byName[k]=r;});
  });
  return {byId,byName};
}
// The paper's total is whatever the points-per-part boxes currently say, so a
// rubric tweak rescales with it rather than going stale.
// Chosen in the export dialog and kept with the progress; until then the
// config's canvas_out_of, else what Canvas says the assignment is worth.
if(!S.canvas)S.canvas={};
const ctarget=()=>S.canvas.outOf!=null?+S.canvas.outOf
  :CANVAS.outOf!=null?CANVAS.outOf:CANVAS.points!=null?CANVAS.points:maxTotal();
const cstep=()=>S.canvas.step!=null?+S.canvas.step:CANVAS.step;
const cup=()=>S.canvas.mode==='up';
function cscale(v){
  const paper=maxTotal(),t=ctarget();
  if(!paper)return v;
  let x=t===paper?v:v*t/paper;
  // The nudge keeps a true half (6.35 on a 0.1 grid) from rounding down
  // because binary floating point stores it as 6.34999...
  // Rounding is the last thing done to a score before it uploads: after the
  // curve and after scaling.  "Always up" leaves a score already on a step
  // where it is (the -1e-9 absorbs floating point noise).
  if(cstep())x=cup()?Math.ceil(x/cstep()-1e-9)*cstep():Math.round(x/cstep()+1e-9)*cstep();
  return Math.round(x*1e4)/1e4;
}
function openCanvas(){
  if(!CANVAS.roster.length)
    return alert('No roster was loaded with this page, so there are no Canvas '
                +'ids to upload against. Rebuild with: redpen grade');
  $('#ccol').textContent='Into the column "'+CANVAS.column+'"'
    +(CANVAS.existing?'':' — Canvas has no such assignment yet, so importing would create it.');
  const t=ctarget(); $('#ctot').value=t; $('#cfac').value=+(t/(maxTotal()||1)).toPrecision(6);
  $('#cstep').value=String(cstep()||0);
  $('#cmode').value=cup()?'up':'nearest'; $('#cmode').disabled=!cstep();
  paintCanvas(); $('#cdlg').classList.add('on'); $('#ctot').focus(); $('#ctot').select();
}
function paintCanvas(){
  const paper=maxTotal(), t=ctarget();
  const notes=['Marked out of '+fmt(paper,2)+' on the paper'
    +(t===paper?'; uploaded as they are.':'; scaled × '+fmt(t/paper,4)+' to '+fmt(t,2)+' for Canvas.')];
  if(CANVAS.points!=null&&Math.abs(CANVAS.points-t)>1e-9)
    notes.push('Canvas has this assignment out of '+fmt(CANVAS.points,2)
              +', not '+fmt(t,2)+' — the Points Possible row will say '+fmt(t,2)+'.');
  if(cstep())notes.push('Last of all, every score is '+(cup()?'rounded up to the next ':'rounded to the nearest ')
    +fmt(cstep(),2)+'.');
  if(curveOn()&&curveK()<1)notes.unshift('Final curve on (target mean '+fmt(+S.curve.target,2)
    +'%): the curved totals are what upload.');
  $('#cnote').textContent=notes.join(' ');
  // A few real sheets, spread from lowest to highest, so the effect is visible.
  const K=curveK();
  const tots=[...new Set(DATA.map(s=>finalTotal(s.k,K)))].sort((a,b)=>b-a);
  const pick=tots.length<=5?tots:[0,.25,.5,.75,1].map(f=>tots[Math.round(f*(tots.length-1))]);
  $('#cprev').innerHTML=[...new Set(pick)].map(v=>fmt(v,2)+' → <b>'+fmt(cscale(v),4)+'</b>').join(' · ');
}
function exportCanvas(){
  if(!CANVAS.roster.length)
    return alert('No roster was loaded with this page, so there are no Canvas '
                +'ids to upload against. Rebuild with: redpen grade');
  const ix=canvasIndex(),rows=[],lost=[],twice=[],claimed={}, K=curveK();
  DATA.forEach(s=>{
    const id=(S.sid[s.k]||'').trim().toLowerCase();
    const r=(id&&ix.byId[id])||ix.byName[cfold(S.name[s.k])];
    if(!r)return lost.push((S.name[s.k]||s.k)+'  (sheet '+s.sheet+')');
    const key=r.i||r.s||r.n;
    if(claimed[key])return twice.push(r.n+'  (sheet '+s.sheet+')');
    claimed[key]=1;
    rows.push([r.n,r.i,r.s,r.l,r.sec,cscale(finalTotal(s.k,K))]);
  });
  const warn=[];
  if(lost.length)warn.push(lost.length+' sheet(s) are not on the roster and will be '
                          +'left out:\n  '+lost.join('\n  '));
  if(twice.length)warn.push(twice.length+' student(s) already had a sheet; the later '
                           +'one is left out — settle this first:\n  '+twice.join('\n  '));
  const un=DATA.filter(s=>!touched(s.k)).length;
  if(un)warn.push(un+' sheet(s) are not reviewed yet and would upload at their '
                 +'suggested marks.');
  // No (id) on the column means Canvas has no such assignment and would make a
  // second one rather than filling the one you meant.
  if(!CANVAS.existing)
    warn.push('Canvas has no assignment called "'+CANVAS.column+'" as of the '
             +'roster export, so importing this would CREATE one.\n  If it '
             +'exists now, export the gradebook from Canvas again and rebuild '
             +'the page:\n    redpen grade <config>');
  if(ctarget()!==maxTotal())
    warn.unshift('Marks are scaled from '+maxTotal()+' to '+ctarget()
                +(cstep()?(cup()?', rounded up to the next ':', to the nearest ')+cstep():'')+'.');
  if(!rows.length)return alert('Nothing to upload.\n\n'+warn.join('\n\n'));
  if(warn.length&&!confirm(warn.join('\n\n')+'\n\nExport the remaining '+rows.length
                          +' rows for '+CANVAS.column+'?'))return;
  const q=v=>{const s=String(v==null?'':v);
              return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
  const out=[['Student','ID','SIS User ID','SIS Login ID','Section',CANVAS.column],
             ['Points Possible','','','','',ctarget()]].concat(rows)
            .map(r=>r.map(q).join(','));
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([out.join('\n')+'\n'],{type:'text/csv'}));
  a.download=STORE+'_canvas.csv';document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
  $('#saved').textContent=rows.length+' rows for Canvas';
}
function filt(){
  const m=$('#filt').value;
  DATA.forEach(s=>{
    let show=true;
    if(m==='unreviewed')show=!touched(s.k);
    else if(m==='partial')show=PARTS.some(p=>{const v=S.score[s.k][p.id];
                                              return v>0&&v<S.max[p.id];});
    else if(m==='zero')show=PARTS.some(p=>S.score[s.k][p.id]===0&&S.max[p.id]>0);
    else if(m==='flagged')show=!!s.flags;
    else if(m==='mistake')show=PARTS.some(p=>tagsOf(s.k,p.id).length);
    $('#n_'+s.k).classList.toggle('hide',!show);
  });
  go(cur,false);
}
/* ---- stats -------------------------------------------------------------
   Computed here, from the marks as they stand, because this page is where
   the marks live: nothing on disk knows them until an export. */
const fmt=(x,nd=1)=>(Math.round(x*10**nd)/10**nd).toString();
function summary(v){
  v=[...v].sort((a,b)=>a-b); const n=v.length;
  const mean=v.reduce((a,b)=>a+b,0)/n;
  const pct=p=>{if(n===1)return v[0];const k=(n-1)*p,lo=Math.floor(k),hi=Math.ceil(k);
                return v[lo]+(v[hi]-v[lo])*(k-lo);};
  const sd=n>1?Math.sqrt(v.reduce((a,x)=>a+(x-mean)**2,0)/(n-1)):0;
  return {n,mean,median:pct(.5),sd,min:v[0],max:v[n-1],q1:pct(.25),q3:pct(.75)};
}
let SEL=null;                      // the histogram bin whose students are listed
// Binning: S.hist = {lo, hi, n, fit, pct}.  pct bins the totals as percent of
// the paper, and lo/hi are then percents too.  Whatever is not pinned follows the marks
// as they stand, every time the stats are drawn: an unset end is the paper's
// (0 .. full marks), and fit spans the current lowest .. highest total.  Only
// the box you type in is pinned, and a pinned top never passes the paper's
// total (a total that later shrank would otherwise leave it stranded).
const byPct=()=>!!(S.hist||{}).pct;
// a total on the histogram's axis: points, or percent of the paper
const axisVal=t=>byPct()?100*t/(maxTotal()||1):t;
const unit=()=>byPct()?'%':'';
function histRange(){
  const h=S.hist||{}, top=byPct()?100:(maxTotal()||1);
  let lo=h.lo!=null&&isFinite(h.lo)?+h.lo:0, hi=h.hi!=null&&isFinite(h.hi)?Math.min(+h.hi,top):top;
  if(h.fit){
    const K=curveK(), t=statSheets().map(s=>axisVal(finalTotal(s.k,K)));
    if(t.length){lo=Math.floor(Math.min(...t));hi=Math.ceil(Math.max(...t));}
  }
  if(hi<=lo)hi=lo+1;
  const n=Math.max(1,Math.min(200,Math.round(+h.n||10)));
  return {lo,hi,n};
}
function paintBinset(){
  const r=histRange(); $('#stlo').value=r.lo; $('#sthi').value=r.hi; $('#stn').value=r.n;
  $('#stfit').classList.toggle('on',!!(S.hist||{}).fit);
  $('#stunit').value=byPct()?'pct':'pts';
}
function readBinset(e){
  const x=e.target.value.trim(), v=x===''?null:+x;
  const f={stlo:'lo',sthi:'hi',stn:'n'}[e.target.id];
  S.hist={...(S.hist||{}),[f]:v};
  if(f!=='n')delete S.hist.fit;           // typing an end takes over from fit
  paintBinset(); SEL=null; save(); renderStats();
}
function statSheets(){
  return DATA.filter(s=>$('#stscope').value==='all'||touched(s.k));
}
function tip(html,ev){
  const t=$('#tip'); if(!html){t.style.display='none';return;}
  t.innerHTML=html; t.style.display='block';
  const r=t.getBoundingClientRect();
  let x=ev.clientX+14, y=ev.clientY+14;
  if(x+r.width>innerWidth-8)x=ev.clientX-r.width-14;
  if(y+r.height>innerHeight-8)y=ev.clientY-r.height-14;
  t.style.left=x+'px'; t.style.top=y+'px';
}
function renderStats(){
  const sheets=statSheets(), mt=maxTotal();
  const un=DATA.filter(s=>!touched(s.k)).length;
  $('#stsub').textContent=sheets.length+' of '+DATA.length+' sheets · out of '+fmt(mt)
    +(curveOn()&&curveK()<1?' · after the final curve':'')
    +($('#stscope').value==='all'&&un?' · '+un+' not yet reviewed, counted at their suggested marks':'');
  if(!sheets.length){
    $('#sttiles').innerHTML='';$('#sthist').innerHTML='';$('#stparts').innerHTML='';
    $('#stbin').textContent='No sheets reviewed yet.';$('#sttable').innerHTML='';
    $('#stmist').innerHTML='';return;
  }
  renderCurve();
  // with the curve on, everything below describes the curved totals
  const K=curveK(), ftot=k=>finalTotal(k,K);
  const tots=sheets.map(s=>ftot(s.k)), st=summary(tots);
  const pc=x=>mt?' <small>'+Math.round(100*x/mt)+'%</small>':'';
  const tile=(k,v)=>'<div class="tile"><div class="k">'+k+'</div><div class="v">'+v+'</div></div>';
  $('#sttiles').innerHTML=tile('Graded',st.n)+tile('Mean',fmt(st.mean)+pc(st.mean))
    +tile('Median',fmt(st.median)+pc(st.median))+tile('Std dev',fmt(st.sd))
    +tile('Min',fmt(st.min)+pc(st.min))+tile('Max',fmt(st.max)+pc(st.max))
    +tile('Q1 – Q3',fmt(st.q1)+' – '+fmt(st.q3));

  // ---- histogram of totals: equal-width bins over [from, to].  The top
  // edge belongs to the last bin; anything outside is counted, not binned.
  const {lo:hlo,hi:hhi,n:nb}=histRange(), bw=(hhi-hlo)/nb;
  const bins=Array.from({length:nb},(_,i)=>({lo:hlo+i*bw,hi:hlo+(i+1)*bw,who:[]}));
  let under=0, over=0;
  sheets.forEach((s,i)=>{const t=axisVal(tots[i]);
    if(t<hlo-1e-9){under++;return;} if(t>hhi+1e-9){over++;return;}
    bins[Math.min(nb-1,Math.floor((t-hlo)/bw+1e-9))].who.push(s);});
  const u=unit();
  $('#stcap').textContent='Students per score range · bins of '+fmt(bw,2)+(u||' pts')
    +(under||over?' · '+[under&&under+' below '+fmt(hlo)+u,over&&over+' above '+fmt(hhi)+u]
      .filter(Boolean).join(', ')+', not shown':'');
  const box=$('#sthist'), W=Math.max(320,box.clientWidth), H=250;
  const m={l:34,r:10,t:30,b:26}, pw=W-m.l-m.r, ph=H-m.t-m.b;
  const top=Math.max(...bins.map(b=>b.who.length),1);
  const stepY=top<=5?1:top<=10?2:top<=25?5:Math.ceil(top/5/5)*5;
  const yMax=Math.ceil(top/stepY)*stepY;
  const X=v=>m.l+pw*(v-hlo)/(hhi-hlo), Y=c=>m.t+ph*(1-c/yMax), cw=pw/nb;
  let g='', caps='';
  for(let c=0;c<=yMax;c+=stepY)
    g+=`<line class="${c?'grid':'axis'}" x1="${m.l}" x2="${W-m.r}" y1="${Y(c)}" y2="${Y(c)}"/>`
      +`<text x="${m.l-6}" y="${Y(c)+4}" text-anchor="end">${c}</text>`;
  // Edge labels thinned to roughly one per 56px, always keeping both ends.
  const every=Math.max(1,Math.ceil(nb/Math.max(1,Math.floor(pw/56))));
  const ticks=[];
  for(let i=0;i<nb;i+=every)ticks.push(i);
  if(ticks.length>1&&(nb-ticks[ticks.length-1])*cw<34)ticks.pop();   // crowds the end
  ticks.push(nb);
  ticks.forEach(i=>g+=`<text x="${X(hlo+i*bw)}" y="${H-8}" text-anchor="middle">${fmt(hlo+i*bw)+u}</text>`);
  bins.forEach((b,i)=>{
    const n=b.who.length, x=m.l+i*cw+1, w=Math.max(1,cw-2);
    if(n){
      const y=Y(n), h=m.t+ph-y, r=Math.min(4,h,w/2);
      g+=`<path class="col${SEL!=null&&SEL!==i?' dim':''}" d="M${x},${y+h}V${y+r}Q${x},${y} ${x+r},${y}`
        +`H${x+w-r}Q${x+w},${y} ${x+w},${y+r}V${y+h}Z"/>`
;
      caps+=`<text class="capn" x="${x+w/2}" y="${y-5}" text-anchor="middle">${n}</text>`;
    }
    g+=`<rect class="hit" data-bin="${i}" x="${m.l+i*cw}" y="${m.t}" width="${cw}" height="${ph}"/>`;
  });
  // mean and median: solid hairlines, labels kept apart when they crowd
  const refs=[{v:axisVal(st.mean),t:'mean '+fmt(axisVal(st.mean))+u,c:''},
              {v:axisVal(st.median),t:'median '+fmt(axisVal(st.median))+u,c:' med'}];
  // The lower of the two labels goes left of its line, the higher right, so
  // they splay apart instead of printing over each other when close.
  const lo=st.mean<=st.median?0:1;   // same order in either unit
  refs.forEach((r,i)=>{
    if(r.v<hlo||r.v>hhi)return;              // outside the plotted range
    const x=X(r.v);
    let left=i===lo;
    if(x<m.l+80)left=false; else if(x>W-m.r-80)left=true;
    g+=`<line class="ref${r.c}" x1="${x}" x2="${x}" y1="${m.t-18}" y2="${m.t+ph}" pointer-events="none"/>`
      +`<text class="reft${r.c}" x="${x+(left?-5:5)}" y="${m.t-9}" text-anchor="${left?'end':'start'}">${r.t}</text>`;
  });
  g+=caps;
  box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Histogram of total scores">${g}</svg>`;
  const range=b=>fmt(b.lo)+u+' – '+fmt(b.hi)+u;
  $$('.hit',box).forEach(el=>{
    const b=bins[+el.dataset.bin];
    el.addEventListener('mousemove',ev=>tip('<b>'+range(b)+'</b><br>'+b.who.length+' student'
      +(b.who.length===1?'':'s')+(b.who.length?' · click to list':''),ev));
    el.addEventListener('mouseleave',()=>tip(null));
    el.addEventListener('click',()=>{const i=+el.dataset.bin;SEL=SEL===i?null:i;renderStats();});
  });
  const sb=SEL!=null&&bins[SEL];
  $('#stbin').innerHTML=sb
    ? '<b>'+range(sb)+'</b> — '+(sb.who.length?sb.who.map(s=>
        `<button data-go="${DATA.indexOf(s)}">${esc(S.name[s.k]||s.k)} · ${fmt(ftot(s.k),2)}`
        +`${u?' ('+Math.round(axisVal(ftot(s.k)))+'%)':''}</button>`).join('')
        :'nobody')
    : '<span class="muted">Click a bar to list its students.</span>';
  $$('#stbin [data-go]').forEach(b=>b.addEventListener('click',()=>{closeStats();go(+b.dataset.go);}));
  $('#sttable').innerHTML='<tr><th>range</th><th>students</th></tr>'
    +bins.map(b=>'<tr><td>'+range(b)+'</td><td>'+b.who.length+'</td></tr>').join('');

  // ---- by part: zero / partial / full, as one stacked bar each
  const rows=PARTS.map(p=>{
    const mx=+S.max[p.id]||0, v=sheets.map(s=>+S.score[s.k][p.id]||0);
    const z=v.filter(x=>x<=0).length, f=v.filter(x=>mx>0&&x>=mx-1e-9).length;
    const mean=v.reduce((a,b)=>a+b,0)/v.length;
    return {p,mx,mean,z,f,part:v.length-z-f,n:v.length};
  });
  const seg=(cls,c,n,lab)=>c?`<span class="${cls}" style="flex:${c}" data-tip="<b>${c}</b> of ${n} ${lab}"></span>`:'';
  $('#stparts').innerHTML='<tr><th>Part</th><th class="n">out of</th><th class="n">mean</th>'
    +'<th class="n">%</th><th style="width:38%">distribution</th><th class="n">zero</th><th class="n">full</th></tr>'
    +rows.map(r=>`<tr><td>${esc(r.p.label)}</td><td class="n">${fmt(r.mx)}</td>`
      +`<td class="n">${fmt(r.mean,2)}</td><td class="n">${r.mx?Math.round(100*r.mean/r.mx):0}%</td>`
      +`<td><div class="stack">${seg('z',r.z,r.n,'scored zero')}${seg('p',r.part,r.n,'partial credit')}${seg('f',r.f,r.n,'full marks')}</div></td>`
      +`<td class="n">${r.z}</td><td class="n">${r.f}</td></tr>`).join('');
  renderMistakes(sheets);
  $$('#stparts [data-tip]').forEach(el=>{
    el.addEventListener('mousemove',ev=>tip(el.dataset.tip,ev));
    el.addEventListener('mouseleave',()=>tip(null));
  });
}
function renderMistakes(sheets){
  const box=$('#stmist'); let h='';
  PARTS.forEach((p,pi)=>{
    const tags=allTags(p.id,sheets); if(!tags.length)return;
    h+=`<div class="mpart">${esc(p.label)}</div>`+tags.map(t=>`<div class="mrow"><span>${esc(t.label)}</span>`
      +`<span class="n">${t.who.length} · ${Math.round(100*t.who.length/sheets.length)}%</span><span>`
      +t.who.map(s=>`<button data-go="${DATA.indexOf(s)}" data-part="${pi}">${esc(S.name[s.k]||s.k)}`
        +` · ${fmt(+S.score[s.k][p.id]||0)}</button>`).join('')+'</span></div>').join('');
  });
  box.innerHTML=h||'<span class="muted" style="font-size:12.5px">No notes yet. Type one '
    +'under any part while grading (<kbd>m</kbd>), and the same wording will group here.</span>';
  $$('[data-go]',box).forEach(b=>b.addEventListener('click',()=>{
    closeStats(); go(+b.dataset.go); focusPart=+b.dataset.part; markFocus(true);
    toggleNotes(DATA[+b.dataset.go].k,PARTS[focusPart].id,true); document.activeElement.blur();}));
}
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function renderCurve(){
  const on=curveOn(), F=maxTotal()||1, K=curveK();
  const raw=DATA.map(s=>total(s.k));
  $('#stcurve').classList.toggle('on',on);
  $('#cvon').checked=!!(S.curve&&S.curve.on);
  if(document.activeElement!==$('#cvtarget'))
    $('#cvtarget').value=S.curve&&S.curve.target!=null?S.curve.target:'';
  $('#cvstep').value=String(curveStep());
  if(!$('#cvstep').value)$('#cvstep').value='0';
  $('#cvmode').value=curveUp()?'up':'nearest';
  $('#cvmode').disabled=!curveStep();
  if(!raw.length){$('#cvnote').textContent='';$('#cvtab').innerHTML='';return;}
  const P=x=>fmt(100*x/F,1)+'%', r0=summary(raw);
  const un=DATA.filter(s=>!touched(s.k)).length;
  const scope='Over all '+DATA.length+' sheets'+(un?' ('+un+' not reviewed yet, at their suggested marks)':'');
  if(!on){
    $('#cvnote').textContent='Class mean now '+P(r0.mean)+'. Squeezes every total toward full marks '
      +'so the mean lands on the target: full marks stay full, the order never changes, the '
      +'lowest scores gain the most. The marks on each part are not touched.';
    $('#cvtab').innerHTML=''; return;
  }
  if(K>=1){
    $('#cvnote').textContent='The class mean is already '+P(r0.mean)+', at or above the target, '
      +'so nothing changes. The curve only raises marks.';
    $('#cvtab').innerHTML=''; return;
  }
  const cv=raw.map(t=>curveOf(t,K)), r1=summary(cv);   // rounded, as they will export
  $('#cvnote').textContent=scope+'. Every total keeps '+fmt(100*K,1)+'% of its distance '
    +'from full marks (curved = '+fmt(F,2)+' − ('+fmt(F,2)+' − raw) × '+fmt(K,4)+')'
    +(curveStep()?(curveUp()?', rounded up to the next ':', rounded to the nearest ')
      +fmt(curveStep(),2)+(curveUp()?'':' but never below the raw total')+', '
      +'so the mean comes out at '+fmt(100*r1.mean/F,2)+'% (target '+fmt(+S.curve.target,2)+'%).':'.');
  const row=(l,a,b)=>`<tr><td>${l}</td><td>${fmt(a,2)} · ${P(a)}</td><td><b>${fmt(b,2)} · ${P(b)}</b></td></tr>`;
  const ex=[.4,.5,.6,.7,.8,.9].map(f=>`${Math.round(f*100)}% → ${P(curveOf(f*F,K))}`).join(' · ');
  $('#cvtab').innerHTML='<table><tr><th></th><th>raw</th><th>curved</th></tr>'
    +row('Mean',r0.mean,r1.mean)+row('Median',r0.median,r1.median)
    +row('Lowest',r0.min,r1.min)+row('Highest',r0.max,r1.max)
    +`<tr><td>Std dev</td><td>${fmt(r0.sd,2)}</td><td><b>${fmt(r1.sd,2)}</b></td></tr></table>`
    +`<div class="hint" style="margin-top:6px">${ex}</div>`;
}
function setCurve(c){
  S.curve={...(S.curve||{}),...c}; saveNow();
  DATA.forEach(s=>paint(s.k)); SEL=null; paintBinset(); renderStats();
}
function openStats(){SEL=null;$('#stats').classList.add('on');paintBinset();renderStats();}
function closeStats(){$('#stats').classList.remove('on');tip(null);}
/* ---- wiring ----------------------------------------------------------- */
document.addEventListener('DOMContentLoaded',()=>{
  PARTS.forEach(p=>$('#mx_'+p.id).addEventListener('change',applyMax));
  // Quick-mark pickers, delegated because they are redrawn on every change.
  $('details.pts').addEventListener('click',e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.allpct!=null){
      const p=+b.dataset.allpct;
      // Parts on custom marks are left alone: those were typed on purpose.
      const ps=PARTS.filter(q=>S.qmode[q.id]==='pct');
      const every=ps.every(q=>pctsOf(q.id).includes(p));
      ps.forEach(q=>{const l=pctsOf(q.id);
        setPcts(q.id,every?l.filter(x=>x!==p):l.concat([p]));});
    } else {
      const pid=b.closest('.qm')?.dataset.pid; if(!pid)return;
      if(b.dataset.mode){S.qmode[pid]=b.dataset.mode;paintPicker(pid);paintChips(pid);
                         if(b.dataset.mode==='text')$('.qm[data-pid="'+pid+'"] input').focus();}
      else if(b.dataset.pct!=null){
        const p=+b.dataset.pct, l=pctsOf(pid);
        setPcts(pid,l.includes(p)?l.filter(x=>x!==p):l.concat([p]));
      }
    }
    paintAll(); save();
  });
  $('details.pts').addEventListener('input',e=>{
    const box=e.target.closest('.qm'); if(!box||!box.dataset.pid)return;
    const pid=box.dataset.pid; S.chips[pid]=e.target.value;
    markBad(pid,e.target); paintChips(pid); save();
  });
  // Mistake notes: Enter adds, × removes, Escape leaves the box.
  document.addEventListener('keydown',e=>{
    if(!e.target.classList||!e.target.classList.contains('mistin'))return;
    const k=e.target.closest('.stu').dataset.k, pid=e.target.closest('.mist').dataset.pid;
    if(e.key==='Enter'){addTag(k,pid,e.target.value);e.target.value='';e.preventDefault();}
    else if(e.key==='Escape'){e.target.value='';e.target.blur();toggleNotes(k,pid,false);}
  },true);
  document.addEventListener('click',e=>{
    const nb=e.target.closest('.notebtn');
    if(nb){toggleNotes(nb.closest('.stu').dataset.k,nb.dataset.pid);return;}
    const sb=e.target.closest('.simbtn');
    if(sb){const k=sb.closest('.stu').dataset.k;
      if(SIM&&SIM.k===k&&SIM.pid===sb.dataset.pid)closeSim(); else openSim(k,sb.dataset.pid);
      return;}
    const b=e.target.closest('.mist [data-rm]'); if(!b)return;
    rmTag(b.closest('.stu').dataset.k,b.closest('.mist').dataset.pid,+b.dataset.rm);
  });
  PARTS.forEach(p=>{refreshList(p.id);DATA.forEach(s=>paintTags(s.k,p.id));});
  // Delegated: the buttons are redrawn whenever the quick marks change.
  document.addEventListener('click',e=>{
    const b=e.target.closest('.chips button'); if(!b)return;
    setScore(b.closest('.stu').dataset.k,b.dataset.pid,+b.dataset.v);
  });
  $('#filt').addEventListener('change',filt);
  $('#exp').addEventListener('click',exportCSV);
  $('#expcanvas').addEventListener('click',openCanvas);
  const cclose=()=>$('#cdlg').classList.remove('on');
  $('#ctot').addEventListener('input',()=>{const v=+$('#ctot').value;
    if(!($('#ctot').value.trim())||!(v>=0))return;
    S.canvas.outOf=v; $('#cfac').value=+(v/(maxTotal()||1)).toPrecision(6); paintCanvas(); save();});
  $('#cfac').addEventListener('input',()=>{const f=+$('#cfac').value;
    if(!($('#cfac').value.trim())||!(f>=0))return;
    S.canvas.outOf=Math.round(f*maxTotal()*1e6)/1e6; $('#ctot').value=S.canvas.outOf; paintCanvas(); save();});
  $('#cstep').addEventListener('change',()=>{S.canvas.step=+$('#cstep').value;
    $('#cmode').disabled=!cstep();paintCanvas();save();});
  $('#cmode').addEventListener('change',()=>{S.canvas.mode=$('#cmode').value;paintCanvas();save();});
  $('#cpaper').addEventListener('click',()=>{S.canvas.outOf=maxTotal();
    $('#ctot').value=S.canvas.outOf;$('#cfac').value=1;paintCanvas();save();});
  $('#ccancel').addEventListener('click',cclose);
  $('#cgo').addEventListener('click',()=>{cclose();exportCanvas();});
  $('#cdlg').addEventListener('click',e=>{if(e.target.id==='cdlg')cclose();});
  $('#savef').addEventListener('click',saveFile);
  $('#openstats').addEventListener('click',openStats);
  $('#stclose').addEventListener('click',closeStats);
  $('#stscope').addEventListener('change',()=>{SEL=null;paintBinset();renderStats();});
  $('#cvon').addEventListener('change',()=>{
    const c={on:$('#cvon').checked};
    // first time on: start from the current mean, rounded up
    if(c.on&&(S.curve==null||S.curve.target==null)&&DATA.length){
      const F=maxTotal()||1;
      c.target=Math.ceil(100*DATA.reduce((a,s)=>a+total(s.k),0)/DATA.length/F);
    }
    setCurve(c);
  });
  // typing a target means "curve to this": it switches the curve on
  $('#cvstep').addEventListener('change',()=>setCurve({step:+$('#cvstep').value}));
  $('#cvmode').addEventListener('change',()=>setCurve({mode:$('#cvmode').value}));
  $('#cvtarget').addEventListener('input',()=>{
    const v=parseFloat($('#cvtarget').value);
    if(isFinite(v)&&v>=0&&v<=100)setCurve({target:v,on:true});
  });
  ['#stlo','#sthi','#stn'].forEach(id=>$(id).addEventListener('change',readBinset));
  $('#stfit').addEventListener('click',()=>{
    const h=S.hist||{};
    S.hist=h.fit?{n:h.n,pct:h.pct}:{n:h.n,pct:h.pct,fit:true};
    paintBinset(); SEL=null; save(); renderStats();
  });
  $('#streset').addEventListener('click',()=>{S.hist={pct:byPct()};paintBinset();SEL=null;save();renderStats();});
  // switching units carries pinned ends across, so the same range stays shown
  $('#stunit').addEventListener('change',()=>{
    const h={...(S.hist||{})}, pct=$('#stunit').value==='pct', mt=maxTotal()||1;
    if(pct!==!!h.pct){
      const f=pct?100/mt:mt/100, r=x=>Math.round(x*f*100)/100;
      if(h.lo!=null)h.lo=r(h.lo); if(h.hi!=null)h.hi=r(h.hi);
    }
    h.pct=pct; S.hist=h; paintBinset(); SEL=null; save(); renderStats();
  });
  window.addEventListener('resize',()=>{if($('#stats').classList.contains('on'))renderStats();});
  $('#loadf').addEventListener('change',loadFile);
  $('#resetAll').addEventListener('click',()=>{
    if(!confirm('Put every sheet back to full marks?'))return;
    S.touched={};DATA.forEach(s=>PARTS.forEach(p=>setScore(s.k,p.id,suggested(s.k,p.id),false)));});
  DATA.forEach((s,i)=>$('#n_'+s.k).addEventListener('click',()=>go(i)));
  $('#sortby').value=S.sort||'sheet';
  if(!$('#sortby').value)$('#sortby').value='sheet';
  $('#sortby').addEventListener('change',()=>{S.sort=$('#sortby').value;save();sortList();});
  $('#resort').addEventListener('click',sortList);
  sortList(false);
  $$('.prev').forEach(b=>b.addEventListener('click',()=>step(-1)));
  $$('.next').forEach(b=>b.addEventListener('click',()=>step(1)));
  DATA.forEach(s=>{
    const k=s.k,c=$('#s_'+k);
    $$('.spin input',c).forEach(i=>i.addEventListener('change',e=>
      setScore(k,e.target.dataset.pid,e.target.value)));
    $$('.spin button',c).forEach(b=>b.addEventListener('click',()=>
      setScore(k,b.dataset.pid,(+S.score[k][b.dataset.pid]||0)+(+b.dataset.step))));
    $('.rst',c).addEventListener('click',()=>{
      PARTS.forEach(p=>setScore(k,p.id,S.max[p.id],false));
      delete S.touched[k];paint(k);save();});
    const nm=$('#f_name_'+k),sd=$('#f_sid_'+k),cm=$('#cmt_'+k);
    if(nm){nm.value=S.name[k]||'';nm.addEventListener('input',()=>{
      S.name[k]=nm.value;S.touched[k]=true;paint(k);save();});}
    if(sd){sd.value=S.sid[k]||'';sd.addEventListener('input',()=>{
      S.sid[k]=sd.value;S.touched[k]=true;save();});}
    cm.value=S.note[k]||'';cm.addEventListener('input',()=>{
      S.note[k]=cm.value;S.touched[k]=true;paint(k);save();});
    $$('.shots img, .idrow img',c).forEach((im,idx)=>im.addEventListener('click',()=>{
      const list=shotsOf(k);openViewer(list,idx<list.length?idx:0);}));
    $$('.pagebtn',c).forEach((b,i)=>b.addEventListener('click',()=>openViewer(pagesOf(k),i)));
  });
  // viewer controls
  $('#vclose').onclick=closeViewer;
  $('#vin').onclick=()=>zoomAt(1.25);
  $('#vout').onclick=()=>zoomAt(0.8);
  $('#vfit').onclick=fit;
  $('#vkeybtn').onclick=toggleKey;
  // similar-answers drawer
  $('#simclose').onclick=closeSim;
  $('#simback').onclick=()=>{if(SIM)simGo(SIM.k);};
  $('#simbody').addEventListener('click',e=>{
    const el=e.target.closest('[data-act]'); if(!el||!SIM)return;
    const act=el.dataset.act, it=el.closest('.sit'), pid=SIM.pid;
    if(act==='go')simGo(it.dataset.k);
    else if(act==='page')pageAt(it.dataset.k,pid);
    else if(act==='zoom')openViewer([{src:el.getAttribute('src'),
      label:(S.name[it.dataset.k]||it.dataset.k)+' — '+PARTS.find(p=>p.id===pid).label}],0);
    else if(act==='match')setScore(it.dataset.k,pid,+S.score[SIM.k][pid]||0);
    else if(act==='matchall'){
      const ref=+S.score[SIM.k][pid]||0, g=el.dataset.g;
      const l=SIM.list.filter(s=>g==='Same read'?s.sim>=1:(s.sim<1&&s.sim>=.6))
        .filter(s=>Math.abs((+S.score[s.k][pid]||0)-ref)>1e-9);
      if(!confirm('Give '+fmt(ref,2)+' to all '+l.length+' in "'+g+'"?'))return;
      l.forEach(s=>setScore(s.k,pid,ref));
    }
  });
  $('#vprev').onclick=()=>{V.at=(V.at-1+V.list.length)%V.list.length;showShot();};
  $('#vnext').onclick=()=>{V.at=(V.at+1)%V.list.length;showShot();};
  const st=$('#vstage');
  st.addEventListener('wheel',e=>{e.preventDefault();
    zoomAt(e.deltaY<0?1.12:0.89,e.clientX,e.clientY);},{passive:false});
  let drag=null;
  st.addEventListener('mousedown',e=>{drag={x:e.clientX-V.x,y:e.clientY-V.y};
    st.classList.add('drag');});
  window.addEventListener('mousemove',e=>{if(!drag)return;
    V.x=e.clientX-drag.x;V.y=e.clientY-drag.y;apply();});
  window.addEventListener('mouseup',()=>{drag=null;st.classList.remove('drag');});
  window.addEventListener('resize',()=>{if($('#viewer').classList.contains('on'))fit();});
  // keyboard
  document.addEventListener('keydown',e=>{
    const typing=['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName);
    if($('#viewer').classList.contains('on')){
      if(e.key==='Escape')closeViewer();
      else if(e.key==='ArrowRight')$('#vnext').click();
      else if(e.key==='ArrowLeft')$('#vprev').click();
      else if(e.key==='+'||e.key==='=')zoomAt(1.25);
      else if(e.key==='-')zoomAt(0.8);
      else if(e.key==='0')fit();
      else if((e.key==='k'||e.key==='K')&&KEY.length&&V.list[V.at].page)toggleKey();
      e.preventDefault(); return;
    }
    if($('#cdlg').classList.contains('on')){
      if(e.key==='Escape'){$('#cdlg').classList.remove('on');e.preventDefault();}
      else if(e.key==='Enter'&&document.activeElement.tagName!=='BUTTON'){$('#cgo').click();e.preventDefault();}
      return;
    }
    if($('#stats').classList.contains('on')){
      if(e.key==='Escape'||(e.key==='s'&&!typing)){closeStats();e.preventDefault();}
      return;
    }
    if(typing)return;
    if(e.key==='s'){openStats();e.preventDefault();return;}
    if(e.key==='g'&&$$('.simbtn').length){
      const k=DATA[cur].k, pid=PARTS[focusPart].id;
      if(SIM&&SIM.k===k&&SIM.pid===pid)closeSim(); else openSim(k,pid);
      e.preventDefault();return;}
    if(SIM){
      if(e.key==='Escape'){closeSim();e.preventDefault();return;}
      if(e.key===']'){simHop(1);e.preventDefault();return;}
      if(e.key==='['){simHop(-1);e.preventDefault();return;}
    }
    if(e.key==='m'){
      toggleNotes(DATA[cur].k,PARTS[focusPart].id,true); e.preventDefault();
      return;
    }
    const k=DATA[cur].k, ps=PARTS;
    const pid=ps[focusPart].id, now=+S.score[k][pid]||0;
    if(e.key==='J'||e.key==='ArrowDown'){step(1);e.preventDefault();}
    else if(e.key==='K'||e.key==='ArrowUp'){step(-1);e.preventDefault();}
    else if(e.key==='j'||e.key==='ArrowRight'){focusPart=Math.min(ps.length-1,focusPart+1);markFocus(true);e.preventDefault();}
    else if(e.key==='k'||e.key==='ArrowLeft'){focusPart=Math.max(0,focusPart-1);markFocus(true);e.preventDefault();}
    else if(e.key==='h'||e.key==='l'){
      // Step through this part's quick marks.  From a score between two of
      // them, the first press lands on the neighbour in that direction.
      const v=chipVals(pid);
      const to=e.key==='l'?v.find(x=>x>now+1e-9):[...v].reverse().find(x=>x<now-1e-9);
      if(to!=null)setScore(k,pid,to);
      e.preventDefault();
    }
    else if(e.key==='H'){setScore(k,pid,now-1);e.preventDefault();}
    else if(e.key==='L'){setScore(k,pid,now+1);e.preventDefault();}
    else if(e.key==='0'){setScore(k,ps[focusPart].id,0);}
    else if(e.key==='f'){
      // open on the page the focused part is printed on
      const pl=pagesOf(k), part=ps[focusPart];
      openViewer(pl,Math.max(0,Math.min(pl.length-1,(part?.page||1)-1)));e.preventDefault();}
    else if(e.key==='v'){const l=shotsOf(k);if(l.length)openViewer(l,0);e.preventDefault();}
    else if(/^[1-9]$/.test(e.key)){const i=+e.key-1;if(i<ps.length){focusPart=i;markFocus();}}
  });
  if(STALE){S.autoStamp=AUTO_STAMP;save();}
  applyMax(); go(0,false);
});
"""
