# dngscan

[English](README.md)

面向物理测量的 RAW/DNG 分析器与 **AgX / 亮度核**色调映射导出工具。读取相机原始文件，测量传感器实际捕获的内容（动态范围、逐通道剪切、信噪比、色域压力），将 scene-linear 信号渲染为 8-bit JPEG；可选叠加一层 **成片风格**（色度 Look 或输出滤镜）。支持命令行与本地 Web GUI。

项目最初是诊断工具（六面板 PNG 仪表盘），后来扩展为无需经 RAW 编辑器中转、直接产出成片 JPEG 的工作流。

## 功能概览

- **诊断** — 六面板 PNG：SNR–档数曲线、逐通道 RAW 分布、RGB 曝光直方图、各输出色域的溢出风险、空间曝光分区图、剪切通道高光图；以及逐通道满阱 / 剪切 / 黑电平 / 白平衡读数。
- **拆分式 DRT** — 分析生成不可变 `RenderPlan`：可靠 scene-Y 分布只决定 C1 曲线的黑白端点；RAW CFA 剪切驱动门控色度路径的许可权重；输出色域压力只决定末端色域适配。默认 `--tone-core gated` 在全图走亮度 C1 收肩，仅在 RAW 证据、场景高光 EV、色域压力与肤色/青绿 sector 策略允许处混入 AgX 色度几何（人像中调保留在 luma 路径）。`--tone-core agx` 全图 Rec.2020 inset → log2 → sigmoid → outset；`--tone-core lum` 把同一端点 DRT 施于亮度 norm。AgX 原色几何预设 `base`/`punchy`/`muted`/`smooth`，别名 `agx_blender_strong`、`agx_dt_smooth` 等与之等价。DRT 工作空间固定为 scene-linear Rec.2020，交付显式 sRGB 或 P3。
- **AgX 前馈（实验）** — 可选 `--scene-transform arri_skin_d55`，在相机色彩变换之后、AgX 之前的 scene-linear Rec.2020 域，对肤色/青色区域施加受限 3×3 色度矩阵；默认关闭。
- **成片风格（互斥）** — AgX 之上可选一层（`--grade`）：
  - **色度 Look** — 由官方 LUT 实测的 Oklab 几何（富士胶片模拟、ARRI Classic / Reveal）。色调仍由 AgX 负责；只改色相 / 饱和度 / 肤色塑形。
  - **输出滤镜** — 完整 Log 编码输出变换（Kodak 2383 FPE、RED IPP2），经 Cineon / Log3G10 编码后采样 `.cube`。
- **保色相色域适配** — 用 Oklab adaptive-L0 裁切（保色相、降色度），而非逐通道 clip；适用于 sRGB 与 Display P3。
- **导出高质量去马赛克** — 全分辨率导出默认 `--demosaic auto`（Bayer 优先 DHT，非 Bayer / X-Trans 走 libraw 原生）；预览用轻量去马赛克。仅选插值画质，**不做降噪**。**富士 RAF**（X-Trans 与 Bayer）与 **尼康 NEF/NRW**（Bayer，libraw 原生）已支持：RAF 从专有头与内嵌 JPEG EXIF 读机型/ISO；NEF/NRW 走标准 TIFF EXIF；X-Trans 在去马赛克前捕获 CFA pattern 以保证分析正确。
- **本地 Web GUI**（`python -m dngscan.gui`）— 选文件、曝光、AgX 基调、成片风格、质量、去马赛克与输出色域；实时预览；单文件曝光余量估计；sRGB / Display P3；高光处理（clip / blend / reconstruct）。控件按曝光 / 色彩与风格 / 输出分组；滑条数值与标签同行；输出文件夹可用浏览选择器（不必手填路径）。
- **可选 Ultra HDR JPEG** — ISO/Ultra HDR gain-map，带 SDR 回退底图。成片风格目前仅 SDR。默认仍为普通 SDR JPEG。

## 处理管线

固定 scene body、端点与色彩几何彼此拆开。`--grade` 在 **同一份 tone-core 成品** 上三选一；Oklab 与 Log 编码是两种
互不叠加的实现方式，对应两类不同的官方 LUT，不是上下两层滤镜。

```text
┌─────────────────────────────────────────────────────────────┐
│ ① RAW 还原                                                   │
│    DNG ──► 去马赛克 ──► 白平衡 ──► 色彩矩阵 ──► scene Rec.2020 │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ② Capture 分析 + 计划                                        │
│    analyze() · 固定锚定 + 手动/auto EV · RenderPlan            │
│    scene Y → C1 toe/shoulder；RAW clip → 色度退让             │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ②b Tone-core 前馈（可选）                                     │
│    scene Rec.2020 ──► skin/cyan chroma mask ──► constrained M │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ Tone core                                                  │
│    agx: inset → 端点归一化 C1 曲线 → outset                  │
│    lum: Y/power/max norm → 同一 C1 曲线，保持 RGB 比例        │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③b 色彩几何 + 成片风格  `--grade` · 三选一                   │
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

**为何两套机制？** 都接在所选 tone 核产出的渲染之后。富士 / ARRI 官方 LUT 被 **实测** 为
Oklab 色度几何，运行时只在 Oklab 里改 a/b，**亮度 L 不动**。注意：这意味着 Look 自身从不决定
亮度——**L 来自其下运行的 tone 核**（`agx` 逐通道成形、`lum` 亮度 norm、或 `neutral` 直通），
Look 只在其上重塑 a/b。Kodak / RED 的 `.cube` 是 **Log 入 → 显示出** 的完整变换，必须按厂商
约定做 Log 编码再采样；若强行抽成 LookField，饱和度会崩塌，因此走独立的 Log → `.cube` 支路，
并与色度 Look **互斥**。

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
- **预览 vs 导出** — GUI 用半分辨率场景 proxy 编译 tone plan（分析仍为全分辨率），预览快且基本一致；但稀疏高光与 clip mask 边界在全尺寸下可能有细微差别——**逐像素对比 tone 核（如 AgX vs neutral）时以实际导出为准**，不要看 proxy 预览。

指标均为单帧估计（非光子转移曲线测量）；位深不等于可用动态范围。

## 安装

仓库内不捆绑 Python 或 Homebrew 依赖；系统环境保持常规，项目专属资源放在 `dngscan_assets/`。

需要 Python 3.10+：

```
pip install -r requirements.txt
```

（`numpy`、`rawpy`、`matplotlib`、`pillow`。）GUI 在浏览器中运行，**不需要** Tkinter。

若要重新拟合 AgX 前馈的光谱矩阵，可额外安装校准依赖：

```bash
pip install -r requirements-calibration.txt
```

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
  spectral/             # AgX 前馈校准 CSV：SSF/QE/IR-cut/反射率
  darktable_agx.*       # 本地 AgX 参考副本
tools/
  calibrate_skin_matrix.py # 光谱 CSV → 前馈矩阵/遮罩 JSON
```

## 用法

命令行：

```bash
# 仅诊断 PNG
python -m dngscan photo.dng

# AgX JPEG，+0.5 EV，Display P3
python -m dngscan photo.dng --jpeg out.jpg --ev 0.5 --output-gamut p3

# 富士 RAF（X-Trans）或尼康 NEF — 与 DNG 相同 CLI/GUI
python -m dngscan photo.raf --jpeg out.jpg
python -m dngscan photo.nef --jpeg out.jpg

# 富士 Velvia 色度 Look（叠在 AgX 上的几何）
python -m dngscan photo.dng --jpeg out.jpg --grade look:fuji_velvia --grade-strength 1.0

# 更浓郁的 AgX outset（更高纯度恢复）
python -m dngscan photo.dng --jpeg out.jpg --agx-primaries punchy

# Classic Neg 褪色黑位（Look 内置 hue_keep + target_black）
python -m dngscan photo.dng --jpeg out.jpg --grade look:fuji_classic_neg

# 光学暖肤 / 青色环境 look（手写创意场，非厂商 LUT）
python -m dngscan photo.dng --jpeg out.jpg --grade optic_warm_cyan --grade-strength 1.0

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

`--grade NAME` 选择 **一种** 可选风格（`--grade-strength 0–1.5`）。CLI/GUI 使用带前缀
的 ID：`look:classic`、`filter:kodak_2383_d65` 等；无冲突时仍可用裸名。色度 Look 与输出滤镜 **互斥**。

**色度 Look**（`look:classic`、`look:reveal`、`look:fuji_*` 等）在 AgX 成品上施加实测 Oklab 场。内置 ARRI 场来自官方显示 LUT 几何；富士场由 F-Log2 胶片模拟 `.cube` 实测。**导出时不采样 LUT**，只读 `dngscan_assets/look_fields.json` 中的色相/色度参数。

每个 Look 还可携带 **AgX 核心覆盖**（在 Oklab 层之前生效）：`hue_keep`（曲线后保留多少 per-channel 色相偏斜；Velvia 高于默认 0.4）、`target_black`（抬黑，用于 Eterna / Classic Neg 等褪色胶片感）。`--grade-strength` 会在默认 AgX 与 Look 目标值之间插值。

`optic_warm_cyan` 是另一类：它是手写的创意 look，不是官方厂商 LUT 测量结果。它保留 AgX 的色调映射，
然后把低色度环境色轻推向 cyan / blue-green，保护偏红/偏黄的暖肤色，并压低非肤色的洋红溢出。目标是在
不分发、不采样专有 LUT 的前提下，得到更接近 ARRI 式的肤色 / 环境分离。

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
来自 `tools/calibrate_skin_matrix.py` 的光谱拟合：默认读取 `dngscan_assets/spectral/`
中的 ALEV3 SSF、IMX410 QE、Sigma fp hot mirror、皮肤与青色材料反射率 CSV，然后在
scene-linear Rec.2020 域拟合受限矩阵和色度遮罩。运行时只读取
`dngscan/scene_transform_presets.json`，不需要 `colour-science` 或 `scipy`。

重新生成默认参数：

```bash
python tools/calibrate_skin_matrix.py --out dngscan/scene_transform_presets.json
```

生成/刷新 bootstrap CSV：

```bash
python tools/calibrate_skin_matrix.py --write-bootstrap-csv dngscan_assets/spectral
```

精确校准时，把 `dngscan_assets/spectral/` 里的 bootstrap CSV 替换为数字化 ALEV3 SSF、
ZWO ASI2400MC / IMX410 QE、实测 Sigma fp hot mirror 透过率和真实皮肤反射率库。脚本也支持
`--skin-dir` / `--cyan-dir` 批量读取目录，支持 `colour-science` 提供 D55/A 光源与 CIE 1931 CMF；
当前 CSV 仍是可替换的粗值，目的是把“IMX410 → ALEV 皮肤子空间差异 → 受限矩阵 → AgX 前输入”
这条链路数据化。

## 许可与署名

**GPL-3.0-or-later**（见 [LICENSE](LICENSE)）。AgX 实现移植自 [darktable](https://github.com/darktable-org/darktable) 的 GPL AgX 代码。第三方资源见 [NOTICE.md](NOTICE.md)。
