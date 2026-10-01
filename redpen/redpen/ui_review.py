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
.open button.al{padding:2px 8px;font-size:11.5px;border-radius:99px}
.open button.al.on{border-color:var(--acc);color:var(--acc)}
.open button.al.on::after{content:" \\2713"}
.sug{font-size:11.5px;color:var(--acc)}
#al{position:fixed;inset:0;z-index:98;background:var(--bg);display:none;flex-direction:column}
#al.on{display:flex}
.altool{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:9px 14px;
 background:var(--card);border-bottom:1px solid var(--line)}
.alscroll{flex:1;overflow:auto;padding:14px;text-align:center}
.stage{position:relative;display:inline-block;touch-action:none;cursor:move;
 user-select:none;-webkit-user-select:none}
.stage img{display:block;height:calc(100vh - 100px);width:auto;background:#fff}
#al.zoom .stage img{height:calc(250vh - 250px)}
#alov{position:absolute;inset:0;transform-origin:50% 50%;pointer-events:none;
 outline:1px dashed var(--acc)}
#alov .z{position:absolute;border:1.5px solid var(--acc);background:rgba(30,95,168,.10)}
#alov .z.name{border-color:var(--name);background:rgba(122,79,181,.12)}
#alov .z span{position:absolute;left:2px;top:-15px;font-size:10px;color:var(--acc);
 white-space:nowrap}
#alov .z.name span{color:var(--name)}
#alov .x{position:absolute;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;
 border-radius:50%;border:1.5px solid var(--acc)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) td img,
 :root:not([data-theme="light"]) #big img,
 :root:not([data-theme="light"]) .stage img{filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"] td img,:root[data-theme="dark"] #big img,
:root[data-theme="dark"] .stage img{filter:invert(1) hue-rotate(180deg)}
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
    $('#bigimg').src='/page?sheet='+b.dataset.sheet+'&p='+b.dataset.page+'&v='+Date.now();
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
  alInit();
  refresh(); filt();
});

/* ---- alignment: move/turn the template's zones onto a crooked scan ---- */
const IDENT={dx:0,dy:0,rot:0,scale:1};
const AL={sheet:null,page:1,a:{...IDENT},saved:{...IDENT}};
const bySheet=n=>SHEETS.find(s=>String(s.sheet)===String(n));
function alDraw(){
  const im=$('#alimg'), w=im.clientWidth, h=im.clientHeight, a=AL.a;
  $('#alov').style.transform=
    `translate(${a.dx*w}px,${a.dy*h}px) rotate(${a.rot}deg) scale(${a.scale})`;
  if(document.activeElement!==$('#alrot'))$('#alrot').value=(+a.rot).toFixed(2);
  if(document.activeElement!==$('#alscale'))$('#alscale').value=(a.scale*100).toFixed(2);
  const dirty=Object.keys(IDENT).some(k=>Math.abs(a[k]-AL.saved[k])>1e-9);
  $('#almsg').textContent=dirty?'unsaved':'';
}
function alZones(){
  $('#alov').innerHTML='<div class="x"></div>'+ZONES.filter(z=>z.page===AL.page).map(z=>
    `<div class="z${z.name?' name':''}" style="left:${z.rect[0]*100}%;top:${z.rect[1]*100}%;`+
    `width:${z.rect[2]*100}%;height:${z.rect[3]*100}%"><span>${z.id}</span></div>`).join('');
}
function alPage(p){
  AL.page=p;
  const s=bySheet(AL.sheet), cur=(s.align||{})[String(p)]||{};
  AL.saved={...IDENT,...cur};
  AL.a={...AL.saved};
  alZones();
  $('#alimg').onload=alDraw;
  $('#alimg').src='/raw?sheet='+AL.sheet+'&p='+p;
  alDraw();
}
function alOpen(sheet){
  AL.sheet=sheet;
  $('#altitle').textContent='Align sheet '+sheet;
  const pages=[...Array(PAGES).keys()].map(i=>i+1);
  const s=bySheet(sheet), first=pages.find(p=>ZONES.some(z=>z.page===p&&z.name))||1;
  $('#alpage').innerHTML=pages.map(p=>`<option value="${p}">page ${p}`+
    `${(s.align||{})[p]?' \u2713':''}</option>`).join('');
  $('#alpage').style.display=PAGES>1?'':'none';
  $('#alpage').value=first;
  $('#al').classList.add('on');
  alPage(first);
}
function alClose(){$('#al').classList.remove('on');AL.sheet=null;}
function alInit(){
  $$('button.al').forEach(b=>b.addEventListener('click',()=>alOpen(b.dataset.sheet)));
  $('#alpage').addEventListener('change',()=>alPage(+$('#alpage').value));
  $('#alrot').addEventListener('input',()=>{
    const v=parseFloat($('#alrot').value); if(!isNaN(v)){AL.a.rot=v;alDraw();}});
  $('#alscale').addEventListener('input',()=>{
    const v=parseFloat($('#alscale').value);
    if(!isNaN(v)&&v>=50&&v<=200){AL.a.scale=v/100;alDraw();}});
  $('#al180').addEventListener('click',()=>{
    AL.a.rot=((AL.a.rot+360)%360)-180; alDraw();});
  $('#alreset').addEventListener('click',()=>{AL.a={...IDENT};alDraw();});
  $('#alzoom').addEventListener('click',()=>{
    $('#al').classList.toggle('zoom');alDraw();});
  $('#alcancel').addEventListener('click',alClose);
  window.addEventListener('resize',()=>{if(AL.sheet)alDraw();});

  const stage=$('.stage'); let drag=null;
  stage.addEventListener('pointerdown',e=>{
    const r=$('#alimg').getBoundingClientRect(), a=AL.a;
    const cx=r.left+r.width*(.5+a.dx), cy=r.top+r.height*(.5+a.dy);
    drag={x:e.clientX,y:e.clientY,w:r.width,h:r.height,a0:{...a},turn:e.shiftKey,
          size:e.altKey&&!e.shiftKey,
          ang:Math.atan2(e.clientY-cy,e.clientX-cx),
          dist:Math.max(8,Math.hypot(e.clientX-cx,e.clientY-cy))};
    stage.setPointerCapture(e.pointerId); e.preventDefault();
  });
  stage.addEventListener('pointermove',e=>{
    if(!drag)return;
    if(drag.size){
      const r=$('#alimg').getBoundingClientRect();
      const cx=r.left+r.width*(.5+drag.a0.dx), cy=r.top+r.height*(.5+drag.a0.dy);
      const k=Math.hypot(e.clientX-cx,e.clientY-cy)/drag.dist;
      AL.a.scale=Math.min(2,Math.max(.5,drag.a0.scale*k));
    }else if(drag.turn){
      const r=$('#alimg').getBoundingClientRect();
      const cx=r.left+r.width*(.5+drag.a0.dx), cy=r.top+r.height*(.5+drag.a0.dy);
      const ang=Math.atan2(e.clientY-cy,e.clientX-cx);
      AL.a.rot=drag.a0.rot+(ang-drag.ang)*180/Math.PI;
    }else{
      AL.a.dx=drag.a0.dx+(e.clientX-drag.x)/drag.w;
      AL.a.dy=drag.a0.dy+(e.clientY-drag.y)/drag.h;
    }
    alDraw();
  });
  const end=()=>{drag=null;};
  stage.addEventListener('pointerup',end); stage.addEventListener('pointercancel',end);

  document.addEventListener('keydown',e=>{
    if(!AL.sheet||e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
    const im=$('#alimg'), px=e.shiftKey?10:1, deg=e.shiftKey?1:0.1;
    const mv={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];
    if(mv){AL.a.dx+=mv[0]*px/im.clientWidth;AL.a.dy+=mv[1]*px/im.clientHeight;}
    else if(e.key==='[')AL.a.rot-=deg;
    else if(e.key===']')AL.a.rot+=deg;
    else if(e.key==='-'||e.key==='_')AL.a.scale=Math.max(.5,AL.a.scale-(e.shiftKey?.01:.001));
    else if(e.key==='='||e.key==='+')AL.a.scale=Math.min(2,AL.a.scale+(e.shiftKey?.01:.001));
    else if(e.key==='Escape'){alClose();return;}
    else return;
    e.preventDefault(); alDraw();
  });

  $('#alsave').addEventListener('click',async()=>{
    const sheet=AL.sheet, page=AL.page, a={...AL.a};
    a.rot=((a.rot+180)%360+360)%360-180;
    $('#almsg').textContent='re-cutting...'; $('#alsave').disabled=true;
    try{
      const r=await fetch('/align',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({sheet,page,align:a})});
      const j=await r.json();
      if(!j.ok){$('#almsg').textContent='error: '+j.error;return;}
      const s=bySheet(sheet); s.align=s.align||{}; s.align[String(page)]=a;
      const tr=$(`tr[data-sheet="${sheet}"]`);
      $(`button.al[data-sheet="${sheet}"]`).classList.toggle('on',j.aligned);
      if(j.name_img){const im=$('td img',tr); if(im)im.src=j.name_img;}
      $('td.ocr',tr).textContent=j.ocr||'';
      const sug=$('.sug',tr), pick=$('.pick',tr);
      if(j.suggest){
        if(j.suggest.key===pick.value){
          sug.textContent='re-read after aligning: agrees ('+j.suggest.score+')';
        }else if(j.suggest.confident){
          pick.value=j.suggest.key;
          sug.textContent='re-read after aligning: '+j.suggest.display+
            ' ('+j.suggest.score+') — selected, press Apply to keep';
        }else{
          sug.textContent='re-read after aligning: maybe '+j.suggest.display+
            ' ('+j.suggest.score+'), too weak to pick';
        }
        refresh(); filt();
      }
      alClose();
    }catch(err){$('#almsg').textContent='error: '+err.message;}
    finally{$('#alsave').disabled=false;}
  });
}
"""
