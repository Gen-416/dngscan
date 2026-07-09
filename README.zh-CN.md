# dngscan

[English](README.md)

`dngscan` 是一个本地、离线运行的 RAW 分析器与 JPEG 渲染器。它不把 RAW 只当成等待套曲线的像素，而是先读取它留下的采集证据：逐 CFA 通道的黑/白电平、剩余满阱、剪切类别、SNR、可靠场景亮度分布，以及交付色域压力；再把 scene-linear Rec.2020 信号编译为 SDR JPEG。

它不是通用 RAW 编辑器。它的目标是把少数关键渲染决策变成可解释、可重复的流程：保住拍摄时的曝光意图，把肩部留给有证据的高光，并且只在采集信息或交付容器确实要求时改变高光色彩。

## 核心思路

默认的 **保真：RAW 证据驱动** 策略，把两类决定严格拆开：

1. 全图亮度由一条 scene-luminance C1 曲线决定。
2. 只有 RAW 证据、场景亮度、SNR、色域压力与色相策略允许时，才混入 AgX 向白色收敛的色彩路径。

这种拆分很重要。高光重建后的一盏灯可以在视觉上连续，但它不等于传感器重新获得了满阱余量，因此不能定义整张图的全局白端点。反过来，一块正常曝光的肤色也不应因为画面别处有一盏剪切灯就被整体抽掉色度。

```text
RAW / DNG
  |
  +-- CFA 证据：逐通道黑/白、剪切类别、headroom、SNR
  |
  +-- LibRaw 解码：去马赛克、白平衡、相机矩阵 -> scene-linear Rec.2020
                                                    |
                                                    +-- 可选相机响应校正
                                                    |
可靠场景 body / tail --------------------------------+-- RenderPlan
                                                         | tone：C1 端点、toe、shoulder
                                                         | colour：RAW / 色域许可
                                                         v
                                                   所选压缩策略
                                                         |
                                      可选成片 Look 或输出 LUT（二选一）
                                                         |
                                     Oklab 色域适配 -> sRGB/P3 编码 -> 抖动 -> JPEG
```

分析和导出使用同一种高光模式与场景缓冲。CFA/RAW 域指标仍独立于去马赛克和高光重建，因此工具能区分“渲染器把高光补得连贯”与“传感器原本仍剪切了这个通道”。

## 曝光与全图亮度参考

对三个 tone-mapped 策略，工具会使用一个固定、与照片内容无关的常数，把名义中灰放到曲线的 18% 锚点。这不是从画面内容自动算出来的。因此在 `EV 0` 时，夜景仍是夜景：tone plan 可以塑造 toe 和 shoulder，但不会把暗场景重写成灰亮的日景。

`EV` 是这个锚点上的手动偏移。GUI 的 **全图亮度参考** 按钮，以及 CLI 的 `--ev auto`，是可选的参考操作：它读取整张图的中位亮度，计算把中灰放到 18% 所需的 EV，并用渲染后的高光安全上限限制向上提升。它适合“本应正常曝光、但整体明显偏暗”的照片，也适合用作比较起点；它不是对场景意图的判断，只有用户主动点击或显式指定时才会应用。

## 压缩策略

除了 `neutral`，所有策略都从**可靠**场景亮度分布编译黑白端点：黑端受可用动态范围/噪声估计约束，白端来自可靠 tail，而不是 CFA 已剪切或经重建的样本。它们共用同一族 C1 连续的 toe/shoulder，并保持同一个 18% 固定 pivot。差异只在于谁拥有色彩决定权。

| GUI 名称 / CLI 核 | 底层处理 | 预期画面 | 适用场景 |
| --- | --- | --- | --- |
| **保真：RAW 证据驱动** / `gated` | 全图 Rec.2020 亮度先走 C1 曲线；同时计算一份完整 AgX 结果，把它重新缩放回相同的 Rec.2020 Y，再按逐像素许可权重只混入其色度/向白路径。 | 主体与肤色保留采集到的色度；不确定或很亮的高光会向白退色，且 RAW mask 边界不会产生亮度接缝。 | 默认的成片策略。 |
| **AgX：全图色彩路径** / `agx` | 每个像素都走 AgX 的 inset -> log2 C1 曲线 -> hue mix -> outset，并接场景驱动的中间调纯度算子。 | 最统一、最典型的全图 AgX 观感：饱和高光遵循一致的 AgX 路径，但中间调的鲜艳物体也会受到这套几何影响。 | 直接比较 AgX，或希望全图都服从同一 AgX 色彩逻辑。 |
| **亮度优先：保持通道比例** / `lum` | 将一个标量亮度 norm 走 C1 曲线，再以所得比例缩放 RGB。除已知剪切样本和最终显示端保护外，RGB 比例保持。 | 三个 tone-mapped 选项中最接近 scene RGB 比例；饱和高光可能更直白、较少 filmic 的向白路径。 | 判断 AgX 几何是否帮到这张照片，或尽量保住产品/图形色。 |
| **线性参考：不做 tone 压缩** / `neutral` | 跳过 tone core。scene-linear Rec.2020 只做交付色域转换、色域适配与编码。 | 没有设计好的肩部或 toe；亮值会直接触到交付上限，因此它是技术参考，不是完成风格。 | A/B 分析，检查某种 DRT 的实际代价。 |

`gated` 的色彩许可是连续量，不是二元的“剪切/未剪切”遮罩。逐通道 headroom 耗尽和多通道剪切会提高许可；很亮的 shoulder、交付色域压力、可信的色彩 SNR 也能逐步打开它。可靠肤色中调会被保护，亮的绿/青色则可略微更开放。RAW 信息损失的信号永远优先于这层审美色相策略。

`lum` 有三种标量 norm：`y` 是 Rec.2020 亮度，也是正常选择；`power` 让强单通道更有影响；`max` 跟随最亮通道，对高光最保守，但画面可能更平。这是亮度度量的比较开关，不是三种不同的曝光锚点。

## AgX 高光路径

**AgX 高光路径** 只在 `gated` 和 `agx` 下有意义。它**不会**选择另一条 shoulder 曲线、白端点、曝光或动态范围计划。四个选项使用相同的场景 C1 曲线；它们改变的是曲线两侧的 AgX 原色几何：

```text
Rec.2020 RGB -> inset / 原色旋转 -> 逐通道 C1 曲线 -> hue mix -> outset
```

Inset 会在曲线前有意混合、收缩原色，使一个饱和高光不会像三个互不相关的通道剪切。Outset 决定曲线之后回收多少色彩几何。因此这个选择改变的是**向白色走的路线**，不是亮度 shoulder 的位置。

| 路径 | 底层几何 | 预期高光表现 |
| --- | --- | --- |
| **标准：平衡退白** / `base` | Blender-like / darktable blender-like 的 Rec.2020 原色构造，色相混合锚点遵循 Blender 的 0.4。 | 默认的平衡关系。明亮饱和色会柔和地向白靠近，不会强行做很重的创意色彩回收。 |
| **鲜明：保留更多纯度** / `punchy` | 与 `base` 使用相同 inset，但在几何构造中减少 outward-primary recovery（`master_outset_ratio=0.5`），曲线后保留更多可见纯度。 | 有色光、霓虹、叶片等高光会更有颜色和局部区分；极端 sRGB/P3 颜色仍可能在最终色域适配中被降色度。 |
| **柔和：更早感觉退白** / `muted` | 采用 base inset，同时恢复 outward primary 的旋转（`master_unrotation_ratio=1`）。亮度曲线不变，改变的只有曲线后的色彩几何。 | 比 `base` 更安静、较少强调高亮色的回收。它可能**看起来**更早走向中性，但亮度 shoulder 实际起点相同。 |
| **平滑：darktable 几何** / `smooth` | darktable 的 smooth-primary 构造：不同的 inset/outset 距离和旋转；它不是另一种 sigmoid。 | 饱和高光会沿一条不同、通常更安静的色相轨迹移动。应在实际照片上与 `base` 并排比较；它不是简单的全局饱和度控制。 |

独立的 **中间调纯度** 不是这四条路径之一。它是只在 `gated` 与 `agx` 后运行的、由场景条件门控的色度算子；不适合的暗场/高 ISO 场景会自动降到零。它不改变曝光、toe、shoulder 或白端点。

## RAW 还原选项

这些设置发生在 tone core 之前，其事实性影响通常大于后面的创意 Look。

| 设置 | 含义 | 取舍 |
| --- | --- | --- |
| **保持剪切** / `clip` | LibRaw 保留已剪切的高光。 | 不凭空估颜色；最清楚地反映传感器损失。 |
| **高光混合** / `blend` | LibRaw 混合幸存通道的信息。 | 单通道剪切时可能保住更多颜色；严重剪切时不如原始值字面。 |
| **高光重建** / `reconstruct` | LibRaw 的邻域高光重建。 | 高光往往更连续、更有颜色，但部分结果是估计；gated 策略仍可读取原始 CFA 剪切证据。 |
| **相机记录白平衡** / `camera` | 使用相机 As Shot 白平衡。 | 最接近拍摄元数据。 |
| **固定日光配平** / `daylight` | 使用 LibRaw 的标定日光乘子。 | 为整组照片提供可重复基线；不代表现场一定是日光。 |
| **细节插值自动** / `auto` | 全分辨率 Bayer 导出优先 DHT，再 DCB/AHD；非 Bayer 走 LibRaw 原生路径。 | 只影响细节重建。dngscan 不做降噪。 |

## 其他色彩与交付层

**相机响应校正** 是实验性的、tone core 前的 scene-linear 变换。内置的 ARRI-like 与 ALEV 材质预设，在软色度窗口中混入受约束矩阵，保持中性轴，不是显示 LUT。它们的光谱输入仍是可替换的 bootstrap/校准数据，不能被理解为严格 ALEXA 仿真。需要中性基线时应关闭它。

**成片风格** 可选，发生在 tone core 后。色度 LookField 在 Oklab 中改色相/色度而保持亮度；输出 LUT 则是完整的 log-in/display-out 变换，可能同时改变色调和色彩。两者互斥。厂商 LUT 文件不会随仓库分发，只应在本机安装你有权使用的副本。

**交付色域** 是另一层约束。场景渲染一直留在 Rec.2020，直到最后才转 sRGB 或 P3。出界颜色在 Oklab 中尽量保色相、降低色度拉回，而不是逐 RGB 通道硬剪。`sRGB` 适合兼容性；`Display P3` 会嵌入 P3 ICC，如果找不到 profile 会直接报错，不会写出被误读为 sRGB 的 P3 数据。JPEG 默认质量 100、4:4:4 色度采样。

ISO gain-map HDR 路径仍是**实验性**输出，在跨平台兼容性验证完成前不属于推荐的稳定交付流程。普通 SDR JPEG 是当前受支持的默认结果。

## 诊断图

`--scan` 会输出六面板诊断 PNG。它是采集报告，不是审美评分。

- **SNR 对档数**：用于判断暗部可恢复余量。约 SNR 32 通常较干净，约 10 通常可用但有代价，接近 1 时信号已被噪声淹没。它不是要求把所有阴影抬到固定亮度的指令。
- **R/G/B 原始分布**：横轴为距离剪切的档数。R/G/B 分开避免遮挡，红带是剪切区；图上可平滑，但统计仍用未平滑 RAW 数据。
- **RGB 曝光分布与色域压力**：用于判断交付时可能需要多少色彩处理；它们不改动 C1 tone 端点。
- **空间曝光/剪切通道图**：用来判断 tail 是少量光源、大片主体剪切，还是单通道问题。

## 安装与使用

需要 Python 3.10+。

```bash
pip install -r requirements.txt
python -m dngscan.gui
```

GUI 在 localhost 中运行。它会缓存同一文件的解码/分析，用 proxy 加速连续预览，但导出始终使用全分辨率缓冲。建议工作流：

1. 从 `保真：RAW 证据驱动`、`标准`、`EV 0` 与选定的 RAW 高光模式开始。
2. 把**全图亮度参考**当作主动比较工具；低调/高调意图正确时回到 `EV 0`。
3. 在加入相机响应校正或成片风格之前，先对比 `gated`、`agx` 与 `lum`。
4. 决定手动 EV 上限时，以全分辨率导出的指标为准，不只看 proxy 预览的近白比例。
5. 广泛交付用 sRGB；已知 P3 色彩管理观看环境时用 Display P3。

CLI 示例：

```bash
# 成片 SDR JPEG：默认 RAW 门控策略，质量 100，4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# 同时输出采集报告和 JPEG
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# 在相同 EV 下比较三条有意义的 DRT 分支
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg agx.jpg --tone-core agx --agx-primaries base
python -m dngscan photo.dng --jpeg lum.jpg --tone-core lum --lum-norm y

# 改变 RAW 还原或交付色域
python -m dngscan photo.dng --jpeg photo_p3.jpg --highlight-mode reconstruct --output-gamut p3

# 主动应用全图亮度参考
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

完整参数见 `python -m dngscan --help`。

## 校准资源与许可

仓库保留可运行代码、光谱 bootstrap 数据和开源许可的来源资产。可选的厂商 LUT 留在本机，并被 Git 忽略。当前 scene-transform 校准数据及其限制见 [`dngscan_assets/spectral/README.md`](dngscan_assets/spectral/README.md)。

dngscan 使用 [GPL-3.0-or-later](LICENSE)。AgX 实现派生自 darktable 的 GPL-3.0-or-later AgX 代码；第三方声明，包括历史性的 Tony McMapface LUT，见 [NOTICE.md](NOTICE.md)。
