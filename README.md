# WeChat DeepSeek Screen Bot

一个不依赖 `wx4py` 的 Windows 微信群 AI 自动回复机器人。它直接绑定手动打开的群聊独立窗口，通过 Windows UI Automation 读取新消息，并调用 DeepSeek API 生成回复。

## 功能

- `@机器人昵称` 时自动回复
- 支持多个自定义唤醒词
- 全局快捷键 `Ctrl + 空格`，立即回复最近一条群消息
- 多群独立上下文
- DeepSeek V4 Flash Chat Completions
- Windows DPAPI 加密保存 API Key
- 中文菜单启动器
- 不搜索联系人，不修改或注入微信客户端

## 环境要求

- Windows 10/11
- 微信 PC 版已安装并登录
- Python 3.9 或更高版本
- DeepSeek 开放平台 API Key

> 运行前需要在微信聊天列表中双击目标群，使其弹出标题为群名的独立窗口。运行期间不要最小化或关闭该群窗口。

## 快速开始

```powershell
git clone https://github.com/YOUR_NAME/wechat-deepseek-screen-bot.git
cd wechat-deepseek-screen-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

然后双击 `微信机器人启动器.cmd`：

1. 选择“首次配置 / 重新配置”。
2. 填写群名、你在群里的昵称和唤醒词。
3. 在弹出的窗口中粘贴 DeepSeek API Key。
4. 在微信中双击目标群，打开独立群聊窗口。
5. 选择“启动机器人”。

API Key 使用当前 Windows 用户的 DPAPI 加密保存到本地 `api-key.secure`，该文件已被 Git 忽略。

## 手动配置

复制配置模板：

```powershell
Copy-Item .\config.example.json .\config.json
```

主要配置项：

- `groups`：要监听的微信群名称，必须与独立窗口标题一致。
- `bot_nickname`：机器人账号在群里显示的昵称。
- `wake_words`：不需要 `@` 也能触发回复的关键词。
- `context_size`：每个群保留的对话上下文条数。
- `ai.model`：DeepSeek 模型 ID。
- `ai.system_prompt`：机器人回复风格。

手动运行时设置 API Key：

```powershell
$env:AI_API_KEY = "你的 DeepSeek API Key"
.\.venv\Scripts\python.exe .\screen_bot.py --check
.\.venv\Scripts\python.exe .\screen_bot.py
```

## 触发方式

```text
@小助手 帮我解释这个问题
小助手 帮我写一段通知
```

机器人运行后，按全局快捷键 `Ctrl + 空格` 可跳过关键词检查，回复最近监听到的一条群消息。

## 工作原理

1. 用户手动打开群聊独立窗口。
2. 程序绑定窗口并把当前可见消息作为基线。
3. 持续读取新增的可见消息控件。
4. 命中 `@`、唤醒词或快捷键后调用 DeepSeek。
5. 将模型回复粘贴到群聊输入框并发送。

## 已知限制

- 依赖微信当前可见的 UI Automation 控件，微信更新后可能需要调整识别规则。
- 群聊独立窗口不能最小化或关闭。
- 只能可靠读取机器人运行期间可见的新消息，不能作为完整聊天记录工具。
- 图片、语音、表情和复杂引用消息可能无法正确解析。
- 快捷键可能与输入法或其他软件冲突。
- 自动化可能触发微信平台的风控，请控制频率并使用测试账号验证。

## 隐私与安全

- `config.json`、`api-key.secure`、日志和虚拟环境不会被提交。
- 群消息在触发回复时会发送给所配置的 DeepSeek API。
- 请确保群成员知情，并遵守微信、DeepSeek 及所在地区的适用规则。
- 不要将真实 API Key 写入源码、Issue 或截图。

## 开源许可

[MIT License](LICENSE)
