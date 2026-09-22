"""The app shell: a library of quizzes down the side, one quiz's work beside it."""
from .ui_style import TOKENS

CSS = TOKENS + """
html,body{height:100%}
.wrap{display:grid;grid-template-columns:248px minmax(0,1fr);height:100vh}
.side{background:var(--card);border-right:1px solid var(--line);display:flex;
 flex-direction:column;min-height:0}
.brand{display:flex;align-items:center;gap:8px;padding:12px 14px 10px;font-weight:700}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--no)}
.side h4{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);
 margin:12px 14px 6px;font-weight:600}
.qs{list-style:none;margin:0;padding:0 8px;overflow:auto;flex:1;min-height:0}
.qs li{padding:7px 9px;border-radius:8px;cursor:pointer;margin-bottom:2px}
.qs li:hover{background:var(--bg)}
.qs li.on{background:var(--sel);color:#fff}
.qs .t{font-size:13px;font-weight:500;display:block;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.qs .m{font-size:11px;color:var(--mut);display:flex;gap:7px;margin-top:1px}
.qs li.on .m{color:#cfe0f3}
.qs .tag{padding:0 5px;border-radius:4px;background:var(--line2);font-size:10px}
.qs li.on .tag{background:rgba(255,255,255,.22)}
.foot{padding:9px 12px;border-top:1px solid var(--line);display:flex;gap:6px;
 flex-wrap:wrap}
.foot button{padding:4px 9px;font-size:12px}
.main{display:flex;flex-direction:column;min-width:0;min-height:0}
.top{display:flex;gap:8px;align-items:center;padding:8px 12px;background:var(--card);
 border-bottom:1px solid var(--line);flex-wrap:wrap}
.top .name{font-weight:650}
.tabs{display:flex;gap:5px}
.tabs button{padding:4px 11px;font-size:12.5px}
.tabs button.on{background:var(--sel);border-color:var(--sel);color:#fff}
.tabs button:disabled{opacity:.35}
.body{flex:1;min-height:0;position:relative;background:var(--bg)}
.body iframe{width:100%;height:100%;border:0;display:block;background:var(--bg)}
.panel{position:absolute;inset:0;overflow:auto;padding:22px 26px}
.panel.hide{display:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:16px 18px;margin:0 auto 16px;max-width:760px}
.card h3{margin:0 0 4px;font-size:14.5px}
.card p{margin:4px 0 12px;color:var(--mut);font-size:13px;line-height:1.5}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.log{background:var(--bg);border:1px solid var(--line2);border-radius:9px;
 padding:10px 12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 font-size:11.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;
 max-height:46vh;overflow:auto;margin-top:12px}
.log .w{color:var(--no)}
.log .g{color:var(--ok)}
.empty{max-width:520px;margin:12vh auto;text-align:center;color:var(--mut)}
.empty h2{color:var(--ink);font-size:19px;margin:0 0 8px}
.flist{list-style:none;margin:8px 0 0;padding:0;font-size:12.5px}
.flist li{display:flex;gap:8px;align-items:center;padding:5px 8px;border-radius:7px;
 background:var(--bg);margin-bottom:5px}
.flist code{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
 font-size:11.5px}
.sug{font-size:12px;margin-top:4px}
.sug button{padding:3px 8px;font-size:11.5px;margin:3px 4px 0 0;text-align:left}
.spin{display:inline-block;width:10px;height:10px;border-radius:50%;
 border:2px solid var(--line);border-top-color:var(--acc);animation:sp .7s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.pill{font-size:11px;padding:1px 7px;border-radius:20px;background:var(--line2);
 color:var(--mut)}
.pill.ok{background:var(--okbg);color:var(--ok)}
.pill.no{background:var(--nobg);color:var(--no)}
input[type=text].path{width:100%;font-size:12px;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let LIB={folders:[],quizzes:[],suggestions:[]}, CUR=null, TAB="compose";

const api=async(p,body)=>{
  const r=await fetch(p, body?{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)}:{});
  return r.json();
};

async function loadLib(keep){
  LIB=await api("/api/library");
  if(keep&&LIB.quizzes.some(q=>q.id===keep)) CUR=keep;
  else if(!LIB.quizzes.some(q=>q.id===CUR)) CUR=LIB.quizzes[0]?.id||null;
  paintSide(); paintMain();
}

function paintSide(){
  const notes=Object.entries(LIB.notes||{});
  $("#qs").innerHTML=LIB.quizzes.map(q=>`
    <li data-id="${q.id}" class="${q.id===CUR?"on":""}">
     <span class="t">${esc(q.title)}</span>
     <span class="m">${q.authored?'<span class="tag">written</span>':'<span class="tag">drawn</span>'}
      ${q.graded?'<span class="tag">graded</span>':""}
      <span>${q.parts||0} parts</span><span>${q.points||0} pts</span></span>
    </li>`).join("")
    || (notes.length
        ? notes.map(([f,n])=>`<li class="muted" style="cursor:default;display:block">
            <span class="t">${esc(f.replace(/^.*\//,""))}</span>
            <span class="m" style="display:block;white-space:normal">${esc(n)}</span></li>`).join("")
        : `<li class="muted" style="cursor:default">no quizzes yet</li>`);
}

function paintMain(){
  const q=LIB.quizzes.find(x=>x.id===CUR);
  if(!LIB.folders.length){ show("folders"); $("#qname").textContent=""; setTabs(null); return; }
  if(!q){ show(TAB==="new"?"new":"none"); $("#qname").textContent=""; setTabs(null); return; }
  $("#qname").textContent=q.title;
  $("#qmeta").innerHTML=`<span class="pill">${esc(q.stem)}</span>`+
    (q.authored?"":' <span class="pill">no source — zones were drawn by hand</span>');
  setTabs(q);
  show(TAB, q);
}

function setTabs(q){
  $$("#tabs button").forEach(b=>{
    b.classList.toggle("on", b.dataset.t===TAB);
    const need=b.dataset.need;
    b.disabled = !q || (need==="src"&&!q.authored) || (need==="cfg"&&!q.config);
  });
}

function show(what, q){
  $$(".panel").forEach(p=>p.classList.add("hide"));
  const frame=$("#frame");
  if(what==="compose"&&q){ frame.src=`/q/${q.id}/compose`; frame.style.display="block"; return; }
  frame.style.display="none"; frame.removeAttribute("src");
  const own=["folders","none","new"].includes(what);
  const el=$("#panel-"+(own?what:"step"));
  if(el) el.classList.remove("hide");
  if(what==="folders") paintFolders();
  else if(what==="new") paintNew();
  else if(what!=="none") paintStep(what,q);
}

function paintFolders(){
  $("#flist").innerHTML=LIB.folders.map(f=>
    `<li><code>${esc(f)}</code><button data-drop="${esc(f)}">Remove</button></li>`).join("")
    ||'<li class="muted">none yet</li>';
  $("#sug").innerHTML=LIB.suggestions.length
    ? "Found on this Mac: "+LIB.suggestions.map(d=>
      `<button data-add="${esc(d)}">${esc(d.replace(/^.*\/Users\/[^/]+\//,"~/"))}</button>`).join("")
    : "";
}

function paintNew(){
  $("#newerr").textContent="";
  $("#newtitle").value="";
  $("#newfolder").innerHTML=LIB.folders.map(f=>
    `<option value="${esc(f)}">${esc(f.replace(/^\/Users\/[^/]+\//,"~/"))}</option>`).join("");
  setTimeout(()=>$("#newtitle").focus(),30);
}

const STEPS={
 build:{h:"Build the paper",p:"Regenerate the quiz PDF, the answer key and the grading config from the source.",b:"Build"},
 zones:{h:"Zones",p:"Drag the answer rectangles on the template. Written quizzes get these from the build and do not need it.",b:"Open the zone editor"},
 scan:{h:"Split a scan",p:"Cut a bulk scan into one PDF per student, read the names on device and match them to the roster.",b:"Split"},
 verify:{h:"Verify names",p:"Confirm or correct who each sheet belongs to.",b:"Open the verifier"},
 grade:{h:"Grade",p:"Build the grading page and open it.",b:"Open the grading page"},
 canvas:{h:"Canvas",p:"Turn a graded export into a CSV the Canvas gradebook will import.",b:"Write the CSV"},
};

function paintStep(name,q){
  const s=STEPS[name]||{h:name,p:"",b:"Run"};
  $("#step-h").textContent=s.h; $("#step-p").textContent=s.p;
  $("#step-go").textContent=s.b; $("#step-go").dataset.step=name;
  $("#step-extra").innerHTML = name==="scan"
    ? `<label class="hint">Scan PDFs, one path per line — drag the files in from Finder
       <textarea id="scans" rows="3" style="width:100%;margin-top:4px"
        placeholder="/path/to/bulk-scan.pdf"></textarea></label>` : "";
  $("#step-log").innerHTML="";
}

// ---- events ------------------------------------------------------
document.addEventListener("click",async e=>{
  const li=e.target.closest("#qs li[data-id]");
  if(li){ CUR=li.dataset.id; paintSide(); paintMain(); return; }
  const t=e.target.closest("#tabs button");
  if(t&&!t.disabled){ TAB=t.dataset.t; setTabs(LIB.quizzes.find(x=>x.id===CUR)); paintMain(); return; }
  const add=e.target.closest("[data-add]");
  if(add){ await api("/api/folders",{add:add.dataset.add}); loadLib(CUR); return; }
  const drop=e.target.closest("[data-drop]");
  if(drop){ await api("/api/folders",{remove:drop.dataset.drop}); loadLib(CUR); return; }
  if(e.target.id==="addfolder"){
    const p=$("#folderpath").value.trim(); if(!p) return;
    const j=await api("/api/folders",{add:p});
    if(!j.ok) alert(j.error); else { $("#folderpath").value=""; loadLib(CUR); }
    return;
  }
  if(e.target.id==="managefolders"){ TAB="folders"; show("folders"); return; }
  if(e.target.id==="newquiz"){
    if(!LIB.folders.length){ TAB="folders"; show("folders"); return; }
    TAB="new"; show("new"); return;
  }
  if(e.target.id==="newcancel"){ TAB="compose"; paintMain(); return; }
  if(e.target.id==="newgo"){
    const title=$("#newtitle").value.trim();
    const folder=$("#newfolder").value;
    if(!title){ $("#newerr").textContent="give it a title"; return; }
    const j=await api("/api/new",{title,folder});
    if(!j.ok){ $("#newerr").textContent=j.error; return; }
    TAB="compose"; await loadLib(j.id);
    return;
  }
  const go=e.target.closest("#step-go");
  if(go) runStep(go.dataset.step);
});

async function runStep(name){
  const q=LIB.quizzes.find(x=>x.id===CUR); if(!q) return;
  const log=$("#step-log"); const go=$("#step-go");
  const body={};
  if(name==="scan") body.scans=$("#scans").value.split("\n").map(s=>s.trim()).filter(Boolean);
  go.disabled=true; log.innerHTML='<span class="spin"></span> working…';
  let j;
  try{
    j=await api(`/q/${q.id}/step/${name}`, body);
  }catch(err){
    j={log:["error: "+err]};
  }finally{
    // Always: a button left disabled by a failure is indistinguishable from
    // an app that has died.
    go.disabled=false;
  }
  if(j.url){ window.open(j.url,"_blank"); }
  log.innerHTML=(j.log||[j.error||"no output"]).map(l=>
    `<span class="${/warning|error/i.test(l)?"w":"g"}">${esc(l)}</span>`).join("\n");
  loadLib(CUR);
}

document.addEventListener("keydown",e=>{
  if(e.key==="Enter"&&e.target.id==="newtitle"){ e.preventDefault(); $("#newgo").click(); }
  if(e.key==="Escape"&&TAB==="new"){ TAB="compose"; paintMain(); }
});

loadLib();
"""
