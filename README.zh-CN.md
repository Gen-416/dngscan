# dngscan

一个离线的小工具：读取 RAW，再用 AgX 把它压缩成 JPEG。AgX 实现来自 darktable 的
`agx` 模块。

[English](README.md) · [许可证](LICENSE) · [第三方声明](NOTICE.md)

dngscan 读取 RAW，测量传感器实际记录下的信号，在 scene-linear Rec.2020 中渲染，
再经由 AgX 压缩为 8-bit sRGB 或 Display P3 JPEG。它的职责到此为止：没有图库、图层、
蒙版与局部修饰。**它不是修图工具**——更准确的定位是一个信号处理工具：一个只关心
"如何用 AgX 压制 RAW"的显影器。

## 为什么做它

我对 darktable 的判断是：它本质上是一个信号与算法处理工具——或者说，一件面向信号的
玩具。这个词在这里不含贬义，指的是那种以理解和操纵信号为乐趣的仪器。它的
scene-referred 管线严谨而完整，但这份完整同时背负了通用编辑器的全部复杂度：
对"用 AgX 压缩一张 RAW"这个单一需求而言，其中大部分功能并无意义——
dngscan 因此存在。它把这一条路径从完整的编辑体系中取出，做成独立、可复现、刻意
简单的工具：LibRaw 解释、scene-linear Rec.2020，以及移植自 darktable GPL `agx`
模块的曲线构造与原色几何，仅此而已。

两个立场贯穿整个设计。

**其一，自动判断的正当性只能来自测量。** 数码化的光学信号是这个工具绝对依赖的数据
来源：黑白电平、逐通道 CFA 剪切、暗部可用范围、场景亮度分布——压缩曲线由这些测量值
编译而来。自动化在这里是对采集信号的尊重，而不是替使用者做审美决定。因此 EV 0 下
夜景保持黑暗；一盏已在传感器上剪切的灯，即使被高光重建补得平滑连续，也不具备重新
定义全图白点的资格。

**其二，成像路径必须保持可解释。** AgX 压缩管线本身是确定的；场景测量为它编译工作
参数，但口味永远不进入自动分析。所有表达意图的控制——曝光补偿、白平衡策略、相机
响应前馈、色彩风格与 LUT 滤镜——都位于 AgX 核心之外，以显式选项的形式存在，默认
关闭或中性。当画面发生变化时，变化的来源可以被指认：RAW 本身、DRT，或使用者的选择。

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

## 管线各级的选择

GUI 里出现的每个选项都对应管线中的一个真实环节，这里按顺序解释它们各自在做什么。

**去马赛克。** 全分辨率导出默认 `--demosaic auto`：Bayer 传感器按 DHT → DCB → AHD
的优先级选取当前构建可用的最佳算法；非 Bayer（如富士 X-Trans）保持 libraw 原生路径；
预览完全绕过插值，使用半尺寸超像素合并（2×2 直接并为一个像素），因此预览的纹理不能
用来评判插值质量。可手动指定 `dht / dcb / ahd / aahd / vng / ppg`。这里需要一个明确
的判断：本工具不做任何降噪，去马赛克因此是唯一的纹理杠杆。DHT 在低 ISO 的干净信号上
细节解析最好；但在高 ISO 重噪声文件上，细节激进的插值会把色度噪声放大成迷宫纹与
伪色——此时更平滑的 `vng`、`ppg`，或以伪色抑制见长的 `dcb`、`aahd`，往往给出更耐看
的结果。噪声重的夜景值得手动切一次算法对比。另外值得知道：libraw 本身还定义了更多
算法——LMMSE（专为重噪声场景设计的经典选择）、AMaZE、VCD、AFD 等，它们来自 GPL
demosaic pack，标准的 rawpy 轮子构建不包含；若你的 libraw 构建带有这些算法，把名字
加进 `DEMOSAIC_CHOICES` 一行即可暴露——选择逻辑本就会检查可用性并在缺失时回退。

**白平衡。** `camera` 使用机内 AsShot；`daylight` 使用 libraw 标定的日光乘子，提供
胶片式的整卷一致性——同一光源下每张配平相同，色偏作为拍摄现场的属性被保留下来。
无论选择哪种，AsShot 相对日光的偏离始终作为现场光源的证词出现在报告里。

**高光。** `clip / blend / reconstruct` 三种 libraw 策略：clip 硬剪切、blend 混合
过渡、reconstruct 尝试从未剪切通道重建。选择只影响观感的连续性，不影响证据：CFA
剪切状态在去马赛克前就已留存，重建像素永远不会反向定义曲线端点。

**压缩核心与 lum norm。** 四个核心见下节。选择 `lum` 时还有一个 norm 选项，决定
C1 曲线作用在哪种标量上：`y` 为 Rec.2020 亮度（色度学意义上的明度）；`max` 取最大
通道，饱和色的能量不会被低估，画面最平但饱和度保持最好；`power` 为 4 次幂加权的
折中。三者只改变"什么算亮"，RGB 比例始终保持。

**纯度补偿（punch）。** AgX Base 类成像天生偏灰——inset 前置去纯度，只有深趾部
内容通过逐通道扩张赚回纯度，因此高 ISO 夜景显得浓郁而日光宽 DR 场景发淡。punch
是针对这一点的场景门控色度补偿：明亮、低 ISO、宽窗口的场景自动获得 Oklab 色度
提升（灰轴、深影、高光、肤色带各自衰减），夜景与高 ISO 自动归零并完全短路。滑块
是自动值的倍率：1 为分析值，0 为关闭。

**输出与色域。** SDR 为 8-bit JPEG，默认质量 100、4:4:4 色度采样（可选 4:2:2 /
4:2:0），量化前施加确定性 TPDF 抖动以避免平滑渐变的断层。`--output-gamut srgb`
面向最大兼容；`p3` 嵌入 Display P3 ICC profile，找不到 profile 时宁可报错也不输出
未标记的宽色域数据。`--output-format ultrahdr` 输出 ISO gain-map HDR JPEG，
`--hdr-headroom` 以 EV 指定 gain map 的亮度上限；该路径目前仍属实验。

**曝光。** 锚点是与内容无关的常数：名义曝光的中灰映射到 scene-linear 0.18，`--ev`
在此之上做人工偏移。`--ev auto` 是显式的亮度参考——中位对齐 18% 灰，同时用高光
增长预算限制提升——它是一种主动选择的读法，永不静默启用。

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

## 相机响应前馈（实验性）

这里的"前馈"指在成像变换之前、于 scene-linear 域对相机色度学的系统性偏差做前置
校正，而不是在渲染之后叠加风格。它的依据是：一台相机的颜色由其光谱敏感度函数
（SSF）与滤镜栈透过率共同决定，这些是可测量、且在同一台机器上稳定复现的物理量。
第一层目标因此很直接——偏差既然已知，就在进入 DRT 之前用数字方法补偿。第二层是
它的推广：若两套响应都测得足够清楚，同一套算子可以把相机 A 的部分响应关系映射向
相机 B 或另一套 CMOS/滤镜栈。这一步有明确的物理边界：任何逐像素算子都无法恢复
传感器未曾记录的光谱信息——在 A 上构成同色异谱的两种材料，它们在 B 上本应呈现的
差异是原理上不可重建的。可行的只是按材料类别逼近响应关系，并为每一类给出误差与
置信度。

当前实现即按这一边界设计。对皮肤、植物、青色、中性、洋红五类材料，在合成响应
（SSF × 光源 × 反射谱）上拟合受约束的逐类 3×3 映射；运行时以 (R/G, B/G) 色度平面
上的软高斯窗口界定每个映射的适用域，窗口经 von Kries 传输随白平衡移动；逐类拟合
残差与跨类泄漏记录于标定报告，并以置信度权重折入生效强度。输入数据均为公开来源：
ALEV III SSF 数字化自 Leonhardt & Brendel（CIC23）——ARRI 对五台 ALEXA 实测取平均，
逐台平均正是因为传感器叠层的干涉纹理因个体而异，这也说明严肃的前馈标定应以每一台
实体相机为单位，而非每一款型号；Sigma fp 一侧使用 AMPAS rawtoaces-data 中由 Weta
Digital 实测的 Sony A7 III 整机 SSF（与 fp 同为 IMX410）；相机 → Rec.2020 的 profile
在 AMPAS 的 190 条训练反射谱上拟合。需要区分的是：CFA 剪切与满阱证据在去马赛克前
采集并前馈给 tone 计划与 gated 核心；色彩前馈本身则作用于去马赛克与相机色彩解释
之后、AgX 之前。

选择 ARRI 作为映射目标出于个人动机：我想接近 ARRI 画面里的那种肤色——由血色撑起
来的温润感，配合偏冷的 cyan 环境。我推测这部分源自 ALEV 叠层相对宽松的红光/近红外
通带；本项目的标定报告与该推测方向一致——五类材料中原生分歧最大的，正是依赖红边
响应的植物类。但必须说明：这是目标，不是成果。我没有可控光源、标准靶与光谱测量
设备，现有映射只是由公开曲线数字化与解析光谱构建的几何近似，其表现更接近一个克制
的颜色映射，离 ARRI 的肤色质感仍有距离。误差、置信度与数据出处见
`dngscan_assets/spectral/README.md`。

## 风格与 LUT 槽位

公开版自带一个项目自制的色彩风格——`optic_warm_cyan`，暖肤色配偏冷的环境——因为
我自己就挺喜欢它，是ARRI look的副产物。它是写在本仓库里的 AgX 后 Oklab 色度场，不是厂商 LUT。

LUT 滤镜适配器保留了三个有文档的槽位（Kodak 2383 印片模拟、RED IPP2、Sony
LC-709TypeA）：把合法获得的 `.cube` 放到 `dngscan_assets/vendor_luts/` 下的对应路径
（准确路径见 `dngscan/display_filter.py`），滤镜就会自动出现在 CLI 和 GUI 里；删掉
文件它就消失。什么LUT 真正"适合"接在 AgX 这条 DRT 之后，我并不知道——这个
问题留给大伙，希望能有好的新想法。**本仓库不分发任何厂商 LUT**；没有明确再分发许可时，
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

项目公开就是为了让人来玩AgX、推向新的边界。欢迎相机实测数据、更好的 RAW 证据
模型、基于真实场景的 AgX/DRT 对比，以及原创或明确可再分发的风格。请在代码与文档里
保持"实测证据 / 启发式策略 / 创意口味"三者边界清晰；不要提交测试 RAW 或未经许可的
第三方 LUT。

## 许可证与致谢

dngscan 采用 GPL-3.0-or-later，因为其 AgX 实现派生自 darktable 的 GPL 代码；光谱数据
来源与可选依赖见 [NOTICE.md](NOTICE.md)。AgX 本身由 Troy Sobotka 提出，在 Blender /
EaryChow 生态中发展成熟，本项目经由 darktable 的 `agx` 模块继承。这是一个独立实验：
ARRI、ALEXA、ALEV、darktable、Blender、Fujifilm、Sony、RED、Kodak、Resolve 等名称属于
各自权利人，文中引用仅用于来源与比较说明。
