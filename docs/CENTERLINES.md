# 可选中心线：原版 XODR 处理链

默认流程使用通用完整几何 GT，无需 MapTRv2；`--sampler maptr`、`export-maptr` 和 `dataset-check` 才启用模型适配。配置与完整步骤以[通用 GT 指南](GENERIC_GT.md)为准。

自动生成采用原版 XODR 解析、车道边界中线、局部重叠去重和拓扑校验流程。已迁入项目自身模块，不再调用 CARLA API，不连接服务器，也不需要 GPU。

| extract 参数（check 仅预检查） | 行为 | 需要已有中心线文件 |
|---|---|---|
| `--centerline none` | 默认关闭，中心线数组为空 | 否 |
| `--centerline generate` | 从匹配 XODR 按原版处理链生成、变换到当前模型坐标并裁剪 | 否 |
| `--centerline provided` | 导入 `centerline_labels`（兼容 native_labels）中的逐帧中心线 | 是 |

## 随提取生成

```bash
python run.py extract --limit 1 --topdown-only \
  --centerline generate --bev-range -16 -31 16 31 \
  --output outputs/gt_with_centerline
```

生成器使用 `runtime_python` 指定的 CPU 几何环境，只依赖 Python、NumPy、Shapely 等项目依赖。`carla_python` 仅用于顶视图重新采集。

## 原版处理步骤

1. 用原版 XODR 解析器重建参考线、laneOffset、分段车道宽度和内外边界，按相邻边界中点计算中心线。仅选择 driving 车道，正 lane_id 按 s 递减、负 lane_id 按 s 递增保留行驶方向。
2. 按原版规则移除局部共享路段，保留未重叠片段；每个输出保留全部关联原始车道的 `source_refs`，不是只检查整条曲线是否相同。
3. 从 road link、lane link 和 junction laneLink 构建原始有向图，检查端点和方向；缺失或不一致的连接保留 excluded/review 状态，不臆造桥接，也不自动加入非 driving 的历史待审核车道。
4. 核对来源完整性、0.06 米包络下原始几何覆盖、0.05 米包络下输出重复、路口孤立车道及 accepted 拓扑的端点间隙。
5. 保留世界中心线和原始图，逐帧使用完整位姿变换，再按请求 BEV 范围裁剪。几何去重不等于把有向拓扑合并成一条导航路线。

迁移实现位于 `semgt/legacy_xodr.py`、`legacy_centerlines.py` 和 `legacy_centerline_pipeline.py`，源文件指纹与迁移说明见 `config/extraction/legacy_centerline_provenance.json`。生成/去重/拓扑函数体保持原逻辑；移除了历史 IO、固定范围和渲染依赖，仅做 NumPy 1.x 积分 API 兼容与坐标说明修正。

## 独立生成和缓存复用

```bash
python run.py centerlines --step-m 0.5 --output /data/lanegt/centerlines_world.json
python run.py extract --limit 1 --topdown-only --centerline generate \
  --centerline-world /data/lanegt/centerlines_world.json \
  --output outputs/gt_from_centerline_cache
```

也可以在几何环境中直接执行 `tools/generate_centerlines.py`。`--xodr` 可以显式指定文件，但须匹配当前 Town10 指纹；`--step-m` 接受 0.05～2 米，默认 0.5 米。输出文件必须不存在。调整采样间隔后须重新检查质量，不能假定与默认历史结果相同。

世界文件 schema 为 `lanegt_centerline_world_v2`，generator 为 `legacy_xodr_lane_geometry_v1`，包含去重后的 `features`、`raw_centerlines`、去重统计、拓扑、校验和未自动选入车道。原临时 CARLA 采样实现的 v1 缓存会明确拒绝，必须重新生成，不能只改 schema 字段复用。

## 验证与边界

匹配 Town10 的默认生成结果为 168 条原始车道、170 条去重几何，移除约 357.48 米局部重复长度，保留全部来源；拓扑有 200 条 accepted 连接，另有 81 条 excluded 记录。原始世界点和来源与历史文件逐值一致，原版去重重算一致。

67 帧、895 个中心线实例的来源和数量一致，完整 XYZ 最大差异为约 4.44×10⁻¹⁶ 米，实际 fixed20/shift_v2 和类别数组逐值一致。世界几何摘要 ID 不保证跨历史运行字节一致；验证记录保存在开发证据中，不随源码分发。不得自动套用旧图册补线文件。

provided 在默认范围下沿用完整几何与来源；通用输出仍将模型采样 points 置为 null，不保证所有附加字段字节不变；变更范围仅裁剪已有几何，无法补出旧输入在扩大区域缺失的中心线。页面与 CAD 中中心线仍只读。none 表示未提供中心线监督；只训练三类时应同步配置模型与数据集类别，不能将未知中心线当成四类模型的负样本。

已验证地图范围与[参数索引](PARAMETERS.md)一致；离线中心线生成不要求六相机、cases 或顶视图，但逐帧裁剪需要完整 BEV 变换，生成 semantic 图册仍需匹配顶视参考。
