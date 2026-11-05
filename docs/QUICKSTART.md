# 操作指南

默认流程使用通用完整几何 GT，无需 MapTRv2；`--sampler maptr`、`export-maptr` 和 `dataset-check` 才启用模型适配。配置与完整步骤以[通用 GT 指南](GENERIC_GT.md)为准。

本文所有 `python run.py ...` 命令在仓库根目录执行。路径和帧 token 为示例，使用前替换为实际值。

## 1. 安装、配置与资源导入

按[安装说明](INSTALL.md)准备环境，按[配置说明](CONFIGURATION.md)生成 `config/paths.local.json` 并导入资源。先确认已具备[数据接口](INPUTS.md)要求的全部文件。

```bash
python run.py doctor --topdown-only
python run.py check --limit 1 --topdown-only
```

`doctor` 检查路径与 Node.js 是否存在，不验证提取结果。`check` 检查选中帧的文件、地图、测量参数和完整位姿绑定，但不会解码所有图像、运行采样或生成 GT。

## 2. 单帧提取和图册生成

```bash
python run.py extract --limit 1 --topdown-only --centerline none --output outputs/extraction1
python run.py review --source outputs/extraction1 --output outputs/review1
```

`extract` 默认生成三类完整几何 GT（中心线数组为空）、候选世界几何和观测审计；实际采样按需启用；`review` 渲染顶视与 BEV，启用相机输入时附加六相机视图，生成审核和编辑页面。使用 Firefox 打开 `outputs/review1/gallery.html`，先确认投影、覆盖范围与类别，再扩大选帧数量。

## 3. 明确选择帧

按帧 token 提取：

```bash
python run.py extract \
  --tokens FRAME_TOKEN_A FRAME_TOKEN_B --topdown-only --centerline generate \
  --output outputs/extraction_selected
```

也可准备选择文件 `selection.json`：

```json
{"frames": [{"token": "FRAME_TOKEN_A"}, {"token": "FRAME_TOKEN_B"}]}
```

```bash
python run.py check --selection selection.json --topdown-only
python run.py extract --selection selection.json --topdown-only --output outputs/extraction_batch
python run.py review --source outputs/extraction_batch --output outputs/review_batch
```

选择文件可以是帧对象数组、token 字符串数组，或包含 `frames` 的对象。实际记录仍从 `frame_manifest` 读取，选择文件不是另一套标定输入；执行顺序遵循原始清单顺序。`--tokens` 与 `--selection` 互斥。`--limit N` 取选定结果的前 N 帧，N 必须大于 0。未指定 token/选择文件/limit 时拒绝隐式全量运行。全量运行应提供覆盖全部目标 token 的明确选择文件。

中心线可用 `--centerline generate` 自动生成，或用 `provided` 导入已有结果；默认 `none`。范围可加 `--bev-range -16 -31 16 31`，表示 32×62 米。两者完整操作见[中心线](CENTERLINES.md)和[BEV 范围](BEV.md)。

## 4. 通用几何检查与可选模型导出

```bash
python run.py geometry-check --root outputs/review_batch
```

该检查不需要模型。需要 MapTRv2 时，单独配置适配器环境，再运行 `export-maptr`，对新结果生成图册后执行 `dataset-check`。完整示例见[通用 GT 指南](GENERIC_GT.md)。

## 5. 审核、编辑与应用

在图册中选择帧、审核实例，导出审核记录；断线可在人工补线区处理，导出补线操作 JSON。两类导出文件不同，详见[页面操作](POSTPROCESSING.md)。

```bash
python run.py postprocess \
  --source outputs/review_batch \
  --patch /data/exports/geometry_edits.json \
  --output /data/lanegt/manual_v1
```

将输出路径替换为符合目录保护规则的新目录。完成后打开 `/data/lanegt/manual_v1/gallery.html` 继续审核；修改帧已保存通用完整几何并重新渲染；显式 --sampler maptr 时才采样。后续命令显式指定新的 `--source`。

## 6. 采集与诊断选项

顶视参考尚未采集时，见[采集说明](CAPTURE.md)。`collect-plan` 不启动 CARLA/GPU，只有显式 `collect --execute` 执行采集。

`extract --skip-sampler` 与默认 `--sampler none` 一样生成可审核、可编辑的通用完整几何 GT；不生成模型采样 NPZ。`--hint-world` 是可选地图诊断，不代替默认启用的同哈希 XODR 连接先验。输出字段和状态说明见[输出格式](OUTPUTS.md)。

## 7. XODR-only 与同帧对照

XODR-only V4.1 通过 `run.py xodr-only` 独立运行。准备世界缓存后可生成同帧结果：

V4.2 B 的 divider base 依赖 `assets/maps/xodr_connection_prior_v41.json`。该文件由 V4.1 世界缓存生成；首次使用或资源变化后先执行：

```bash
python tools/generate_xodr_world.py --xodr assets/capture/server_Town10HD.xodr \
  --output /data/lanegt/xodr_world.json
python tools/build_xodr_connection_reference.py \
  --world /data/lanegt/xodr_world.json \
  --xodr assets/capture/server_Town10HD.xodr \
  --output assets/maps/xodr_connection_prior_v41.json \
  --pin config/extraction/connection_prior_v41.json
```

世界生成的几何环境和资源要求见 [XODR-only 指南](XODR_ONLY.md)。

```bash
python run.py xodr-only --selection selection.json --topdown-only --centerline generate \
  --world /data/lanegt/xodr_world.json --output outputs/xodr_selected
python run.py extract --selection selection.json --topdown-only --centerline generate \
  --output outputs/semantic_selected
python run.py compare --xodr outputs/xodr_selected --semantic outputs/semantic_selected \
  --output outputs/scheme_comparison
```

打开 `outputs/scheme_comparison/gallery.html` 查看并排 BEV。完整世界生成、资源和审核图册要求见 [XODR-only 指南](XODR_ONLY.md)。比较只写入新目录，不改动两份输入结果。

## 从其他采集器的顶视数据开始

按[通用顶视接口](TOPDOWN_INPUT.md)准备 metadata 和 COMPLETE 后，先运行 `tools/prepare_topdown.py` 生成清单及配置草稿，再执行配置、资源导入、单帧检查与提取。无需 nuCarla 原始表或六相机。
