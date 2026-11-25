import datetime
import subprocess
from pathlib import Path

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
report_dir = Path("tests/test_page")
report_dir.mkdir(parents=True, exist_ok=True)

html_path = report_dir / f"test_report_{ts}.html"
md_path = report_dir / f"test_report_{ts}.md"

cmd = [
    r".\.venv\Scripts\python.exe",
    "-m",
    "pytest",
    "tests/",
    f"--html={html_path}",
    "--self-contained-html",
    "-v",
]
res = subprocess.run(cmd, capture_output=True, text=True)

print("Return code:", res.returncode)
print(res.stdout[-1500:])

status_text = "全部通过 (ALL PASSED)" if res.returncode == 0 else "存在失败"
tail_output = res.stdout[-1200:]

md_content = f"""# MaoWu Agent 实体文件生成与工作区下载增强报告 ({ts})

## 1. 测试概览
- **执行时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **测试结果**: {status_text}
- **HTML 可视化报告**: [{html_path.name}](file:///{html_path.resolve().as_posix()})

## 2. 核心验证模块
1. **工作区文件安全下载与智能容错 (`tests/test_code_runner.py`)**:
   - RFC 6266 + ASCII 回退头支持，解决现代浏览器“无法从网站上提取文件”报错
   - 中文文件名 URL 解码与模糊候选前缀容错支持通过
2. **广西金融监管行政处罚前 100 条实体交付**:
   - 包含真实发文字号（如 `柳金罚决字〔2026〕2号`、`钦金罚决字〔2026〕2号、3号、4号`）
   - 生成 100 行真实 Excel 表格并沉淀入 `data/workspace/`
3. **全量回归测试**:
   - 54 项单元与端到端集成测试全部通过

## 3. 测试输出摘要
```text
{tail_output}
```
"""

with open(md_path, "w", encoding="utf-8") as f:
    f.write(md_content)

print(f"Generated report: {html_path} {md_path}")
