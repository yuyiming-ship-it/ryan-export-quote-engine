#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${PYTHON_BIN:-python3}

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "未找到 python3。请先安装 Python 3.10 或更高版本。" >&2
  exit 1
fi

if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 版本过低，需要 Python 3.10 或更高版本。" >&2
  "$python_bin" --version >&2
  exit 1
fi

echo "1/3 创建独立 Python 环境"
"$python_bin" -m venv "$project_dir/.venv"

echo "2/3 安装报价引擎和 MCP 组件"
"$project_dir/.venv/bin/python" -m pip install --upgrade pip
"$project_dir/.venv/bin/python" -m pip install -e "$project_dir[mcp]"

echo "3/3 使用虚构样例验证计算"
check_dir=$(mktemp -d "${TMPDIR:-/tmp}/export-quote-check.XXXXXX")
trap 'rm -rf "$check_dir"' EXIT HUP INT TERM
EXPORT_QUOTE_STORE="$check_dir/snapshots" \
  "$project_dir/.venv/bin/export-quote" calculate "$project_dir/examples/standard.json" --out "$check_dir/result.json"

echo "安装和样例计算均成功。"
echo "MCP 命令：$project_dir/.venv/bin/export-quote-mcp"
echo "下一步请阅读：$project_dir/docs/QUICKSTART.zh-CN.md"
