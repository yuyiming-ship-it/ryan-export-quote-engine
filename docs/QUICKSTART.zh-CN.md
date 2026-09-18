# 出口报价引擎小白使用说明

这套产品负责把车源、运输、资金和其他费用按固定规则算清楚。AI 负责读询价、追问缺项和解释结果；最终金额由报价引擎计算，避免不同 AI 各算一套。

## 先理解两个词

- **Skill**：相当于给 AI 的岗位说明书，告诉它按什么步骤做报价、哪些内容不能猜、哪些内部信息不能发给客户。
- **MCP**：相当于 AI 和报价计算器之间的插头。接好后，AI 可以调用 `validate_quote`、`calculate_quote` 等工具完成真实计算。

最好同时使用 Skill 和 MCP。只有 Skill 时，AI 知道流程，但不能保证金额一定由本引擎计算；只有 MCP 时，能算金额，但 AI 不一定遵循完整的业务步骤。

## 第一次安装（macOS / Linux）

电脑需要 Python 3.10 或更高版本。在“终端”中逐行粘贴：

```bash
git clone https://github.com/yuyiming-ship-it/ryan-export-quote-engine.git
cd ryan-export-quote-engine
sh scripts/install_local.sh
```

脚本会建立独立的 `.venv` 环境、安装报价引擎和 MCP 组件，再用虚构样例做一次计算。看到 `安装和样例计算均成功` 就完成了。

如果已经下载项目，进入项目文件夹后只运行：

```bash
sh scripts/install_local.sh
```

Windows 用户可以使用 WSL 后执行同样命令。直接使用 PowerShell 时，可手动执行：

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.venv\Scripts\export-quote.exe calculate examples\standard.json
```

## 不接 AI，先试算一次

在项目目录运行：

```bash
.venv/bin/export-quote calculate examples/standard.json --out demo-result.json
```

`examples/standard.json` 是虚构样例。生成的 `demo-result.json` 是完整结果。真实业务不要直接修改样例里的价格后当成正式报价；正式报价还需要公司已确认规则、有效价格和证据。

## 接入你使用的 AI

先取得项目绝对路径：

```bash
pwd
```

假设输出为 `/Users/yourname/ryan-export-quote-engine`，那么 MCP 启动命令就是：

```text
/Users/yourname/ryan-export-quote-engine/.venv/bin/export-quote-mcp
```

下面配置中的 `/绝对路径/ryan-export-quote-engine` 都要换成你的真实路径。先用公开样例体验时，可以暂时不填三个 `EXPORT_QUOTE_*` 环境变量；做公司真实报价前再按“使用公司规则包”一节配置。

### Codex 桌面版

1. 打开 **设置 → MCP 服务器 → 添加服务器**。
2. 名称填 `export_quote`，类型选 `STDIO`。
3. 命令填 `.venv/bin/export-quote-mcp` 的绝对路径。
4. 保存并重新启动 Codex。
5. 在对话里输入 `/mcp`，应看到 `export_quote` 和六个工具。

也可以在终端执行：

```bash
codex mcp add export_quote -- /绝对路径/ryan-export-quote-engine/.venv/bin/export-quote-mcp
codex mcp list
```

Codex 的手工配置模板见 [`integrations/codex-config.toml.example`](../integrations/codex-config.toml.example)。用户配置文件通常是 `~/.codex/config.toml`。

若要安装配套 Skill，把仓库中的 `skills/export-quote` 文件夹复制到 `~/.codex/skills/export-quote`，然后重启 Codex。

### Kimi Code CLI

这里指 **Kimi Code CLI**，普通 Kimi 网页聊天不能直接启动你电脑上的本地 MCP。

```bash
kimi mcp add --transport stdio export_quote -- /绝对路径/ryan-export-quote-engine/.venv/bin/export-quote-mcp
kimi mcp test export_quote
```

测试结果应列出六个工具。运行 `kimi` 后就可以用自然语言要求报价。也可以把 [`integrations/mcp.json.example`](../integrations/mcp.json.example) 的内容按 Kimi 当前配置方式加入 `~/.kimi/mcp.json`。

### Tencent WorkBuddy

1. 打开侧边栏 **插件 → MCP 服务器 → 配置 MCP**。
2. 复制 [`integrations/mcp.json.example`](../integrations/mcp.json.example) 的内容。
3. 把 `command` 改成自己电脑上的绝对路径。
4. 先删除暂时不用的 `env` 三行，或把路径换成真实私有目录。
5. 保存后确认状态为绿色。

经常使用可保存到 `~/.workbuddy/mcp.json`；只想让当前项目使用，可保存到项目目录的 `.workbuddy/mcp.json`。

### Claude Desktop、Claude Code 和 Cursor

- Claude Desktop：把标准模板加入 `claude_desktop_config.json`，完全退出后重新打开。macOS 配置文件通常在 `~/Library/Application Support/Claude/claude_desktop_config.json`。
- Claude Code：运行 `claude mcp add export_quote -- /绝对路径/ryan-export-quote-engine/.venv/bin/export-quote-mcp`，进入会话后用 `/mcp` 检查。
- Cursor：把标准模板保存为当前项目的 `.cursor/mcp.json`，再到 MCP 设置查看连接状态。

### DeepSeek DSH

参考 [`integrations/dsh-overlay.yaml`](../integrations/dsh-overlay.yaml)，把 `command` 和私有目录改为绝对路径，再按当前 DSH 版本加载 overlay。DSH MCP client 仍是开发者预览能力，若 profile 或 patch 参数发生变化，应以所用 DSH 版本文档为准。

### 其他 AI 工具

只要产品支持本地 `stdio` MCP，通常都能使用 [`integrations/mcp.json.example`](../integrations/mcp.json.example)。配置时填写一个命令：

```text
/绝对路径/ryan-export-quote-engine/.venv/bin/export-quote-mcp
```

如果产品只支持网页聊天、不能运行本地命令，就先用命令行生成 `result.json`，再把对客稿或需要分析的部分复制进去。不要把包含采购成本、利润、资金政策的内部完整结果上传到未经公司批准的外部 AI。

## 第一次对话怎么说

接入后，把询价文件放在当前项目可访问的位置，然后说：

> 使用 export_quote 工具处理这份询价。先提取车型、数量、交付地点、贸易条件、付款和回款节点；集中列出缺项，不要猜价格。资料齐全后比较车源、运输和资金方案，生成内部测算、对客报价稿和 MOSS 填写材料。任何金额都必须由工具计算。

AI 应按以下顺序工作：

1. 调用 `normalize_request` 整理需求。
2. 把付款条款拆成定金比例、尾款节点、账期和支付方式，再调用 `screen_funders`。
3. 将车源、仓储、物流等供应商询价整理成带来源和有效期的候选项。
4. 调用 `validate_quote` 检查缺项、过期数据、资金方适用性和冲突。
5. 资料齐全后调用 `calculate_quote`。
6. 有多个可比方案时调用 `compare_quotes`。
7. 人工选定方案后调用 `export_moss` 生成填写包。

如果你的业务包含固定资金政策和微信临时询价，请继续阅读 [微信询价与资金方选择工作流](询价与资金方工作流.md)。

结果状态的含义：

- `blocked`：关键数据缺失或冲突，不能正式对外报价。
- `conditional`：带明确假设的条件测算，不是已确认报价。
- `ready`：计算资料完整，但仍不代表业务负责人已经审批。

## 使用公司规则包

公司真实规则、客户资料、价格和飞书证据不能放进公开 GitHub 仓库。本公司已经创建飞书规则、快照和 MOSS 映射资源，可以直接配置：

```json
"env": {
  "EXPORT_QUOTE_RULES": "https://tdar7qsr83.feishu.cn/docx/FC66dkiFnopKrxx7HUAcvz8Fn4f",
  "EXPORT_QUOTE_STORE": "https://tdar7qsr83.feishu.cn/drive/folder/BPxbfMtQHlpMSdd68WwcLKJknsc",
  "EXPORT_QUOTE_MOSS_MAPPING": "https://tdar7qsr83.feishu.cn/docx/IYcPd21JTopANxx7QZvcLytZnKd",
  "EXPORT_QUOTE_FEISHU_IDENTITY": "user"
}
```

- `EXPORT_QUOTE_RULES`：每次调用从飞书读取；只有负责人批准的版本才能用于正式报价。
- `EXPORT_QUOTE_STORE`：本地保留不可变副本，并把快照上传到这个飞书文件夹。
- `EXPORT_QUOTE_MOSS_MAPPING`：调用导出工具时从飞书读取的 MOSS 字段映射。
- `EXPORT_QUOTE_FEISHU_IDENTITY`：默认 `user`，使用当前员工自己的飞书登录和权限。

使用前需安装并登录 `lark-cli`。完整说明见 [飞书公司配置接入](飞书公司配置接入.md)。当前规则包仍是 `pending`；没有已批准规则时，引擎会阻止正式加载，不会自行套用公司价格。

## 常见问题

**提示 command not found**  
检查 `command` 是否是绝对路径，并确认该文件存在：

```bash
ls -l /绝对路径/ryan-export-quote-engine/.venv/bin/export-quote-mcp
```

**MCP 显示红色或连接失败**  
先重新运行 `sh scripts/install_local.sh`，再完全重启 AI 产品。JSON 配置不能有中文引号、尾随逗号或注释。

**AI 没有调用计算工具**  
先查看 MCP 工具列表是否出现六个工具，再明确说“任何金额必须调用 `export_quote` 工具计算”。

**结果是 blocked**  
查看返回的缺项清单。缺运费、汇率、利润目标或有效证据时，正确行为就是停止正式报价，而不是把缺失值当成零。

**能不能直接操作 MOSS？**  
当前版本生成逐字段可复制的 MOSS 填写包，由人核对和提交，不会自动改变库存。以后有 MOSS API 时可替换适配层，不需要重写计算核心。

**如何更新项目？**  

```bash
cd /绝对路径/ryan-export-quote-engine
git pull
sh scripts/install_local.sh
```

## 安全底线

- 不把私有规则包、客户信息、飞书原始链接、真实报价快照提交到公开仓库。
- 对客只发对客报价稿，不发内部测算和完整 JSON。
- AI 可以准备 MOSS 内容，最终提交由人确认。
- `ready` 代表数据足以计算，不等于审批完成。
