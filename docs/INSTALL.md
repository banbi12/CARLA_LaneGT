# 安装与环境

默认流程使用 requirements.txt 的几何环境与通用完整几何 GT，无需 MapTRv2；`--sampler maptr`、`export-maptr` 和 `dataset-check` 才启用模型适配。配置与完整步骤以[通用 GT 指南](GENERIC_GT.md)为准。

## CPU 运行环境

支持 Linux。推荐使用独立 Python 环境安装几何处理依赖；依赖版本见 `requirements.txt`。已验证的模型集成环境使用 Python 3.8。Node.js 18+ 用于命令行 CAD DXF 导入导出。

```bash
python -m pip install -r requirements.txt
```

浏览器中的编辑和 CAD 导入导出不需要 Node.js 服务。推荐 Firefox 打开生成的 `gallery.html`；图册使用文件方式加载数据，不要求启动 HTTP 服务。

## 可选 MapTRv2 采样与 Dataset 环境

可选 MapTRv2 采样调用外部 MapTRv2 的 `LiDARInstanceLines`，生成实际 `fixed20` 与 `shift_v2`。几何处理依赖清单不是完整的 OpenMMLab 环境安装脚本；请分别准备模型环境，并在配置中指定解释器和仓库位置。

| 配置字段 | 要求 |
|---|---|
| `model_root` | MapTRv2 仓库根目录；包含 `projects/mmdet3d_plugin` 与 `mmdetection3d` |
| `maptr_python` | 已安装 MapTRv2/OpenMMLab 依赖的 Python 可执行文件绝对路径 |

已通过集成检查的一组依赖为：Python 3.8、PyTorch 1.9.1+cu111、mmcv-full 1.4.0、mmdet 2.14.0、mmdet3d 0.17.2、nuscenes-devkit 1.1.11、pyquaternion 0.9.9、NumPy 1.23.5、SciPy 1.10.1、Shapely 1.8.5.post1 和 Pillow 10.4.0。OpenMMLab 的编译依赖应按所选模型环境准备，不要直接用几何依赖清单覆盖已有模型环境。

`run.py` 默认按 `runtime_python` 调用几何脚本；显式模型适配按 `maptr_python` 运行，并为 CPU 操作关闭 CUDA 可见设备、限制线程数；存在对应 `libstdc++.so.6` 时会设置其加载路径。GT 提取和采样不加载模型权重，也不执行检测推理。

## CARLA 采集环境

中心线生成复用原版 XODR 几何和去重流程，只需要 CPU 几何环境，不需要 CARLA API、服务器、GPU 或 NVML。只有重新采集顶视参考时才需要运行 CARLA 服务器、GPU 和 NVML。当前采集配置已在 CARLA 0.9.16 的 Town10HD/Opt 地图及匹配资源上验证，需要对应 Python API 以及环境对象可见性接口；其他城镇和版本需先适配并验证。安装额外 Python 依赖：

```bash
python -m pip install -r requirements-capture.txt
```

CARLA 服务器与 Python API 单独安装，分别用 `carla_root`、`carla_python` 配置。服务器版本与地图内容不能通过修改资源指纹来替换。配置完成后先执行 `collect-plan`；采集参数和执行命令见[采集说明](CAPTURE.md)。

## XODR-only 可选几何环境

仅在生成旧版基线世界缓存时需要独立 Python 3.10 / Shapely 2 环境，依赖见 `requirements-xodr.txt`。世界缓存生成与 MapTRv2 采样分进程运行，不升级或覆盖当前模型环境的 Shapely 1.8；缓存准备完成后可仅用几何环境导出各帧。该几何环境不需要 CARLA API、服务器或 GPU，操作见 [XODR-only](XODR_ONLY.md)。

目前仅在 CARLA 0.9.16 的 Town10HD/Opt 上完成验证；其他城镇和版本尚未验证。当前默认资源和采集配置对应这一验证环境，接入其他地图须先适配并验证，不能仅改名称或摘要。相机、BEV、提取、分段和导出参数的实际生效位置及修改影响见[参数索引](PARAMETERS.md)。
