# dngscan 推进进度（2026-07）

本文档总结近期在 `main` 上完成的工作：模块化重构、ARRI 风格 look 层、EV auto 曝光、GUI 拆分，以及样张对比结论。

## 总览

| 领域 | 状态 |
|------|------|
| `core.py` 拆包 | ✅ 完成，`core` 仅作兼容 re-export |
| Web GUI 拆包 | ✅ `dngscan/gui/` 包，入口不变 `python -m dngscan.gui` |
| ARRI look（GPL 合规） | ✅ 参数化 Oklab 色度场，无 LUT 入库 |
| EV auto | ✅ CLI `--ev auto` + GUI **auto** 按钮 |
| 单元测试 | ✅ `tests/test_look.py`、`tests/test_auto_ev.py` |
| 样张对比脚本 | ✅ `test_output/run_compare.py`（JPEG 输出被 `.gitignore` 忽略） |

---

## 1. 代码库模块化（`core.py` 拆分）

原先约 3400 行的 `dngscan/core.py` 拆为职责清晰的子模块，`core.py` 保留约 20 行 re-export，保证 `import dngscan as dg` 与 `from dngscan.core import *` 仍可用。

| 模块 | 职责 |
|------|------|
| `_deps.py` | numpy / matplotlib 可选依赖与错误信息 |
| `constants.py` | 全局常量（`GRAY_EV`、`MIDGRAY_HEADROOM_STOPS` 等） |
| `models.py` | `RawBundle`、`Analysis`、`ToneCompressionPlan`、`AutoEvResult` |
| `color.py` | 色彩空间、Oklab、gamut fit |
| `raw_io.py` | libraw 加载、demosaic、高光模式 |
| `analysis.py` | RAW 物理分析、EV 指标、健康度 |
| `tone.py` | 曝光锚定、`build_tone_compression_plan`、smart 压缩 |
| `render.py` | scene-linear → 显示域（neutral/smart/agx/tony + look） |
| `export.py` | JPEG / Ultra HDR 写出 |
| `plot.py` | 六面板诊断图 |
| `report.py` | 终端报告、CSV |
| `cli.py` | `python -m dngscan` 命令行 |
| `auto_ev.py` | EV auto 计算与高光安全扫描 |
| `look.py` | AgX 之上的 ARRI 风格色度 look |
| `agx.py` / `priors.py` / `metadata.py` | 既有子系统（未改职责） |

---

## 2. ARRI look 层（`look.py` + `tools/extract_arri_look.py`）

### 设计原则

- **不 ship ARRI LUT**：官方 `.cube` 仅本地放在 `dngscan_assets/arri/`（gitignore）。
- **测几何、不抄表**：合成 hue×L×C 色块 → 过本地 ARRI LUT → 与 dngscan AgX 对比 → 在 Oklab 记录 Δ，拟合为参数化算子。
- **只动色度**：`apply_look_oklab()` 不改 L，tone 仍由 AgX 负责。

### 算子族（`LookField`）

1. 12 扇区 hue 旋转（`hue_rotation_deg`）
2. 随 L 变化的 shadow / highlight chroma 斜坡
3. 高饱和软膝（`sat_knee_relief`）
4. 肤色带 hue 收敛 + chroma 衰减

### 接入点

- CLI：`--look {none,classic,reveal}`、`--look-strength 0–1.5`（仅 `agx` 模式）
- GUI：look 下拉 + 强度滑块（agx 模式显示）
- Ultra HDR 导出暂不支持 look（底图一致性优先）

### 提取工具

```bash
python tools/extract_arri_look.py --lut path/to/ARRI.cube --emit python --validate
```

---

## 3. EV auto（`auto_ev.py`）

### 动机

固定 `--ev 0` 把「标称中灰」映射到 0.18，**不会**按画面内容增亮；暗场景在导出时比机内预览偏暗。EV auto 在保留高光保护的前提下，尽量把**画面中位**对齐 18% 灰。

### 算法

1. **中灰目标**：`median_align_ev(mode, analysis) = -median_vs_gray_ev - log2(compute_exposure_gain(mode, 0))`
2. **高光上限**：对 subsample 像素走完整 tone mapping 管线，用 `output_highlight_margin()` 检查 p99.9 亮度、通道顶白、近白比例；二分搜索 `max_safe_ev()`（默认自 EV 0 起最多 +3 EV）。
3. **最终 EV**：`ev = min(中灰目标, 高光上限)`；若被截断则 `highlight_limited=True`。

### 高光阈值（与 GUI headroom 估计一致）

| 指标 | 阈值 |
|------|------|
| p99.9 亮度 | < 92% |
| p99.9 最大通道 | < 96% |
| 剪切像素 | < 0.03% |
| 近白像素 | < 0.25% |

### 使用方式

**CLI**

```bash
python -m dngscan photo.dng --jpeg out.jpg --jpeg-mode agx --ev auto --output-gamut p3
```

**GUI**：曝光区 **auto** 按钮 → 计算 EV → 预览图左上角烧录 `EV auto +x.xx` → 滑块自动更新，可再手动微调后导出。

### 报告字段

- 终端：`EV auto: 提升 +x.xx EV；高光限制…；应用 EV=…`
- CSV：`jpeg_ev_auto_boost`、`jpeg_ev_auto_limited`、`jpeg_ev_auto_median_target`
- 诊断 PNG（`--scan`）：标题栏黄色条显示 auto 结果

---

## 4. GUI 包（`dngscan/gui/`）

| 文件 | 职责 |
|------|------|
| `page.py` | 单页 HTML/JS（localStorage v3、look UI、**auto** 按钮） |
| `service.py` | 预览缓存、导出任务、`annotate_preview_rgb_u8()` |
| `server.py` | HTTP 路由 `/preview`、`/export`、`/list`、`/reveal` |
| `constants.py` | 代理长边、RAW 扩展名 |

预览路径仍用 `rawpy` half_size；全分辨率导出走 `--demosaic`。

---

## 5. 测试与样张对比

### 单元测试

```bash
python -m unittest tests.test_look tests.test_auto_ev
```

### 批量对比（开发脚本）

```bash
python test_output/run_compare.py
```

当前设置：**quality=100、4:4:4、highlight=reconstruct、每模式独立 EV auto**。

### 两张 Sigma fp 样张结论（2026-07-06）

**`_SDI0133`（ISO 1600，极暗）**

- `median_vs_gray` ≈ -4.1 EV；高光在 EV=0 已接近输出上限。
- agx / classic / reveal：**auto EV = 0**（无法提亮）；tony 扫到 +3.0 EV 仍难完全对齐中灰。

**`_SDI0165`（ISO 200）**

- `median_vs_gray` ≈ -2.4 EV；高光余量较好。
- tony：**+1.88 EV**，锚定后中灰 **0.00 EV**（完全对齐）。
- agx 系：**+1.12 EV**，锚定约 -0.76 EV（高光限制未完全达到中灰目标）。

### JPEG 体积（q100 4:4:4，约 24.5 MP）

- 单张约 **20–25 MB**（此前 q95 批量约 5–7 MB 属正常差异）。
- look 版（classic/reveal）因降饱和度，通常比 plain agx 小 **5–7%**。

---

## 6. Bug 修复

- **`models.py`**：拆分后恢复 `@dataclass`，修复 `RawBundle()` 构造错误。
- **`look.py`**：`_periodic_interp` 在 hue 边界 `pos≈12` 时越界；加 `clip` 后高 EV 导出不再崩溃。

---

## 7. 尚未完成（见 `TODO.md`）

- **P0**：Ultra HDR gain-map 底图 / SDR 线性不一致问题（`export_ultrahdr_jpeg`）
- README 项目结构说明仍部分指向旧 `gui.py` / 单体 `core.py`
- ARRI look：更多机型/场景下的实测校验与 strength 曲线微调

---

## 8. 快速命令

```bash
source .venv/bin/activate

# GUI
python -m dngscan.gui

# 分析 + AgX + EV auto + P3
python -m dngscan photo.dng --scan --jpeg out.jpg --jpeg-mode agx --ev auto \
  --look classic --jpeg-quality 100 --chroma 444 --output-gamut p3

# 样张批量对比
python test_output/run_compare.py
```
