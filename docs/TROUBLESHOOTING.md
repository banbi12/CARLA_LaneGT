# 常见问题

| 现象 | 检查与处理 |
|---|---|
| 没有环境配置 | 先执行 `tools/configure.py --from-json ...`；之后明确编辑生成的配置文件 |
| 配置导入拒绝覆盖 | 工具不会覆盖已有 `config/paths.local.json`，请编辑该文件并保留需要的旧配置 |
| 资源指纹不匹配 | 核对已验证 CARLA_0.9.16 / Town10 的匹配资源；不要只重算指纹掩盖地图差异 |
| RGB/semantic/depth 形状不同 | 核对同帧、同内参、同分辨率，检查深度是否为 H×W 数组 |
| 语义图颜色正确但没有标线 | 提取需要单通道 ID 值 24，不读取绿色/紫色调色板颜色 |
| 六相机投影整体偏转或左右颠倒 | 检查 optical/native/world/model 轴定义和矩阵方向，保留完整平移与姿态 |
| 参考与帧位姿不匹配 | 无 cases 时核对 source_frame_token 与 token、GT_model_from_world 与 transform；有 cases 时另核对代表帧；不同完整位姿不能共享参考 |
| 图册部分原图打不开 | 检查 `native_images/CAM_*/文件名`、绝对路径、外部链接目标是否仍存在 |
| Dataset 检查图像形状失败 | 当前 DataLoader 验证要求 6 张 1600×900 图像，缩放必须同步修正内参和相关标定 |
| 默认提取意外要求 mmcv/mmdet/Torch | 默认不导入模型；先确认没有请求 --sampler maptr/export-maptr/dataset-check，runtime_python 指向已安装几何依赖的解释器。只有显式模型适配才配置 maptr_python/model_root |
| 输出目录被拒绝 | 使用尚不存在、位于目录保护范围之外的新目录；不要覆盖已有图册 |
| 补线点不到端点 | 先选对 divider/boundary 类别，再放大；闭合线和非所选类别不会成为连接端点 |
| 浏览器仍显示载入 | 检查当前帧 `audit_data.js`、`editor_data` 是否存在，使用 Firefox 并确认外部数据链接可读 |
| 补线 JSON 不能应用 | 确认导出的是补线操作而非审核记录/完整 GT，并使用其绑定的源图册 |
| CAD 导回冲突 | DXF 必须配套原 context，数据集/帧/会话及编辑历史一致；先备份再基于正确版本重新导出 |
| CAD 连接后仍是多实例 | 在 CAD 中将实体 JOIN 成一条连续多段线，不只新增独立桥接线 |
| BEV 超出覆盖 | 缩小范围，或提高顶视采集高度重新生成实测参考；安全边缘不可用修改摘要绕过 |
| 中心线缓存被拒绝 | 当前中心线缓存接口接受原版 XODR 处理链的 v2 文件，原临时 CARLA 采样缓存需要重新生成 |
| 没有中心线输出 | 默认 none，需显式 `--centerline generate` 或 `provided`；六相机不是中心线来源 |
| 少量 divider 漏连 | 先核对实际图像和源几何，个别情况人工补线；成批同模式问题再评估规则调整 |

`check` 是输入预检查，不会证明所有像素和 GT 都正确。模型适配后才出现的 `sampling_hd_m` 是几何采样表示偏差，不能据此推断检测模型 AP 或训练效果。

新增来源、同步、可选预览与字段别名见[通用顶视接口](TOPDOWN_INPUT.md)，采集/提取参数的实际生效位置见[参数索引](PARAMETERS.md)。
