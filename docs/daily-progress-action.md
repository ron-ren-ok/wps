# WPS 日进度 GitHub Actions

工作流 `.github/workflows/daily-progress.yml` 在每个工作日北京时间 10:00 发送一次日进度播报；也可在 Actions 页面手动运行。它只读取 Google 表格中已有的公式结果，不修改表格，也不使用任何 AI 服务。

在仓库 **Settings → Secrets and variables → Actions** 中添加以下 Secrets：

| Secret | 必填 | 说明 |
| --- | --- | --- |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 是 | 有目标表格读取权限的 Google 服务账号 JSON 完整内容。将对应服务账号邮箱共享到表格。 |
| `WPS_WEBHOOK_URL` | 是 | WPS 群机器人 webhook 地址。 |
| `WPS_WEBHOOK_KEY` | 否 | 机器人启用签名校验时的 key。 |
| `WPS_WEBHOOK_SECRET` | 否 | 机器人启用签名校验时的 secret；必须与 key 一同设置。 |

首次配置后，在 GitHub Actions 中手动运行 **WPS daily progress** 一次，确认机器人收到卡片后再等待定时任务。
