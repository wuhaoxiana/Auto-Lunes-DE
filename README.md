## Lunes Host 自动保活（GitHub Actions）

基于 GitHub Actions 的自动化脚本，定时登录 [Lunes Host](https://betadash.lunes.host/) 并访问服务器页面，保持账号活跃，避免因长时间不活动被暂停。

### Secrets 配置说明

| Secret 名称        | 是否必填 | 说明 |
|--------------------|----------|------|
| LUNES              | ✅ 必填  | 格式 `邮箱-----密码`，Lunes 平台登录凭证 |
| LUNES_SERVER_ID    | ❌ 可选  | 服务器 ID，默认 89950 |
| SESSION_COOKIE     | ❌ 可选  | 预置 session cookie 值，可跳过完整登录流程 |
| NODE_LINK          | ❌ 可选  | 代理链接（vless:// vmess:// trojan:// hysteria2:// 等） |
| TG_BOT_TOKEN       | ❌ 可选  | Telegram Bot Token（用于发送通知） |
| TG_CHAT_ID         | ❌ 可选  | Telegram Chat ID |

### 部署步骤

1. Fork 本项目，在 Actions 菜单允许工作流
2. 在 `Settings` ➡ `Secrets and variables` ➡ `Actions` 添加上方 Secrets
3. 去 Actions 菜单手动试运行工作流
4. 定时任务默认每月 1/11/21 号执行，可在 `renew.yml` 调整 cron

### SESSION_COOKIE 获取

登录后从浏览器开发者工具中获取名为 `session` 的 cookie 值，添加到 Secrets 中可跳过每次的完整登录流程。

### 免责声明

本程序仅供学习了解，非盈利目的。使用本程序必须遵守部署服务器所在地、所在国家和用户所在国家的法律法规。
