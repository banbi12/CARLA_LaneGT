# 更新记录

## 1.1.2（2026-11-06）

- 移除损坏的 `src/postprocessing/project.json` 软链接；该文件是可选的本地覆盖，不随仓库分发。
- `.gitignore` 忽略 `src/postprocessing/project.json`；缺失时后处理使用 `config/paths.local.json` 默认值。
- 不改变算法、数据格式、已生成数据集或人工补线格式。

## 1.1.1（2026-11-05）

- 文档清理：移除未采用的连接路径实验介绍；V4.2 B 为最终 semantic 方案。
- `compare` 工具只接受 V4.2 B semantic 输出。
- 不改变算法、数据格式、已生成数据集或人工补线格式。

## 1.1.0（2026-11-05）

本版本将 XODR-only 升级到 V4.1，并将默认 semantic 方案升级到 V4.2 B。

- XODR-only V4.1：新增被拒 divider 恢复、XODR 拓扑连接、同 road/lane 局部连接和 ≤0.5m 几何回退；全量 3000 帧通过，divider 20,116、实例 126,370，`geometry-check` 通过。
- semantic V4.2 B：divider 使用 XODR V4.1 stitched base + semantic supplement；新增 0.20m 覆盖去重、0.35m 平行/双黄线抑制、≤2m Hermite 平滑接入、connected supplement 合并和 boundary ≤1.5m 平滑修补；全量 3000 帧 79,299 实例，实际采样 3000 帧，容量超限 0。
- 页面补线、补线应用后 GT 重生成、CAD 往返和可选 MapTRv2 采样沿用；结果仍需人工审核，不自动批准训练。
- 文档与工具：补充 V4.2 B 参数索引、V4.1 prior 生成说明；`compare` 工具接受 V4.2 B 输出。
- 软件版本升至 `1.1.0`。

## 1.0.0 当前源码状态

- 已验证 CARLA_0.9.16 的 Town10HD/Opt（采集使用 Opt），其他版本和城镇暂未验证，保留资源指纹约束。
- 默认 semantic V4.2 和独立 XODR-only 两套几何方案；基础输出为 `lanegt_geometry_v1` 完整折线，默认不运行模型采样。
- 通用顶视输入不要求 nuCarla 来源；支持 source_frame_token、自包含位姿时省略 cases、可选语义展示图和 prepare_topdown 清单工具。旧字段和历史路径名保持兼容。
- 中心线支持 none/generate/provided，自动生成复用原版 XODR 几何、局部重叠去重和拓扑校验。BEV 可配置，检查覆盖和完整位姿。
- 审核、HTML补线、JSON应用和CAD DXF往返无需模型；MapTRv2 作为可选采样/导出/Dataset适配。
- 公开源码包含运行代码、界面、参数、配置示例、中文说明、许可及 `docs/images/` 中的少量文档示例图；原始数据、人工标注、运行产物、测试及开发归档不随源码分发。

## XODR-only divider 连接实验（2026-11-04）

- XODR-only 世界生成在 `deduplicate_dividers` 后新增 `stitch_dividers`：同线型/同颜色、切向连续、可行驶面支持且不穿越第三条线的端点进行受约束拼接。
- broken 最大 9m，solid/solid-solid 最大 2m；合并保留 `source_refs` 和 `stitch_components`。
- 世界缓存版本升至 `xodr_only_legacy_v2_stitched`；旧 v1 缓存必须重新生成。
- 本轮只在 scene-0079/0080 上验证，默认 semantic V4.2 尚未接入该逻辑。

## XODR-only v3：拒绝线段恢复（2026-11-04）

- 新增 `recover_rejected_dividers`：对被 80% surface 规则整段拒绝的 divider，用 `surface.buffer(-0.01)` 裁剪，保留 ≥0.5m 的有效部分。
- 恢复来源保留 `original_interior_fraction`、`recovered_from_rejected` 和 `recovered_length_m`。
- 保留 v2 的同线型端点 stitch；世界缓存版本升至 `xodr_only_legacy_v3_recovered_stitched`。
- 旧 v1/v2 世界缓存必须重新生成。默认 semantic V4.2 尚未接入。

## XODR-only v4：拓扑连接（2026-11-04）

- 新增 `xodr_topology.py`：解析 road predecessor/successor、lane predecessor/successor、junction connection 和 laneLink。
- `stitch_dividers` 在 v4 要求端点具有 XODR 拓扑关系；几何切向、横向、surface 和第三条线只做二次校验。
- 支持 road link、junction connection 和反向 junction laneLink；合并记录写入 `stitch_topology`。
- 世界缓存版本升至 `xodr_only_legacy_v4_topology_stitched`；旧 v1/v2/v3 缓存必须重新生成。
- 100 帧虚线+交叉口选择集上，v4 divider 数量显著少于 v3，但总长度基本保持；仍需人工检查是否过度合线。

## XODR-only v4.1：拓扑 + 局部连接（2026-11-04）

- 保留 v4 的 XODR road/lane/junction 拓扑连接。
- 增加同 road/同 lane 的局部 s 连续连接，修复 v4 丢失的 7m dashed 断口。
- 增加 ≤0.5m 极小 gap 的几何回退，修复部分跨 road 的 0.1–0.17m 断口。
- 连接按 evidence 分级：`xodr_topology`、`same_road_local`、`small_gap_geometric`。
- 世界缓存版本升至 `xodr_only_legacy_v41_topology_local_stitched`；旧 v1–v4 缓存必须重新生成。
- 100 帧 v3/v4.1 双向 0.20m 覆盖均为 100%；divider 数量少是合并链变长，不是几何丢失。

## semantic V4.2 B：XODR V4.1 base + semantic supplement（2026-11-05）

- 新增 `divider_base_mode=xodr_v41`：divider 以 XODR-only V4.1 的 63 条 stitched chain 为几何主体，semantic 观测线只补充 base 没有的线。
- 新增 `divider_base.py`：base 短线过滤、0.20m 覆盖去重、0.35m 平行重复抑制、双黄线重复抑制和 base 端点延伸保留；两条 base 线之间的 semantic 中段桥会被丢弃。
- semantic 长连接在 B 模式下限制为 ≤2m；base 的连续性由 V4.1 拓扑拼接负责。
- 新增 supplement 到 base 的短平滑连接：端点距离 ≤2m 时用 Hermite 曲线接入最近的 base 线，最小 gap 0.02m，曲线长度不超过 gap 的 2 倍；记录 `smooth_connections`。
- 新增 connected supplement 合并：只有一个平滑连接、且接在 base 端点的 supplement 与 base 合并为一个 divider feature，再进入 `assemble`/MapTRv2 采样；避免同一视觉线被分成两个 20 点目标。
- boundary 在原有 0.35m no-angle 修补后新增 boundary-only 平滑修补：最大 gap 1.5m，要求切向对齐和曲线/弦长比 ≤1.5，用于缓解俯视图中信号灯造成的短断口；divider 路径不变。200 帧累计 76 处 boundary 平滑连接，最大 gap 0.946m，boundary 985→901；divider 200/200 帧 SHA256 一致。
- 200 帧检查（scene-0079 全部 40 帧）：B divider 1,780，V4.2 1,475，XODR V4.1 1,390；B/V4.2 覆盖率 97.56%，B/V4.1 94.86%；`geometry-check` 通过。
- 全量 3000 帧完成：divider 20,149（19,721 base/merged + 428 independent supplement），boundary 13,810，总实例 79,299；target 合并将 2,639 条 supplement 并入 base；实际采样 3000 帧，容量超限 0，`geometry-check` 通过；六相机/BEV 全量图册已生成。
- 版本升至 `semantic_v4_2_b_xodr_v41_base`。

## 兼容性说明

- 中心线世界缓存使用 `lanegt_centerline_world_v2`；不接受 CARLA waypoint v1 缓存，需重新生成，不能只修改 schema。
- 默认通用完整几何不依赖模型；MapTRv2 采样、导出与 Dataset 检查需显式启用。
- 接入其他城镇或 CARLA 版本时，需适配配套资源与采集配置并重新验证。
