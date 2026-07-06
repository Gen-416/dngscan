# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-page HTML shell for the local dngscan web GUI."""
from __future__ import annotations

import json

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>dngscan</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,"PingFang SC",system-ui,sans-serif;background:#15171c;color:#e7e9ee}
.wrap{max-width:960px;margin:0 auto;padding:22px}
h1{font-size:17px;font-weight:600;margin:0 0 16px}
.card{background:#1d2028;border:1px solid #2b2f3a;border-radius:12px;padding:16px;margin-bottom:14px}
label{display:block;font-size:12px;color:#9aa1b0;margin:0 0 6px}
input[type=text],input[type=number],select{width:100%;background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#e7e9ee;padding:8px 10px;font:inherit}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>div{flex:1;min-width:150px}
.modes{display:flex;gap:8px;flex-wrap:wrap}
.modes button{flex:1;min-width:110px;background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#cdd2dd;padding:10px;cursor:pointer;font:inherit;text-align:left}
.modes button .m{font-weight:600;color:#e7e9ee}
.modes button .d{font-size:11px;color:#828a99}
.modes button.sel{border-color:#5b8cff;background:#1a2233}
.evrow{display:flex;align-items:center;gap:12px}
input[type=range]{flex:1}
.evval{width:64px;text-align:right;font-variant-numeric:tabular-nums}
button.go{background:#5b8cff;border:0;border-radius:9px;color:#fff;padding:11px 18px;font:inherit;font-weight:600;cursor:pointer}
button.go:disabled{opacity:.5;cursor:default}
button.ghost{background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#cdd2dd;padding:8px 12px;cursor:pointer;font:inherit}
button.preview{background:#2c3444;border:1px solid #46536b;border-radius:9px;color:#eef2ff;padding:11px 18px;font:inherit;font-weight:600;cursor:pointer}
button.preview:disabled{opacity:.5;cursor:default}
.muted{color:#828a99;font-size:12px}
#status{margin-top:10px;min-height:20px}
.err{color:#ff8a8a}.ok{color:#8ae08a}
#browser{display:none;margin-top:10px;border:1px solid #2b2f3a;border-radius:8px;max-height:260px;overflow:auto;background:#12141a}
#browser div{padding:6px 10px;cursor:pointer;border-bottom:1px solid #20242e;font-size:13px}
#browser div:hover{background:#1a2233}
#previewWrap{position:relative;margin-top:12px;min-height:0}
#previewWrap.loading{min-height:240px}
#preview{max-width:100%;border-radius:8px;display:none;transition:opacity .15s ease}
#previewWrap.loading #preview{opacity:.4}
#spinner{display:none;position:absolute;left:50%;top:50%;width:34px;height:34px;margin:-17px 0 0 -17px;border:3px solid rgba(255,255,255,.22);border-top-color:#eef2ff;border-radius:50%;animation:spin .8s linear infinite}
#previewWrap.loading #spinner{display:block}
@keyframes spin{to{transform:rotate(360deg)}}
.dim{opacity:.45;pointer-events:none}
.chk{display:flex;align-items:center;gap:8px}.chk input{width:auto}
</style></head>
<body><div class="wrap">
<h1>dngscan · AgX RAW → JPEG</h1>

<div class="card">
  <label>DNG / RAW 文件</label>
  <div class="row" style="align-items:flex-end">
    <div style="flex:4"><input type="text" id="input" placeholder="/path/to/photo.dng"></div>
    <div style="flex:0"><button class="ghost" id="browseBtn">浏览…</button></div>
  </div>
  <div id="browser"></div>
</div>

<div class="card">
  <div class="row">
    <div>
      <label>曝光补偿 EV（手动或 auto 对齐 18% 灰）</label>
      <div class="evrow"><input type="range" id="ev" min="-3" max="3" step="0.05" value="0"><span class="evval" id="evval">+0.00</span></div>
      <div class="modes" style="margin-top:8px">
        <button type="button" data-ev="-0.50"><span class="m">-0.50</span></button>
        <button type="button" data-ev="0"><span class="m">0.00</span></button>
        <button type="button" data-ev="0.50"><span class="m">+0.50</span></button>
        <button type="button" data-ev="1.00"><span class="m">+1.00</span></button>
        <button type="button" id="evAutoBtn"><span class="m">auto</span><br><span class="d">18%灰·高光保护</span></button>
      </div>
    </div>
    <div style="flex:0;min-width:120px">
      <label>JPEG 质量</label>
      <input type="number" id="quality" min="1" max="100" value="100">
    </div>
    <div style="flex:0;min-width:150px">
      <label>色度采样</label>
      <select id="chroma" title="444=满色度、最高保真、体积最大；420=最小体积、投递推荐">
        <option value="444">4:4:4 · 满色度</option>
        <option value="422">4:2:2</option>
        <option value="420">4:2:0 · 最小</option>
      </select>
    </div>
    <div style="flex:0;min-width:160px">
      <label>高光处理</label>
      <select id="highlight">
        <option value="clip">clip · 硬剪切</option>
        <option value="blend">blend · 高光混合</option>
        <option value="reconstruct">reconstruct · 高光重建</option>
      </select>
    </div>
    <div style="flex:0;min-width:150px">
      <label>输出色域</label>
      <select id="gamut">
        <option value="srgb">sRGB · 兼容优先</option>
        <option value="p3">Display P3 · 宽色域</option>
      </select>
    </div>
    <div style="flex:0;min-width:220px">
      <label>成片风格</label>
      <select id="grade" title="色度 Look（Fujifilm/ARRI）与输出滤镜（Kodak/RED）互斥，一次只能选一种">
GRADE_OPTIONS
      </select>
    </div>
    <div id="gradeStrengthBlock" style="flex:0;min-width:180px;display:none">
      <label>风格强度</label>
      <div class="evrow"><input type="range" id="gradeStrength" min="0" max="1.5" step="0.05" value="1"><span class="evval" id="gradeStrengthVal">1.00</span></div>
    </div>
    <div style="flex:0;min-width:150px">
      <label>白平衡</label>
      <select id="wb" title="camera=相机 AsShot；daylight=固定日光配平（胶片式，整卷一致）">
        <option value="camera">相机 AsShot</option>
        <option value="daylight">日光固定配平</option>
      </select>
    </div>
    <div style="flex:0;min-width:170px">
      <label>去马赛克（画质·非降噪）</label>
      <select id="demosaic" title="彩色重建的插值算法，仅影响细节画质、仅全分辨率导出生效；本工具不做任何降噪">
        <option value="auto">auto · 自动(DHT优先)</option>
        <option value="dht">DHT</option>
        <option value="dcb">DCB</option>
        <option value="ahd">AHD</option>
        <option value="aahd">AAHD</option>
        <option value="vng">VNG</option>
        <option value="ppg">PPG</option>
      </select>
    </div>
    <div style="flex:0;min-width:190px">
      <label>输出格式</label>
      <select id="format">
        <option value="sdr">SDR JPEG</option>
        <option value="ultrahdr">HDR gain-map JPEG</option>
      </select>
    </div>
    <div style="min-width:220px">
      <label>HDR headroom（仅 HDR 输出）</label>
      <div class="evrow"><input type="range" id="hdrHeadroom" min="1" max="5" step="0.25" value="3"><span class="evval" id="hdrHeadroomVal">+3.00</span></div>
      <div class="muted" id="hdrHint">微信/QQ 想保住 HDR：走原图或文件，别走朋友圈。</div>
    </div>
  </div>
  <div style="margin-top:12px">
    <label>输出文件夹（留空=与源文件同目录）</label>
    <input type="text" id="outdir" placeholder="默认：源文件所在文件夹">
  </div>
  <div class="chk" style="margin-top:12px">
    <input type="checkbox" id="png"><label for="png" style="margin:0">同时导出六面板分析 PNG</label>
  </div>
</div>

<div class="card">
  <button class="preview" id="previewBtn">预览</button>
  <button class="go" id="go">导出</button>
  <button class="ghost" id="revealBtn" style="display:none">在 Finder 中显示</button>
  <div id="status"></div>
  <div id="previewWrap"><img id="preview"><div id="spinner"></div></div>
</div>

<script>
const $=s=>document.querySelector(s);
const STORE_KEY="dngscan.settings.v4";
function setGradeStrengthLabel(){const v=+$("#gradeStrength").value;$("#gradeStrengthVal").textContent=v.toFixed(2);}
function updateGradeUi(){$("#gradeStrengthBlock").style.display=$("#grade").value!=="none"?"block":"none";}
function setEvLabel(){const v=+$("#ev").value;$("#evval").textContent=(v>=0?"+":"")+v.toFixed(2);}
function setHdrLabel(){const v=+$("#hdrHeadroom").value;$("#hdrHeadroomVal").textContent="+"+v.toFixed(2);}
function fmtPct(v){if(v===undefined||!isFinite(v))return "";if(v<=0)return "0%";if(v<0.005)return "<0.01%";if(v<1)return "~"+v.toFixed(2)+"%";return v.toFixed(1)+"%";}
function fmtEv(v){return (v>=0?"+":"")+v.toFixed(2);}
function metricText(j){
  if(!j.metrics)return "";
  const m=j.metrics;
  if(m.luma_p999_pct===undefined)return "";
  const room=m.safe_ev_remaining!==undefined?m.safe_ev_remaining:m.headroom_luma_ev;
  const label=j.metrics_kind==="full"?" · 全分辨率真值":" · 预览估计";
  const roomText=j.metrics_kind==="full"&&room!==undefined?" · 可再加约 "+fmtEv(room)+"EV":"";
  return label+
    " · p99.9亮度 "+fmtPct(m.luma_p999_pct)+
    " · 近白 "+fmtPct(m.near_white_pct)+
    " · 顶白 "+fmtPct(m.clipped_channel_pct)+
    roomText;
}
function evAutoStatus(j){
  if(!j.ev_auto)return "";
  const a=j.ev_auto;
  let t=" · EV auto "+fmtEv(a.ev_boost);
  if(a.highlight_limited)t+="（高光限制，目标 "+fmtEv(a.ev_median_target)+"）";
  return t;
}
function applyJobEv(j){
  if(j.ev!==undefined){$("#ev").value=j.ev;setEvLabel();saveSettings();}
}
function saveSettings(){
  try{localStorage.setItem(STORE_KEY,JSON.stringify({
    input:$("#input").value,ev:$("#ev").value,quality:$("#quality").value,
    highlight:$("#highlight").value,gamut:$("#gamut").value,wb:$("#wb").value,demosaic:$("#demosaic").value,chroma:$("#chroma").value,format:$("#format").value,
    grade:$("#grade").value,gradeStrength:$("#gradeStrength").value,
    hdrHeadroom:$("#hdrHeadroom").value,outdir:$("#outdir").value,png:$("#png").checked
  }));}catch(e){}
}
function restoreSettings(){
  let s={};try{s=JSON.parse(localStorage.getItem(STORE_KEY)||"{}")||{};}catch(e){}
  if(s.input)$("#input").value=s.input;
  if(s.ev!==undefined)$("#ev").value=s.ev;
  if(s.quality)$("#quality").value=s.quality;
  if(s.highlight)$("#highlight").value=s.highlight;
  if(s.gamut)$("#gamut").value=s.gamut;
  if(s.wb)$("#wb").value=s.wb;
  if(s.demosaic)$("#demosaic").value=s.demosaic;
  if(s.chroma)$("#chroma").value=s.chroma;
  if(s.grade&&[...$("#grade").options].some(o=>o.value===s.grade))$("#grade").value=s.grade;
  else if(s.filter&&s.filter!=="none"&&[...$("#grade").options].some(o=>o.value===s.filter))$("#grade").value=s.filter;
  else if(s.look&&s.look!=="none"&&[...$("#grade").options].some(o=>o.value===s.look))$("#grade").value=s.look;
  if(s.gradeStrength!==undefined)$("#gradeStrength").value=s.gradeStrength;
  else if(s.filterStrength!==undefined&&s.filter&&s.filter!=="none")$("#gradeStrength").value=s.filterStrength;
  else if(s.lookStrength!==undefined)$("#gradeStrength").value=s.lookStrength;
  if(s.format)$("#format").value=s.format;
  if(s.hdrHeadroom!==undefined)$("#hdrHeadroom").value=s.hdrHeadroom;
  if(s.outdir)$("#outdir").value=s.outdir;
  if(s.png!==undefined)$("#png").checked=!!s.png;
  setEvLabel();setHdrLabel();setGradeStrengthLabel();updateGradeUi();
}
["input","quality","highlight","gamut","outdir","png"].forEach(id=>$("#"+id).addEventListener("change",saveSettings));
["wb","demosaic","chroma","grade"].forEach(id=>$("#"+id).addEventListener("change",()=>{updateGradeUi();saveSettings();}));
$("#format").addEventListener("change",()=>{if($("#format").value==="ultrahdr")$("#gamut").value="p3";saveSettings();});
$("#ev").oninput=()=>{setEvLabel();saveSettings();};
$("#hdrHeadroom").oninput=()=>{setHdrLabel();saveSettings();};
$("#gradeStrength").oninput=()=>{setGradeStrengthLabel();saveSettings();};
restoreSettings();
document.querySelectorAll("button[data-ev]").forEach(b=>b.onclick=()=>{$("#ev").value=b.dataset.ev;setEvLabel();saveSettings();});
let lastSavedPath="";

let curDir=INIT_DIR;
async function listDir(d){
  const r=await fetch("/list?dir="+encodeURIComponent(d));const j=await r.json();
  curDir=j.cwd;const b=$("#browser");b.innerHTML="";
  const mk=(t,fn)=>{const e=document.createElement("div");e.textContent=t;e.onclick=fn;b.appendChild(e);};
  mk("⬆︎ "+j.parent,()=>listDir(j.parent));
  j.dirs.forEach(d=>mk("📁 "+d,()=>listDir(j.cwd+"/"+d)));
  j.files.forEach(f=>mk("🖼 "+f,()=>{$("#input").value=j.cwd+"/"+f;b.style.display="none";saveSettings();}));
}
$("#browseBtn").onclick=()=>{const b=$("#browser");if(b.style.display==="block"){b.style.display="none";}else{b.style.display="block";listDir(curDir);}};

function payload(){
  const input=$("#input").value.trim();
  if(!input){setStatus("请先选择一个 DNG/RAW 文件","err");return null;}
  return {
    input,highlight:$("#highlight").value,gamut:$("#gamut").value,wb:$("#wb").value,demosaic:$("#demosaic").value,chroma:$("#chroma").value,format:$("#format").value,
    grade:$("#grade").value,gradeStrength:+$("#gradeStrength").value,
    hdrHeadroom:+$("#hdrHeadroom").value,ev:+$("#ev").value,quality:+$("#quality").value,
    outdir:$("#outdir").value.trim(),png:$("#png").checked
  };
}

async function postJob(path, body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  return await r.json();
}
function beginBusy(){const w=$("#previewWrap");w.classList.add("loading");}
function endBusy(){const w=$("#previewWrap");w.classList.remove("loading");}
function setPreviewImage(b64, ondone){
  const img=$("#preview");
  img.onload=()=>{img.style.display="block";endBusy();if(ondone)ondone();};
  img.onerror=()=>{endBusy();};
  img.src="data:image/jpeg;base64,"+b64;
}

function handleJobResult(j, prefix){
  if(!j.ok)return false;
  applyJobEv(j);
  setStatus(prefix+"：EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+j.highlight+"，色域 "+j.gamut+evAutoStatus(j)+metricText(j),"ok");
  setPreviewImage(j.preview);
  return true;
}

$("#previewBtn").onclick=async()=>{
  const body=payload();if(!body)return;
  $("#previewBtn").disabled=true;$("#revealBtn").style.display="none";beginBusy();setStatus("生成预览…（首次会建立缓存）","");
  try{
    const j=await postJob("/preview",body);
    if(!handleJobResult(j,"预览")){endBusy();setStatus("错误："+j.error,"err");}
  }catch(e){endBusy();setStatus("请求失败："+e,"err");}
  $("#previewBtn").disabled=false;
};

$("#evAutoBtn").onclick=async()=>{
  const body=payload();if(!body)return;
  body.evAuto=true;
  $("#previewBtn").disabled=true;$("#evAutoBtn").disabled=true;$("#revealBtn").style.display="none";beginBusy();setStatus("计算 EV auto…","");
  try{
    const j=await postJob("/preview",body);
    if(!handleJobResult(j,"EV auto 预览")){endBusy();setStatus("错误："+j.error,"err");}
  }catch(e){endBusy();setStatus("请求失败："+e,"err");}
  $("#previewBtn").disabled=false;$("#evAutoBtn").disabled=false;
};

$("#go").onclick=async()=>{
  const body=payload();if(!body)return;
  $("#go").disabled=true;$("#previewBtn").disabled=true;$("#revealBtn").style.display="none";beginBusy();setStatus("导出 full-res…","");
  try{
    const j=await postJob("/export",body);
    if(!j.ok){endBusy();setStatus("错误："+j.error,"err");}
    else{applyJobEv(j);setStatus("已保存："+j.saved.join(" · ")+"（"+j.format+"，EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+j.highlight+"，色域 "+j.gamut+evAutoStatus(j)+metricText(j)+"）","ok");
      lastSavedPath=j.saved[0]||"";$("#revealBtn").style.display=lastSavedPath?"inline-block":"none";setPreviewImage(j.preview);}
  }catch(e){endBusy();setStatus("请求失败："+e,"err");}
  $("#go").disabled=false;$("#previewBtn").disabled=false;
};
$("#revealBtn").onclick=async()=>{
  if(!lastSavedPath)return;
  $("#revealBtn").disabled=true;
  try{
    const j=await postJob("/reveal",{path:lastSavedPath});
    if(!j.ok)setStatus("Finder 打开失败："+j.error,"err");
  }catch(e){setStatus("Finder 请求失败："+e,"err");}
  $("#revealBtn").disabled=false;
};
function setStatus(t,c){const s=$("#status");s.textContent=t;s.className=c||"";}
</script>
</div></body></html>
"""


_LOOK_LABELS = {"classic": "ARRI Classic 709", "reveal": "ARRI Reveal 709"}


def _grade_options_html() -> str:
    from ..display_filter import DISPLAY_FILTERS, FILTER_CHOICES
    from ..look import LOOK_CHOICES

    lines = ['        <option value="none">无</option>']
    lines.append('        <optgroup label="色度 Look（Fujifilm / ARRI）">')
    for name in LOOK_CHOICES:
        if name == "none":
            continue
        label = _LOOK_LABELS.get(name, name.replace("fuji_", "Fujifilm ").replace("_", " "))
        lines.append(f'          <option value="{name}">{label}</option>')
    lines.append("        </optgroup>")
    lines.append('        <optgroup label="输出滤镜（Kodak / RED IPP2）">')
    for name in FILTER_CHOICES:
        if name == "none":
            continue
        lines.append(f'          <option value="{name}">{DISPLAY_FILTERS[name].label}</option>')
    lines.append("        </optgroup>")
    return "\n".join(lines)


def render_page(init_dir: str) -> bytes:
    html = PAGE.replace("INIT_DIR", json.dumps(init_dir)).replace("GRADE_OPTIONS", _grade_options_html())
    return html.encode("utf-8")
