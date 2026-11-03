# 通用 GT 与可选模型适配

默认流程不需要 MapTRv2、Torch、OpenMMLab 或模型权重。这里的“通用”指基础几何表示与采集来源；地图验证目前只有 CARLA 0.9.16 / Town10HD/Opt，相机几何假设和配套资源检查仍须满足。XODR-only 与 semantic 的几何来源和选择建议见[XODR-only 与方法对比](XODR_ONLY.md)。

## 环境与配置

在独立几何 Python 环境安装 `requirements.txt`。配置必须提供 `frame_manifest`、`data_root`，semantic 另需 `topdown_root`，自包含位姿时 `cases` 可省略；六相机、中心线和地图资源按所用功能准备。可选 `runtime_python` 指定几何解释器，省略时取配置工具当前解释器。默认不要求 `model_root` 或 `maptr_python`。

```json
{
  "frame_manifest": "/data/input/frames.json",
  "topdown_root": "/data/input/topdown_cases",
  "data_root": "/data/lanegt",
  "runtime_python": "/path/to/geometry/python"
}
```

```bash
python tools/configure.py --from-json /data/config/paths.json
python tools/import_resources.py --from-directory /data/town10-resources
python run.py doctor --topdown-only
python run.py extract --limit 1 --topdown-only --centerline generate --output outputs/generic1
python run.py geometry-check --root outputs/generic1
python run.py review --source outputs/generic1 --output outputs/review1
```

XODR-only 同样默认不采样。其世界生成另需独立 Shapely 2 环境；有世界缓存后不必调用该环境，见 [XODR-only](XODR_ONLY.md)。模型独立并不构成其他城镇、版本或任意图像输入的验收结论；现有地图指纹、标定、完整位姿和输入要求继续生效。

## 通用标注契约

`frames/<token>/gt.json.gz` 的通用 schema 为 `lanegt_geometry_v1`，使用米制、模型局部 x 右/y 前/z 上坐标。包含 `token`、四类 `classes`、每类 `counts`、`BEV_range_m`、完整几何和来源；`geometry_schema`、`units`、`coordinate_convention`、`class_order` 显式声明约定。

每个实例的 `id`、`parent_id`、`render_xyz`（N×3）、`render_points`（对应 N×2）和 `source` 是基础标注。点数可变，点序保留。`points=null` 表示没有请求模型采样，不表示没有几何。默认 `sampling_backend=none`、`actual_sampler_applied=false`，不生成采样 NPZ，也不以 128 个 query 限制通用 GT 实例数。

`targets.json.gz` 保留实例顺序和对应完整 `full`/`full_xyz`。三类任务采用 divider/ped_crossing/boundary，四类任务另启用 centerline；关闭中心线表示未提供其监督，下游应同步配置类别。双黄线合并、虚线逻辑连接、道路边缘、斑马线轮廓和中心线方向等标注口径仍需与目标任务一致，不能只按类别名称判断兼容性。

`geometry-check` 只读验证有限坐标、XY/XYZ 对应、BEV 范围、类别数量及 GT/targets 实例绑定；不导入模型，不代表语义质量或人工验收。

## 审核与人工处理

审核页默认只显示完整几何。未采样时隐藏采样图和 NPZ 下载，禁用 fixed20/shift_v2 选项；不生成伪造的采样数据。页面审核、两点补线、JSON 导出、应用修改、CAD DXF 导出导回均可在通用模式运行。

```bash
python run.py postprocess --source outputs/review1 \
  --patch /data/exports/geometry_edits.json --output /data/lanegt/manual1
python run.py geometry-check --root /data/lanegt/manual1
```

补线后重新保存完整几何并生成新图册，默认不请求模型采样。原始输入和旧审核记录不覆盖。已有采样图册仍可打开；旧补线/CAD schema 名称为兼容保留，不代表运行需要 MapTR。浏览器导出的修改后完整 GT 也清除过期模型点集。未修改帧可保留原有表示，页面按帧识别是否存在有效采样。

## 可选 MapTRv2 适配

需要 MapTRv2 训练表示时，另外准备原模型环境，在配置 JSON 中加入 `model_root` 与 `maptr_python`。它们只用于显式适配，不作为默认几何解释器。依赖安装和版本见 [安装说明](INSTALL.md)。

```bash
python run.py export-maptr --source outputs/generic1 --output outputs/maptr1
python run.py review --source outputs/maptr1 --output outputs/maptr_review1
python run.py dataset-check --root outputs/maptr_review1
```

适配器在新目录中生成实际 fixed20/shift_v2/labels 和采样诊断，不改变完整几何、实例 ID 或源数据。`dataset-check` 是可选 MapTR Dataset 检查；通用检查用 `geometry-check`。没有配置模型环境时，显式适配命令会清楚报错。

也支持 `extract --sampler maptr`、`xodr-only --sampler maptr`、`postprocess --sampler maptr`，以兼容直接采样流程。默认均为 `--sampler none`；旧 `--skip-sampler` 保留为不采样别名。通用模式不再把未采样结果视为仅供诊断的无效标注。所有结果仍须人工审核，代码不会自动批准训练使用。

其他模型可直接读取通用完整几何，按各自需要转换为固定点数、栅格或其他表示；本版没有声称已实现这些模型的专用适配器。

通用顶视来源无需 nuCarla 原始表；自包含位姿与同步证据的输入、`prepare_topdown.py` 及路径别名见[通用顶视接入](TOPDOWN_INPUT.md)。

目前仅在 CARLA 0.9.16 的 Town10HD/Opt 上完成验证；其他城镇和版本尚未验证。当前默认资源和采集配置对应这一验证环境，接入其他地图须先适配并验证，不能仅改名称或摘要。相机、BEV、提取、分段和导出参数的实际生效位置及修改影响见[参数索引](PARAMETERS.md)。
