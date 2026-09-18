# Export Quote Engine

一个面向整车出口的可审计报价计算核心。AI 负责理解询价、整理证据和解释结果；金额由同一套 Python 十进制规则计算，因此 Codex、DeepSeek/DSH 或其他 MCP 客户端会得到一致结果。

## 能做什么

- 分别计算车源、运输、资金成本，支持按车、批次、柜、天、比例和年化计息。
- 支持多车型、多币种、承担方、批次分摊、费用打包、退税抵减和集采分润。
- 把缺失金额与 `0` 分开；过期、冲突和待确认依据会阻止正式报价。
- 输出内部测算、方案比较、对客报价和 MOSS 填写包。
- 每次计算保留输入、规则版本、证据、计算过程和内容哈希。

公开仓库只包含通用代码和虚构样例。公司规则、真实价格、客户、飞书链接及报价快照应放在操作系统权限隔离的私有目录。

## 安装与一句话调用

```bash
git clone https://github.com/yuyiming-ship-it/ryan-export-quote-engine.git
cd ryan-export-quote-engine
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp]'
.venv/bin/export-quote calculate examples/standard.json
```

配置 Skill/MCP 后，日常可直接说：

> 按这份询价比较车源、运输和资金方案，给出建议售价，并准备 MOSS 填写材料。

命令行示例：

```bash
export EXPORT_QUOTE_RULES=/secure/company-rules/approved-v1.json
export EXPORT_QUOTE_STORE=/secure/quote-snapshots
export EXPORT_QUOTE_MOSS_MAPPING=/secure/company-rules/moss-mapping.json

export-quote validate inquiry.json
export-quote calculate inquiry.json --out result.json
export-quote compare scenarios.json
export-quote customer result.json
export-quote export-moss result.json --mapping "$EXPORT_QUOTE_MOSS_MAPPING"
```

输入格式见 [schemas/quote-request.schema.json](schemas/quote-request.schema.json)，完整虚构样例见 [examples/standard.json](examples/standard.json) 和 [examples/central.json](examples/central.json)。金额、费率及汇率必须用十进制字符串，不能传 JSON 浮点数。

## MCP 与 DSH

服务器通过 stdio 暴露五个工具：`normalize_request`、`validate_quote`、`calculate_quote`、`compare_quotes`、`export_moss`。

通用 MCP 配置：

```json
{
  "mcpServers": {
    "export_quote": {
      "command": "/absolute/path/.venv/bin/export-quote-mcp",
      "env": {
        "EXPORT_QUOTE_RULES": "/secure/company-rules/approved-v1.json",
        "EXPORT_QUOTE_STORE": "/secure/quote-snapshots",
        "EXPORT_QUOTE_MOSS_MAPPING": "/secure/company-rules/moss-mapping.json"
      }
    }
  }
}
```

DSH overlay 示例见 [integrations/dsh-overlay.yaml](integrations/dsh-overlay.yaml)。它使用 DSH 的 MCP client 插件，把五个工具暴露为 `mcp__export_quote__*`。DSH 仍处于开发者预览阶段，首次使用需按宿主版本核对 profile/patch 参数。

## 工作流和状态

1. `normalize_request` 保留原文，不猜价格。
2. AI 集中补齐车型、交易边界、费用、来源和有效期。
3. `validate_quote` 返回结构化缺项。`blocked` 不可对外，`conditional` 只表示带假设测算，`ready` 也不等于业务审批通过。
4. `calculate_quote` 计算并保存不可覆盖快照。
5. `compare_quotes` 仅比较交易边界一致的方案。任一候选缺少交期或垫资指标时，相应维度不排名。
6. 人选方案后生成对客稿和 MOSS 填写包，由人核对并提交。

贸易术语只作为适用范围字段；系统不会看到 `FOB/CIF` 就自行增删费用。资金费应拆成实际占款阶段。合作结算价是结果，不会再次计入完整成本。

## 私有规则包

规则先生成候选版本，再由负责人用内容哈希批准为新文件：

```bash
export-quote rules-diff candidate.json --rules approved-v1.json
HASH=$(python -c 'import json;from export_quote.engine import digest;print(digest(json.load(open("candidate.json"))))')
export-quote rules-approve candidate.json --reviewer reviewer --expected-hash "$HASH" --out approved-v2.json
```

引擎只加载 `status=confirmed` 且带批准元数据的规则包；单条未确认规则也不会启用。历史结果嵌入当时的输入与规则快照，更新规则不会重算历史。

本地文件权限只是单机边界。如果以共享服务部署，必须在服务层增加用户认证、规则包授权和租户隔离，不能把个人飞书凭证或规则目录共享给全团队。

## MOSS 边界

当前版本只生成经过核验的字段和值，以及无法映射字段清单；不自动点击提交，也不改变库存。字段映射必须记录页面、字段单位、核验方式和证据。页面没有对应字段时，内容留在 `unmapped`，不会塞入“其他费用”。未来接入 MOSS API 时只替换适配层，计算核心不变。

## 开发与验证

```bash
python -m unittest discover -s tests -v
python scripts/privacy_scan.py .
```

项目使用 Python 标准库完成计算；MCP 是可选依赖。当前测试覆盖多币种、混合车型、分摊、资金计息、费用已含、共同承担、集采分润、过期/冲突/缺项、快照防篡改和对客脱敏。

历史资料检索工具 [scripts/collect_evidence.py](scripts/collect_evidence.py) 只负责分页保存可访问证据和覆盖记录。关键词检索不能证明“已读完全部历史”；附件、图片表格、删除内容、权限外资料及服务端搜索召回都是明确缺口。
