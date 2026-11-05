# 配置说明

默认流程使用通用完整几何 GT，无需 MapTRv2；`--sampler maptr`、`export-maptr` 和 `dataset-check` 才启用模型适配。配置与完整步骤以[通用 GT 指南](GENERIC_GT.md)为准。

从仓库根目录执行命令。JSON 中的路径应使用绝对路径，不使用 `~`、环境变量或 shell 表达式；路径不会统一进行变量展开。输入清单内部的图片路径也应为绝对路径。

## 创建环境配置

```bash
cp config/paths.example.json /tmp/lanegt-paths.json
# 编辑 /tmp/lanegt-paths.json，填写数据路径与解释器路径
python tools/configure.py --from-json /tmp/lanegt-paths.json
```

工具生成 Git 忽略的 `config/paths.local.json`，补全项目路径并加入目录保护。目标文件已存在时会拒绝覆盖；后续调整请明确编辑该文件。文件名中的 `.local` 表示部署环境专用配置，不属于公开参数。

| 字段 | 类型与含义 | 使用条件 |
|---|---|---|
| `frame_manifest` | 逐帧清单 JSON 文件 | 提取、选帧、采集计划 |
| `cases` | 顶视参考与代表帧对应表 | 普通自包含元数据可省略；共享参考或采集时提供 |
| `topdown_root` | `<reference>/` 顶视目录的父目录 | 已有顶视参考时必需 |
| `camera_metadata`（兼容 `native_metadata`） | `<token>.json.gz` 六相机和车辆元数据目录 | 可选六相机投影、相机 Dataset 检查 |
| `centerline_labels`（兼容 `native_labels`） | `<token>.json.gz` 逐帧中心线输入目录 | 仅 `--centerline provided` |
| `camera_images`（兼容 `native_images`） | 按 `CAM_*` 分目录存放的六相机图片根目录 | 图册原图链接、渲染 |
| `model_root` | 可选外部 MapTRv2 仓库根目录 | 仅显式采样、导出、Dataset 检查 |
| `runtime_python` | 通用几何环境 Python，省略时取配置解释器 | 默认提取、审核与后处理 |
| `maptr_python` | 可选模型环境 Python | 仅显式 MapTRv2 适配 |
| `carla_root` | 包含 `CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping` 的安装目录 | 仅重新采集 |
| `carla_python` | 能导入匹配 CARLA API 的 Python 可执行文件绝对路径 | 仅重新采集 |
| `data_root` | 数据工作目录 | 人工应用工具用于保护已存在的数据目录 |
| `review60` | 默认源图册目录；名称为兼容接口保留，不限制帧数为 60 | `review` 默认源、CAD 默认源与补线默认源 |
| `previous_editor` | 兼容配置字段，可填与 `review60` 相同的目录 | 不是提取算法输入 |
| `protected_output_roots` | 禁止写入的目录列表 | 所有新输出应避开这些目录及其子目录 |
| `project_root` | 项目根目录 | 配置工具自动填写 |
| `dataset_adapter_root` | `src/adapters` 目录 | 配置工具自动填写 |

配置工具仅要求 `frame_manifest`、`topdown_root` 和 `data_root`。未提供的相机/已有标签目录被设为禁写占位路径，不读取其中数据。`review60` 与 `previous_editor` 默认指向计划中的 `outputs/review1`。自动生成中心线使用 `runtime_python` 的 CPU 几何依赖；不需要 `carla_python` 或 CARLA API。已生成的原版 v2 世界文件可以复用。

按用途检查：`doctor --topdown-only` 不检查六相机目录；`doctor --centerline provided` 检查已有中心线目录；`doctor --centerline generate` 不要求已有中心线标签；地图/参考一致性由后续 check 检查；`doctor --capture` 额外检查 cases、CARLA 解释器和安装路径；无六相机时同时加 --topdown-only。doctor 不校验依赖能否导入、所有文件内容或传感器是否可用。`check` 还会校验请求的 BEV 覆盖范围。

## 导入匹配地图资源

准备以下目录结构：

```text
/data/town10-resources/
├── maps/
│   ├── xodr_crosswalk_world.json
│   ├── xodr_connection_prior.json
│   └── xodr_connection_prior_v41.json   # 由 V4.1 世界缓存生成
└── capture/
    ├── server_Town10HD.xodr
    ├── selective_occluder_allowlist.json
    └── calibration_case.json
```

```bash
python tools/import_resources.py --from-directory /data/town10-resources
```

工具按 `config/resources.town10.json` 校验 5 个文件的 SHA256，再导入 `assets/maps/` 与 `assets/capture/`。已有同内容文件可复用，内容不同则拒绝覆盖。资源不随公开源码分发，使用者需要取得匹配资源及其使用权限；仓库不提供下载服务。只拥有原版 Town10 地图不代表资源已匹配。

`config/extraction/connection_prior.json` 固定旧版 divider 连接先验；`config/extraction/connection_prior_v41.json` 固定 V4.2 B/V4.3 使用的 V4.1 stitched divider 参考及 XODR 指纹。V4.1 参考由 `tools/build_xodr_connection_reference.py` 从对应世界缓存生成，不计入上述 5 个外部资源文件的导入清单。资源指纹用于一致性验证，不能仅重算指纹来跳过地图内容差异。

## 输出目录保护

新输出目录必须不存在。不要把输出设置为输入数据、现有图册、代码、资源或其子目录。人工应用工具还会保护 `data_root` 下已经存在的各个数据目录；建议为每次应用选用 `data_root` 下尚不存在的直接子目录，而不是已有数据目录中的子目录。

例如 `data_root=/data/lanegt` 时，可用 `/data/lanegt/manual_v1` 作为新的人工结果目录。源图册和被链接的原图、顶视数据仍须保留；结果目录不是自包含的数据归档。

## XODR-only 部署选项

完整 semantic 配置可以直接复用。仅部署基线时，`tools/configure.py --xodr-only --from-json ...` 只要求 `frame_manifest`、`data_root`；`cases` 与 `topdown_root` 可以省略，未启用项指向不存在的占位路径。配置中可选 `xodr_python` 指定 Shapely 2 几何解释器，命令行 `--geometry-python` 优先；使用 `--world` 缓存时无需该解释器。`doctor --xodr-only --topdown-only` 检查基线路径；原有 doctor 和提取命令的默认行为不变。

只配置基线几何后不能直接生成顶视图册，需先补全真实的顶视 RGB、标定和元数据；六相机字段只在启用六相机时需要，详见 [XODR-only 指南](XODR_ONLY.md)。

通用顶视来源无需 nuCarla 原始表；自包含位姿与同步证据的输入、`prepare_topdown.py` 及路径别名见[通用顶视接入](TOPDOWN_INPUT.md)。

目前仅在 CARLA 0.9.16 的 Town10HD/Opt 上完成验证；其他城镇和版本尚未验证。当前默认资源和采集配置对应这一验证环境，接入其他地图须先适配并验证，不能仅改名称或摘要。相机、BEV、提取、分段和导出参数的实际生效位置及修改影响见[参数索引](PARAMETERS.md)。

新配置推荐使用 camera_metadata、camera_images、centerline_labels；configure.py 将其映射为内部旧键。两套名称同时提供但不一致会拒绝。配置文件创建后若手工修改这些路径，应同时保持内部旧键一致，或备份配置后通过配置工具重新生成；运行脚本并非都会再次解析别名。
