# XODR-only 历史几何方案

默认流程使用通用完整几何 GT，无需 MapTRv2；`--sampler maptr`、`export-maptr` 和 `dataset-check` 才启用模型适配。配置与完整步骤以[通用 GT 指南](GENERIC_GT.md)为准。

项目提供两套独立入口：`extract` 使用 V4.2 semantic 主导方案；`xodr-only` 复用基于 XODR 的几何提取函数。两方案共用通用完整几何、审核、人工后处理及可选模型适配接口。XODR 指 OpenDRIVE 地图文件。

## 旧代码复用范围

| 输出 | XODR-only 的处理 |
|---|---|
| divider | 原版 roadMark 分段和几何；可行驶面向内缩 0.05 米后，线长至少 80% 位于内部才保留；再按旧版局部重叠算法去重、保留全部来源 |
| boundary | 原版可行驶条带构造、0.005 米精度网格、并集及内外环；小于 5 平方米的非横道关联孔洞按原规则处理；可选移除已审核的非物理封口边 |
| ped_crossing | 原版 XODR crosswalk 对象轮廓 |
| centerline | `none` / `generate` / `provided`，复用项目已有原版中心线模块 |

默认条带采样间隔 0.5 米、shoulder 宽度阈值 1.5 米。完整 roadMark 区间表示逻辑 divider，broken 标线不逐条绘制物理短划；双线 roadMark 复用单条车道边界曲线，默认不会生成两条独立黄线。不在没有 roadMark 来源的路口补造 divider。

复用模块放在 `src/xodr_only/code/xodrgt/`。车道标线和 divider 去重文件按原文件复制；条带、表面、横道等所需函数抽出后保持函数体不变。原文件摘要和函数 AST 摘要见 `config/xodr_only/provenance.json`；AST 摘要的 Python 版本同时记录，跨版本应在同一解释器中解析两份源码再比较。原版 XODR 解析器和中心线库直接导入现有模块，不复制第二份，不运行 semantic 观测或补线函数，也不依赖历史归档路径。

## 世界生成、通用运行与可选模型环境

世界生成单独使用 Shapely 2 的 `set_precision`（requirements-xodr.txt）；逐帧通用提取/审核使用 requirements.txt 的几何环境。MapTRv2 仅是额外的可选采样环境，不是运行基线的前提。环境按解释器分进程，**不要用下面的依赖覆盖现有 MapTRv2 环境**。

```bash
# 使用单独的 Python 3.10 环境
/path/to/xodr-python -m pip install -r requirements-xodr.txt
```

世界几何可单独生成，不需要帧数据、图像、CARLA Python API、服务器或 GPU：

```bash
/path/to/xodr-python tools/generate_xodr_world.py \
  --xodr /data/maps/town10hd_opt.xodr \
  --output /data/lanegt/xodr_world.json
```

当前工具按随项目提供的验证资源清单检查 XODR 指纹；该清单目前来自 Town10 验证环境。接入其他地图须适配资源与配置后重新验证。缓存包含三类世界几何、被拒绝 divider、表面/孔洞审计、去重来源、原版中心线及拓扑；schema 为 `lanegt_xodr_world_v1`。世界缓存不纳入公开源码。

## 配置与最小输入

已经配置 semantic 方案时可以直接共用 `config/paths.local.json`。XODR-only 几何生成不读取 `cases`、顶视 RGB、语义 ID 或深度；逐帧提取只需要帧清单、完整模型变换、世界缓存以及几何处理环境。

只部署基线时可准备配置 JSON：

```json
{
  "frame_manifest": "/data/input/frames.json",
  "runtime_python": "/path/to/geometry/python",
  "data_root": "/data/lanegt"
}
```

```bash
python tools/configure.py --xodr-only --from-json /data/config/xodr-paths.json
python run.py doctor --xodr-only --topdown-only
```

配置工具为未启用的输入填入不存在的占位路径，不创建或读取伪造数据。帧清单沿用[数据接口](INPUTS.md)的 `token`、`scene`、`frame_idx`、`weather`、`reference`、`transform`；`reference` 可以是稳定的占位标识，纯几何提取无需对应顶视目录。`image_paths` 可为空。

复用已有世界缓存提取：

```bash
python run.py xodr-only --limit 1 --topdown-only --centerline generate \
  --world /data/lanegt/xodr_world.json \
  --bev-range -15 -30 15 30 --output outputs/xodr1
```

也可一次完成世界生成和逐帧提取：

```bash
python run.py xodr-only --limit 1 --topdown-only --centerline generate \
  --geometry-python /path/to/xodr-python --output outputs/xodr1
```

省略 `--world` 时，生成器默认读取 `assets/capture/server_Town10HD.xodr`，也可用 `--xodr` 指定；生成解释器依次取 `--geometry-python`、可选配置项 `xodr_python`、当前几何解释器。后者不具备 Shapely 2 时明确报错。世界缓存已有时，不需要运行 Shapely 2 环境。

选帧支持 `--tokens`、`--selection` 和 `--limit`，规则与主方案一致，禁止隐式全量操作。默认中心线关闭；若进行四类对比，两方案显式使用同一 `--centerline generate` 设置。默认不采样即可生成可编辑通用图册；`--skip-sampler` 保留为兼容别名。

输出沿用 `frames/<token>/gt.json.gz`、`targets.json.gz`、可选 `actual_sampler_targets.npz` 和 `geometry/<reference>/` 接口；默认 GT schema 为 `lanegt_geometry_v1`；直接请求 MapTR 采样的兼容入口可保留 maptrv2_xodr_gt_v1，`scheme=xodr-only`，记录地图和世界摘要。完整位姿、BEV、boundary 分段及可选 fixed20/shift_v2 接口复用现有库；不使用旧脚本的仅 yaw 位姿或固定窗口导出。

## 可选地图几何修正

默认使用自动几何规则，不加载外部人工修正。需要应用已审核的地图几何修正时，可显式指定修正文件：

```bash
/path/to/xodr-python tools/generate_xodr_world.py \
  --xodr /data/maps/town10hd_opt.xodr \
  --lane-decisions /data/review/town10hd_lane_decisions.json \
  --boundary-decisions /data/review/town10hd_boundary_segment_decisions.json \
  --output /data/lanegt/xodr_world_reviewed.json
```

`lane-decisions` 包含 `xodr_sha256`，以及原版 `shoulder_overrides`、`lane_inclusion_overrides`、`hole_fill_overrides`；`boundary-decisions` 包含同一指纹和 `excluded_crosscaps`。世界生成按原版规则匹配坐标并应用，未匹配孔洞/封口会报错。文件可选，人工标注和证据图不在源码中分发。世界和逐帧结果记录是否应用及文件摘要，不能把带人工修正结果称为纯自动结果。中心线仍按既有 driving 车道规则，不自动补造缺失拓扑。

## 生成同帧对照

XODR-only 的原始几何提取不受相机覆盖限制；**生成图册时**必须补全匹配同一位姿的顶视 RGB、标定和元数据，并确保包含 BEV 安全边缘。六相机投影另需原图和各自标定。已有 semantic 输入可直接共用；图册渲染不靠语义图或深度决定 XODR 几何。

```bash
# 两次提取使用同一配置、选帧、相机模式、中心线模式及 BEV
python run.py xodr-only --selection selection.json --topdown-only --centerline generate \
  --world /data/lanegt/xodr_world.json --output outputs/xodr_selected
python run.py extract --selection selection.json --topdown-only --centerline generate \
  --output outputs/semantic_selected
python run.py review --source outputs/xodr_selected --output outputs/xodr_review
python run.py review --source outputs/semantic_selected --output outputs/semantic_review
python run.py compare --xodr outputs/xodr_selected --semantic outputs/semantic_selected \
  --output outputs/scheme_comparison
```

以上示例采用纯顶视；启用六相机时从两条提取命令同时去掉 --topdown-only，并配置匹配图片和标定。`compare` 先校验共有 token、完整变换、reference、相机路径、地图指纹、中心线模式及 BEV，全部通过后才创建输出；不跨位置或跨帧拼接。也可输入两份已渲染图册，默认比较交集 token，或用 `--tokens` 指定。

`outputs/scheme_comparison/gallery.html` 提供并排完整几何 BEV；原图、六相机投影和顶视叠加在各自 review 图册中。`comparison.json` 记录实例数、总长度及默认 0.20 米包络内的双向长度覆盖比例（`--tolerance-m` 可调）。这是**几何差异统计，不是 AP、召回率或精度**，两方案都不是独立的人工真值；实例数量还受几何断开及分段影响，不能据此认定数量越少越好。中心线和斑马线使用共同的 XODR 来源，不是独立方法对比。

## 差异与选择

| 比较项 | XODR-only | 当前 semantic 主导方案 |
|---|---|---|
| 数据准备 | 地图和位姿即可生成，成本低 | 需要匹配位姿的顶视 RGB、语义和深度 |
| 遮挡 | 世界几何不受树叶、车辆遮挡影响 | 去遮挡采集可减少影响，残留遮挡仍可能造成小断口 |
| 道路边缘 | 可行驶面并集，路口可能有尖角、细碎环、非物理封口，与渲染路缘不一致 | 从渲染道路/人行道交界提取，更直接贴合实际可见边缘 |
| divider | 受 roadMark 是否完整及表面内部判定影响，可能漏掉实际可见线，也可能保留地图中有而渲染不清楚的线 | 实际标线主导，能保留 XODR 缺失或匹配不明的可见线；双黄线合并、虚线平滑连接 |
| 连接可靠性 | 不凭图像修正地图几何；没有来源的路口不补 divider | XODR 只辅助否决歧义生成连接；仍需审核少量误连、漏连和停止线 |
| 保证边界 | 地图真值不等于相机渲染真值 | 更贴图像的几何来源不等于已逐帧获得人工批准 |

因此保留 XODR-only 作为低采集成本、无遮挡的地图基线和诊断参照；面向图像训练的默认方案继续采用 semantic 主导提取。优点应结合相同帧的道路转角、实际标线和人工审核说明，不从两幅 BEV 或差异比例推断模型训练精度提升。两方案均保留人工后处理入口。

目前仅在 CARLA 0.9.16 的 Town10HD/Opt 上完成验证；其他城镇和版本尚未验证。当前默认资源和采集配置对应这一验证环境，接入其他地图须先适配并验证，不能仅改名称或摘要。相机、BEV、提取、分段和导出参数的实际生效位置及修改影响见[参数索引](PARAMETERS.md)。
