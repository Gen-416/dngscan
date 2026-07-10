# dngscan

一个离线的小工具：读取 RAW，再用 AgX 把它压缩成 JPEG。AgX 实现来自 darktable 的
`agx` 模块。

[English](README.md) · [许可证](LICENSE) · [第三方声明](NOTICE.md)

dngscan 做的事情很简单：读取 RAW，看看传感器实际留下了什么，再用 AgX 把这些信号
装进 8-bit sRGB 或 Display P3 JPEG。它没有图库、图层、蒙版和局部修饰。**这不是修图
工具**，更像一个信号处理工具，或者干脆说，是一个拿来试验 RAW 和成像算法的玩具。

## 为什么做它

我很喜欢 darktable，尤其是它的 scene-referred 管线。但它确实需要学习，而且当我只是
想把一张 RAW 经由 AgX 处理出来时，其中大部分功能都用不上。dngscan 就是把我最关心的
这条路径单独拿出来：LibRaw 解释、scene-linear Rec.2020，再接上来自 darktable GPL
`agx` 模块的曲线构造与原色几何。它不是重新发明一套 AgX，也不准备和 darktable 竞争，
只是想把这件事做得简单、固定、方便反复试。

我做它时只有两个很朴素的原则。

**自动判断不等于自动修图。** 它只是认真对待已经数码化的光学信号。工具测量黑白电平、
逐通道 CFA 剪切、暗部可用范围和场景亮度分布，再用这些事实决定怎样压缩。EV 0 时夜景
依然是暗的；一盏已经剪切的灯，也不能因为高光重建把它补得平滑，就重新定义整张图的白点。

**AgX 这条路应该让人看得懂。** 场景测量可以决定它的工作参数，但口味不应该偷偷混进
自动分析。曝光、白平衡、细节选择、相机前馈、色彩风格和 LUT 都放在 AgX 核心之外，
作为看得见的选项。这样一张图发生变化时，至少能知道它来自 RAW、DRT，还是我后来做的选择。

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

## 我说的“相机前馈”是什么（实验性）

这里的前馈不是再加一层风格滤镜。第一层意思很实际：如果知道一台相机的 CMOS 和滤镜栈
会稳定地产生什么偏差，就在进入 DRT 之前用数字方法补偿它。再往前走一步，如果两套响应
测得足够清楚，同一个算子也可以把一台相机的部分响应关系映射到另一台相机或另一套
CMOS/滤镜栈上。它不可能找回传感器从未记录的光谱信息，但或许能接近另一台相机的一些
颜色关系和质感。

现在这个实验从 Sigma fp 出发。我原本想尝试的，是接近我在 ARRI 画面里喜欢的那种肤色：
皮肤里带一点由血色撑起来的温润感，同时用偏冷的 cyan 环境去衬托。我猜这和 ARRI 的
传感器以及相对宽松的红光/近红外滤镜栈有一定关系。这是目标，不是成果。现在的结果还不太
尽如人意，更像一个克制的几何颜色映射，离我心里那种 ARRI 肤色还有距离。

dngscan 确实会在去马赛克前读取 CFA 剪切和满阱余量，并把这些证据带进后面的渲染；但
颜色前馈本身目前运行在去马赛克和相机色彩解释之后、AgX 之前的 scene-linear Rec.2020
域。严肃版本需要可控光源、标准靶和光谱测量，而且理想上应针对每一台实体相机，而不只是
每一款型号。我没有这些设备。现在提供的只是由公开曲线数字化和解析光谱搭出来的粗略
ALEV-like 映射，误差和置信度记录在 `dngscan_assets/spectral/README.md`。它是一个起点，
不是 ARRI 色彩科学的宣称。

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
来源与可选依赖见 [NOTICE.md](NOTICE.md)。AgX 本身由 Troy Sobotka 提出，在 Blender /
EaryChow 生态中发展成熟，本项目经由 darktable 的 `agx` 模块继承。这是一个独立实验：
ARRI、ALEXA、ALEV、darktable、Blender、Fujifilm、Sony、RED、Kodak、Resolve 等名称属于
各自权利人，文中引用仅用于来源与比较说明。
