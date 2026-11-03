# 第三方代码与资源说明

项目自行编写的脚本和界面使用根目录 `LICENSE` 中的 MIT 许可。上游代码、外部库、地图和数据各自的许可继续适用，不因本项目许可而改变。

| 组成 | 使用方式与许可说明 |
|---|---|
| 可选 MapTRv2 | Dataset 适配器继承其数据集类；模型代码、权重和 OpenMMLab 栈单独安装。上游 MIT 声明保存在 [LICENSES/MapTR-MIT.txt](LICENSES/MapTR-MIT.txt) |
| CARLA | 采集脚本调用其 API；服务器和 Python API 不随源码捆绑。代码许可声明保存在 [LICENSES/CARLA-MIT.txt](LICENSES/CARLA-MIT.txt) |
| nuCarla Town10 数据集 | 仅用于验证/测试；原始数据不随源码分发；`docs/images/` 中的少量文档示例图除外，按上游许可与引用要求使用。 |
| 地图、附加资产与外部数据（含可选 nuCarla） | 独立取得和配置，不属于项目代码许可授权的资源；原始数据不纳入公开源码，少量文档示例图除外 |
| NumPy、SciPy、Shapely、scikit-image、OpenCV、Pillow、PyTorch、OpenMMLab、nuScenes-devkit、pyquaternion、可选 ezdxf | 作为外部依赖安装，按各软件包的许可使用；仓库未复制其完整库实现 |
| ASCII DXF 模板 | 由 ezdxf 1.4.3 生成的数据模板，运行时不捆绑 ezdxf；CAD 往返处理脚本为项目代码 |

来源文件与摘要记录见 `RELEASE_SOURCE.json`。`LICENSES/` 中上游法律文本保留原文，文档中文说明不替代相应许可条款。公开源码不包含第三方地图、原始图片、深度、模型权重或人工标注；`docs/images/` 仅保留少量文档示例图，原始验证数据与 GT 不随源码分发。

默认通用几何流程不需要模型代码或权重。CARLA_0.9.16 / Town10 是已验证环境说明，不构成其地图资产再分发授权；具体依赖使用条件见[安装说明](docs/INSTALL.md)。
