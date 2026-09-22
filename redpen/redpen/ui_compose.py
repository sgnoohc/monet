"""Composer: write the quiz in a form, watch the paper build itself."""
from .ui_style import TOKENS

CSS = TOKENS + """
.bar{position:sticky;top:0;z-index:30;display:flex;gap:10px;align-items:center;
 flex-wrap:wrap;padding:9px 14px;background:var(--card);border-bottom:1px solid var(--line)}
.bar input[type=number]{width:60px}
.main{display:grid;grid-template-columns:230px minmax(0,1fr) minmax(0,46vw);
 height:calc(100vh - 47px)}
.col{overflow:auto;padding:12px 14px}
.left{border-right:1px solid var(--line);background:var(--card)}
.prev{border-left:1px solid var(--line);background:var(--card);padding:0;
 display:flex;flex-direction:column}
h3{display:flex;align-items:baseline;gap:8px;font-size:11.5px;text-transform:uppercase;
 letter-spacing:.05em;color:var(--mut);margin:16px 0 8px;
 border-bottom:1px solid var(--line2);padding-bottom:5px}
h3:first-child{margin-top:0}
label{display:block;font-size:12px;color:var(--mut);margin-bottom:8px}
label input[type=text],label input[type=number],label textarea,label select{
 display:block;width:100%;margin-top:3px}
textarea{background:var(--card);border:1px solid var(--line);border-radius:6px;
 padding:5px 7px;font:inherit;color:inherit;width:100%;resize:vertical;
 line-height:1.4;overflow:hidden}
textarea.mono,input.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 font-size:12px}
textarea:focus,input:focus{outline:2px solid var(--acc);outline-offset:-1px}

/* ---- outline ---- */
.tree{list-style:none;margin:0 0 10px;padding:0;font-size:12.5px}
.tree li{padding:3px 7px;border-radius:6px;cursor:pointer;display:flex;gap:6px}
.tree li:hover{background:var(--bg)}
.tree li.p{font-weight:600;margin-top:5px}
.tree li.q{padding-left:20px;color:var(--mut)}
.tree li .g{margin-left:auto;font-variant-numeric:tabular-nums;font-size:11.5px}
.tally{font-size:12.5px;padding:7px 9px;border-radius:8px;background:var(--bg);
 border:1px solid var(--line2);margin-bottom:8px}
.tally b{font-variant-numeric:tabular-nums}
.tally.bad{background:var(--nobg);border-color:var(--no)}
.tally.good{background:var(--okbg)}
#status{font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
#status .w{color:var(--no)}
#status .k{color:var(--ok)}

/* ---- problem cards ---- */
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;
 padding:11px 13px 13px;margin-bottom:13px}
/* Wraps rather than pushing the delete button off the edge: the middle
   column is whatever the preview leaves, which is not much. */
.chead{display:flex;gap:7px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.chead .num{font-weight:700;font-size:15px;min-width:17px;color:var(--mut)}
.chead input[type=text]{flex:1;min-width:120px;font-weight:600}
/* Archived: legible enough to find and restore, quiet enough to scroll past. */
.card.off{border-style:dashed;background:none;padding-bottom:11px}
/* One line: the note gives way before the buttons do. */
.card.off .chead{margin-bottom:0;flex-wrap:nowrap}
.card.off .tiny{flex:0 1 auto;min-width:0;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.card.off .num,.card.off .offtitle{color:var(--mut)}
/* The title is what identifies the thing you archived, so it holds its width
   and the note beside it gives way instead. */
.offtitle{flex:0 0 auto;max-width:55%;font-weight:600;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis;text-decoration:line-through;
 text-decoration-color:var(--line2)}
.tree li.p.off span:first-child{text-decoration:line-through;
 text-decoration-color:var(--line2)}
.tree li.p.off{font-weight:500;color:var(--mut)}
.chead input[type=number]{width:62px}
.part{border-top:1px solid var(--line2);margin-top:11px;padding-top:9px}
.phead{display:flex;gap:7px;align-items:center;margin-bottom:6px}
.phead .lbl{font-weight:600;min-width:22px}
.phead input[type=number]{width:58px}
.room{display:inline-flex;align-items:center;gap:2px;border:1px solid var(--line);
 border-radius:7px;padding:1px 2px;background:var(--bg)}
.room b{min-width:46px;text-align:center;font-size:11.5px;font-weight:500;
 color:var(--mut);font-variant-numeric:tabular-nums}
.room .icon{padding:1px 6px;border:0;background:none}
.room .icon:hover{background:var(--card);border-radius:5px}
.tiny{font-size:11px;color:var(--mut)}
.icon{padding:2px 7px;font-size:12px;line-height:1.5}
.icon.danger{color:var(--no);border-color:var(--line)}
.icon.danger:hover{background:var(--nobg)}
.add{padding:3px 9px;font-size:12px;margin-top:7px}
.boxes{margin:8px 0 6px}
.boxes table{width:100%;border-collapse:collapse;font-size:12.5px}
.boxes th{text-align:left;font-weight:500;font-size:10.5px;color:var(--mut);
 text-transform:uppercase;letter-spacing:.04em;padding:0 5px 3px 0}
.boxes td{padding:0 5px 5px 0;vertical-align:top}
.boxes input{width:100%}
.boxes select{padding:4px 5px;width:100%;min-width:76px}
.boxes td.x{width:26px;padding-right:0}
.boxes td.pts,.boxes th:nth-last-child(2){width:62px}
.sketch td.dim{width:78px}
.sol{margin-top:2px}

/* ---- preview ---- */
.tabs{display:flex;gap:6px;padding:8px 10px;border-bottom:1px solid var(--line);
 align-items:center}
.tabs button.on{background:var(--sel);border-color:var(--sel);color:#fff}
.pane{flex:1;overflow:auto;background:var(--bg);padding:10px;min-height:0}
.pane embed,.pane iframe{width:100%;height:100%;border:0;background:#fff}
.pg{position:relative;display:block;margin:0 auto 12px;box-shadow:0 1px 5px rgba(0,0,0,.18);
 background:#fff;width:100%}
.pg img{display:block;width:100%;height:auto}
.zn{position:absolute;border:1.5px solid var(--acc);background:rgba(30,95,168,.13)}
.zn.name{border-color:var(--name);background:rgba(122,79,181,.15)}
.zn i{position:absolute;top:-15px;left:-1px;font-size:9.5px;font-style:normal;
 background:var(--acc);color:#fff;padding:0 4px;border-radius:3px 3px 0 0;white-space:nowrap}
.zn.name i{background:var(--name)}
.spin{display:inline-block;width:9px;height:9px;border-radius:50%;
 border:2px solid var(--line);border-top-color:var(--acc);animation:sp .7s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const LETTERS="abcdefghijklmnopqrstuvwxyz";
let DOC=STATE.doc, VER=0, ZONES=[], PAGES=1, dirty=false;
// ?view=zones deep-links a pane, which is also how the pane is checked
// without a human in front of it.
let VIEW=new URLSearchParams(location.search).get("view")||"quiz";
// Every request is relative to this, so the composer works both on its own
// and mounted under /q/<id>/ inside the app window.
const BASE=STATE.base||"";

// ---- paths -------------------------------------------------------
// Every field carries the path of the value it edits, so one listener binds
// the whole form and adding a field needs no new wiring.
const get=p=>p.split(".").reduce((o,k)=>o[k],DOC);
const setv=(p,v)=>{const k=p.split("."),l=k.pop();k.reduce((o,x)=>o[x],DOC)[l]=v;};

const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// ---- writing room -------------------------------------------------
// Sub-parts share what is left of the page equally, so 1 is "equal" and the
// stepper is the only way to set it: a decimal typed into a box was the thing
// that made this hard to aim, and there is no useful value between 1 and 1.25.
const ROOM=[0.25,0.5,0.75,1,1.25,1.5,2,2.5,3,4];
const roomLabel=g=>{const v=Number(g??1);
  return v===1?"equal":"\u00d7"+v;};
function roomStep(g,d){
  const v=Number(g??1);
  // Nearest rung first, so a value typed into the JSON by hand still steps.
  let i=0; ROOM.forEach((x,k)=>{if(Math.abs(x-v)<Math.abs(ROOM[i]-v))i=k;});
  return ROOM[Math.max(0,Math.min(ROOM.length-1,i+d))];
}

function blankBox(){return{label:"answer",answer:"",key:"",alt:[],kind:"answer",
  points:"",w:"3.4cm",h:"1.9em"};}
function blankPart(){return{question:"",boxes:[blankBox()],solution:[],gap:1};}
function blankProblem(){return{title:"",points:10,page:0,direct:false,off:false,
  stem:"",parts:[blankPart()]};}

// ---- marks -------------------------------------------------------
// Mirrors quizdoc.part_points: shown live so a rubric that does not add up is
// visible while it is being written, not when the marking is done.
const nval=v=>{const t=String(v==null?"":v).trim();
  if(t==="")return null; const n=Number(t); return isNaN(n)?null:n;};
const splitBoxes=q=>q.boxes.some(b=>nval(b.points)!==null);
// What a sub-part is worth if it says so itself: set on the sub-part, or
// implied by every box carrying its own marks.
function partTotal(q){
  const v=nval(q.points); if(v!==null) return v;
  const bp=q.boxes.map(b=>nval(b.points));
  return bp.length&&bp.every(x=>x!==null) ? bp.reduce((a,b)=>a+b,0) : null;
}
function boxPoints(q,total){
  const n=q.boxes.length, out=new Array(n).fill(0), free=[];
  q.boxes.forEach((b,i)=>{const v=nval(b.points); if(v!==null) out[i]=v; else free.push(i);});
  if(free.length){
    let left=Number(total)-out.reduce((a,b)=>a+b,0), acc=0;
    free.forEach((i,k)=>{ out[i]= k===free.length-1 ? Math.round((left-acc)*1000)/1000
                                                    : Math.round(left/free.length*2)/2;
                          acc+=out[i]; });
  }
  return out;
}
function partPoints(p){
  const n=p.parts.length, out=new Array(n).fill(0), free=[];
  let left=Number(p.points)||0;
  p.parts.forEach((q,i)=>{ const t=partTotal(q);
    if(t!==null){out[i]=t;left-=t;} else free.push(i); });
  if(free.length){
    const w=free.map(i=>p.parts[i].boxes.length), tot=w.reduce((a,b)=>a+b,0)||1;
    let acc=0;
    free.forEach((i,n2)=>{
      if(n2===free.length-1) out[i]=Math.round((left-acc)*1000)/1000;
      else {out[i]=Math.round(left*w[n2]/tot*2)/2; acc+=out[i];}
    });
  }
  return out;
}
// Archived problems are not on the paper, so they are not in the tally, not
// in the outline and not in the numbering -- the marks have to add up to what
// gets printed, not to what happens to be in the file.
const onPaper=()=>DOC.problems.filter(p=>!p.off);
const totalPoints=()=>onPaper().reduce((a,p)=>a+(Number(p.points)||0),0);

// ---- the form ----------------------------------------------------
function boxRow(bp,b,pi,qi,bi,nb,pts){
  const sk=b.kind==="sketch";
  return `<tr class="${sk?"sketch":""}">
   <td><input type="text" data-path="${bp}.label" value="${esc(b.label)}"></td>
   <td><input type="text" class="mono" data-path="${bp}.answer" value="${esc(b.answer)}"
        placeholder="printed on the key"></td>
   <td><input type="text" data-path="${bp}.key" value="${esc(b.key||"")}"
        placeholder="${esc(b.answer||"same")}"></td>
   <td><input type="text" data-list="${bp}.alt" value="${esc((b.alt||[]).join(" | "))}"
        placeholder="a | b"></td>
   <td><select data-path="${bp}.kind">
     <option value="answer"${sk?"":" selected"}>answer</option>
     <option value="sketch"${sk?" selected":""}>sketch</option></select></td>
   ${sk?`<td class="dim"><input type="text" data-path="${bp}.w" value="${esc(b.w)}"></td>
        <td class="dim"><input type="text" data-path="${bp}.h" value="${esc(b.h)}"></td>`
      :`<td colspan="2"></td>`}
   <td class="pts"><input type="number" step="0.5" min="0" data-path="${bp}.points"
        value="${b.points!=null&&b.points!==""?b.points:""}" placeholder="${pts}"
        title="marks for this box alone — blank shares the sub-part's marks"></td>
   <td class="x">${nb>1?`<button class="icon danger" data-act="delbox"
     data-pi="${pi}" data-qi="${qi}" data-bi="${bi}" title="remove this box">&times;</button>`:""}</td>
  </tr>`;
}

function partCard(p,q,pi,qi,pts,direct){
  const qp=`problems.${pi}.parts.${qi}`;
  const each=boxPoints(q,pts);
  const rows=q.boxes.map((b,bi)=>
    boxRow(`${qp}.boxes.${bi}`,b,pi,qi,bi,q.boxes.length,each[bi])).join("");
  // An answers-only problem has no letter and no question of its own: the
  // problem statement is the question, and the boxes sit beside it.
  return `<div class="part">
   <div class="phead">
    <span class="lbl">${direct?"":"("+LETTERS[qi]+")"}</span>
    ${direct?'<span class="tiny">writing room</span>':`
    <input type="number" step="0.5" min="0" data-path="${qp}.points"
      value="${q.points!=null&&q.points!==""?q.points:""}" placeholder="${pts}"
      title="marks — blank splits the problem's marks by box count">`}
    <span class="room" title="writing room \u2014 every sub-part on the page gets an equal share; this nudges it off equal">
     <button class="icon" data-act="room-" data-pi="${pi}" data-qi="${qi}">&minus;</button>
     <b>${roomLabel(q.gap)}</b>
     <button class="icon" data-act="room+" data-pi="${pi}" data-qi="${qi}">+</button>
    </span>
    <span class="grow"></span>
    ${direct?"":`
    <button class="icon" data-act="upq" data-pi="${pi}" data-qi="${qi}" title="move up">&uarr;</button>
    <button class="icon" data-act="dnq" data-pi="${pi}" data-qi="${qi}" title="move down">&darr;</button>
    <button class="icon danger" data-act="delq" data-pi="${pi}" data-qi="${qi}"
      title="delete this sub-part">&times;</button>`}
   </div>
   ${direct?"":`<textarea data-path="${qp}.question" rows="2"
     placeholder="What the student is asked…">${esc(q.question)}</textarea>`}
   <div class="boxes"><table>
    <tr><th>label</th><th>answer (on the key)</th><th>OCR reads</th><th>also accept</th>
        <th>kind</th><th colspan="2"></th><th>marks</th><th></th></tr>
    ${rows}
   </table>
   <button class="add" data-act="addbox" data-pi="${pi}" data-qi="${qi}">+ Add box</button>
   </div>
   <textarea class="sol mono" data-join="${qp}.solution" rows="2"
     placeholder="Worked solution — a blank line starts the next step. Key only."
     >${esc((q.solution||[]).join("\n\n"))}</textarea>
  </div>`;
}

function render(){
  // The whole form is thrown away and rebuilt, so note where the caret is and
  // put it back: without this, a field that re-renders as you type (marks,
  // kind, the layout switch) loses focus after one character.
  const a=document.activeElement;
  const keep=a&&a.dataset?(a.dataset.path||a.dataset.list||a.dataset.join):null;
  let s0=null,s1=null;
  if(keep){try{s0=a.selectionStart;s1=a.selectionEnd;}catch(_){}}
  const pageOpts=n=>{let s=`<option value="0"${n?"":" selected"}>auto</option>`;
    for(let i=1;i<=DOC.pages;i++) s+=`<option value="${i}"${n===i?" selected":""}>p${i}</option>`;
    return s;};
  let num=0;
  $("#form").innerHTML=DOC.problems.map((p,pi)=>{
    // Archived: it keeps its place in the form so it can be found and put
    // back, but collapses to its title -- an off problem that still filled
    // the column would be the same clutter as deleting it was meant to avoid.
    if(p.off) return `<section class="card off" id="prob${pi}">
     <div class="chead">
      <span class="num">&ndash;</span>
      <span class="offtitle">${esc(p.title||"untitled")}</span>
      <span class="tiny">archived &mdash; ${p.points||0} points, not on the paper</span>
      <span class="grow"></span>
      <button class="icon" data-act="onoff" data-pi="${pi}"
        title="put it back on the paper">Restore</button>
      <button class="icon danger" data-act="delp" data-pi="${pi}"
        title="delete this problem for good">&times;</button>
     </div>
    </section>`;
    const pts=partPoints(p);
    const direct=!!p.direct;
    num++;
    return `<section class="card" id="prob${pi}">
     <div class="chead">
      <span class="num">${num}</span>
      <input type="text" data-path="problems.${pi}.title" value="${esc(p.title)}"
        placeholder="Problem title">
      <input type="number" step="0.5" min="0" data-path="problems.${pi}.points"
        value="${p.points}" title="marks for the whole problem">
      <select data-path="problems.${pi}.page" data-num="1"
        title="which page">${pageOpts(Number(p.page)||0)}</select>
      <select data-path="problems.${pi}.direct" data-bool="1"
        title="lettered sub-parts, or answer boxes straight on the problem">
       <option value=""${direct?"":" selected"}>(a) (b) (c)</option>
       <option value="1"${direct?" selected":""}
        ${p.parts.length>1&&!direct?" disabled":""}>answers only</option>
      </select>
      <button class="icon" data-act="upp" data-pi="${pi}" title="move up">&uarr;</button>
      <button class="icon" data-act="dnp" data-pi="${pi}" title="move down">&darr;</button>
      <button class="icon" data-act="onoff" data-pi="${pi}"
        title="archive &mdash; keep it here, off the paper">Off</button>
      <button class="icon danger" data-act="delp" data-pi="${pi}"
        title="delete this problem">&times;</button>
     </div>
     <textarea data-path="problems.${pi}.stem" rows="2"
       placeholder="Set the scene — the situation all the sub-parts share.">${esc(p.stem)}</textarea>
     ${p.parts.map((q,qi)=>partCard(p,q,pi,qi,pts[qi],direct)).join("")}
     ${direct?"":`<button class="add" data-act="addpart" data-pi="${pi}">+ Add sub-part</button>`}
    </section>`;
  }).join("");
  $$("textarea").forEach(grow);
  outline();
  if(keep){
    const el=$(`[data-path="${keep}"],[data-list="${keep}"],[data-join="${keep}"]`);
    if(el){el.focus(); if(s0!=null){try{el.setSelectionRange(s0,s1);}catch(_){}}}
  }
}

function outline(){
  let h="", num=0;
  DOC.problems.forEach((p,pi)=>{
    if(p.off){
      h+=`<li class="p off" data-go="prob${pi}"><span>${esc(p.title||"untitled")}</span>
          <span class="g">off</span></li>`;
      return;
    }
    const pts=partPoints(p);
    num++;
    h+=`<li class="p" data-go="prob${pi}"><span>${num}. ${esc(p.title||"untitled")}</span>
        <span class="g">${p.points||0}</span></li>`;
    p.parts.forEach((q,qi)=>{
      const tag=p.direct?"":`(${LETTERS[qi]}) `;
      if(splitBoxes(q)){
        const each=boxPoints(q,pts[qi]);
        q.boxes.forEach((b,bi)=>{
          h+=`<li class="q" data-go="prob${pi}"><span>${tag}${esc(b.label)}</span>
              <span class="g">${each[bi]}</span></li>`;
        });
      } else {
        h+=`<li class="q" data-go="prob${pi}"><span>${tag}${esc(q.boxes.map(b=>b.label).join(", "))}</span>
            <span class="g">${pts[qi]}</span></li>`;
      }
    });
  });
  $("#outline").innerHTML=h;
  const t=totalPoints(), want=Number($("#target").value)||0;
  const el=$("#tally");
  el.className="tally"+(want&&t!==want?" bad":(want?" good":""));
  const nOff=DOC.problems.length-onPaper().length;
  el.innerHTML=`<b>${t}</b> points over ${onPaper().length} problems`+
    (nOff?` <span class="tiny">(${nOff} archived)</span>`:"")+
    (want&&t!==want?` — target is <b>${want}</b>`:"");
}

function grow(t){t.style.height="auto";t.style.height=(t.scrollHeight+2)+"px";}

// ---- editing -----------------------------------------------------
document.addEventListener("input",e=>{
  const t=e.target;
  if(t.tagName==="TEXTAREA") grow(t);
  if(t.id==="target"){outline();return;}
  if(t.dataset.path){
    let v=t.value;
    if(t.type==="number") v = v===""?"":Number(v);
    if(t.dataset.num) v=Number(v);
    if(t.dataset.bool) v=!!v;
    setv(t.dataset.path,v);
  } else if(t.dataset.join){
    setv(t.dataset.join, t.value.split(/\n\s*\n/).map(s=>s.trim()).filter(Boolean));
  } else if(t.dataset.list){
    setv(t.dataset.list, t.value.split("|").map(s=>s.trim()).filter(Boolean));
  } else if(t.dataset.doc){
    setv(t.dataset.doc, t.dataset.num?Number(t.value):t.value);
  } else return;
  // A label shows up only in the outline, which is redrawn either way — so it
  // does not earn a full rebuild of the form.
  if(t.dataset.path&&/\.(kind|points|direct)$/.test(t.dataset.path)) render();
  else outline();
  touch();
});

document.addEventListener("click",e=>{
  const b=e.target.closest("[data-act]"), g=e.target.closest("[data-go]");
  if(g&&!b){const el=$("#"+g.dataset.go); if(el) el.scrollIntoView({behavior:"smooth",block:"start"});}
  if(!b) return;
  const pi=+b.dataset.pi, qi=+b.dataset.qi, bi=+b.dataset.bi, a=b.dataset.act;
  const P=DOC.problems, mv=(arr,i,d)=>{const j=i+d; if(j<0||j>=arr.length)return;
    [arr[i],arr[j]]=[arr[j],arr[i]];};
  // The room stepper edits in place rather than re-rendering: the button has
  // to survive being clicked five times in a row.
  if(a==="room-"||a==="room+"){
    const q=P[pi].parts[qi];
    q.gap=roomStep(q.gap, a==="room+"?1:-1);
    b.parentNode.querySelector("b").textContent=roomLabel(q.gap);
    touch(); return;
  }
  if(a==="addprob") P.push(blankProblem());
  else if(a==="onoff") P[pi].off=!P[pi].off;
  else if(a==="delp"){ if(P.length<2||!confirm(`Delete problem ${pi+1}?`))return; P.splice(pi,1);}
  else if(a==="upp") mv(P,pi,-1);
  else if(a==="dnp") mv(P,pi,1);
  else if(a==="addpart") P[pi].parts.push(blankPart());
  else if(a==="delq"){ if(P[pi].parts.length<2||!confirm("Delete this sub-part?"))return;
    P[pi].parts.splice(qi,1);}
  else if(a==="upq") mv(P[pi].parts,qi,-1);
  else if(a==="dnq") mv(P[pi].parts,qi,1);
  else if(a==="addbox") P[pi].parts[qi].boxes.push(blankBox());
  else if(a==="delbox") P[pi].parts[qi].boxes.splice(bi,1);
  else return;
  render(); touch();
});

// ---- preview -----------------------------------------------------
let timer=null, running=false, again=false;
function touch(){dirty=true; clearTimeout(timer); timer=setTimeout(preview,450);}

async function preview(){
  if(running){again=true;return;}
  running=true; again=false;
  $("#msg").innerHTML='<span class="spin"></span>';
  try{
    const r=await fetch(BASE+"/preview",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(DOC)});
    const j=await r.json();
    if(j.pending){
      // The previous preview stays on screen: it is still the last thing that
      // compiled, and blanking it mid-equation would be worse than stale.
      $("#status").innerHTML='<span class="muted">still typing — '+esc(j.pending)+"</span>";
      $("#msg").textContent="saved";
    }
    else if(!j.ok){ $("#status").innerHTML='<span class="w">'+esc(j.error)+"</span>";
               $("#msg").textContent="saved, not built"; }
    else{
      ZONES=j.zones; PAGES=j.pages; VER++;
      $("#status").innerHTML=j.log.map(l=>
        `<span class="${/warning|error/.test(l)?"w":"k"}">${esc(l)}</span>`).join("\n");
      $("#msg").textContent="saved";
      paint();
    }
  }catch(err){ $("#status").innerHTML='<span class="w">'+esc(err)+"</span>"; }
  running=false;
  if(again) preview();
}

function paint(){
  const pane=$("#pane");
  if(VIEW==="zones"){
    let h="";
    for(let p=1;p<=PAGES;p++){
      h+=`<div class="pg"><img src="${BASE}/png/${p}?v=${VER}">`;
      ZONES.filter(z=>z.page===p).forEach(z=>{
        h+=`<div class="zn ${z.kind==="name"?"name":""}" style="left:${z.x*100}%;
          top:${z.y*100}%;width:${z.w*100}%;height:${z.h*100}%"><i>${esc(z.id)}</i></div>`;
      });
      h+="</div>";
    }
    pane.innerHTML=h;
  } else {
    // An iframe rather than an embed: the same built-in PDF viewer, but it
    // also renders inside a WKWebView, which the Mac app will be.
    pane.innerHTML=`<iframe src="${BASE}/pdf/${VIEW}?v=${VER}#toolbar=0&view=FitH"></iframe>`;
  }
}

$$(".tabs button").forEach(b=>b.classList.toggle("on", b.dataset.v===VIEW));
$$(".tabs button").forEach(b=>b.addEventListener("click",()=>{
  VIEW=b.dataset.v; $$(".tabs button").forEach(x=>x.classList.toggle("on",x===b)); paint();
}));

$("#build").addEventListener("click",async()=>{
  $("#msg").innerHTML='<span class="spin"></span>';
  const r=await fetch(BASE+"/build",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(DOC)});
  const j=await r.json();
  $("#status").innerHTML=(j.log||[esc(j.error)]).map(l=>
    `<span class="${/warning|error/.test(l)?"w":"k"}">${esc(l)}</span>`).join("\n");
  $("#msg").textContent=j.ok?"built":"build failed";
  if(j.ok){ZONES=j.zones;PAGES=j.pages;VER++;paint();}
});

$$("[data-doc]").forEach(el=>el.addEventListener("input",()=>{
  if(el.dataset.doc==="pages") render();
}));

window.addEventListener("beforeunload",e=>{if(dirty&&$("#msg").textContent!=="saved")
  {e.preventDefault();e.returnValue="";}});

render(); paint(); preview();
"""
