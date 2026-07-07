# dngscan

[English](README.md)

面向物理测量的 RAW/DNG 分析器与 **AgX** 色调映射导出工具。读取相机原始文件，测量传感器实际捕获的内容（动态范围、逐通道剪切、信噪比、色域压力），经统一的 AgX 视图变换将 scene-linear 信号渲染为 8-bit JPEG；可选叠加一层 **成片风格**（色度 Look 或输出滤镜）。支持命令行与本地 Web GUI。

项目最初是诊断工具（六面板 PNG 仪表盘），后来扩展为无需经 RAW 编辑器中转、直接产出成片 JPEG 的工作流。

## 功能概览

- **诊断** — 六面板 PNG：SNR–档数曲线、逐通道 RAW 分布、RGB 曝光直方图、各输出色域的溢出风险、空间曝光分区图、剪切通道高光图；以及逐通道满阱 / 剪切 / 黑电平 / 白平衡读数。
- **AgX 导出** — Rec.2020 原生 AgX 视图变换：inset → log2 → sigmoid → outset。通道串扰带来平滑的高光去饱和与 AgX 特有的色相 flourish。所有 JPEG 均走此管线。
- **AgX 前馈（实验）** — 可选 `--scene-transform arri_skin_d55`，在相机色彩变换之后、AgX 之前的 scene-linear Rec.2020 域，对肤色/青色区域施加受限 3×3 色度矩阵；默认关闭。
- **成片风格（互斥）** — AgX 之上可选一层（`--grade`）：
  - **色度 Look** — 由官方 LUT 实测的 Oklab 几何（富士胶片模拟、ARRI Classic / Reveal）。色调仍由 AgX 负责；只改色相 / 饱和度 / 肤色塑形。
  - **输出滤镜** — 完整 Log 编码输出变换（Kodak 2383 FPE、RED IPP2），经 Cineon / Log3G10 编码后采样 `.cube`。
- **保色相色域适配** — 用 Oklab adaptive-L0 裁切（保色相、降色度），而非逐通道 clip；适用于 sRGB 与 Display P3。
- **导出高质量去马赛克** — 全分辨率导出默认 `--demosaic auto`（Bayer 优先 DHT，非 Bayer / X-Trans 走 libraw 原生）；预览用轻量去马赛克。仅选插值画质，**不做降噪**。
- **本地 Web GUI**（`python -m dngscan.gui`）— 选文件、曝光、成片风格、质量、去马赛克与输出色域；实时预览；单文件曝光余量估计；sRGB / Display P3；高光处理（clip / blend / reconstruct）。
- **可选 Ultra HDR JPEG** — ISO/Ultra HDR gain-map，带 SDR 回退底图。成片风格目前仅 SDR。默认仍为普通 SDR JPEG。

## 处理管线

AgX 之前/之中链路固定。`--grade` 在 **同一份 AgX 成品** 上三选一；Oklab 与 Log 编码是两种
互不叠加的实现方式，对应两类不同的官方 LUT，不是上下两层滤镜。

```text
┌─────────────────────────────────────────────────────────────┐
│ ① RAW 还原                                                   │
│    DNG ──► 去马赛克 ──► 白平衡 ──► 色彩矩阵 ──► scene Rec.2020 │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ② 分析 + 曝光                                                │
│    analyze() · EV 手动/auto · compute_exposure_gain(agx)      │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ②b AgX 前馈（可选）                                          │
│    scene Rec.2020 ──► skin/cyan chroma mask ──► constrained M │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ AgX（必有）                                                │
│    scene Rec.2020 ──► AgX core ──► mapped Rec.2020          │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③b 成片风格  `--grade` · 三选一 · 同一 AgX 输入              │
│                                                             │
│   无 ────────────────► rec2020_to_output（仅 AgX 显示）      │
│                                                             │
│   色度 Look ─────────► rec2020_to_output                    │
│     （富士 / ARRI）       └──► Oklab + LookField              │
│                           只改色相/色度/肤色；L 不动           │
│                           （离线实测参数；运行时不再采样 .cube）│
│                                                             │
│   输出滤镜 ──────────► Log 编码 ──► 采样 .cube ──► 显示解码   │
│     （Kodak / RED）      Cineon+709  或  Log3G10+RWG         │
│                          完整输出变换（色调+饱和一体）          │
│                          按强度与 AgX 显示结果混合             │
│                                                             │
│   ✕ 同一次导出不能同时启用色度 Look 与输出滤镜                 │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ 显示编码                                                   │
│    色域适配 · sRGB/P3 OETF + TPDF 抖动 · JPEG / Ultra HDR   │
└─────────────────────────────────────────────────────────────┘
```

**为何两套机制？** 都接在同一份 AgX 之后。富士 / ARRI 官方 LUT 被 **实测** 为相对 AgX 的
Oklab 色度几何，运行时只在 Oklab 里改 a/b，**亮度 L 仍由 AgX 决定**。Kodak / RED 的
`.cube` 是 **Log 入 → 显示出** 的完整变换，必须按厂商约定做 Log 编码再采样；若强行抽成
LookField，饱和度会崩塌，因此走独立的 Log → `.cube` 支路，并与色度 Look **互斥**。

## 设计说明

- **曝光为固定常数，非内容自适应。** AgX 用常数标量把名义中灰锚到 0.18；`--ev` 手动补偿，或 `auto` 将画面中位对齐 18% 灰并保护高光。暗场景保持暗。
- **全程 scene-linear Rec.2020。** 导出缓冲留在宽色域工作空间，避免 tone mapping 前就把饱和高光 clip 到 sRGB。AgX inset/outset 共轭到 Rec.2020，中性色保持中性。
- **TPDF 抖动 8-bit 量化**，减轻平滑渐变上的色带。
- **保色相色域适配** — 出界色用 Oklab adaptive-L0 拉回，避免饱和色逐通道 clip 偏色。
- **去马赛克是重建，不是降噪。** Bayer 导出可用 DHT；非 Bayer（如富士 X-Trans）走 libraw 原生。无平滑、无 NR。
- **Gain-map HDR 为叠加式。** SDR 底图即正常渲染结果；HDR 分子在中调与 SDR 一致，仅释放高光 headroom。HDR 强制 Display P3，默认 +3 EV headroom。
- **逐通道分析** — 按通道重建满阱与剪切阈值（有饱和 pile 时用经验值，否则回退 metadata 白电平）。
- **传感器先验（尽力而为）。** 先验表中的机身（目前含 Sigma fp，来自 PhotonsToPhotos）会报告 e-/DN、噪底、读出噪声与 PDR，并温和约束 tone plan 的 DR 预算；未知机身退回单帧估计。
- **RAW 健康检查** — 双绿差分平面 lag-1 空间相关（判断 RAW 是否已烘焙降噪）及 DN 码缺失（重量化）检查；仅诊断用。
- **固定白平衡选项** — `--wb daylight` 用 libraw 标定日光乘子，胶片式整卷一致；AsShot 始终作为现场光源证词报告。默认仍为相机 AsShot。
- **分析与导出一致** — 依赖渲染的统计（亮度/EV 分布、色域溢出、auto tone 输入）在与导出相同的去马赛克与高光模式下测量；CFA/RAW 域指标（剪切%、SNR、噪底）与去马赛克无关，反映传感器物理捕获。

指标均为单帧估计（非光子转移曲线测量）；位深不等于可用动态范围。

## 安装

仓库内不捆绑 Python 或 Homebrew 依赖；系统环境保持常规，项目专属资源放在 `dngscan_assets/`。

需要 Python 3.10+：

```
pip install -r requirements.txt
```

（`numpy`、`rawpy`、`matplotlib`、`pillow`。）GUI 在浏览器中运行，**不需要** Tkinter。

Ultra HDR 优先用 macOS ImageIO/PyObjC，亦可安装 Google `libultrahdr` CLI：

```bash
brew install libultrahdr
```

项目结构：

```text
dngscan/
  cli.py                # 命令行入口
  agx.py                # AgX inset/outset、对数曲线与 sigmoid 核心
  look.py               # 色度 LookField 层（Oklab）
  scene_transform.py    # AgX 前 scene-linear 前馈层
  scene_transform_presets.json # demo ARRI skin prefeed 参数
  display_filter.py     # Kodak / RED 显示 LUT 滤镜
  grade.py              # 统一成片风格选择（Look 或滤镜二选一）
  render.py / export.py # scene → AgX → JPEG / Ultra HDR
  gui/                  # 本地 Web GUI
dngscan_assets/
  look_fields.json      # 用户实测 look（gitignore）
  vendor_luts/          # 下载的 .cube（gitignore）
  darktable_agx.*       # 本地 AgX 参考副本
tools/
  calibrate_skin_matrix.py # 光谱 demo → 前馈矩阵/遮罩 JSON
```

## 用法

命令行：

```bash
# 仅诊断 PNG
python -m dngscan photo.dng

# AgX JPEG，+0.5 EV，Display P3
python -m dngscan photo.dng --jpeg out.jpg --ev 0.5 --output-gamut p3

# 富士 Velvia 色度 Look（叠在 AgX 上的几何）
python -m dngscan photo.dng --jpeg out.jpg --grade fuji_velvia --grade-strength 1.0

# Kodak 2383 输出滤镜（Log 编码 .cube）
python -m dngscan photo.dng --jpeg out.jpg --grade kodak_2383_d65

# AgX 前 ARRI 式肤色前馈（实验；可与后置 grade 分开比较）
python -m dngscan photo.dng --jpeg out.jpg --scene-transform arri_skin_d55 \
  --scene-transform-strength 1.0

# 指定去马赛克（默认 auto → Bayer 用 DHT；仅全分辨率导出）
python -m dngscan photo.dng --jpeg out.jpg --demosaic dht

# Ultra HDR gain-map JPEG（无成片风格；SDR 底图强制 Display P3）
python -m dngscan photo.dng --jpeg out_hdr.jpg --highlight-mode reconstruct \
  --output-format ultrahdr --hdr-headroom 3

# 同时输出诊断 PNG 与指标 CSV
python -m dngscan photo.dng --jpeg out.jpg --scan --csv metrics.csv
```

本地 GUI：

```bash
python -m dngscan.gui   # 启动 localhost 服务并打开浏览器
```

微信/QQ 若要保留 HDR gain map，请走原文件或文件传输；朋友圈/动态类上传通常会重压缩为 SDR 并剥离 gain map。

## 成片风格

`--grade NAME` 选择 **一种** 可选风格（`--grade-strength 0–1.5`）。色度 Look 与输出滤镜 **互斥**。

**色度 Look**（`classic`、`reveal`、`fuji_*` 等）在 AgX 成品上施加实测 Oklab 场。内置 ARRI 场来自官方显示 LUT 几何；富士场由 F-Log2 胶片模拟 `.cube` 实测。**导出时不采样 LUT**，只读 `dngscan_assets/look_fields.json` 中的色相/色度参数。

**输出滤镜**（`kodak_2383_d65`、`red_ipp2_rec709_medium`）为完整输出变换：AgX → Log 编码 → 厂商 `.cube` → 显示解码 → 混合。无法压缩成色度 Look（实测为 LookField 时饱和度会崩塌）。

从任意官方 Log→显示 `.cube` 添加色度 Look：

```bash
# 例：富士 ETERNA（官网下载 F-Log2 → ETERNA .cube）
python tools/extract_arri_look.py --lut path/to/eterna.cube --source flog2 \
  --name fuji_eterna --validate --append-json
```

支持的 `--source` 编码：`logc3, logc4, slog3, vlog, flog, flog2, cineon, log3g10`。当 `mid_chroma_ratio < 0.25` 时会警告（完整输出变换，应走 display filter）。测量在 Oklab 中与 AgX 对比，并用 L 归一化饱和度，使场捕获色度性格而非 LUT 的色调曲线。

输出滤镜 `.cube` 放在 `dngscan_assets/vendor_luts/`（路径见 `display_filter.py`）。

## AgX 前馈

`--scene-transform` 是 AgX 之前的 scene-linear 变换，不是后置滤镜。内置 `arri_skin_d55`
来自 `tools/calibrate_skin_matrix.py` 的 demo 光谱拟合：用粗略 ALEV3 / IMX410 曲线、D55 光源与
Sigma fp hot mirror sigmoid 假设生成受限矩阵和色度遮罩。运行时只读取
`dngscan/scene_transform_presets.json`，不需要 `colour-science` 或 `scipy`。

重新生成默认参数：

```bash
python tools/calibrate_skin_matrix.py --out dngscan/scene_transform_presets.json
```

精确校准时，把数字化 ALEV3 SSF、IMX410 QE 和真实皮肤光谱 CSV 传给脚本；当前内置曲线只是为了跑通
“IMX410 → ALEV 皮肤子空间差异 → 受限矩阵 → AgX 前输入”这条链路。

## 许可与署名

**GPL-3.0-or-later**（见 [LICENSE](LICENSE)）。AgX 实现移植自 [darktable](https://github.com/darktable-org/darktable) 的 GPL AgX 代码。第三方资源见 [NOTICE.md](NOTICE.md)。
