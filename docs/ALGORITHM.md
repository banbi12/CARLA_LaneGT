# GT 提取口径

默认 `extract` 入口保持 V4.2 B 提取规则（XODR-only V4.1 base + semantic 补充）。四类输出定义如下：

| 类别 | 提取口径 |
|---|---|
| `divider` | XODR-only V4.1 的 stitched divider 为几何主体；semantic 观测只补充 base 没有的线，抑制双黄线/平行重复和 base 线之间的中段桥 |
| `boundary` | 观测到的道路/人行道交界，保留完整几何后修补小断口 |
| `ped_crossing` | 使用同哈希 XODR 的斑马线对象轮廓 |
| `centerline` | 可选：关闭、从匹配 XODR 离线生成，或导入已有中心线 |

## semantic V4.2 B divider base

`divider_base_mode=xodr_v41` 时，base 来自 XODR-only V4.1 的 63 条 stitched divider。semantic 特征按 0.20m 覆盖去重：覆盖达到 90% 的线丢弃；10% 以下的线整条保留为补充；部分覆盖只保留 semantic 线两端的延伸段，位于两条 base 线之间的中段桥丢弃。与 base 平行且距离 ≤0.35m 的 semantic 线视为重复；双黄线中曲线在 base 黄色线 0.50m 内时丢弃。B 模式下 semantic 长连接限制为 ≤2m，连续性由 V4.1 base 负责。补充线端点距离 base ≤2m 时，用 Hermite 短曲线接入最近 base 线，避免补充线突然截断；连接长度不超过 gap 的 2 倍，并记录 `smooth_connections`。 只有一个平滑连接且接在 base 端点的 supplement 会与 base 合并成一个 feature，再生成 MapTRv2 target；其余 supplement 仍为独立 target。

## 小断点与采样

0.35 米小断点修补保持不按角度拒绝的口径。boundary 额外执行一次 ≤1.5m 的平滑修补：要求两端切向与弦向对齐（min dot ≥0.20）、曲线/弦长比 ≤1.5，并使用 Hermite 曲线；用于缓解俯视图中信号灯造成的短断口。divider 不进入这次额外修补。停止线语义、少量断口和源几何与渲染差异交由人工审核。完整几何始终保留；只有请求模型采样时才另保留 fixed20 与 shift_v2 最坏变体，不在不同 GT 版本之间按误差择优。

参数位于 `config/extraction/semantic_policy.json`，范围与验证边界见[已知限制](../KNOWN_ISSUES.md)。

自动中心线的生成与去重遵循原版流程，见[中心线处理链](CENTERLINES.md)；不再使用临时 CARLA waypoint 采样器。

独立 `xodr-only` 入口复用原版非 semantic 几何函数；不修改上述规则。两方案的几何来源、适用场景与对照方法见 [XODR-only 与方法对比](XODR_ONLY.md)。

目前仅在 CARLA 0.9.16 的 Town10HD/Opt 上完成验证；其他城镇和版本尚未验证。当前默认资源和采集配置对应这一验证环境，接入其他地图须先适配并验证，不能仅改名称或摘要。相机、BEV、提取、分段和导出参数的实际生效位置及修改影响见[参数索引](PARAMETERS.md)。
