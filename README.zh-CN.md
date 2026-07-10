# dngscan

**一个以 darktable AgX 为基础、本地离线运行的轻量 RAW 转 JPEG 实验室。**

[English](README.md) · [许可证](LICENSE) · [第三方声明](NOTICE.md)

`dngscan` 读取 RAW，分析采集信号，在 scene-linear Rec.2020 中完成渲染，再压缩为
8-bit sRGB 或 Display P3 JPEG。它刻意比 darktable 窄：没有图库、图层、蒙版、局部修饰，
也不试图成为完整的修图软件。

更准确地说，它是一个**信号处理工具、算法玩具和专注于 AgX 的 RAW 压缩器**。

## 为什么做这个工具

[darktable](https://github.com/darktable-org/darktable) 很强大，它的 scene-linear 管线也是
本项目的基础；但 darktable 的编辑体系很广，上手门槛也不低。我想要一个更小、更专注的工具，
只回答一个问题：

> 面对 RAW 记录下来的数码化光学信号，怎样用一条确定的 AgX 成像管线把它压缩成普通 JPEG，
> 同时不随意丢掉高光色彩、暗场意图和传感器证据？

AgX 的结构是 dngscan 的稳定中心。这里的“自动判断”不是替你修图，而是尊重数码化的光学信息：
先测量黑白电平、逐通道剪切、暗部可用范围、场景分布和输出色域压力，再用这些事实编译保守的曲线参数。

曝光补偿、白平衡、去马赛克、相机响应校正和创意色彩都在 AgX 核心之外。它们保持显式可选，
因为这些控制表达的是人的意图，而不是这张 RAW 唯一正确的答案。

## 它是什么，不是什么

| dngscan 是 | dngscan 不是 |
| --- | --- |
| 本地离线的 RAW 分析器与转换器 | Lightroom 或 darktable 的替代品 |
| 聚焦 darktable AgX 的轻量渲染器 | 局部修图、蒙版或磨皮工具 |
| RAW 证据驱动压缩的可重复实验 | 自动审美评分器 |
| 比较 tone 与色彩几何的算法玩具 | 完美相机色彩科学的宣称 |

在 `EV 0` 时，dngscan 保留拍摄时的相对亮度：夜景仍然应该是暗的。可选的**亮度参考**按钮
只是一个对照工具，它会尝试把全图中位亮度推向 18% 灰，同时受渲染后高光余量限制；它不会静默启用。

## 处理管线

```text
RAW / DNG
  |
  +-- 去马赛克前的 CFA 证据
  |     黑白电平 · 逐通道剪切 · 满阱余量 · 噪声置信度
  |
  +-- LibRaw
        去马赛克 · 所选白平衡 · 相机色彩解释
  |
scene-linear Rec.2020
  |
  +-- 可选相机响应前馈
  |
  +-- 由可靠场景 body/tail 与 RAW 证据编译 RenderPlan
  |
  +-- 所选压缩核心
  |     AgX · RAW 门控 AgX · 仅亮度 C1 对照 · 通用曲线对照
  |
  +-- 可选项目内置色彩风格
  |
Oklab 色域适配 · sRGB/P3 编码 · 8-bit 抖动 · JPEG
```

这里最重要的是区分**证据**与**观感**。高光重建可以让画面看起来连续，但不会让传感器重新获得
满阱余量。dngscan 会在去马赛克前保存 CFA 剪切证据，使重建出来的像素不能错误地定义全局白端点。

## 压缩核心

所有成片模式共用同一个曝光锚点和交付保护。

| GUI / CLI | 作用 | 预期画面 |
| --- | --- | --- |
| **AgX** / `agx` | 默认的 darktable 风格全图 AgX，使用 `smooth` 原色几何；RAW 分析编译可靠的 C1 端点。 | 最统一的向白路径，也是正常成片默认。 |
| **RAW 门控** / `gated` | 使用同一份 darktable `smooth` 候选结果，但由 RAW 证据决定每个像素混入多少 AgX 色彩路径。 | 当全图 AgX 改色过宽时，提供更保守的替代方案。 |
| **场景 C1，仅亮度** / `lum` | 使用与 AgX 相同的场景 C1 toe/shoulder，但保持 RGB 比例。 | 用来观察 AgX 色彩几何在亮度曲线之外增加了什么。 |
| **通用曲线** / `neutral` | 固定的非 AgX 亮度 shoulder，共用相同曝光锚点和交付色域适配。 | 常规导出参考，不是成片推荐。 |

可选的 AgX 几何只是比较参考，不是不同的曝光算法：

- `smooth`：darktable 几何，默认。
- `base`：Blender 风格的平衡参考。
- `punchy`：曲线后恢复更多颜色。
- `muted`：更柔和的 outward 色彩几何。

## RAW 证据如何参与判断

dngscan 只在 RAW 分析具有事实权威的地方使用自动判断：

- 逐通道黑白电平和剪切阈值来自元数据与实际 RAW 分布。
- CFA 剪切 mask 在白平衡与去马赛克前提取。
- 剪切或重建样本不会参与定义可靠场景 body 和 tone 端点。
- 暗部边界同时参考实测噪声和机型先验，不把所有暗码值都当成可恢复细节。
- 输出色域压力只影响色彩压缩，不反向改变曝光或 tone 端点。

这也是它与独立 tone-mapping 模块最根本的区别：渲染器仍然可以访问在普通编辑器后段通常已经丢失的
采集证据。

## 实验性相机前馈

我最喜欢的想法，是在去马赛克前读取传感器证据，再让它指导后面的色彩变换。dngscan 已经把这个
思路用于 CFA 剪切和满阱余量。当前实验性的**相机响应前馈**本身则运行在去马赛克和相机色彩解释之后、
AgX 之前的 scene-linear Rec.2020 域。

内置的肤色/材质前馈是一个刻意保持诚实的粗糙原型：它使用软色度窗口和受约束矩阵，输入来自公开测量、
论文曲线数字化和解析光谱模型。它**不是** ARRI 官方变换，也不是严格的 ALEXA/ALEV 仿真。

严肃的前馈标定需要可控光源、标准靶、光谱测量设备，而且理想情况下应针对每一台实体相机，而不只是
每一款型号。我目前缺少这些设备，所以现在的 ALEV-like 几何映射只是一个不严肃但可运行的实验，
也希望它能成为社区补充实测数据的起点。

校准输入与局限见
[`dngscan_assets/spectral/README.md`](dngscan_assets/spectral/README.md)。

## 风格与 LUT

公开版保留了一个项目自制的“暖肤冷背景”色度风格，因为我自己很喜欢它。它是 AgX 后的小型 Oklab
色度场，不是厂商 LUT。

代码也保留了本地 LUT 适配器，方便大家把自己合法获得的 LUT 接在 AgX 周围做实验。什么 LUT 真正适合
这条 DRT 没有唯一答案，这部分可以自由探索。仓库**不会分发 ARRI、Fujifilm、Sony、RED、
Resolve/Kodak 或其它厂商 LUT**。除非具有明确的再分发许可，请不要在 issue 或 PR 中上传厂商 LUT 文件。

## 快速开始

需要 Python 3.10 或更新版本。

```bash
git clone https://github.com/Gen-416/dngscan.git
cd dngscan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m dngscan.gui
```

GUI 在 localhost 打开并完全离线运行。同一文件会缓存 RAW 解码和分析，连续预览使用代理图；最终导出
始终回到全分辨率 scene buffer。

### 推荐 GUI 流程

1. 选择 RAW，第一次预览保持 `EV 0`。
2. 从 `AgX`、`darktable`、拍摄白平衡与“保持剪切”开始。
3. 想知道差异来自哪里时，在相同 EV 下比较 `RAW 门控`、`场景 C1` 和 `通用曲线`。
4. 先理解基线画面，再尝试前馈。
5. 只把**亮度参考**当作主动选择的另一种曝光读法。
6. 广泛分享用 sRGB；确定观看链支持色彩管理时再用 Display P3。

### CLI 示例

```bash
# 默认全图 AgX，质量 100，4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# 同时输出六面板 RAW 报告
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# 在同一 EV 下比较压缩核心
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg lum.jpg --tone-core lum
python -m dngscan photo.dng --jpeg generic.jpg --tone-core neutral

# 高光重建并输出 Display P3
python -m dngscan photo.dng --jpeg photo_p3.jpg \
  --highlight-mode reconstruct --output-gamut p3

# 主动应用全图亮度参考
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

完整参数见 `python -m dngscan --help`。

## 输出与诊断

- SDR 输出为带确定性 TPDF 抖动的 8-bit JPEG，默认质量 100、4:4:4 色度采样。
- Display P3 输出会嵌入 P3 ICC；找不到 profile 时直接失败，不写入未标记 P3。
- ISO gain-map HDR 仍是实验路径，目前不是推荐的兼容性交付目标。
- `--scan` 输出六面板采集报告：SNR 对档数、分离的 R/G/B RAW 分布、曝光与色域压力、空间剪切图。
  显示曲线可以平滑，数值统计始终使用未平滑 RAW 样本。

## 参与改进

项目公开的目的，就是让其他人可以玩这条管线，也可以挑战里面的假设。尤其欢迎：

- 相机实测数据和可复现的标定流程；
- 更好的 RAW 证据模型、高光重建和噪声置信度；
- 基于真实场景的 AgX/DRT 对比；
- GUI、跨平台打包和色彩管理输出测试；
- 原创或具有明确再分发许可的 look 与变换。

请在代码和文档中明确区分“实测证据、启发式策略、创意口味”。不要提交测试 RAW 或没有许可的第三方 LUT。

## 许可证与致谢

dngscan 使用 [GPL-3.0-or-later](LICENSE)，因为 AgX 实现派生自 darktable 的 GPL-3.0-or-later
代码。开源光谱数据与可选依赖见 [NOTICE.md](NOTICE.md)。

这是一个独立的社区实验。ARRI、ALEXA、ALEV、darktable、Blender、Fujifilm、Sony、RED、
Kodak、Resolve 等名称属于各自权利人；文中的引用只用于兼容性、来源或比较说明，不代表官方认可。
