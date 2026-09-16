"""Shared design tokens for the two generated pages."""

TOKENS = """
:root{--bg:#f6f6f3;--card:#fff;--ink:#191919;--mut:#6d6d6d;--line:#e3e3de;--line2:#f0f0ec;
 --ok:#15703f;--okbg:#e9f5ee;--no:#a8201a;--nobg:#fcecea;--bl:#7d6100;--blbg:#fbf3d9;
 --acc:#1e5fa8;--sel:#1e5fa8;--name:#7a4fb5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#16161a;--card:#1f1f24;--ink:#ededef;--mut:#9b9ba3;--line:#32323a;--line2:#28282f;
 --ok:#69d197;--okbg:#153022;--no:#ff9b93;--nobg:#3a1f1d;--bl:#e6cb72;--blbg:#332c15;
 --acc:#6aa9ec;--sel:#2f6fb5;--name:#b389e8}}
:root[data-theme="dark"]{--bg:#16161a;--card:#1f1f24;--ink:#ededef;--mut:#9b9ba3;
 --line:#32323a;--line2:#28282f;--ok:#69d197;--okbg:#153022;--no:#ff9b93;--nobg:#3a1f1d;
 --bl:#e6cb72;--blbg:#332c15;--acc:#6aa9ec;--sel:#2f6fb5;--name:#b389e8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
button,select,input{font:inherit;color:inherit}
button,select{background:var(--card);border:1px solid var(--line);border-radius:7px;
 padding:5px 10px;cursor:pointer}
button:hover{background:var(--line2)}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
button.pri:hover{filter:brightness(1.08)}
button:disabled{opacity:.45;cursor:default}
input[type=number],input[type=text]{background:var(--card);border:1px solid var(--line);
 border-radius:6px;padding:4px 7px}
input[type=number]{text-align:center;font-variant-numeric:tabular-nums}
.muted,.hint{color:var(--mut)}
.hint{font-size:12px;line-height:1.45}
kbd{background:var(--line2);border:1px solid var(--line);border-radius:4px;
 padding:0 5px;font-size:11px;font-family:inherit}
.grow{flex:1}
"""
