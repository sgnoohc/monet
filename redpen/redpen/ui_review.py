"""Identity review: confirm or correct who each sheet belongs to."""
from .ui_style import TOKENS

CSS = TOKENS + """
.bar{position:sticky;top:0;z-index:30;display:flex;gap:10px;align-items:center;
 flex-wrap:wrap;padding:9px 14px;background:var(--card);border-bottom:1px solid var(--line)}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 14px}
/* No overflow:hidden here — it silently disables position:sticky on the header. */
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);
 border:1px solid var(--line);border-radius:10px}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line2);
 vertical-align:middle;font-size:13px}
th{position:sticky;top:var(--barh,52px);z-index:5;
 background:var(--card);color:var(--mut);font-size:11.5px;text-transform:uppercase;
 letter-spacing:.04em;white-space:nowrap;
 border-bottom:1px solid var(--line);box-shadow:0 1px 0 var(--line)}
th:first-child{border-top-left-radius:10px}
th:last-child{border-top-right-radius:10px}
tr:last-child td:first-child{border-bottom-left-radius:10px}
tr:last-child td:last-child{border-bottom-right-radius:10px}
tr:last-child td{border-bottom:none}
col.c-sheet{width:62px}
col.c-name{width:360px}
col.c-pick{width:270px}
col.c-score{width:86px}
tr.flag{background:var(--blbg)}
tr.dupe{background:var(--nobg)}
tr.changed td:first-child{box-shadow:inset 3px 0 0 var(--acc)}
tr.hide{display:none}
td.n{font-variant-numeric:tabular-nums;color:var(--mut);white-space:nowrap}
td:first-child{font-weight:600}
td img{max-width:330px;height:auto;border:1px solid var(--line);border-radius:6px;
 background:#fff;cursor:zoom-in;display:block}
select.pick{width:230px}
.open{display:flex;gap:6px;align-items:center;margin-top:5px;flex-wrap:wrap}
.open a{color:var(--acc);text-decoration:none;font-size:12px}
.open a:hover{text-decoration:underline}
.open button.pg{padding:2px 8px;font-size:11.5px;border-radius:99px}
.ocr{font-size:11.5px;color:var(--mut);max-width:210px;overflow-wrap:anywhere}
.why{font-size:11.5px;color:var(--bl)}
.why.bad{color:var(--no)}
.ok{color:var(--ok);font-weight:600}
#big{position:fixed;inset:0;background:rgba(12,12,14,.94);display:none;z-index:99;
 align-items:center;justify-content:center;cursor:zoom-out}
#big.on{display:flex}
#big img{max-width:96vw;max-height:92vh;background:#fff;cursor:zoom-out}
#big.page img{max-width:none;max-height:none;height:96vh;width:auto;cursor:default}
#big .cap{position:fixed;top:10px;left:14px;color:#ddd;font-size:12px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) td img,
 :root:not([data-theme="light"]) #big img{filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"] td img,:root[data-theme="dark"] #big img{
 filter:invert(1) hue-rotate(180deg)}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const orig={}; SHEETS.forEach(s=>orig[s.sheet]=s.key);
function current(){const m={};$$('.pick').forEach(p=>m[p.dataset.sheet]=p.value);return m;}
function refresh(){
  const m=current(), count={};
  Object.values(m).forEach(v=>{if(v)count[v]=(count[v]||0)+1;});
  let changed=0, dupes=0, unassigned=0;
  $$('tr[data-sheet]').forEach(tr=>{
    const s=tr.dataset.sheet, v=m[s];
    tr.classList.toggle('changed', v!==orig[s]);
    tr.classList.toggle('dupe', !!v && count[v]>1);
    if(v!==orig[s])changed++;
    if(v && count[v]>1)dupes++;
    if(!v)unassigned++;
  });
  $('#stat').innerHTML='<b>'+changed+'</b> changed · '+
    (dupes?('<span style="color:var(--no)"><b>'+dupes+'</b> duplicate</span> · '):'')+
    (unassigned?('<b>'+unassigned+'</b> unassigned · '):'')+SHEETS.length+' sheets';
  $('#save').disabled = dupes>0;
  $('#save').title = dupes ? 'Two sheets point at the same student' : '';
}
function filt(){
  const m=$('#filt').value;
  $$('tr[data-sheet]').forEach(tr=>{
    const flagged=tr.dataset.flag==='1';
    const changed=tr.classList.contains('changed');
    let show = m==='all' || (m==='flagged'&&flagged) || (m==='changed'&&changed);
    tr.classList.toggle('hide',!show);
  });
}
function barHeight(){
  const b=document.querySelector('.bar');
  if(b)document.documentElement.style.setProperty('--barh',b.offsetHeight+'px');
}
window.addEventListener('resize',barHeight);
document.addEventListener('DOMContentLoaded',()=>{
  barHeight();
  $$('.pick').forEach(p=>p.addEventListener('change',()=>{refresh();filt();}));
  $('#filt').addEventListener('change',filt);
  $$('td img').forEach(im=>im.addEventListener('click',()=>{
    $('#big').classList.remove('page');
    $('#bigimg').src=im.src; $('#bigcap').textContent='';
    $('#big').classList.add('on');}));
  $$('button.pg').forEach(b=>b.addEventListener('click',()=>{
    $('#big').classList.add('page');
    $('#bigimg').src='/page?sheet='+b.dataset.sheet+'&p='+b.dataset.page;
    $('#bigcap').textContent='sheet '+b.dataset.sheet+' · page '+b.dataset.page
      +' — scroll to read, click outside to close';
    $('#big').classList.add('on');}));
  $('#big').addEventListener('click',()=>$('#big').classList.remove('on'));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#big').classList.remove('on');});
  $('#save').addEventListener('click',async()=>{
    $('#msg').textContent='applying...'; $('#save').disabled=true;
    try{
      const r=await fetch('/apply',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({assign:current()})});
      const j=await r.json();
      if(j.ok){
        $('#msg').innerHTML='<span class="ok">'+j.renamed+' renamed · '+
          j.resolved+' moved out of review</span> — reload to continue';
        SHEETS.forEach(s=>{if(j.now[s.sheet])orig[s.sheet]=j.now[s.sheet];});
        refresh();
      } else { $('#msg').textContent='error: '+j.error; $('#save').disabled=false; }
    }catch(err){$('#msg').textContent='error: '+err.message;$('#save').disabled=false;}
  });
  refresh(); filt();
});
"""
