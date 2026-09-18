"""Five stdio tools; rule and mapping paths belong to host config, never model input."""
import os
from mcp.server.fastmcp import FastMCP
from . import engine
from .outputs import export_moss as render_moss
from .storage import load_rules, read_json, save_snapshot
from .feishu import read_json_source

server = FastMCP('export-quote')


@server.tool()
def normalize_request(request: dict) -> dict:
    """整理询价结构；不猜测费用或数量。"""
    return engine.normalize_request(request)


@server.tool()
def screen_funders(request: dict) -> dict:
    """按贸易方式、目的地和结构化付款条件筛选已确认资金政策。"""
    return engine.screen_funders(request, load_rules())


@server.tool()
def validate_quote(request: dict) -> dict:
    """检查缺项、有效期、重复费用、适用条件和承担比例。"""
    return engine.validate_quote(request, load_rules())


@server.tool()
def calculate_quote(request: dict) -> dict:
    """按十进制规则计算成本、建议售价和集采分配，并保存私有快照。"""
    result = engine.calculate_quote(request, load_rules())
    save_snapshot(result)
    return result


@server.tool()
def compare_quotes(requests: list[dict]) -> dict:
    """比较相同交易边界的方案；未知指标不排名。"""
    result = engine.compare_quotes(requests, load_rules())
    for item in result['quotes']:
        save_snapshot(item)
    return result


@server.tool()
def export_moss(result: dict) -> dict:
    """生成 MOSS 填写包；不操作线上系统，也不提交审批。"""
    path = os.environ.get('EXPORT_QUOTE_MOSS_MAPPING')
    return render_moss(result, read_json_source(path) if path else None)


def main():
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
