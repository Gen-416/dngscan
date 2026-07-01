#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A minimal local web GUI for dngscan.py. It starts a localhost server, opens the
# browser, and lets you pick one DNG, choose one tone-mapping mode, set exposure /
# quality, and export a JPEG. The analysis PNG is off by default. All heavy lifting
# reuses dngscan.py -- this file only wires a UI onto it.
from __future__ import annotations

import base64
import io
import json
import math
import socket
import sys
import tempfile
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import dngscan as dg

RAW_EXTS = {
    ".dng", ".arw", ".cr2", ".cr3", ".nef", ".nrw", ".raf", ".rw2", ".orf",
    ".raw", ".pef", ".srw", ".x3f", ".iiq", ".3fr", ".mrw", ".dcr", ".kdc",
}

PREVIEW_CACHE: dict[tuple[str, int, str], tuple[dg.RawBundle, dg.Analysis]] = {}
PREVIEW_CACHE_LOCK = threading.Lock()
RENDER_LOCK = threading.Lock()

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
#preview{margin-top:12px;max-width:100%;border-radius:8px;display:none}
.chk{display:flex;align-items:center;gap:8px}.chk input{width:auto}
</style></head>
<body><div class="wrap">
<h1>dngscan · RAW → JPEG</h1>

<div class="card">
  <label>DNG / RAW 文件</label>
  <div class="row" style="align-items:flex-end">
    <div style="flex:4"><input type="text" id="input" placeholder="/path/to/photo.dng"></div>
    <div style="flex:0"><button class="ghost" id="browseBtn">浏览…</button></div>
  </div>
  <div id="browser"></div>
</div>

<div class="card">
  <label>处理方式</label>
  <div class="modes" id="modes">
    <button data-m="neutral"><span class="m">neutral</span><br><span class="d">数学参考，最少损失</span></button>
    <button data-m="smart"><span class="m">smart</span><br><span class="d">分析驱动高光肩+色度</span></button>
    <button data-m="agx"><span class="m">agx</span><br><span class="d">AgX 曲线，柔和高光</span></button>
    <button data-m="tony"><span class="m">tony</span><br><span class="d">Tony McMapface LUT</span></button>
  </div>
</div>

<div class="card">
  <div class="row">
    <div>
      <label>曝光补偿 EV（固定常数，不改拍摄意图）</label>
      <div class="evrow"><input type="range" id="ev" min="-3" max="3" step="0.05" value="0"><span class="evval" id="evval">+0.00</span></div>
      <div class="modes" style="margin-top:8px">
        <button type="button" data-ev="-0.50"><span class="m">-0.50</span></button>
        <button type="button" data-ev="0"><span class="m">0.00</span></button>
        <button type="button" data-ev="0.50"><span class="m">+0.50</span></button>
        <button type="button" data-ev="1.00"><span class="m">+1.00</span></button>
      </div>
    </div>
    <div style="flex:0;min-width:120px">
      <label>JPEG 质量</label>
      <input type="number" id="quality" min="1" max="100" value="100">
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
  <span class="muted" id="modehint" style="margin-left:12px"></span>
  <div id="status"></div>
  <img id="preview">
</div>

<script>
const $=s=>document.querySelector(s);
const STORE_KEY="dngscan.settings.v2";
let mode="agx";
function selMode(m){mode=m;document.querySelectorAll("#modes button").forEach(b=>b.classList.toggle("sel",b.dataset.m===m));
  $("#modehint").textContent=m==="tony"?"tony 需要 ~/dngscan_assets/tony_mc_mapface.spi3d":"";}
function setEvLabel(){const v=+$("#ev").value;$("#evval").textContent=(v>=0?"+":"")+v.toFixed(2);}
function fmtPct(v){return v<0.01?v.toFixed(4):v<1?v.toFixed(3):v.toFixed(2);}
function fmtEv(v){return (v>=0?"+":"")+v.toFixed(2);}
function metricText(j){
  if(!j.metrics)return "";
  const m=j.metrics;
  if(m.luma_p999_pct===undefined)return "";
  const room=m.safe_ev_remaining!==undefined?m.safe_ev_remaining:m.headroom_luma_ev;
  const label=j.metrics_kind==="full"?" · 全分辨率真值":" · 预览估计(偏保守)";
  const roomText=room!==undefined?" · 可再加约 "+fmtEv(room)+"EV":"";
  return label+
    " · p99.9亮度 "+fmtPct(m.luma_p999_pct)+"%"+
    " · 近白 "+fmtPct(m.near_white_pct)+"%"+
    " · 顶白 "+fmtPct(m.clipped_channel_pct)+"%"+
    roomText;
}
function saveSettings(){
  try{localStorage.setItem(STORE_KEY,JSON.stringify({
    input:$("#input").value,mode,ev:$("#ev").value,quality:$("#quality").value,
    highlight:$("#highlight").value,gamut:$("#gamut").value,outdir:$("#outdir").value,png:$("#png").checked
  }));}catch(e){}
}
function restoreSettings(){
  let s={};try{s=JSON.parse(localStorage.getItem(STORE_KEY)||"{}")||{};}catch(e){}
  if(s.input)$("#input").value=s.input;
  if(s.ev!==undefined)$("#ev").value=s.ev;
  if(s.quality)$("#quality").value=s.quality;
  if(s.highlight)$("#highlight").value=s.highlight;
  if(s.gamut)$("#gamut").value=s.gamut;
  if(s.outdir)$("#outdir").value=s.outdir;
  if(s.png!==undefined)$("#png").checked=!!s.png;
  selMode(s.mode||"agx");setEvLabel();
}
document.querySelectorAll("#modes button").forEach(b=>b.onclick=()=>{selMode(b.dataset.m);saveSettings();});
document.querySelectorAll("button[data-ev]").forEach(b=>b.onclick=()=>{$("#ev").value=b.dataset.ev;setEvLabel();saveSettings();});
["input","quality","highlight","gamut","outdir","png"].forEach(id=>$("#"+id).addEventListener("change",saveSettings));
$("#ev").oninput=()=>{setEvLabel();saveSettings();};
restoreSettings();

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
  return {input,mode,highlight:$("#highlight").value,gamut:$("#gamut").value,ev:+$("#ev").value,quality:+$("#quality").value,outdir:$("#outdir").value.trim(),png:$("#png").checked};
}

async function postJob(path, body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  return await r.json();
}

$("#previewBtn").onclick=async()=>{
  const body=payload();if(!body)return;
  $("#previewBtn").disabled=true;setStatus("生成预览…（首次会建立缓存）","");$("#preview").style.display="none";
  try{
    const j=await postJob("/preview",body);
    if(!j.ok){setStatus("错误："+j.error,"err");}
    else{setStatus("预览：EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+j.highlight+"，色域 "+j.gamut+metricText(j),"ok");
      $("#preview").src="data:image/jpeg;base64,"+j.preview;$("#preview").style.display="block";}
  }catch(e){setStatus("请求失败："+e,"err");}
  $("#previewBtn").disabled=false;
};

$("#go").onclick=async()=>{
  const body=payload();if(!body)return;
  $("#go").disabled=true;$("#previewBtn").disabled=true;setStatus("导出 full-res…","");$("#preview").style.display="none";
  try{
    const j=await postJob("/export",body);
    if(!j.ok){setStatus("错误："+j.error,"err");}
    else{setStatus("已保存："+j.saved.join(" · ")+"（EV "+fmtEv(j.ev)+"，曝光增益 "+j.gain.toFixed(3)+"，高光 "+j.highlight+"，色域 "+j.gamut+metricText(j)+"）","ok");
      $("#preview").src="data:image/jpeg;base64,"+j.preview;$("#preview").style.display="block";}
  }catch(e){setStatus("请求失败："+e,"err");}
  $("#go").disabled=false;$("#previewBtn").disabled=false;
};
function setStatus(t,c){const s=$("#status");s.textContent=t;s.className=c||"";}
</script>
</div></body></html>
"""


def make_preview_b64(path: Path, width: int = 1024, icc_profile: bytes | None = None) -> str:
    from PIL import Image

    src = Image.open(path)
    if icc_profile is None:
        icc_profile = src.info.get("icc_profile")
    im = src.convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)))
    buf = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": 85}
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    im.save(buf, **save_kwargs)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def output_luminance_metrics(path: Path, gamut: str, ev: float) -> dict[str, float]:
    from PIL import Image

    np = dg.np
    if np is None:
        return {}
    im = Image.open(path).convert("RGB")
    encoded = np.asarray(im, dtype=np.float32) / np.float32(255.0)
    flat = encoded.reshape(-1, 3)
    linear = np.where(flat <= 0.04045, flat / 12.92, np.power((flat + 0.055) / 1.055, 2.4))
    matrix = dg.RGB_TO_XYZ[dg.output_gamut_space(gamut)]
    y = matrix[1, 0] * linear[:, 0] + matrix[1, 1] * linear[:, 1] + matrix[1, 2] * linear[:, 2]
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    max_channel = np.max(linear, axis=1)
    y_p99, y_p999 = [float(v) for v in np.percentile(y, [99.0, 99.9])]
    max_p999 = float(np.percentile(max_channel, 99.9))
    headroom_luma_ev = math.log2(0.95 / max(y_p999, 1e-9))
    headroom_rgb_ev = math.log2(0.98 / max(max_p999, 1e-9))
    return {
        "median_luma_pct": float(np.median(y) * 100.0),
        "mean_luma_pct": float(np.mean(y) * 100.0),
        "luma_p99_pct": y_p99 * 100.0,
        "luma_p999_pct": y_p999 * 100.0,
        "max_channel_p999_pct": max_p999 * 100.0,
        "near_white_pct": float(np.mean(np.max(flat, axis=1) >= (250.0 / 255.0)) * 100.0),
        "clipped_channel_pct": float(np.mean(np.any(flat >= (254.5 / 255.0), axis=1)) * 100.0),
        "headroom_luma_ev": float(headroom_luma_ev),
        "headroom_rgb_ev": float(headroom_rgb_ev),
        "estimated_ev_before_luma_limit": float(ev + headroom_luma_ev),
    }


def output_metrics_from_linear(rgb_linear: object, gamut: str) -> dict[str, float]:
    np = dg.np
    if np is None:
        return {}
    rgb = np.clip(np.nan_to_num(rgb_linear, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    matrix = dg.RGB_TO_XYZ[dg.output_gamut_space(gamut)]
    y = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    max_channel = np.max(rgb, axis=1)
    y_p999 = float(np.percentile(y, 99.9))
    max_p999 = float(np.percentile(max_channel, 99.9))
    return {
        "luma_p999_pct": y_p999 * 100.0,
        "max_channel_p999_pct": max_p999 * 100.0,
        "near_white_pct": float(np.mean(max_channel >= np.float32(0.956)) * 100.0),
        "clipped_channel_pct": float(np.mean(np.any(rgb >= np.float32(0.999), axis=1)) * 100.0),
    }


def render_sample_output_linear(
    bundle: dg.RawBundle,
    analysis: dg.Analysis | None,
    mode: str,
    gamut: str,
    ev: float,
    sample_rgb: object,
    tony_lut: object | None = None,
) -> object:
    bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)
    rec = dg.scene_rec2020_to_float(sample_rgb, bundle.scene_scale, bundle.exposure_gain)
    if mode == "smart":
        plan = plan_for_bundle(bundle, analysis, mode, gamut)
        out = dg.rec2020_to_output(rec, gamut)
        return dg.compress_linear_output_rgb_for_jpeg(out, analysis, plan, gamut)
    if mode == "agx":
        plan = plan_for_bundle(bundle, analysis, mode, gamut)
        return dg.rec2020_to_output(dg.apply_agx_core(rec, plan), gamut)
    if mode == "tony":
        plan = plan_for_bundle(bundle, analysis, mode, gamut)
        lut = tony_lut if tony_lut is not None else dg.load_tony_spi3d(dg.default_tony_lut_path())
        y = dg.luminance_from_rec2020(rec)
        srgb = dg.rec2020_to_srgb(rec)
        srgb = dg.precondition_tonemapper_rgb(srgb, y, plan, for_tony=True)
        return dg.srgb_to_output(dg.sample_tony_lut(srgb, lut), gamut)
    return dg.rec2020_to_output(rec, gamut)


def estimate_ev_headroom(
    bundle: dg.RawBundle,
    analysis: dg.Analysis | None,
    mode: str,
    gamut: str,
    current_ev: float,
    max_samples: int = 220_000,
) -> dict[str, float | str]:
    np = dg.np
    if np is None:
        return {}
    if mode != "neutral" and analysis is None:
        return {}
    original_gain = bundle.exposure_gain
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = max(1, math.ceil(flat.shape[0] / max_samples))
    sample_rgb = flat[::step, :3]
    tony_lut = dg.load_tony_spi3d(dg.default_tony_lut_path()) if mode == "tony" else None

    def margin_at(ev: float) -> tuple[float, dict[str, float]]:
        rgb = render_sample_output_linear(bundle, analysis, mode, gamut, ev, sample_rgb, tony_lut)
        metrics = output_metrics_from_linear(rgb, gamut)
        # The preview path uses rawpy half_size for speed, which can under-report
        # green/luma clipping. Keep this safety scan conservative so preview EV
        # headroom is a lower-risk estimate, while full export still reports final
        # all-pixel output metrics from the saved JPEG.
        margin_luma = 92.0 - metrics.get("luma_p999_pct", 100.0)
        margin_rgb = 96.0 - metrics.get("max_channel_p999_pct", 100.0)
        margin_clip = 0.03 - metrics.get("clipped_channel_pct", 100.0)
        margin_near = 0.25 - metrics.get("near_white_pct", 100.0)
        return min(margin_luma, margin_rgb, margin_clip * 10.0, margin_near), metrics

    try:
        current_margin, current_metrics = margin_at(current_ev)
        if current_margin <= 0.0:
            return {
                "safe_ev_remaining": 0.0,
                "estimated_safe_ev": current_ev,
                "headroom_limit": "当前预览已接近/触及高光上限",
            }

        low = current_ev
        high = current_ev + 0.5
        high_margin, _ = margin_at(high)
        while high_margin > 0.0 and high < current_ev + 3.0:
            low = high
            high += 0.5
            high_margin, _ = margin_at(high)

        if high_margin > 0.0:
            safe_ev = high
        else:
            for _ in range(5):
                mid = (low + high) * 0.5
                mid_margin, _ = margin_at(mid)
                if mid_margin > 0.0:
                    low = mid
                else:
                    high = mid
            safe_ev = low

        return {
            "safe_ev_remaining": max(0.0, float(safe_ev - current_ev)),
            "estimated_safe_ev": float(safe_ev),
            "headroom_limit": "p99.9高光/通道顶白/近白比例阈值",
            "sample_luma_p999_pct": current_metrics.get("luma_p999_pct", 0.0),
            "sample_max_channel_p999_pct": current_metrics.get("max_channel_p999_pct", 0.0),
        }
    finally:
        bundle.exposure_gain = original_gain


def list_dir(raw: str) -> dict:
    p = Path(raw).expanduser() if raw else Path.home()
    if not p.is_dir():
        p = Path.home()
    dirs: list[str] = []
    files: list[str] = []
    try:
        for entry in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            try:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    dirs.append(entry.name)
                elif entry.suffix.lower() in RAW_EXTS:
                    files.append(entry.name)
            except OSError:
                continue
    except PermissionError:
        pass
    return {"cwd": str(p), "parent": str(p.parent), "dirs": dirs, "files": files}


def parse_job_params(params: dict) -> tuple[Path, str, str, str, float, int, bool, Path | None]:
    inp = Path(str(params["input"])).expanduser()
    if not inp.is_file():
        raise FileNotFoundError(f"文件不存在：{inp}")
    mode = str(params.get("mode", "neutral"))
    if mode not in ("neutral", "smart", "agx", "tony"):
        raise ValueError(f"未知模式：{mode}")
    highlight = str(params.get("highlight", "clip"))
    if highlight not in ("clip", "blend", "reconstruct"):
        raise ValueError(f"未知高光处理：{highlight}")
    gamut = str(params.get("gamut", "srgb"))
    if gamut not in ("srgb", "p3"):
        raise ValueError(f"未知输出色域：{gamut}")
    ev = float(params.get("ev", 0.0))
    quality = int(params.get("quality", 100))
    if not 1 <= quality <= 100:
        raise ValueError("质量需在 1-100 之间")
    want_png = bool(params.get("png", False))
    outdir = Path(str(params["outdir"])).expanduser() if params.get("outdir") else None
    return inp, mode, highlight, gamut, ev, quality, want_png, outdir


def plan_for_bundle(bundle: dg.RawBundle, analysis: dg.Analysis, mode: str, gamut: str) -> dg.ToneCompressionPlan | None:
    return dg.plan_for_mode(bundle, analysis, mode, gamut) if mode != "neutral" else None


def export_preview_jpeg(
    inp: Path,
    mode: str,
    highlight: str,
    gamut: str,
    ev: float,
    quality: int,
    max_width: int = 1400,
) -> dict:
    dg.require_dependencies()
    stat = inp.stat()
    key = (str(inp), int(stat.st_mtime_ns), highlight)
    with PREVIEW_CACHE_LOCK:
        cached = PREVIEW_CACHE.get(key)
    if cached is None:
        bundle = dg.load_raw(inp, highlight, scene_half_size=True)
        analysis, _, _ = dg.analyze(bundle, 4)
        with PREVIEW_CACHE_LOCK:
            PREVIEW_CACHE.clear()
            PREVIEW_CACHE[key] = (bundle, analysis)
    else:
        bundle, analysis = cached

    with RENDER_LOCK:
        bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)
        tone_plan = plan_for_bundle(bundle, analysis, mode, gamut)
        icc_profile = dg.output_icc_profile_bytes(gamut)
        tmp = tempfile.NamedTemporaryFile(prefix="dngscan_preview_", suffix=".jpg", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            dg.export_srgb_jpeg(inp, tmp_path, quality, mode, bundle, analysis, None, tone_plan, gamut)
            metrics = output_luminance_metrics(tmp_path, gamut, ev)
            metrics.update(estimate_ev_headroom(bundle, analysis, mode, gamut, ev))
            preview = make_preview_b64(tmp_path, width=max_width, icc_profile=icc_profile)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return {
        "ok": True,
        "preview": preview,
        "metrics": metrics,
        "metrics_kind": "preview",
        "gain": bundle.exposure_gain,
        "ev": ev,
        "highlight": dg.highlight_mode_cn(highlight),
        "gamut": dg.output_gamut_label(gamut),
    }


def run_preview(params: dict) -> dict:
    inp, mode, highlight, gamut, ev, quality, _, _ = parse_job_params(params)
    return export_preview_jpeg(inp, mode, highlight, gamut, ev, min(quality, 95))


def run_export(params: dict) -> dict:
    dg.require_dependencies()
    inp, mode, highlight, gamut, ev, quality, want_png, outdir_arg = parse_job_params(params)
    outdir = outdir_arg if outdir_arg is not None else inp.parent
    outdir.mkdir(parents=True, exist_ok=True)

    bundle = dg.load_raw(inp, highlight)
    bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)

    analysis = None
    y = ev_img = None
    if mode != "neutral" or want_png:
        analysis, y, ev_img = dg.analyze(bundle, 4)
    tone_plan = plan_for_bundle(bundle, analysis, mode, gamut) if analysis is not None else None

    suffix_parts = [mode]
    if highlight != "clip":
        suffix_parts.append(highlight)
    if gamut != "srgb":
        suffix_parts.append(gamut)
    suffix = "_".join(suffix_parts)
    jpg_path = outdir / f"{inp.stem}_{suffix}.jpg"
    with RENDER_LOCK:
        bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)
        icc_profile = dg.output_icc_profile_bytes(gamut)
        dg.export_srgb_jpeg(inp, jpg_path, quality, mode, bundle, analysis, None, tone_plan, gamut)
        metrics = output_luminance_metrics(jpg_path, gamut, ev)
        metrics.update(estimate_ev_headroom(bundle, analysis, mode, gamut, ev, max_samples=600_000))
        preview = make_preview_b64(jpg_path, icc_profile=icc_profile)
        saved = [str(jpg_path)]

        if want_png:
            png_path = outdir / f"{inp.stem}_scan.png"
            dg.plot_dashboard(bundle, analysis, y, ev_img, png_path)
            saved.append(str(png_path))

    return {
        "ok": True,
        "saved": saved,
        "preview": preview,
        "metrics": metrics,
        "metrics_kind": "full",
        "gain": bundle.exposure_gain,
        "ev": ev,
        "highlight": dg.highlight_mode_cn(highlight),
        "gamut": dg.output_gamut_label(gamut),
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.replace("INIT_DIR", json.dumps(str(_default_dir()))).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/list":
            q = parse_qs(parsed.query)
            self._json(list_dir(q.get("dir", [""])[0]))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/export", "/preview"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
            self._json(run_preview(params) if path == "/preview" else run_export(params))
        except Exception as exc:  # surface any pipeline error to the UI
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, code=200)

    def log_message(self, fmt: str, *args: object) -> None:  # keep the console quiet
        return


def _default_dir() -> Path:
    pics = Path.home() / "Pictures"
    return pics if pics.is_dir() else Path.home()


def main() -> int:
    if dg.IMPORT_ERRORS:
        print("警告：dngscan 依赖未就绪，导出会失败。请先安装 rawpy/numpy/matplotlib/pillow：")
        print("  " + "\n  ".join(dg.IMPORT_ERRORS))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://127.0.0.1:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"dngscan GUI: {url}  (Ctrl+C 退出)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
