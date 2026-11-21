# 贡献指南

感谢你对 Lysmor 的关注！欢迎通过 Issue 与 Pull Request 参与贡献。

## 报告问题

- 先在 [Issues](https://github.com/Lingximo/Lysmor/issues) 中搜索是否已有相同问题；
- 使用「问题报告」模板，写清复现步骤、环境信息与实际结果；
- **不要**在 Issue / 截图中粘贴任何密钥、口令、QQ 号、真实路径等隐私信息。

## 提交代码

1. Fork 本仓库并创建分支：`git checkout -b feature/your-feature`；
2. 修改代码，保持与现有代码风格一致；
3. 本地检查：
   ```bash
   python -m py_compile configure.py open_entry.py setup/server.py
   ```
4. 提交并推送：
   ```bash
   git commit -m "feat: 简述改动"
   git push origin feature/your-feature
   ```
5. 在 GitHub 上发起 Pull Request，填写 PR 模板中的检查清单。

## 代码约定

- 服务端与工具尽量只用 Python 标准库（第三方库需在 PR 中说明理由）；
- 新增配置项时，同步更新 `config.example.json` 与 `docs/` 下相关文档；
- 前端页面保持零依赖，不引入外部 CDN 资源；
- 中文文档、注释保持简洁准确。

## 安全红线

提交前务必阅读 [SECURITY.md](SECURITY.md)。以下内容**永远**不能出现在仓库中：

- 密钥、口令、token、cookie、证书；
- 账号（QQ 号、手机号、邮箱）、实例 UUID；
- 真实绝对路径、个人数据、角色记忆与形象素材。

## 许可

向本项目提交的代码将按 [AGPL-3.0](LICENSE) 许可发布。
