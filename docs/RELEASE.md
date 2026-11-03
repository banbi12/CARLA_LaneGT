# 源码发布

## 公开文件范围

源码仓库包含维护中的 Python/JavaScript 代码、审核界面、算法参数、配置示例、文档和许可文件。

公开源码不包含 nuCarla 原始图像、CARLA 地图资产、topdown 参考、GT 或审核产物；`docs/images/` 仅保留少量文档示例图。

下列内容不纳入 Git：环境路径配置、原始图片、语义/深度数据、地图及派生资源、遮挡物清单、权重、运行产物、审核/补线记录、测试脚本及报告和开发历史归档（`docs/images/` 中的少量文档示例图除外）。空资源目录中的 `.gitkeep` 仅用于保留目录结构。

`config/resources.town10.json` 和连接先验配置只记录一致性约束，不构成资源分发或使用许可。使用者需要自行取得适用的数据与地图资源。具体许可范围见[第三方说明](../THIRD_PARTY_NOTICES.md)。

## 发布前检查

```bash
git add .
python tools/check_release.py
git diff --cached --stat
```

检查跟踪文件不含环境专用路径和受忽略的运行数据，再由维护者按仓库流程提交与推送。不要使用强制添加绕过忽略规则。真实数据测试输出应保存在 `outputs/`、`reports/` 等受忽略目录中。

`RELEASE_FILES_SHA256.json` 记录公开文件指纹与内部符号链接，自身不递归纳入指纹。修改公开文件后需要更新该清单，不能继续声称旧摘要代表新内容。`RELEASE_SOURCE.json` 记录初始代码来源，不应被解释为所有未来修订文件都与初始来源字节相同。

## 源码包

源码包只应包含受跟踪的公开文件，并保留项目内部相对符号链接。完成提交后可使用 Git 创建归档，例如：

```bash
git archive --format=tar.gz --prefix=CARLA_LaneGT/ \
  --output=../CARLA_LaneGT-1.0.0-source.tar.gz HEAD
```

将归档输出放在仓库之外，或在创建后避免将归档本身加入跟踪。源码包不包含运行资源；解压后仍需按安装与配置文档准备输入。

发布前按 README、TOPDOWN_INPUT、INPUTS、OUTPUTS、CONFIGURATION、PARAMETERS 核对同一接口契约：默认通用 GT、模型适配可选、通用来源与地图支持范围分别声明。文档或配置变化后更新公开指纹和源码包；历史验证数据及人工记录继续保存在仓库之外。
