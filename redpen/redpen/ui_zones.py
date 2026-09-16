"""Template editor: draw zones on the blank/key PDF and set the rubric."""
from .ui_style import TOKENS

CSS = TOKENS + """
.bar{position:sticky;top:0;z-index:30;display:flex;gap:10px;align-items:center;
 flex-wrap:wrap;padding:9px 14px;background:var(--card);border-bottom:1px solid var(--line)}
.bar input[type=number]{width:64px}
.main{display:grid;grid-template-columns:minmax(0,1fr) 520px}
.pane{padding:14px 14px 40px}
.tabs{display:flex;gap:6px;margin-bottom:10px;align-items:center}
.tabs button.on{background:var(--sel);border-color:var(--sel);color:#fff}
.stage{position:relative;display:inline-block;max-width:100%;
 border:1px solid var(--line);background:#fff;user-select:none;cursor:crosshair}
.stage img{display:block;max-width:100%;height:auto}
.zone{position:absolute;border:2px solid var(--acc);background:rgba(30,95,168,.10);
 cursor:move}
.zone .tag{position:absolute;top:-19px;left:-2px;font-size:11px;background:var(--acc);
 color:#fff;padding:0 5px;border-radius:4px 4px 0 0;white-space:nowrap}
.zone.name{border-color:var(--name);background:rgba(122,79,181,.12)}
.zone.name .tag{background:var(--name)}
.zone.sel{box-shadow:0 0 0 2px rgba(0,0,0,.2)}
.zone .grip{position:absolute;right:-6px;bottom:-6px;width:12px;height:12px;
 background:#fff;border:2px solid var(--acc);border-radius:2px;cursor:nwse-resize}
.side{position:sticky;top:48px;height:calc(100vh - 48px);overflow:auto;padding:12px 14px;
 border-left:1px solid var(--line);background:var(--card)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px;align-items:start}
.col{min-width:0}
.col.wide{grid-column:1 / -1;border-top:1px solid var(--line2);padding-top:4px}
.list.scroll{max-height:34vh;overflow:auto;padding-right:2px}
.side h3{display:flex;align-items:baseline;gap:8px;font-size:11.5px;text-transform:uppercase;
 letter-spacing:.05em;color:var(--mut);margin:14px 0 8px;
 border-bottom:1px solid var(--line2);padding-bottom:5px}
.col > h3:first-child{margin-top:0}
.side h3 .tot{margin-left:auto;text-transform:none;letter-spacing:0;font-size:12px}
.side label{display:flex;justify-content:space-between;gap:8px;align-items:center;
 font-size:12.5px;margin-bottom:7px}
.side label input[type=text],.side label input[type=number],.side label select{
 width:100%;max-width:190px}
.side label.ck{justify-content:flex-start;gap:7px}
.box{padding:9px;border:1px solid var(--line2);border-radius:8px;background:var(--bg);
 margin-bottom:9px}
#form.off,#pform.off{display:none}
.list{list-style:none;margin:0;padding:0;font-size:12.5px}
.list li{display:flex;justify-content:space-between;gap:8px;padding:4px 7px;
 border-radius:6px;cursor:pointer;align-items:center}
.list li:hover{background:var(--bg)}
.list li.on{background:var(--sel);color:#fff}
.list li .p{color:var(--mut);font-variant-numeric:tabular-nums}
.list li.on .p{color:#dbe8f7}
.list li input[type=checkbox]{margin:0 2px 0 0;cursor:pointer}
.list li .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bulk{display:flex;flex-wrap:wrap;gap:5px;margin:7px 0 6px}
.bulk button{padding:3px 8px;font-size:11.5px}
.bulk button.danger{color:var(--no);border-color:var(--nobd)}
.bulk button.danger:hover{background:var(--nobg)}
.selhdr{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--mut);
 margin-bottom:5px}
.selhdr .count{margin-left:auto;font-variant-numeric:tabular-nums}
.stepper{display:flex;align-items:center;gap:6px;margin-bottom:9px}
.stepper button{padding:4px 11px}
.stepper .at{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums;
 margin-left:auto}
.zone.mark{outline:2px dashed var(--acc);outline-offset:2px}
.tot{font-variant-numeric:tabular-nums}
.warn{color:var(--bl)}
@media (max-width:1240px){.main{grid-template-columns:minmax(0,1fr) 400px}
 .cols{grid-template-columns:1fr}.col.wide{grid-column:auto}}
@media (max-width:980px){.main{grid-template-columns:1fr}
 .side{position:static;height:auto;border-left:none;border-top:1px solid var(--line)}
 .list.scroll{max-height:none}}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
let cfg=STATE.cfg, page=1, sel=null;
const marked=new Set();            // multi-selection for the bulk actions
cfg.zones=cfg.zones||[]; cfg.parts=cfg.parts||[];
const PPS=()=>Math.max(1,+$('#pps').value||1);
const partOf=id=>cfg.parts.find(p=>p.zones.includes(id));
const byId=id=>cfg.parts.find(p=>p.id===id);
const uniq=b=>{let n=b,i=1;while(cfg.zones.some(z=>z.id===n))n=b+'_'+(++i);return n;};

function tabs(){
  const t=$('#tabs'); t.innerHTML='';
  for(let i=1;i<=PPS();i++){
    const b=document.createElement('button');
    b.textContent='Page '+i; if(i===page)b.className='on';
    b.onclick=()=>{page=i;sel=null;render();};
    t.appendChild(b);
  }
}
function render(){
  tabs();
  const st=$('#stage');
  st.innerHTML='<img id="sheet" src="'+(PAGES[page-1]||PAGES[0])+'" alt="template page">';
  const img=$('#sheet');
  const place=()=>{
    $$('.zone',st).forEach(e=>e.remove());
    cfg.zones.filter(z=>z.page===page).forEach(z=>{
      const d=document.createElement('div');
      const isName=cfg.name_zone===z.id;
      d.className='zone'+(isName?' name':'')+(sel===z.id?' sel':'');
      d.style.left=(z.rect[0]*100)+'%'; d.style.top=(z.rect[1]*100)+'%';
      d.style.width=(z.rect[2]*100)+'%'; d.style.height=(z.rect[3]*100)+'%';
      const p=partOf(z.id);
      if(marked.has(z.id))d.classList.add('mark');
      d.innerHTML='<span class="tag">'+z.id+(isName?' (name)':(p?' · '+p.points+'p':''))
                 +'</span><span class="grip"></span>';
      d.onmousedown=ev=>drag(ev,z,ev.target.classList.contains('grip')?'size':'move');
      st.appendChild(d);
    });
  };
  img.complete?place():img.onload=place;
  st.onmousedown=ev=>{ if(ev.target.id==='sheet') draw(ev); };
  list(); form();
}
function rel(ev){
  const r=$('#sheet').getBoundingClientRect();
  return {x:Math.min(1,Math.max(0,(ev.clientX-r.left)/r.width)),
          y:Math.min(1,Math.max(0,(ev.clientY-r.top)/r.height))};
}
function draw(ev){
  ev.preventDefault();
  const a=rel(ev);
  const z={id:'_new',page:page,rect:[a.x,a.y,0,0],kind:'answer'};
  cfg.zones.push(z);
  const mv=e=>{const b=rel(e);
    z.rect=[Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(b.x-a.x),Math.abs(b.y-a.y)];
    render();};
  const up=()=>{
    document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);
    if(z.rect[2]<0.006||z.rect[3]<0.004){cfg.zones.pop();render();return;}
    const suggested=cfg.name_zone?('q'+(cfg.zones.length)):'name';
    const label=(window.prompt('Label for this zone (e.g. 1a, 2b_gap, name):',suggested)||'').trim();
    if(!label){cfg.zones.pop();render();return;}
    z.id=uniq(label.replace(/\s+/g,'_'));
    if(!cfg.name_zone && /^name$/i.test(label)){ cfg.name_zone=z.id; z.kind='name'; }
    else { addToPart(z.id,z.id); }
    sel=z.id; render();
  };
  document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
}
function addToPart(zid,pid){
  let p=byId(pid);
  if(!p){p={id:pid,label:pid,key:'',points:1,zones:[]};cfg.parts.push(p);}
  cfg.parts.forEach(q=>q.zones=q.zones.filter(x=>x!==zid));
  p.zones.push(zid);
  cfg.parts=cfg.parts.filter(q=>q.zones.length);
}
function drag(ev,z,mode){
  ev.preventDefault();ev.stopPropagation();sel=z.id;
  const s=rel(ev), r0=z.rect.slice();
  const mv=e=>{const p=rel(e),dx=p.x-s.x,dy=p.y-s.y;
    if(mode==='move') z.rect=[Math.max(0,Math.min(1-r0[2],r0[0]+dx)),
                              Math.max(0,Math.min(1-r0[3],r0[1]+dy)),r0[2],r0[3]];
    else z.rect=[r0[0],r0[1],Math.max(0.006,Math.min(1-r0[0],r0[2]+dx)),
                             Math.max(0.004,Math.min(1-r0[1],r0[3]+dy))];
    render();};
  const up=()=>{document.removeEventListener('mousemove',mv);
                document.removeEventListener('mouseup',up);};
  document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
  render();
}
function list(){
  const ul=$('#zlist'); ul.innerHTML='';
  cfg.zones.forEach(z=>{
    const li=document.createElement('li'); if(sel===z.id)li.className='on';
    const p=partOf(z.id);
    const cb=document.createElement('input');
    cb.type='checkbox'; cb.checked=marked.has(z.id);
    cb.onclick=ev=>{ev.stopPropagation();
      cb.checked?marked.add(z.id):marked.delete(z.id);render();};
    const nm=document.createElement('span'); nm.className='nm';
    nm.innerHTML=z.id+(cfg.name_zone===z.id?' <em>name</em>':'');
    const pp=document.createElement('span'); pp.className='p';
    pp.textContent='p'+z.page+(p?' · '+p.id:'');
    li.append(cb,nm,pp);
    li.onclick=()=>{page=z.page;sel=z.id;render();};
    ul.appendChild(li);
  });
  $('#selcount').textContent=marked.size+' selected';
  $$('.bulk button.needsel').forEach(b=>b.disabled=(marked.size===0));
  const pl=$('#plist'); pl.innerHTML='';
  cfg.parts.forEach(p=>{
    const li=document.createElement('li');
    li.innerHTML='<span>'+p.label+'</span><span class="p">'+p.points+'p · '+
                 p.zones.length+' zone'+(p.zones.length>1?'s':'')+'</span>';
    li.onclick=()=>{const z=cfg.zones.find(z=>z.id===p.zones[0]);
                    if(z){page=z.page;sel=z.id;render();}};
    pl.appendChild(li);
  });
  const tot=cfg.parts.reduce((a,p)=>a+(+p.points||0),0);
  const want=+$('#target').value||0;
  $('#tot').innerHTML='<b>'+tot+'</b> points across '+cfg.parts.length+' parts'+
    (want&&tot!==want?' <span class="warn">(target '+want+')</span>':'');
  $('#nameok').textContent = cfg.name_zone ? ('name zone: '+cfg.name_zone)
                                           : 'no name zone yet — draw one and label it "name"';
}
function stepZone(d){
  if(!cfg.zones.length)return;
  const i=cfg.zones.findIndex(z=>z.id===sel);
  let n;
  if(i<0) n = d>0 ? 0 : cfg.zones.length-1;
  else    n = (i+d+cfg.zones.length)%cfg.zones.length;
  const z=cfg.zones[n];
  sel=z.id; page=z.page; render();
}
function form(){
  const z=cfg.zones.find(x=>x.id===sel);
  $('#form').classList.toggle('off',!z);
  $$('.stepper button').forEach(b=>b.disabled=!cfg.zones.length);
  if(!z){ $('#zat').textContent=cfg.zones.length?('— of '+cfg.zones.length):'no zones'; return; }
  const at=cfg.zones.findIndex(x=>x.id===z.id);
  $('#zat').textContent=(at+1)+' of '+cfg.zones.length;
  $('#z_id').value=z.id; $('#z_page').value=z.page;
  $('#z_name').checked=(cfg.name_zone===z.id);
  const p=partOf(z.id);
  $('#pform').classList.toggle('off',!p);
  $('#z_part').value=p?p.id:'';
  if(p){$('#p_label').value=p.label;$('#p_key').value=p.key;$('#p_points').value=p.points;}
}
function bind(){
  const Z=()=>cfg.zones.find(x=>x.id===sel);
  $('#z_id').onchange=e=>{const z=Z(),n=e.target.value.trim().replace(/\s+/g,'_');
    if(!n||cfg.zones.some(x=>x!==z&&x.id===n)){e.target.value=z.id;return;}
    cfg.parts.forEach(p=>{const i=p.zones.indexOf(z.id);if(i>=0)p.zones[i]=n;
                          if(p.id===z.id)p.id=n;});
    if(cfg.name_zone===z.id)cfg.name_zone=n;
    z.id=n;sel=n;render();};
  $('#z_page').onchange=e=>{const z=Z();z.page=Math.max(1,Math.min(PPS(),+e.target.value||1));
    page=z.page;render();};
  $('#z_name').onchange=e=>{const z=Z();
    if(e.target.checked){cfg.name_zone=z.id;z.kind='name';
      cfg.parts.forEach(p=>p.zones=p.zones.filter(x=>x!==z.id));
      cfg.parts=cfg.parts.filter(p=>p.zones.length);}
    else{if(cfg.name_zone===z.id)cfg.name_zone=null;z.kind='answer';addToPart(z.id,z.id);}
    render();};
  $('#z_part').onchange=e=>{const z=Z(),n=e.target.value.trim();
    if(n)addToPart(z.id,n);render();};
  $('#p_label').onchange=e=>{const p=partOf(sel);if(p){p.label=e.target.value;render();}};
  $('#p_key').onchange=e=>{const p=partOf(sel);if(p)p.key=e.target.value;};
  $('#p_points').onchange=e=>{const p=partOf(sel);if(p){p.points=+e.target.value||0;render();}};
  $('#z_del').onclick=()=>{const z=Z();
    cfg.zones=cfg.zones.filter(x=>x!==z);
    cfg.parts.forEach(p=>p.zones=p.zones.filter(x=>x!==z.id));
    cfg.parts=cfg.parts.filter(p=>p.zones.length);
    if(cfg.name_zone===z.id)cfg.name_zone=null;
    sel=null;render();};
  // ---- bulk actions on the ticked zones -----------------------------------
  const removeZones=ids=>{
    cfg.zones=cfg.zones.filter(z=>!ids.has(z.id));
    cfg.parts.forEach(p=>p.zones=p.zones.filter(x=>!ids.has(x)));
    cfg.parts=cfg.parts.filter(p=>p.zones.length);
    if(cfg.name_zone&&ids.has(cfg.name_zone))cfg.name_zone=null;
    ids.forEach(i=>marked.delete(i));
    if(ids.has(sel))sel=null;
    render();
  };
  $('#selall').onclick=()=>{cfg.zones.forEach(z=>marked.add(z.id));render();};
  $('#selpage').onclick=()=>{cfg.zones.filter(z=>z.page===page)
                               .forEach(z=>marked.add(z.id));render();};
  $('#selnone').onclick=()=>{marked.clear();render();};
  $('#delsel').onclick=()=>{
    if(!marked.size)return;
    if(!confirm('Delete '+marked.size+' selected zone'+(marked.size>1?'s':'')+'?'))return;
    removeZones(new Set(marked));
  };
  $('#delpage').onclick=()=>{
    const ids=new Set(cfg.zones.filter(z=>z.page===page).map(z=>z.id));
    if(!ids.size)return;
    if(!confirm('Delete all '+ids.size+' zone(s) on page '+page+'?'))return;
    removeZones(ids);
  };
  $('#delall').onclick=()=>{
    if(!cfg.zones.length)return;
    if(!confirm('Delete ALL '+cfg.zones.length+' zones and the whole rubric? '
                +'This cannot be undone.'))return;
    cfg.zones=[];cfg.parts=[];cfg.name_zone=null;marked.clear();sel=null;render();
  };
  $('#grpsel').onclick=()=>{
    const ids=[...marked].filter(i=>i!==cfg.name_zone);
    if(ids.length<2){alert('Tick two or more answer zones to group them.');return;}
    const pid=(prompt('Grade these '+ids.length+' zones as one part. Part id:',ids[0])||'').trim();
    if(!pid)return;
    ids.forEach(i=>addToPart(i,pid));
    render();
  };
  $('#ptssel').onclick=()=>{
    const ids=[...marked].filter(i=>i!==cfg.name_zone);
    if(!ids.length)return;
    const v=prompt('Points for each of these parts:','1');
    if(v===null)return;
    const n=+v||0;
    new Set(ids.map(i=>partOf(i)).filter(Boolean)).forEach(p=>p.points=n);
    render();
  };
  $('#alignsel').onclick=()=>{
    const zs=cfg.zones.filter(z=>marked.has(z.id));
    if(zs.length<2){alert('Tick two or more zones to line them up.');return;}
    const first=zs[0];
    zs.slice(1).forEach(z=>{z.rect[0]=first.rect[0];z.rect[2]=first.rect[2];});
    render();
  };
  $('#zprev').onclick=()=>stepZone(-1);
  $('#znext').onclick=()=>stepZone(1);
  $('#pps').onchange=()=>{tabs();render();};
  $('#target').onchange=list;
  document.addEventListener('keydown',e=>{
    if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return;
    if(e.key==='Escape'){sel=null;render();}
    if(e.key===']'||e.key==='n'){e.preventDefault();stepZone(1);}
    if(e.key==='['||e.key==='p'){e.preventDefault();stepZone(-1);}
    if((e.key==='Delete'||e.key==='Backspace')&&sel){e.preventDefault();$('#z_del').click();}
  });
  $('#save').onclick=async()=>{
    $('#msg').textContent='saving...';
    const body={zones:cfg.zones,parts:cfg.parts,name_zone:cfg.name_zone,
                pages_per_student:PPS(),dpi:+$('#dpi').value||200,
                ocr_dpi:+$('#odpi').value||400};
    try{
      const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
                                  body:JSON.stringify(body)});
      const j=await r.json();
      $('#msg').textContent=j.ok?('saved · '+j.zones+' zones · '+j.parts+' parts · '+j.points+' pts')
                                :('error: '+j.error);
    }catch(err){$('#msg').textContent='error: '+err.message;}
  };
}
bind(); render();
"""
