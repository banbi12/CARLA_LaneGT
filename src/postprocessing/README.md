# 人工后处理组件

本组件将页面或 CAD 导出的补线操作应用到指定源图册，默认生成新的通用完整几何 GT 和审核图册，无需模型；显式 --sampler maptr 时才运行模型采样。支持连接、新增、删除、撤销/重做及 DXF 导入导出；中心线只读。

从项目根目录使用 `run.py postprocess` 或 `run.py cad`。完整步骤见[页面审核与补线](../../docs/POSTPROCESSING.md)和[CAD 往返](../../docs/CAD_GUIDE.md)，输入/输出绑定要求见[输出格式](../../docs/OUTPUTS.md)。

## 本地覆盖（不分发）

`src/postprocessing/project.json` 是可选的本地覆盖入口，不随仓库分发，并已在 `.gitignore` 中忽略。需要覆盖 `base_review`、`canonical_review` 等字段时，手动创建该 JSON 文件；不存在时工具使用 `config/paths.local.json` 的默认值。不要把它加入 Git。
