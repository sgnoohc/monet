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
.nav li{display:flex;justify-content:space-between;gap:6px;padding:5px 8px;
 border-radius:6px;cursor:pointer;font-size:12.5px;align-items:center}
.nav li:hover{background:var(--bg)}
.nav li.on{background:var(--sel);color:#fff}
.nav li .s{font-variant-numeric:tabular-nums;color:var(--mut)}
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
.tot b{font-size:20px}
.tot.edited{color:var(--acc)}
.idrow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:9px 0 3px}
.idrow img{height:34px;width:auto;border:1px solid var(--line);border-radius:6px;
 background:#fff;cursor:zoom-in}
.idrow input{width:210px}
.pagelinks{display:flex;gap:8px;align-items:center;margin-left:auto}
.pagelinks a.paper{color:var(--acc);text-decoration:none;font-size:12.5px;white-space:nowrap}
.pagelinks a.paper:hover{text-decoration:underline}
.part{display:grid;grid-template-columns:220px 1fr 200px;gap:14px;align-items:start;
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
.ptsgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
 gap:8px;margin-top:10px}
.ptsgrid label{display:flex;justify-content:space-between;gap:6px;align-items:center;
 font-size:12.5px;color:var(--mut)}
.ptsgrid input{width:64px}
#viewer{position:fixed;inset:0;z-index:100;background:rgba(12,12,14,.93);
 display:none;flex-direction:column}
#viewer.on{display:flex}
#viewer .vbar{display:flex;gap:10px;align-items:center;padding:9px 14px;color:#eee;
 font-size:13px;background:rgba(0,0,0,.35)}
#viewer .vbar button{background:#2a2a30;border-color:#44444c;color:#eee}
#viewer .vbar button:hover{background:#36363e}
#viewer .vstage{flex:1;overflow:hidden;position:relative;cursor:grab}
#viewer .vstage.drag{cursor:grabbing}
#viewer img{position:absolute;transform-origin:0 0;background:#fff;
 image-rendering:-webkit-optimize-contrast}
.vhint{color:#9a9aa2;font-size:12px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .shots img,
 :root:not([data-theme="light"]) .idrow img{filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"] .shots img,:root[data-theme="dark"] .idrow img{
 filter:invert(1) hue-rotate(180deg)}
@media (max-width:1100px){.layout{grid-template-columns:1fr}
 .nav{position:static;height:auto}.part{grid-template-columns:1fr}
 .sc{align-items:flex-start}.tot{margin-left:0;width:100%}}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
let S={max:{},score:{},note:{},name:{},sid:{},touched:{}};
try{const r=localStorage.getItem(STORE);if(r)S=Object.assign(S,JSON.parse(r));}catch(e){}
PARTS.forEach(p=>{if(S.max[p.id]==null)S.max[p.id]=p.points;});
function suggested(k,pid){
  const v=(AUTO[k]||{})[pid];
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
let cur=0, focusPart=0, T=null;
const maxTotal=()=>PARTS.reduce((a,p)=>a+(+S.max[p.id]||0),0);
const total=k=>PARTS.reduce((a,p)=>a+(+S.score[k][p.id]||0),0);
const touched=k=>!!S.touched[k];
function save(){clearTimeout(T);T=setTimeout(()=>{
  try{localStorage.setItem(STORE,JSON.stringify(S));$('#saved').textContent='saved locally';}
  catch(e){$('#saved').textContent='browser storage unavailable — use Save progress';}},250);}

function setScore(k,pid,v,flag=true){
  const mx=+S.max[pid]||0;
  v=Math.max(0,Math.min(mx,Math.round((+v||0)*2)/2));
  S.score[k][pid]=v; if(flag)S.touched[k]=true;
  const card=$('#s_'+k);
  const inp=$('#in_'+k+'_'+pid,card); if(inp)inp.value=v;
  $$('.chips button',$('#p_'+k+'_'+pid,card)).forEach(b=>
    b.classList.toggle('on',Math.abs((+b.dataset.v)-v)<1e-9));
  paint(k); save();
}
function paint(k){
  const el=$('#t_'+k); el.innerHTML='<b>'+total(k)+'</b> / '+maxTotal();
  el.classList.toggle('edited',touched(k));
  const li=$('#n_'+k);
  li.querySelector('.s').textContent=total(k);
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
      $$('.chips button',$('#p_'+s.k+'_'+p.id)).forEach(b=>{
        const nv=b.dataset.kind==='full'?v:b.dataset.kind==='half'?Math.round(v)/2:0;
        b.dataset.v=nv;b.textContent=b.dataset.kind==='full'?'full':String(nv);
        b.classList.toggle('on',Math.abs(nv-S.score[s.k][p.id])<1e-9);});
    });
  });
  $('#mxtot').textContent=maxTotal();
  DATA.forEach(s=>paint(s.k)); save();
}
/* ---- navigation ------------------------------------------------------- */
function go(i,scroll=true){
  const vis=visible();
  if(!vis.length)return;
  if(!vis.includes(i)) i = vis.find(n=>n>=i);
  if(i==null) i=vis[vis.length-1];
  cur=Math.max(0,Math.min(DATA.length-1,i)); focusPart=0;
  $$('.stu').forEach((c,n)=>c.classList.toggle('cur',n===cur));
  $$('.nav li').forEach((li,n)=>li.classList.toggle('on',n===cur));
  const pos=vis.indexOf(cur)+1;
  $$('.pos').forEach(e=>e.textContent=pos+' of '+vis.length);
  markFocus();
  const li=$('#n_'+DATA[cur].k);
  if(li)li.scrollIntoView({block:'nearest'});
  if(scroll)window.scrollTo({top:0,behavior:'instant'});
}
function visible(){
  return DATA.map((s,i)=>i).filter(i=>!$('#n_'+DATA[i].k).classList.contains('hide'));
}
function step(d){
  const vis=visible(), at=vis.indexOf(cur);
  if(at<0)return go(cur);
  const next=vis[Math.max(0,Math.min(vis.length-1,at+d))];
  go(next);
}
function markFocus(){
  $$('.part').forEach(p=>p.classList.remove('focus'));
  const card=$('#s_'+DATA[cur].k);
  const ps=$$('.part',card);
  if(ps[focusPart])ps[focusPart].classList.add('focus');
}
/* ---- full-screen viewer ----------------------------------------------- */
let V={list:[],at:0,zoom:1,x:0,y:0,nat:[0,0]};
function openViewer(list,at){
  V.list=list; V.at=at; $('#viewer').classList.add('on'); showShot();
}
function showShot(){
  const it=V.list[V.at];
  const img=$('#vimg');
  img.onload=()=>{V.nat=[img.naturalWidth,img.naturalHeight];fit();};
  img.src=it.src;
  $('#vlabel').textContent=it.label;
  $('#vcount').textContent=(V.at+1)+' / '+V.list.length;
}
function fit(){
  const st=$('#vstage').getBoundingClientRect();
  const [w,h]=V.nat;
  V.zoom=Math.min(st.width/w,st.height/h)*0.96;
  V.x=(st.width-w*V.zoom)/2; V.y=(st.height-h*V.zoom)/2; apply();
}
function apply(){
  const img=$('#vimg');
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
  return s.pages.map((p,i)=>({src:p,label:'full page '+(i+1)}));
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
    DATA.forEach(s=>{
      PARTS.forEach(p=>setScore(s.k,p.id,S.score[s.k][p.id],false));
      const nm=$('#f_name_'+s.k),sd=$('#f_sid_'+s.k),cm=$('#cmt_'+s.k);
      if(nm)nm.value=S.name[s.k]||'';if(sd)sd.value=S.sid[s.k]||'';
      if(cm)cm.value=S.note[s.k]||'';
      paint(s.k);
    });
    $('#saved').textContent='progress loaded';
  }catch(e){alert('Could not load: '+e.message);}};
  rd.readAsText(f); ev.target.value='';
}
function exportCSV(){
  const head=['Sheet','Name','ID'].concat(PARTS.map(p=>p.label+' /'+S.max[p.id]))
             .concat(['Total /'+maxTotal(),'Reviewed','Comment','Flags']);
  const q=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
  const out=[head.map(q).join(',')];
  DATA.forEach(s=>out.push([s.sheet,S.name[s.k],S.sid[s.k]]
    .concat(PARTS.map(p=>S.score[s.k][p.id]))
    .concat([total(s.k),touched(s.k)?'yes':'no',S.note[s.k],s.flags||'']).map(q).join(',')));
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
const ctarget=()=>CANVAS.outOf==null?maxTotal():CANVAS.outOf;
function cscale(v){
  const paper=maxTotal(),t=ctarget();
  if(!paper||t===paper)return v;
  let x=v*t/paper;
  if(CANVAS.step)x=Math.round(x/CANVAS.step)*CANVAS.step;
  return Math.round(x*1e4)/1e4;
}
function exportCanvas(){
  if(!CANVAS.roster.length)
    return alert('No roster was loaded with this page, so there are no Canvas '
                +'ids to upload against. Rebuild with: redpen grade');
  const ix=canvasIndex(),rows=[],lost=[],twice=[],claimed={};
  DATA.forEach(s=>{
    const id=(S.sid[s.k]||'').trim().toLowerCase();
    const r=(id&&ix.byId[id])||ix.byName[cfold(S.name[s.k])];
    if(!r)return lost.push((S.name[s.k]||s.k)+'  (sheet '+s.sheet+')');
    const key=r.i||r.s||r.n;
    if(claimed[key])return twice.push(r.n+'  (sheet '+s.sheet+')');
    claimed[key]=1;
    rows.push([r.n,r.i,r.s,r.l,r.sec,cscale(total(s.k))]);
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
                +(CANVAS.step?', to the nearest '+CANVAS.step:'')+'.');
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
    $('#n_'+s.k).classList.toggle('hide',!show);
  });
  go(cur,false);
}
/* ---- wiring ----------------------------------------------------------- */
document.addEventListener('DOMContentLoaded',()=>{
  PARTS.forEach(p=>$('#mx_'+p.id).addEventListener('change',applyMax));
  $('#filt').addEventListener('change',filt);
  $('#exp').addEventListener('click',exportCSV);
  $('#expcanvas').addEventListener('click',exportCanvas);
  $('#savef').addEventListener('click',saveFile);
  $('#loadf').addEventListener('change',loadFile);
  $('#resetAll').addEventListener('click',()=>{
    if(!confirm('Put every sheet back to full marks?'))return;
    S.touched={};DATA.forEach(s=>PARTS.forEach(p=>setScore(s.k,p.id,suggested(s.k,p.id),false)));});
  $$('.nav li').forEach((li,i)=>li.addEventListener('click',()=>go(i)));
  $$('.prev').forEach(b=>b.addEventListener('click',()=>step(-1)));
  $$('.next').forEach(b=>b.addEventListener('click',()=>step(1)));
  DATA.forEach(s=>{
    const k=s.k,c=$('#s_'+k);
    $$('.spin input',c).forEach(i=>i.addEventListener('change',e=>
      setScore(k,e.target.dataset.pid,e.target.value)));
    $$('.spin button',c).forEach(b=>b.addEventListener('click',()=>
      setScore(k,b.dataset.pid,(+S.score[k][b.dataset.pid]||0)+(+b.dataset.step))));
    $$('.chips button',c).forEach(b=>b.addEventListener('click',()=>
      setScore(k,b.dataset.pid,+b.dataset.v)));
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
      e.preventDefault(); return;
    }
    if(typing)return;
    const k=DATA[cur].k, ps=PARTS;
    if(e.key==='j'||e.key==='ArrowDown'){step(1);e.preventDefault();}
    else if(e.key==='k'||e.key==='ArrowUp'){step(-1);e.preventDefault();}
    else if(e.key==='ArrowRight'){focusPart=Math.min(ps.length-1,focusPart+1);markFocus();e.preventDefault();}
    else if(e.key==='ArrowLeft'){focusPart=Math.max(0,focusPart-1);markFocus();e.preventDefault();}
    else if(e.key==='h'){setScore(k,ps[focusPart].id,(+S.score[k][ps[focusPart].id]||0)-1);}
    else if(e.key==='l'){setScore(k,ps[focusPart].id,(+S.score[k][ps[focusPart].id]||0)+1);}
    else if(e.key==='0'){setScore(k,ps[focusPart].id,0);}
    else if(e.key==='f'){openViewer(pagesOf(k),0);e.preventDefault();}
    else if(e.key==='v'){const l=shotsOf(k);if(l.length)openViewer(l,0);e.preventDefault();}
    else if(/^[1-9]$/.test(e.key)){const i=+e.key-1;if(i<ps.length){focusPart=i;markFocus();}}
  });
  if(STALE){S.autoStamp=AUTO_STAMP;save();}
  applyMax(); go(0,false);
});
"""
