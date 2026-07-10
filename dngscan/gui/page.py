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
.wrap{max-width:1480px;margin:0 auto;padding:22px}
h1{font-size:17px;font-weight:600;margin:0 0 16px}
.card{background:#1d2028;border:1px solid #2b2f3a;border-radius:8px;padding:16px;margin-bottom:14px}
.secTitle{font-size:12px;font-weight:600;color:#8fa0c4;text-transform:uppercase;letter-spacing:.06em;margin:0 0 12px}
.workspace{display:grid;grid-template-columns:minmax(360px,480px) minmax(0,1fr);gap:14px;align-items:start}
.controlPanel{min-width:0}
.previewCard{position:sticky;top:16px;min-height:calc(100vh - 44px);display:flex;flex-direction:column}
.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
label{display:block;font-size:12px;color:#9aa1b0;margin:0 0 6px}
input[type=text],input[type=number],select{width:100%;background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#e7e9ee;padding:8px 10px;font:inherit}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>div{flex:1;min-width:150px}
.row>.evMain{flex:1 1 100%;min-width:0}
.modes{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.modes button{flex:1;min-width:56px;overflow:hidden;background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#cdd2dd;padding:8px 4px;cursor:pointer;font:inherit;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;line-height:1.25;min-height:48px}
.modes button .m{font-weight:600;color:#e7e9ee;font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}
.modes button .d{font-size:10px;color:#828a99;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.modes button.sel{border-color:#5b8cff;background:#1a2233}
.modes button#evReferenceBtn{flex:1.8;min-width:100px}
.sliderField{flex:1;min-width:170px}
.labelRow{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:6px}
.labelRow label{margin:0;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.labelRow .val{font-size:13px;color:#e7e9ee;font-variant-numeric:tabular-nums;white-space:nowrap}
input[type=range]{display:block;width:100%;margin:6px 0 2px;accent-color:#5b8cff;height:18px}
button.go{background:#5b8cff;border:0;border-radius:9px;color:#fff;padding:11px 18px;font:inherit;font-weight:600;cursor:pointer}
button.go:disabled{opacity:.5;cursor:default}
button.ghost{background:#12141a;border:1px solid #2b2f3a;border-radius:8px;color:#cdd2dd;padding:8px 12px;cursor:pointer;font:inherit;white-space:nowrap}
button.preview{background:#2c3444;border:1px solid #46536b;border-radius:9px;color:#eef2ff;padding:11px 18px;font:inherit;font-weight:600;cursor:pointer}
button.preview:disabled{opacity:.5;cursor:default}
.muted{color:#828a99;font-size:12px}
.coreFacts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.coreFacts span{background:#151922;border:1px solid #303746;border-radius:6px;padding:5px 8px;color:#9aa1b0;font-size:12px}
.coreFacts b{color:#e7e9ee;font-weight:500}
#status{margin-top:10px;min-height:20px}
.err{color:#ff8a8a}.ok{color:#8ae08a}
.browserList{display:none;margin-top:10px;border:1px solid #2b2f3a;border-radius:8px;max-height:260px;overflow:auto;background:#12141a}
.browserList div{padding:6px 10px;cursor:pointer;border-bottom:1px solid #20242e;font-size:13px}
.browserList div:hover{background:#1a2233}
.browserList div.pick{color:#8ae08a;font-weight:600;position:sticky;top:0;background:#12141a}
#previewWrap{position:relative;margin-top:12px;min-height:420px;flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#11141a;border:1px solid #2b2f3a;border-radius:8px}
#previewWrap.loading{min-height:420px}
#preview{max-width:100%;max-height:calc(100vh - 190px);border-radius:8px;display:none;transition:opacity .15s ease;object-fit:contain}
#previewWrap.loading #preview{opacity:.4}
#spinner{display:none;position:absolute;left:50%;top:50%;width:34px;height:34px;margin:-17px 0 0 -17px;border:3px solid rgba(255,255,255,.22);border-top-color:#eef2ff;border-radius:50%;animation:spin .8s linear infinite}
#previewWrap.loading #spinner{display:block}
@keyframes spin{to{transform:rotate(360deg)}}
.dim{opacity:.45;pointer-events:none}
.chk{display:flex;align-items:center;gap:8px}.chk input{width:auto}
.outdirRow{display:flex;gap:8px;align-items:stretch}
.outdirRow input{flex:1}
@media (max-width:980px){
  .wrap{padding:14px}
  .workspace{display:block}
  .previewCard{position:static;min-height:0}
  #previewWrap{min-height:260px}
  #preview{max-height:none}
  .modes button .d{display:none}
}
</style></head>
<body><div class="wrap">
<h1>dngscan · darktable AgX + RAW 分析</h1>

<div class="card">
  <label>DNG / RAW 文件</label>
  <div class="row" style="align-items:flex-end">
    <div style="flex:4"><input type="text" id="input" placeholder="/path/to/photo.dng"></div>
    <div style="flex:0"><button class="ghost" id="browseBtn">浏览…</button></div>
  </div>
  <div id="browser" class="browserList"></div>
</div>

<div class="workspace">
<div class="controlPanel">

<div class="card">
  <div class="secTitle">曝光</div>
  <div class="row">
    <div class="evMain">
      <div class="labelRow"><label>曝光补偿 EV（默认 0 保留拍摄锚点）</label><span class="val" id="evval">+0.00</span></div>
      <input type="range" id="ev" min="-3" max="3" step="0.05" value="0">
      <div class="modes">
        <button type="button" data-ev="-0.50"><span class="m">-0.50</span></button>
        <button type="button" data-ev="0"><span class="m">0.00</span></button>
        <button type="button" data-ev="0.50"><span class="m">+0.50</span></button>
        <button type="button" data-ev="1.00"><span class="m">+1.00</span></button>
        <button type="button" id="evReferenceBtn" title="以全图中位亮度计算 18% 灰参考值，并受高光安全上限约束；点击会应用建议 EV。"><span class="m">参考</span><span class="d">全图亮度</span></button>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <div class="secTitle">渲染策略</div>
  <div class="row">
    <div style="flex:2;min-width:210px">
      <label>压缩策略</label>
      <select id="toneCore" title="默认是 darktable 风格的全图 AgX；RAW 门控是基于同一 darktable 几何的可选色度策略。">
        <option value="agx" selected>AgX · darktable 全图色彩路径</option>
        <option value="gated">保真 · RAW 证据门控</option>
        <option value="lum">对照 · 场景 C1 仅亮度</option>
        <option value="neutral">对照 · 通用导出曲线</option>
      </select>
    </div>
    <div id="lumNormBlock" style="flex:1;min-width:140px;display:none">
      <label>亮度度量</label>
      <select id="lumNorm">
        <option value="y">Y · 场景亮度</option>
        <option value="power">折中 · 亮度与峰值</option>
        <option value="max">最大通道</option>
      </select>
    </div>
    <div id="agxPrimariesBlock" style="flex:1;min-width:150px">
      <label>AgX 高光路径</label>
      <select id="agxPrimaries" title="仅全图 AgX 使用：选择高亮饱和色的 path-to-white 几何。">
        <option value="smooth" selected>darktable 平滑 · 默认</option>
        <option value="base">Blender 参考 · 平衡退白</option>
        <option value="punchy">Blender 参考 · 鲜明</option>
        <option value="muted">Blender 参考 · 柔和</option>
      </select>
    </div>
  </div>
  <div class="coreFacts" id="coreFacts" aria-live="polite"></div>
</div>

<div class="card">
  <div class="secTitle">相机颜色</div>
  <div class="row">
    <div style="flex:2;min-width:210px">
      <label>相机响应校正</label>
      <select id="sceneTransform" title="在 scene-linear 域，以色度窗口做受限的相机响应校正。">
SCENE_TRANSFORM_OPTIONS
      </select>
    </div>
    <div id="sceneTransformStrengthBlock" class="sliderField" style="display:none">
      <div class="labelRow"><label>校正强度</label><span class="val" id="sceneTransformStrengthVal">1.00</span></div>
      <input type="range" id="sceneTransformStrength" min="0" max="3" step="0.05" value="1" title="1=推荐强度；大于 1 用于诊断或强化 A/B。">
    </div>
    <div id="punchBlock" class="sliderField">
      <div class="labelRow"><label>中间调纯度</label><span class="val" id="punchVal">1.00</span></div>
      <input type="range" id="punch" min="0" max="1.5" step="0.05" value="1" title="1=由场景分析决定的默认量；0=关闭；夜景的自动值为 0。">
    </div>
  </div>
</div>

<div class="card">
  <div class="secTitle">成片风格</div>
  <div class="row">
    <div style="flex:2;min-width:210px">
      <label>成片风格</label>
      <select id="grade" title="相机色彩渲染和输出 LUT 互斥，一次只能选一种。">
GRADE_OPTIONS
      </select>
    </div>
    <div id="gradeStrengthBlock" class="sliderField" style="display:none">
      <div class="labelRow"><label>风格强度</label><span class="val" id="gradeStrengthVal">1.00</span></div>
      <input type="range" id="gradeStrength" min="0" max="1.5" step="0.05" value="1">
    </div>
  </div>
</div>

<div class="card">
  <div class="secTitle">RAW 还原</div>
  <div class="row">
    <div style="flex:1;min-width:160px">
      <label>剪切高光</label>
      <select id="highlight">
        <option value="clip">保持剪切 · 不估算缺失颜色</option>
        <option value="blend">高光混合 · 利用幸存通道</option>
        <option value="reconstruct">高光重建 · 估算邻域颜色</option>
      </select>
    </div>
    <div style="flex:1;min-width:150px">
      <label>拍摄白平衡</label>
      <select id="wb" title="相机记录：使用 AsShot；固定日光：以日光配平作为整卷一致的基准。">
        <option value="camera">相机记录（As Shot）</option>
        <option value="daylight">固定日光配平</option>
      </select>
    </div>
    <div style="flex:1;min-width:170px">
      <label>细节插值</label>
      <select id="demosaic" title="仅影响全分辨率导出的去马赛克算法；不包含降噪。">
        <option value="auto">自动 · DHT 优先</option>
        <option value="dht">DHT</option>
        <option value="dcb">DCB</option>
        <option value="ahd">AHD</option>
        <option value="aahd">AAHD</option>
        <option value="vng">VNG</option>
        <option value="ppg">PPG</option>
      </select>
    </div>
  </div>
</div>

<div class="card">
  <div class="secTitle">交付</div>
  <div class="row">
    <div style="flex:1;min-width:170px">
      <label>输出形式</label>
      <select id="format">
        <option value="sdr">SDR JPEG</option>
        <option value="ultrahdr">HDR gain-map JPEG</option>
      </select>
    </div>
    <div style="flex:1;min-width:140px">
      <label>交付色域</label>
      <select id="gamut">
        <option value="srgb">sRGB · 兼容优先</option>
        <option value="p3">Display P3 · 宽色域</option>
      </select>
    </div>
    <div style="flex:0;min-width:110px">
      <label>JPEG 质量</label>
      <input type="number" id="quality" min="1" max="100" value="100">
    </div>
    <div style="flex:1;min-width:140px">
      <label>色度精度</label>
      <select id="chroma" title="4:4:4 保留完整色度；4:2:0 体积最小。">
        <option value="444">4:4:4 · 满色度</option>
        <option value="422">4:2:2</option>
        <option value="420">4:2:0 · 最小</option>
      </select>
    </div>
  </div>
  <div class="row" id="hdrBlock" style="margin-top:12px">
    <div style="min-width:220px">
      <div class="labelRow"><label>HDR 高光余量（仅 HDR 输出）</label><span class="val" id="hdrHeadroomVal">+3.00</span></div>
      <input type="range" id="hdrHeadroom" min="1" max="5" step="0.25" value="3">
      <div class="muted" id="hdrHint">微信/QQ 想保住 HDR：走原图或文件，别走朋友圈。</div>
    </div>
  </div>
  <div style="margin-top:12px">
    <label>输出文件夹（留空=源文件所在文件夹）</label>
    <div class="outdirRow">
      <input type="text" id="outdir" placeholder="默认：源文件所在文件夹">
      <button class="ghost" id="outdirBtn">选择…</button>
    </div>
    <div id="outdirBrowser" class="browserList"></div>
  </div>
  <div class="chk" style="margin-top:12px">
    <input type="checkbox" id="png"><label for="png" style="margin:0">同时导出 RAW 分析图</label>
  </div>
</div>

</div>

<div class="card previewCard">
  <div class="actions">
    <button class="preview" id="previewBtn">预览</button>
    <button class="go" id="go">导出</button>
    <button class="ghost" id="revealBtn" style="display:none">在 Finder 中显示</button>
  </div>
  <div id="status"></div>
  <div id="previewWrap"><img id="preview"><div id="spinner"></div></div>
</div>
</div>

<script>
const $=s=>document.querySelector(s);
const STORE_KEY="dngscan.settings.v5";
const LEGACY_STORE_KEY="dngscan.settings.v4";
function setGradeStrengthLabel(){const v=+$("#gradeStrength").value;$("#gradeStrengthVal").textContent=v.toFixed(2);}
function updateGradeUi(){$("#gradeStrengthBlock").style.display=$("#grade").value!=="none"?"block":"none";}
function setPunchLabel(){const v=+$("#punch").value;$("#punchVal").textContent=v.toFixed(2);}
function setSceneTransformStrengthLabel(){const v=+$("#sceneTransformStrength").value;$("#sceneTransformStrengthVal").textContent=v.toFixed(2);}
function updateSceneTransformUi(){$("#sceneTransformStrengthBlock").style.display=$("#sceneTransform").value!=="none"?"block":"none";}
const CORE_FACTS={
  gated:["亮度 <b>darktable C1 曲线</b>","色度 <b>smooth 几何 + RAW 门控</b>"],
  agx:["亮度 <b>darktable C1 曲线</b>","色度 <b>全图 AgX path-to-white</b>"],
  lum:["亮度 <b>场景 C1 曲线</b>","色度 <b>保持 RGB 比例（无 AgX）</b>"],
  neutral:["亮度 <b>固定通用 shoulder</b>","色度 <b>Lightroom 式导出基线</b>"]
};
function updateToneCoreUi(){
  const core=$("#toneCore").value;const lum=core==="lum";const neutral=core==="neutral";
  $("#lumNormBlock").style.display=lum?"block":"none";
  $("#agxPrimariesBlock").style.display=core==="agx"?"block":"none";
  $("#punchBlock").style.display=(lum||neutral)?"none":"block";
  $("#coreFacts").innerHTML=(CORE_FACTS[core]||[]).map(v=>"<span>"+v+"</span>").join("");
}
function updateFormatUi(){$("#hdrBlock").style.display=$("#format").value==="ultrahdr"?"flex":"none";}
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
function fullFrameReferenceText(j){
  if(!j.ev_auto)return "";
  const a=j.ev_auto;
  let t=" · 全图亮度参考 "+fmtEv(a.ev_boost)+" EV";
  if(a.highlight_limited)t+="（高光限制，参考目标 "+fmtEv(a.ev_median_target)+"）";
  return t;
}
function sceneTransformText(j){
  if(!j.scene_transform||j.scene_transform==="无")return "";
  const s=j.scene_transform_strength!==undefined?" "+(+j.scene_transform_strength).toFixed(2):"";
  return "，相机校正 "+j.scene_transform+s;
}
function toneCoreText(j){
  if(!j.tone_core)return "";
  const labels={gated:"保真（RAW 门控）",agx:"AgX（darktable 全图）",lum:"对照（场景 C1 仅亮度）",neutral:"对照（通用导出曲线）"};
  const norms={y:"Y",power:"折中",max:"最大通道"};
  const norm=j.tone_core==="lum"&&j.lum_norm?"（"+(norms[j.lum_norm]||j.lum_norm)+"）":"";
  return "，策略 "+(labels[j.tone_core]||j.tone_core)+norm;
}
function highlightText(v){return ({clip:"保持剪切",blend:"高光混合",reconstruct:"高光重建"})[v]||v;}
function gamutText(v){return ({srgb:"sRGB",p3:"Display P3"})[v]||v;}
function formatText(v){return ({sdr:"SDR JPEG",ultrahdr:"HDR gain-map JPEG"})[v]||v;}
function applyJobEv(j){
  if(j.ev!==undefined){$("#ev").value=j.ev;setEvLabel();saveSettings();}
}
function saveSettings(){
  try{localStorage.setItem(STORE_KEY,JSON.stringify({
    input:$("#input").value,ev:$("#ev").value,quality:$("#quality").value,
    highlight:$("#highlight").value,gamut:$("#gamut").value,wb:$("#wb").value,demosaic:$("#demosaic").value,chroma:$("#chroma").value,format:$("#format").value,
    toneCore:$("#toneCore").value,lumNorm:$("#lumNorm").value,agxPrimaries:$("#agxPrimaries").value,
    grade:$("#grade").value,gradeStrength:$("#gradeStrength").value,
    sceneTransform:$("#sceneTransform").value,sceneTransformStrength:$("#sceneTransformStrength").value,punch:$("#punch").value,
    hdrHeadroom:$("#hdrHeadroom").value,outdir:$("#outdir").value,png:$("#png").checked
  }));}catch(e){}
}
function restoreSettings(){
  let s={};let migrated=false;
  try{
    const current=localStorage.getItem(STORE_KEY);
    s=JSON.parse(current||localStorage.getItem(LEGACY_STORE_KEY)||"{}")||{};
    // v4's stock pair was gated + base. Move that old default to the new
    // darktable baseline while retaining every other stored preference.
    if(!current&&s.toneCore==="gated"&&s.agxPrimaries==="base"){
      s.toneCore="agx";s.agxPrimaries="smooth";migrated=true;
    }
  }catch(e){}
  if(s.input)$("#input").value=s.input;
  if(s.ev!==undefined)$("#ev").value=s.ev;
  if(s.quality)$("#quality").value=s.quality;
  if(s.highlight)$("#highlight").value=s.highlight;
  if(s.gamut)$("#gamut").value=s.gamut;
  if(s.wb)$("#wb").value=s.wb;
  if(s.demosaic)$("#demosaic").value=s.demosaic;
  if(s.chroma)$("#chroma").value=s.chroma;
  if(s.toneCore&&[...$("#toneCore").options].some(o=>o.value===s.toneCore))$("#toneCore").value=s.toneCore;
  if(s.lumNorm&&[...$("#lumNorm").options].some(o=>o.value===s.lumNorm))$("#lumNorm").value=s.lumNorm;
  if(s.agxPrimaries&&[...$("#agxPrimaries").options].some(o=>o.value===s.agxPrimaries))$("#agxPrimaries").value=s.agxPrimaries;
  if(s.grade&&[...$("#grade").options].some(o=>o.value===s.grade))$("#grade").value=s.grade;
  else if(s.filter&&s.filter!=="none"){
    const fid="filter:"+s.filter;
    if([...$("#grade").options].some(o=>o.value===fid))$("#grade").value=fid;
    else if([...$("#grade").options].some(o=>o.value===s.filter))$("#grade").value=s.filter;
  }
  else if(s.look&&s.look!=="none"){
    const lid="look:"+s.look;
    if([...$("#grade").options].some(o=>o.value===lid))$("#grade").value=lid;
    else if([...$("#grade").options].some(o=>o.value===s.look))$("#grade").value=s.look;
  }
  if(s.gradeStrength!==undefined)$("#gradeStrength").value=s.gradeStrength;
  else if(s.filterStrength!==undefined&&s.filter&&s.filter!=="none")$("#gradeStrength").value=s.filterStrength;
  else if(s.lookStrength!==undefined)$("#gradeStrength").value=s.lookStrength;
  if(s.sceneTransform&&[...$("#sceneTransform").options].some(o=>o.value===s.sceneTransform))$("#sceneTransform").value=s.sceneTransform;
  if(s.sceneTransformStrength!==undefined)$("#sceneTransformStrength").value=s.sceneTransformStrength;
  if(s.punch!==undefined)$("#punch").value=s.punch;
  if(s.format)$("#format").value=s.format;
  if(s.hdrHeadroom!==undefined)$("#hdrHeadroom").value=s.hdrHeadroom;
  if(s.outdir)$("#outdir").value=s.outdir;
  if(s.png!==undefined)$("#png").checked=!!s.png;
  setEvLabel();setHdrLabel();setGradeStrengthLabel();setSceneTransformStrengthLabel();setPunchLabel();updateGradeUi();updateSceneTransformUi();updateToneCoreUi();updateFormatUi();
  if(migrated)saveSettings();
}
["input","quality","highlight","gamut","outdir","png"].forEach(id=>$("#"+id).addEventListener("change",saveSettings));
["wb","demosaic","chroma","grade"].forEach(id=>$("#"+id).addEventListener("change",()=>{updateGradeUi();saveSettings();}));
$("#toneCore").addEventListener("change",()=>{updateToneCoreUi();saveSettings();});
$("#lumNorm").addEventListener("change",saveSettings);
$("#agxPrimaries").addEventListener("change",saveSettings);
$("#sceneTransform").addEventListener("change",()=>{updateSceneTransformUi();saveSettings();});
$("#format").addEventListener("change",()=>{if($("#format").value==="ultrahdr")$("#gamut").value="p3";updateFormatUi();saveSettings();});
$("#ev").oninput=()=>{setEvLabel();saveSettings();};
$("#hdrHeadroom").oninput=()=>{setHdrLabel();saveSettings();};
$("#gradeStrength").oninput=()=>{setGradeStrengthLabel();saveSettings();};
$("#punch").oninput=()=>{setPunchLabel();saveSettings();};
$("#sceneTransformStrength").oninput=()=>{setSceneTransformStrengthLabel();saveSettings();};
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

async function listOutDir(d){
  const r=await fetch("/list?dir="+encodeURIComponent(d));const j=await r.json();
  const b=$("#outdirBrowser");b.innerHTML="";
  const mk=(t,fn,cls)=>{const e=document.createElement("div");e.textContent=t;e.onclick=fn;if(cls)e.className=cls;b.appendChild(e);};
  mk("✓ 就用这里："+j.cwd,()=>{$("#outdir").value=j.cwd;b.style.display="none";saveSettings();},"pick");
  mk("✕ 清空（与源文件同目录）",()=>{$("#outdir").value="";b.style.display="none";saveSettings();});
  mk("⬆︎ "+j.parent,()=>listOutDir(j.parent));
  j.dirs.forEach(d2=>mk("📁 "+d2,()=>listOutDir(j.cwd+"/"+d2)));
}
$("#outdirBtn").onclick=()=>{
  const b=$("#outdirBrowser");
  if(b.style.display==="block"){b.style.display="none";return;}
  b.style.display="block";
  const seed=$("#outdir").value.trim()
    ||($("#input").value.trim()?$("#input").value.trim().replace(/\\/[^\\/]*$/,""):"")
    ||curDir;
  listOutDir(seed);
};

function payload(){
  const input=$("#input").value.trim();
  if(!input){setStatus("请先选择一个 DNG/RAW 文件","err");return null;}
  return {
    input,highlight:$("#highlight").value,gamut:$("#gamut").value,wb:$("#wb").value,demosaic:$("#demosaic").value,chroma:$("#chroma").value,format:$("#format").value,
    toneCore:$("#toneCore").value,lumNorm:$("#lumNorm").value,agxPrimaries:$("#agxPrimaries").value,
    grade:$("#grade").value,gradeStrength:+$("#gradeStrength").value,
    sceneTransform:$("#sceneTransform").value,sceneTransformStrength:+$("#sceneTransformStrength").value,
    punch:+$("#punch").value,
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
  setStatus(prefix+"：EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+highlightText(j.highlight)+"，色域 "+gamutText(j.gamut)+toneCoreText(j)+sceneTransformText(j)+fullFrameReferenceText(j)+metricText(j),"ok");
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

$("#evReferenceBtn").onclick=async()=>{
  const body=payload();if(!body)return;
  body.evAuto=true;
  $("#previewBtn").disabled=true;$("#evReferenceBtn").disabled=true;$("#revealBtn").style.display="none";beginBusy();setStatus("计算全图亮度参考…","");
  try{
    const j=await postJob("/preview",body);
    if(!handleJobResult(j,"全图亮度参考预览")){endBusy();setStatus("错误："+j.error,"err");}
  }catch(e){endBusy();setStatus("请求失败："+e,"err");}
  $("#previewBtn").disabled=false;$("#evReferenceBtn").disabled=false;
};

$("#go").onclick=async()=>{
  const body=payload();if(!body)return;
  $("#go").disabled=true;$("#previewBtn").disabled=true;$("#revealBtn").style.display="none";beginBusy();setStatus("导出 full-res…","");
  try{
    const j=await postJob("/export",body);
    if(!j.ok){endBusy();setStatus("错误："+j.error,"err");}
    else{applyJobEv(j);setStatus("已保存："+j.saved.join(" · ")+"（"+formatText(j.format)+"，EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+highlightText(j.highlight)+"，色域 "+gamutText(j.gamut)+toneCoreText(j)+sceneTransformText(j)+fullFrameReferenceText(j)+metricText(j)+"）","ok");
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


_LOOK_LABELS = {
    "classic": "ARRI Classic 709",
    "reveal": "ARRI Reveal 709",
    "optic_warm_cyan": "Optic Warm/Cyan",
}


def _grade_options_html() -> str:
    from ..display_filter import DISPLAY_FILTERS, FILTER_CHOICES
    from ..grade import grade_id_for_filter, grade_id_for_look
    from ..look import LOOK_CHOICES

    lines = ['        <option value="none">无</option>']
    lines.append('        <optgroup label="相机色彩渲染">')
    for name in LOOK_CHOICES:
        if name == "none":
            continue
        label = _LOOK_LABELS.get(name, name.replace("fuji_", "Fujifilm ").replace("_", " "))
        gid = grade_id_for_look(name)
        lines.append(f'          <option value="{gid}">{label}</option>')
    lines.append("        </optgroup>")
    lines.append('        <optgroup label="输出 LUT">')
    for name in FILTER_CHOICES:
        if name == "none":
            continue
        gid = grade_id_for_filter(name)
        lines.append(f'          <option value="{gid}">{DISPLAY_FILTERS[name].label}</option>')
    lines.append("        </optgroup>")
    return "\n".join(lines)


def _scene_transform_options_html() -> str:
    from ..scene_transform import SCENE_TRANSFORM_CHOICES, scene_transform_label

    lines = []
    for name in SCENE_TRANSFORM_CHOICES:
        lines.append(f'        <option value="{name}">{scene_transform_label(name)}</option>')
    return "\n".join(lines)


def render_page(init_dir: str) -> bytes:
    html = (
        PAGE.replace("INIT_DIR", json.dumps(init_dir))
        .replace("GRADE_OPTIONS", _grade_options_html())
        .replace("SCENE_TRANSFORM_OPTIONS", _scene_transform_options_html())
    )
    return html.encode("utf-8")
