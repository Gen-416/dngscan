# dngscan

一个离线的小工具：把 RAW 文件经由 AgX 压缩成 JPEG。AgX 实现移植自 darktable 的
`agx` 模块。

[English](README.md) · [许可证](LICENSE) · [第三方声明](NOTICE.md)

dngscan 读取 RAW，测量传感器实际记录下的信号，在 scene-linear Rec.2020 里渲染，
再压缩为 8-bit sRGB 或 Display P3 JPEG。它的工作到此为止：没有图库、没有图层、
没有蒙版和局部修饰——**这不是修图工具**，也不打算变成修图工具。

## 它从哪里来

我很喜欢 darktable。它的 scene-referred 管线本质上是一间信号处理实验室，而这恰恰是
它难以随手推荐给别人的原因：上手门槛真实存在，同一张图可以经由十几个相互作用的模块
到达。dngscan 从这间实验室里取出一条有主张的路径并把它固定下来：LibRaw 解释、
scene-linear Rec.2020、以及曲线构造与原色几何都移植自 darktable GPL `agx` 模块的
AgX 成像。AgX 本身源自 Troy Sobotka，在 Blender / EaryChow 生态中成熟；本项目经由
darktable 继承，而不是另起炉灶。

设计由两个信念决定。

**自动判断是对数码化光学信息的尊重，不是替你修图的机器人。** 工具测量黑白电平、
逐通道 CFA 剪切、暗部可用范围和场景亮度分布，然后由这些测量值编译压缩曲线。EV 0 时
夜景依然是暗的；一盏在传感器上剪切了的灯，不能因为高光重建把它涂抹得平滑连续，
就获得重新定义全图白点的权力。

**压缩管线本身是确定的。** 管线内部会随场景变化的部分，全部由测量编译而来，从不出自
口味；而所有表达口味的东西——曝光补偿、白平衡策略、相机前馈、色彩风格、LUT 滤镜——
都明确地位于 AgX 核心之外，在它之前或之后，并且默认关闭或中性。

## 处理管线

```text
RAW / DNG
  |
  +-- 去马赛克前的 CFA 证据
  |     黑白电平 · 逐通道剪切 · 满阱余量 · 噪声置信度
  |
  +-- LibRaw：去马赛克 · 所选白平衡 · 相机色彩解释
  |
scene-linear Rec.2020
  |
  +-- 可选相机响应前馈                  （核心之外）
  +-- 由可靠场景统计与 RAW 证据编译 RenderPlan
  +-- 压缩核心：agx · gated · lum · neutral
  +-- 可选色彩风格 / LUT 滤镜           （核心之外）
  |
Oklab 色域适配 · sRGB/P3 编码 · 8-bit 抖动 · JPEG
```

高光重建可以让画面看起来连续，但传感器不会因此重新获得满阱余量。CFA 剪切证据在
去马赛克之前采集，并一直保留给渲染器，所以重建出来的像素无法定义全局白端点。

## 压缩核心

四个核心共用同一个曝光锚点和交付保护，因此互相 A/B 时被隔离的变量只有一个。

| 核心 | 作用 |
| --- | --- |
| `agx` | darktable 风格的全图 AgX，`smooth` 原色几何；正常成片的默认。 |
| `gated` | 同一份 AgX 候选，但由 RAW 证据逐像素决定混入多少色彩路径；更保守。 |
| `lum` | 同一条场景编译的 C1 toe/shoulder 只作用于亮度，RGB 比例保持；用来观察 AgX 色彩几何额外做了什么。 |
| `neutral` | 固定的通用 shoulder，完全不含 AgX；常规导出的对照，不是成片推荐。 |

`--agx-primaries` 预设（默认 `smooth`，另有 `base`、`punchy`、`muted`）只改变 AgX 的
inset/outset 几何——它们是比较参考，不是不同的曝光算法。

## 相机前馈（实验性）

我最在意的想法：让去马赛克**之前**从传感器取得的信息，去指导之后运行的色彩变换。
dngscan 已经在 CFA 剪切与满阱余量上严格实践了这一点——证据在去马赛克前采集，由
tone plan 和 gated 核心消费。而实验性的相机响应前馈本身——一个朝 ALEV 风格响应
靠拢的软色度窗口映射——运行在更晚的位置：去马赛克与相机色彩解释之后、AgX 之前的
scene-linear Rec.2020 域。

它的现状我直说：这不是严肃的标定。严肃的前馈设计需要可控光源、标准靶和光谱测量
设备，而且理想上要针对每一台实体相机做，而不是每一款型号——ARRI 自己发布 ALEXA
光谱响应时对五台相机取了平均，正是因为传感器叠层的干涉纹理逐台不同。我没有这些
设备，所以现在装载的是一个由公开曲线数字化和解析光谱构建的几何映射，误差报告与
逐材料置信度全部公开（`dngscan_assets/spectral/README.md`）。请把它当成一份邀请，
而不是一个结论。

## 风格与 LUT 槽位

公开版自带一个项目自制的色彩风格——`optic_warm_cyan`，暖肤色配偏冷的环境——因为
我自己就挺喜欢它。它是写在本仓库里的 AgX 后 Oklab 色度场，不是厂商 LUT。

LUT 滤镜适配器保留了三个有文档的槽位（Kodak 2383 印片模拟、RED IPP2、Sony
LC-709TypeA）：把合法获得的 `.cube` 放到 `dngscan_assets/vendor_luts/` 下的对应路径
（准确路径见 `dngscan/display_filter.py`），滤镜就会自动出现在 CLI 和 GUI 里；删掉
文件它就消失。什么创意 LUT 真正"适合"接在 AgX 这条 DRT 之后，我并不知道——这个
问题有意留白，供大家自由试验。**本仓库不分发任何厂商 LUT**；没有明确再分发许可时，
请不要在 issue 或 PR 里附带厂商 LUT 文件。

## 快速开始

需要 Python 3.10 或更新。

```bash
git clone https://github.com/Gen-416/dngscan.git
cd dngscan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m dngscan.gui
```

GUI 在 localhost 运行，完全离线。同一文件的解码与分析会缓存，预览走代理图，导出
始终回到全分辨率场景缓冲。合理的第一次使用：EV 0、默认 AgX 核心打开一张 RAW，
先看画面；想知道某个视觉差异来自哪里时，再在相同 EV 下切换核心对比。亮度参考按钮
（`--ev auto`）是一种主动选择的替代曝光读法，永远不会被静默启用。

### CLI 示例

```bash
# 默认全图 AgX，质量 100，4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# 同时输出六面板 RAW 报告
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# 相同 EV 下比较压缩核心
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg lum.jpg   --tone-core lum
python -m dngscan photo.dng --jpeg plain.jpg --tone-core neutral

# 高光重建 + Display P3
python -m dngscan photo.dng --jpeg photo_p3.jpg --highlight-mode reconstruct --output-gamut p3

# 主动应用亮度参考
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

完整参数见 `python -m dngscan --help`。

## 输出与诊断

SDR 输出为带确定性 TPDF 抖动的 8-bit JPEG（默认质量 100、4:4:4）。Display P3 会嵌入
ICC profile，找不到 profile 时宁可失败也不写未标记的 P3 数据。ISO gain-map HDR 路径
存在但仍属实验。`--scan` 输出六面板采集报告——SNR 对档数、分离的 R/G/B RAW 分布、
曝光与色域压力、空间剪切图；绘图曲线可能平滑，数值统计从不平滑。

## 参与

项目公开就是为了让人来玩这条管线、挑战它的假设。欢迎相机实测数据、更好的 RAW 证据
模型、基于真实场景的 AgX/DRT 对比，以及原创或明确可再分发的风格。请在代码与文档里
保持"实测证据 / 启发式策略 / 创意口味"三者边界清晰；不要提交测试 RAW 或未经许可的
第三方 LUT。

## 许可证与致谢

dngscan 采用 GPL-3.0-or-later，因为其 AgX 实现派生自 darktable 的 GPL 代码；光谱数据
来源与可选依赖见 [NOTICE.md](NOTICE.md)。这是一个独立实验：ARRI、ALEXA、ALEV、
darktable、Blender、Fujifilm、Sony、RED、Kodak、Resolve 等名称属于各自权利人，文中
引用仅用于来源与比较说明。
