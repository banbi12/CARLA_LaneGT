# 参数索引与修改影响

本文对应当前代码的实际生效位置，长度单位米，角度字段为度，图像尺寸为 `[宽,高]`。未列为命令行或 JSON 配置的值属于代码常量，不能仅编辑 cases 或 metadata 就改变实际采集。

已验证环境为 **CARLA_0.9.16 的 Town10**（资源名称 `Town10HD` / `Town10HD_Opt`，采集入口使用 `Town10HD_Opt`）。其他 CARLA 版本或城镇尚未验证；当前配套资源和默认采集入口来自上述验证环境，其他地图需要适配后验证。同版本同名地图也必须匹配 XODR 指纹及采集接口；不通过改摘要绕过差异。

“可改”表示代码存在该配置入口，不代表任意值已验收。建议保持默认、一次改一组，先小样本人工对照。**输入图像/标定变化需重采；纯提取阈值变化通常只需重新提取；界面变化通常只需重建图册。** 所有输出写新目录，实例 ID、GT 哈希或 BEV 变化后，旧补线/CAD context 不自动迁移。

## 地图、运行及可选导出

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| CARLA 版本 | 0.9.16 | config/resources.town10.json:carla_version | 声明已验证服务器/API环境 | 接入其他环境需适配后验证 | 其他版本未验证；版本号本身不代替地图指纹 | 换版本需重新验证地图、接口、采集和几何 |
| 地图 | Town10HD / Town10HD_Opt | config/resources.town10.json:validated_maps；src/capture/code/run_topdown.py:服务器路径 | 记录已验证地图；当前采集配置使用 Opt | 接入其他环境需适配后验证 | 平面、单 laneSection；指定 XODR和对象接口；非任意Town10构建 | 换城镇需适配、验证并重采/重提取 |
| 地图与资源指纹 | XODR 5d883b…；其他摘要见清单 | config/resources.town10.json:files；config/extraction/connection_prior.json、connection_prior_v41.json | 资源一致性 | 不可作为调参项 | 导入/提取/采集检查 SHA256；采集还比较 XODR 文本 | 资源发生变化必须重建关联先验、标注并重新验证；不能只改摘要 |
| 运行解释器/路径 | 部署时配置 | config/paths.local.json:runtime_python,topdown_root,frame_manifest,cases,data_root | 定位通用数据和几何环境 | 可改 | 输入应真实存在；输出目录保护；cases 提取可选、采集必需 | 只迁路径且内容不变无需重采；按新路径检查并必要时重建图册 |
| BEV 范围 | [-15,-30,15,30] | extract/check/xodr-only/prepare_topdown.py:--bev-range；semgt/bev.py:bounds | 控制裁剪区域 | 可改 | 有限且 min<max；semantic 整个地面 ROI 投影必须在安全边内；支持非对称 | 覆盖足够：重提取、图册、导出；不足：先重采；CAD上下文重建 |
| 中心线模式 | none | extract/xodr-only:--centerline | none/generate/provided | 可改 | provided需标签；generate需匹配XODR；未知监督不当四类负样本 | 不必重采；重提取/图册及模型导出 |
| 中心线世界采样间隔 | 0.5 | tools/generate_centerlines.py:--step-m | 原版车道几何细度 | 可改 | 代码允许0.05～2；只影响独立中心线生成，XODR-only世界仍固定0.5 | 重新生成缓存并重新提取；无需重采 |
| 采样器 | none | extract/xodr-only/postprocess:--sampler；run.py:export-maptr | 可选 MapTRv2 表示 | 可改 | none/maptr；maptr需独立环境；不改变基础完整几何 | 无需重采；按需新导出/图册 |
| MapTR 点数/变体 | 20 / 19×20×2 | semgt/sampling.py:actual_targets固定值 | 匹配原模型采样契约 | 需代码和适配器联动 | 数组形状严格检查；不直接改为其他点数冒充同契约 | 重新适配、导出、Dataset检查；不重采 |
| 通用实例数/MapTR query参考 | 通用不限128；MapTR检查128 | semgt/portable.py:finalize | 区分通用GT与模型容量 | 通用不需改；模型需联动 | 超过128不静默截断；页面提示模型容量 | 模型容量变化重导出/配置检查；不重采 |

## 顶视相机、同步与采集

`cases` 为环境配置中指定的 JSON 数组；下表 `cases[*]` 指其中每个采集参考。`capture_z` 为绝对世界高度，不是离车高度。K 和外参取传感器实测值，不允许为“通过检查”手工篡改。

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| 相机水平位置 | 逐参考测量值 | cases[*]:center_xy；capture_selective.py:capture | 设置相机世界 x/y | 可改 cases | 两个有限坐标；必须覆盖所需 BEV 且对应同一场景 | 重新采集并更新标定/摘要；重提取与图册 |
| 相机高度 | 已验证约车上60；实际用capture_z；缺失回退35 | cases[*]:capture_z；capture_selective.py:capture | 相机绝对世界z | 可改 cases，建议显式提供 | z>0；覆盖检查按实际高度/K；35是旧回退，不代表已验证最终高度 | 重采、更新实测标定和COMPLETE；重提取 |
| 相机偏航 | 逐参考 capture_yaw；缺省0 | cases[*]:capture_yaw；capture_selective.py:capture | 顶视画面的平面朝向 | 可改 cases | 角度为度，取实际记录；不改变帧BEV变换的测量含义 | 重采并重提取；不要旋转图像后沿用旧K/外参 |
| 相机俯仰/横滚 | pitch=-90；roll=0 | src/capture/code/capture_selective.py:capture中carla.Rotation | 垂直顶视 | 本版固定；需代码适配 | geometry.py:validate_meta 要求 t[2,2]≤-0.999、旋转正交；非普通斜视投影器 | 改倾角需算法验证及重采，不只改cases |
| 最终RGB/semantic/depth分辨率 | 1152×2048 | src/capture/code/capture_selective.py:最终sensor blueprint image_size_x/y | 覆盖与米/像素细度 | 需改采集代码，不是现成JSON选项 | 三路一致；image_size与数组一致；覆盖/显存/栅格算法需验证 | 必须重采；更新K、尺寸和摘要，再重提取 |
| 最终水平FOV | 36° | src/capture/code/capture_selective.py:最终blueprint fov | 视场与地面分辨率 | 需改采集代码 | 0<FOV<180为物理建议；当前无独立数值范围校验；以实测K/覆盖验收 | 重采、更新K、重提取 |
| capture_size / capture_fov_deg / capture_height_m | [1152,2048] / 36 / 约60 | cases[*]:对应字段；collection.py:计划摘要 | 记录期望值/计划说明 | 当前仅描述；不控制最终传感器 | 最终宽高FOV仍固定代码；capture_height_m不替代capture_z | 仅改字段不会改变图像；真正改相机须同步实现并重采 |
| 标定试采相机 | 1280×1280、FOV65°、z35 | capture_selective.py:pilot及首次blueprint | 去遮挡前后校准门槛 | 需代码联动，不建议调 | 后续投影遮罩和1280网格亦固定；最终GT不用该试采图 | 需重做校准及重采；不能只改一个常量 |
| 畸变/动态模糊 | lens_k=0,lens_kcube=0；RGB motion_blur_intensity=0 | capture_selective.py:blueprint属性 | 针孔/静态清晰标线 | 本版保持；需适配后改 | 仅属性存在时设置；输入投影不做去畸变 | 改成有畸变需去畸变/模型适配并重采验证 |
| 同步步长与sensor_tick | 0.05s / 0.05s | capture_selective.py:fixed_delta_seconds；两组blueprint:sensor_tick | 同步采集周期 | 需代码联动 | 三路同frame；时间差≤1e-6s；改变tick需验证队列、超时及共享帧等待 | 重采并检查同步证据 |
| 质量/天气 | Epic / ClearNoon | run_topdown.py:服务器命令；capture_selective.py:set_weather | 可见质量与标线观测条件 | 本版固定，需代码改动后验证 | 质量证据会检查Epic；不能单改质量标志；不同天气未形成质量保证 | 重采；需要小样本语义质量对照 |
| 去遮挡层 | C_more_layers；额外6层见文件 | config/capture/layer_variants.json:extra_unloaded_layers | 卸载确认遮挡层 | 可改但属实验配置 | Ground/Decals禁止卸载；Foliage由代码先卸载；地图对象清单需匹配 | 重采、校准前后对照；不改原图/GT假装已去遮挡 |
| 对象去遮挡清单 | 已匹配的外部资源 | assets/capture/selective_occluder_allowlist.json | 选择性隐藏确认对象 | 非通用调参，需审计后重建 | 对象名、位置及资源SHA校验；地图接口有依赖 | 重新验证资源和去遮挡并重采 |
| 显存监控 | 7400MB说明；实际触发7057MiB；0.1s轮询 | run_topdown.py:MemoryWatch；collection.py:计划摘要 | 尽早中止显存增长 | 需代码联动，保持默认 | 7057MiB约7399.8MB；是采样触发阈值，不保证瞬时硬封顶；改值同步计划和报告 | 无须单为阈值重提取；下一次采集生效，需监控验证 |
| RPC/streaming/secondary端口 | 2070/2071/2072 | run_topdown.py:base.PORT、服务器命令、childcmd | 隔离自有服务器 | 需代码联动 | 拒绝已有CARLA和占用端口；相关RPC探测/子进程需一致 | 新采集生效；已有GT无需重跑 |
| 同步证据容差 | 同整数frame ID；时间跨度≤1e-6s | semgt/input_contract.py:validate | 防止三路跨帧 | 固定契约，不建议放宽 | 新通用输入必须提供RGB/SEMANTIC/DEPTH；冲突拒绝 | 真实不同步应重新采集，而不是只放宽阈值 |

## semantic 提取配置（完整键索引）

下表 `S:key` = `config/extraction/semantic_policy.json:key`，默认还在 `src/extraction/code/semgt/policy.py:DEFAULT` 中定义。只修改被实际读取的 JSON 键即可改变对应实验参数。未知键会拒绝。除特别列出的硬校验外，当前 `checked()` **不做完整的类型、正值、有限性或概率区间校验**，表中“建议”不能误读为已实现硬校验。有效实验值必须人工复核，并以新输出重跑提取/图册。

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| border_px | 48 | S:border_px | 观测/连接/ROI安全边缘 | 需跨模块联动，不建议单改 | prepare/check覆盖默认48；boundary和small_gaps也固定48；此键不是全局边缘开关 | 无需重采；重提取、图册及可选模型导出 |
| ground_min_z | -0.08 | S:ground_min_z | divider地面z下限 | 可改配置（实验） | 此JSON影响divider路径；boundary_core地面筛选仍固定-0.08～0.40，不能单改实现整体高度迁移 | 无需重采；重提取、图册及可选模型导出 |
| ground_max_z | 0.4 | S:ground_max_z | divider地面z上限 | 可改配置（实验） | 此JSON影响divider路径；boundary_core地面筛选仍固定-0.08～0.40，不能单改实现整体高度迁移 | 无需重采；重提取、图册及可选模型导出 |
| minimum_stroke_length_m | 0.45 | S:minimum_stroke_length_m | 最短标线候选长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| maximum_thin_width_m | 0.24 | S:maximum_thin_width_m | 细标线最大宽度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| maximum_local_bend_deg | 55.0 | S:maximum_local_bend_deg | 局部弯曲判别阈值 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| compact_span_m | 8.0 | S:compact_span_m | 紧凑候选/分支跨度判别 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| grid_junctions | 6 | S:grid_junctions | 网格/符号分支候选阈值 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| curb_distance_m | 0.85 | S:curb_distance_m | 路缘邻近距离 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| curb_fraction | 0.7 | S:curb_fraction | 路缘关联比例 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| stripe_seed_radius_m | 0.12 | S:stripe_seed_radius_m | 斑马条纹种子膨胀半径 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_length_m | 1.0 | S:stripe_min_length_m | 条纹最短长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_max_length_m | 7.0 | S:stripe_max_length_m | 条纹最长长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_width_m | 0.24 | S:stripe_min_width_m | 条纹最小宽度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_max_width_m | 0.9 | S:stripe_max_width_m | 条纹最大宽度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_aspect | 2.4 | S:stripe_min_aspect | 条纹最小长宽比 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_fill | 0.7 | S:stripe_min_fill | 条纹最小填充率 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_count | 3 | S:stripe_min_count | 横道条纹最少数量 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_parallel_dot | 0.96 | S:stripe_parallel_dot | 条纹方向平行阈值 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_min_gap_m | 0.3 | S:stripe_min_gap_m | 条纹间距下限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_max_gap_m | 1.4 | S:stripe_max_gap_m | 条纹间距上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| stripe_longitudinal_offset_m | 0.5 | S:stripe_longitudinal_offset_m | 条纹纵向错位容许量 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出；这里只影响条纹证据/阻挡，最终ped_crossing仍来自XODR对象 |
| double_min_spacing_m | 0.08 | S:double_min_spacing_m | 双黄线间距下限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| double_max_spacing_m | 0.65 | S:double_max_spacing_m | 双黄线间距上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| double_max_width_variation_m | 0.1 | S:double_max_width_variation_m | 双线间距变化上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| double_min_overlap_m | 0.5 | S:double_min_overlap_m | 双线最少重叠长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_max_observed_run_m | 3.5 | S:dash_max_observed_run_m | 普通虚线短划最大观测长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_min_gap_m | 0.35 | S:dash_min_gap_m | 普通虚线最小断口 | 可改配置（实验） | 硬校验 0<min<max≤8 | 无需重采；重提取、图册及可选模型导出 |
| dash_max_gap_m | 8.0 | S:dash_max_gap_m | 普通虚线最大断口 | 可改配置（实验） | 硬校验 min<max≤8，且max≤straight_max | 无需重采；重提取、图册及可选模型导出 |
| dash_min_tangent_chord_dot | 0.7 | S:dash_min_tangent_chord_dot | 端部切向与连接弦对齐下限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_min_mutual_dot | 0.2 | S:dash_min_mutual_dot | 两端方向一致性下限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_max_curve_chord_ratio | 1.35 | S:dash_max_curve_chord_ratio | 补连曲线/弦长比上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_min_road_fraction | 0.98 | S:dash_min_road_fraction | 连接上道路支持比例下限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_max_unknown_length_m | 0.12 | S:dash_max_unknown_length_m | 连接上未知区域最大连续长度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| small_gap_max_m | 0.35 | S:small_gap_max_m | 固定小断口口径登记 | 本版不可改配置 | 硬校验必须等于0.35；实际修补函数仍写死0.35 | 若改代码另立实验，需要全链路回归；不重采 |
| endpoint_fragment_max_length_m | 0.35 | S:endpoint_fragment_max_length_m | 端部小残段长度上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| endpoint_fragment_contact_m | 0.25 | S:endpoint_fragment_contact_m | 残段接触距离 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| endpoint_fragment_extent_m | 0.6 | S:endpoint_fragment_extent_m | 残段几何延伸判定 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_extension_max_observed_run_m | 6.0 | S:dash_extension_max_observed_run_m | 扩展连接的短划长度上限 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_extension_tangent_dot | 0.96 | S:dash_extension_tangent_dot | 扩展连接切向一致性 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_extension_gap_relative_tolerance | 0.2 | S:dash_extension_gap_relative_tolerance | 扩展连接间距相对差 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| connection_guards_enabled | true | S:connection_guards_enabled | 启用新增连接保护规则 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| connection_use_xodr | true | S:connection_use_xodr | 使用同地图XODR作歧义补连辅助 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_straight_max_gap_m | 9.0 | S:dash_straight_max_gap_m | 有重复共线证据的长直线最大断口 | 可改配置（实验） | 硬校验 dash_max≤此值≤9 | 无需重采；重提取、图册及可选模型导出 |
| dash_straight_max_angle_deg | 5.0 | S:dash_straight_max_angle_deg | 长直线端部/弦角差上限 | 可改配置（实验） | 硬校验 0<角度≤10 | 无需重采；重提取、图册及可选模型导出 |
| dash_straight_max_lateral_m | 0.2 | S:dash_straight_max_lateral_m | 长直线横向错位上限 | 可改配置（实验） | 硬校验 0<横向量≤0.3 | 无需重采；重提取、图册及可选模型导出 |
| dash_straight_min_observed_runs | 3 | S:dash_straight_min_observed_runs | 长直线最少观测段 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_fragment_guard_min_gap_m | 1.0 | S:dash_fragment_guard_min_gap_m | 可疑残段长连接保护起点 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_fragment_parent_min_span_m | 8.0 | S:dash_fragment_parent_min_span_m | 识别大型分支父候选的跨度 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_fragment_parent_length_ratio | 4.0 | S:dash_fragment_parent_length_ratio | 分支父候选长度/跨度判别 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_min_gap_m | 3.0 | S:dash_xodr_min_gap_m | 歧义连接地图检查最小断口 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_uncertain_angle_deg | 15.0 | S:dash_xodr_uncertain_angle_deg | 启动地图检查的方向歧义角 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_endpoint_distance_m | 0.6 | S:dash_xodr_endpoint_distance_m | 端部到地图候选最大距离 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_endpoint_angle_deg | 25.0 | S:dash_xodr_endpoint_angle_deg | 端部到地图切向最大角差 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_endpoint_margin_m | 0.2 | S:dash_xodr_endpoint_margin_m | 地图匹配候选之间的区分余量 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_bridge_max_deviation_m | 1.25 | S:dash_xodr_bridge_max_deviation_m | 生成连接偏离地图路径阈值 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |
| dash_xodr_bad_run_m | 0.5 | S:dash_xodr_bad_run_m | 持续偏离地图的长度阈值 | 可改配置（实验） | 无完整数值硬校验；长度建议正数，成对阈值保持min≤max，比例/点积取合法范围 | 无需重采；重提取、图册及可选模型导出 |

### V4.2 B 新增参数

以下键只影响 semantic 提取。V4.2 B 的 `divider_base_*` 以 XODR V4.1 stitched base 为主体，semantic 观测只做补充；`connection_xodr_*` 是连接校验的高级参数，B 模式下长连接主要由 V4.1 base 负责。全部为实验配置，修改后需在新目录重新提取并重审；几何变化会使旧补线、审核记录和 CAD context 失效。

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| divider_base_mode | xodr_v41 | S:divider_base_mode | divider 主体：`xodr_v41` 用 V4.1 stitched base，`semantic` 保持纯观测 | 可改配置（实验） | 仅允许 `semantic`/`xodr_v41` | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_min_length_m | 0.35 | S:divider_base_min_length_m | base 短线过滤长度 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_min_supplement_m | 0.5 | S:divider_base_min_supplement_m | supplement 最短保留长度 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_coverage_m | 0.2 | S:divider_base_coverage_m | supplement 覆盖判定距离 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_duplicate_coverage | 0.9 | S:divider_base_duplicate_coverage | 覆盖达到该比例时丢弃 supplement | 可改配置（实验） | 无独立硬校验；建议 0–1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_supplement_coverage | 0.1 | S:divider_base_supplement_coverage | 覆盖低于该比例时整条保留 | 可改配置（实验） | 无独立硬校验；建议 0–1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_parallel_m | 0.35 | S:divider_base_parallel_m | 与 base 平行视为重复的距离 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_parallel_fraction | 0.8 | S:divider_base_parallel_fraction | 平行重复的重叠比例 | 可改配置（实验） | 无独立硬校验；建议 0–1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_double_yellow_m | 0.5 | S:divider_base_double_yellow_m | 双黄线重复距离 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_extension_m | 1.0 | S:divider_base_extension_m | base 端点延伸长度 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_smooth_enabled | true | S:divider_base_smooth_enabled | 启用 supplement→base 平滑连接 | 可改配置（实验） | 布尔值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_smooth_max_gap_m | 2.0 | S:divider_base_smooth_max_gap_m | 平滑连接最大 gap | 可改配置（实验） | 无独立硬校验；需大于 min | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_smooth_min_gap_m | 0.02 | S:divider_base_smooth_min_gap_m | 平滑连接最小 gap | 可改配置（实验） | 无独立硬校验；需小于 max | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_smooth_max_curve_ratio | 2.0 | S:divider_base_smooth_max_curve_ratio | 平滑曲线长度/弦长上限 | 可改配置（实验） | 无独立硬校验；建议 ≥1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_smooth_tangent_dot | 0.2 | S:divider_base_smooth_tangent_dot | 端部切向与连接弦对齐下限 | 可改配置（实验） | 无独立硬校验；建议 0–1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| divider_base_merge_endpoint_m | 0.1 | S:divider_base_merge_endpoint_m | supplement 合并到 base 的端点容差 | 可改配置（实验） | 无独立硬校验；建议正值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| boundary_smooth_enabled | true | S:boundary_smooth_enabled | 启用 boundary-only 平滑短断口 | 可改配置（实验） | 布尔值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| boundary_smooth_max_gap_m | 1.5 | S:boundary_smooth_max_gap_m | boundary 平滑最大 gap | 可改配置（实验） | 硬校验 0.35 < 值 ≤ 2.0 | 无需重采；重新提取、图册；旧人工记录需重审 |
| boundary_smooth_min_tangent_dot | 0.2 | S:boundary_smooth_min_tangent_dot | boundary 平滑切向对齐下限 | 可改配置（实验） | 硬校验 0–1 | 无需重采；重新提取、图册；旧人工记录需重审 |
| boundary_smooth_max_curve_ratio | 1.5 | S:boundary_smooth_max_curve_ratio | boundary 平滑曲线/弦长上限 | 可改配置（实验） | 硬校验 1–3 | 无需重采；重新提取、图册；旧人工记录需重审 |
| connection_xodr_required_gap_m | 6.0 | S:connection_xodr_required_gap_m | 超过该 gap 强制 XODR 路线校验 | 可改配置（实验） | 硬校验 0 ≤ 值 < dash_max_gap_m | 无需重采；重新提取、图册；旧人工记录需重审 |
| connection_xodr_route_geometry | true | S:connection_xodr_route_geometry | 同曲线端点用 V4.1 路径几何替代 Hermite 桥 | 可改配置（实验） | 布尔值 | 无需重采；重新提取、图册；旧人工记录需重审 |
| connection_xodr_route_max_length_factor | 2.0 | S:connection_xodr_route_max_length_factor | 生成桥长度上限系数 | 可改配置（实验） | 硬校验 ≥1 | 无需重采；重新提取、图册；旧人工记录需重审 |

## boundary 分段与固定修补

下表 `P:key` = `config/extraction/boundary_partition_policy.json:key`。分段改变实例身份，即使几何覆盖不变也可能使旧审核/补线不再适配。

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| feature_split | true | P:feature_split | 启用特征分段 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| max_length_m | null | P:max_length_m | 可选最大段长 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| sample_step_m | 0.25 | P:sample_step_m | 转角检测采样步长 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| tangent_window_m | 2.0 | P:tangent_window_m | 转角局部窗口 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| turn_threshold_deg | 25.0 | P:turn_threshold_deg | 转弯段阈值 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| helper_simplify_m | 0.03 | P:helper_simplify_m | 辅助折线简化容差 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| sharp_corner_deg | 35.0 | P:sharp_corner_deg | 尖角分段阈值 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| minimum_world_cut_separation_m | 0.5 | P:minimum_world_cut_separation_m | 相邻世界切点最小距离 | 可改配置（实验） | 无集中完整范围校验；步长/窗口/长度建议>0，角度建议0～180；后续校验保持原折线覆盖 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| minimum_local_fragment_m | 0.5 | P:minimum_local_fragment_m | 保留的历史描述字段（当前未读取） | 当前不生效 | partition.py与engine.py没有读取此键；实际裁剪长度另见0.05m规则 | 不重采；重提取和图册；ID与旧人工记录需重新核对 |
| policy sha256 | 见JSON | P:sha256；mapgt/common.py:digest | 参与子实例ID及来源 | 随参数联动更新 | 计算去除sha256字段后的dict摘要；当前加载不会自动重算，不能只改数值却沿用旧指纹 | 重提取、图册；旧ID不可自动迁移 |
| boundary地面z/边缘/简化 | (-0.08,0.40) /48px /0.04m | src/extraction/code/boundary_core.py:extract_boundary | 道路边缘观测筛选与栅格简化 | 代码常量，需实验适配 | 简化后Hausdorff≤0.040001；不随semantic_policy同名值全部改变 | 不重采通常可重提取；若地面数据不足须重采 |
| boundary栅格接缝 | ≤0.10m / 方向差≤25° | boundary_core.py:seam merge | 小栅格裂缝合并 | 代码常量，需回归 | 需位于观测域缓冲且线简单；与下述无角度小断口是两阶段 | 不重采；重提取/图册 |
| 小断口修补 | 0.015<gap≤0.35m；无角度拒绝 | src/extraction/code/small_gaps.py:fill_small_gaps | divider/boundary的小遮挡或栅格断口 | 本版固定；改代码另作实验 | 保留道路/人行道、斑马线、交叉、唯一端点等约束；不是无条件连接 | 不重采；重提取/图册 |
| 裁剪最短片段 | >0.05m | semgt/engine.py:clip_targets；semgt/centerlines.py:local | 过滤退化裁剪线 | 代码常量，需联动 | 两种中心线/三类几何路径保持一致；不是P:minimum_local_fragment_m | 不重采；重提取/图册 |

## XODR-only 世界生成、人工编辑与 CAD

| 参数名 | 当前值 | 文件:字段 | 作用 | 是否可改 | 校验限制 | 改后是否需要重新采集或重新跑 |
|---|---|---|---|---|---|---|
| shoulder_min_width_m | 1.5 | src/xodr_only/code/xodrgt/world.py:generate调用/parameters | 宽路肩纳入阈值 | 当前固定调用值；需改代码 | parameters只是结果记录，不是读入配置；旧函数保留；改变需对照验证 | 不重采；重新生成世界缓存、逐帧GT和图册 |
| surface_step_m | 0.5 | src/xodr_only/code/xodrgt/world.py:generate调用/parameters | 可行驶面条带采样 | 当前固定调用值；需改代码 | parameters只是结果记录，不是读入配置；旧函数保留；改变需对照验证 | 不重采；重新生成世界缓存、逐帧GT和图册 |
| surface_grid_m | 0.005 | src/xodr_only/code/xodrgt/world.py:generate调用/parameters | 几何并集精度网格 | 当前固定调用值；需改代码 | parameters只是结果记录，不是读入配置；旧函数保留；改变需对照验证 | 不重采；重新生成世界缓存、逐帧GT和图册 |
| divider_interior_margin_m | 0.05 | src/xodr_only/code/xodrgt/world.py:generate调用/parameters | 内缩表面过滤标线 | 当前固定调用值；需改代码 | parameters只是结果记录，不是读入配置；旧函数保留；改变需对照验证 | 不重采；重新生成世界缓存、逐帧GT和图册 |
| fill_unconnected_hole_max_area_m2 | 5.0 | src/xodr_only/code/xodrgt/world.py:generate调用/parameters | 小孔洞规则 | 当前固定调用值；需改代码 | parameters只是结果记录，不是读入配置；旧函数保留；改变需对照验证 | 不重采；重新生成世界缓存、逐帧GT和图册 |
| XODR divider去重 | distance0.015 / buffer0.03 / min_fragment0.05m | xodrgt/deduplicate_dividers.py:deduplicate_dividers默认参数 | 去除重复涂装并保留来源 | 改代码需回归 | 来源完整性有校验；当前CLI未暴露 | 重建世界缓存与GT；不重采 |
| CAD曲线展开容差 | 0.01m | web/editor/cad_core.js:TOL；CAD context:curve_tolerance_m | 曲线转折线误差目标 | 需前后端及context联动 | 改context字段不会独立改变解析器；原生CAD行为仍需单帧验收 | 不重采；重新导出CAD并导回新GT |
| CAD实体/点数量保护 | 10000实体 / 100000点 | web/editor/cad_core.js:MAX_ENTITIES,MAX_POINTS | 约束过大导入 | 代码常量，按性能验证 | 不得通过删除实体/来源字段绕过会话和几何校验 | 不重采；重新导入及几何检查 |
| 补线操作数/最短新增线 | 最多2000 / ≥0.01m | src/postprocessing/code/edit_model.py:replay | 限制补线和退化线 | 需与web/editor/edit_core.js联动 | 同类divider/boundary、有限BEV坐标、中心线只读及ID检查仍保留 | 不重采；重新应用补线、图册与可选采样 |

## 修改顺序

1. 先确定改的是相机/输入、BEV、提取阈值、分段还是模型表示，定位表中实际读取点。用 `collect-plan` 查看计划，但计划中的固定相机摘要不意味着 cases 的所有描述字段已接线。
2. 改相机后重新采集并保存实测K、外参、尺寸、同步与COMPLETE；对外部采集数据修改参数，同样需要采集器实现这些参数。不要编辑旧metadata去伪装新相机。
3. 改提取配置后在新目录跑少量样本、`geometry-check` 和人工图册；多源硬编码的参数先统一对应路径再验证，不在旧GT原地运行。
4. 完整几何确定后再做人工补线和可选模型导出。已有人工操作绑定实例/哈希/BEV；重提取后应重新核对，不能假定自动复用。

本文列出当前公开配置的全部 semantic 键及分段数值键；JSON中 version、name、approved_for_release、geometry_output 等标识/状态字段不是提取质量旋钮。未来参数接口变化时，应同时更新本索引、配置示例和实际校验逻辑。

## 其他地图或版本的接入检查

项目说明中的 Town10 表示目前已完成的验证环境。接入其他地图/版本属于尚未验证的适配工作，应逐项检查：

1. **地图几何和坐标。** 当前 XODR 处理链要求平面、单 laneSection，并使用现有 CARLA 世界坐标约定。更复杂几何需要实现和验证相应支持。
2. **世界资源。** 重新生成并审核对应 XODR 的横道轮廓、连接辅助及可选中心线；按真实资源更新清单，不能只重算摘要来假装旧资源已适配。
3. **采集配置。** 当前启动路径、地图名检查、校准参考、去遮挡层和对象清单对应已验证环境。更换地图需逐项适配，检查 CARLA API 与语义编号，并保留质量、同步和显存监控证据。
4. **完整流程。** 先用新数据小样本检查标定、BEV覆盖、完整几何及人工后处理；需要模型适配时另外检查其 Dataset 接口。
5. **验证声明。** 完成上述适配和验收后再扩展已验证环境列表。本版没有宣称其他城镇/版本已开箱可用。
