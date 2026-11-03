# 更新记录

## 1.0.0 当前源码状态

- 已验证 CARLA_0.9.16 的 Town10HD/Opt（采集使用 Opt），其他版本和城镇暂未验证，保留资源指纹约束。
- 默认 semantic V4.2 和独立 XODR-only 两套几何方案；基础输出为 `lanegt_geometry_v1` 完整折线，默认不运行模型采样。
- 通用顶视输入不要求 nuCarla 来源；支持 source_frame_token、自包含位姿时省略 cases、可选语义展示图和 prepare_topdown 清单工具。旧字段和历史路径名保持兼容。
- 中心线支持 none/generate/provided，自动生成复用原版 XODR 几何、局部重叠去重和拓扑校验。BEV 可配置，检查覆盖和完整位姿。
- 审核、HTML补线、JSON应用和CAD DXF往返无需模型；MapTRv2 作为可选采样/导出/Dataset适配。
- 公开源码包含运行代码、界面、参数、配置示例、中文说明、许可及 `docs/images/` 中的少量文档示例图；原始数据、人工标注、运行产物、测试及开发归档不随源码分发。

## 兼容性说明

- 中心线世界缓存使用 `lanegt_centerline_world_v2`；不接受 CARLA waypoint v1 缓存，需重新生成，不能只修改 schema。
- 默认通用完整几何不依赖模型；MapTRv2 采样、导出与 Dataset 检查需显式启用。
- 接入其他城镇或 CARLA 版本时，需适配配套资源与采集配置并重新验证。
