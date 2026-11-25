# -*- coding: utf-8 -*-
"""
国家金融监督管理总局（广西监管局）行政处罚信息公开表批量采集脚本
功能：自动分页请求 NFRA 内部 JSON 接口，抓取各分局及区局前 100 条行政处罚，提取发文字号并导出为 Excel 表格
"""
import json
import re
import urllib.request
import ssl
import pandas as pd
from pathlib import Path

BASE_API = "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nfra.gov.cn/branch/guangxi/view/pages/common/ItemList.html",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_list_page(item_id: int, page_index: int, page_size: int = 20) -> list:
    url = f"{BASE_API}?itemId={item_id}&pageSize={page_size}&pageIndex={page_index}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        ctx = create_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("rows", [])
    except Exception as e:
        print(f"[-] 请求栏目 {item_id} 第 {page_index} 页异常: {e}")
    return []


def extract_doc_num(text: str) -> str:
    if not text:
        return "见详情公开表"
    m = re.search(r"[\u4e00-\u9fa5]{1,8}金罚决字〔\d{4}〕[0-9\-、号\s]+", text)
    if m:
        return m.group(0).strip()
    m2 = re.search(r"[\u4e00-\u9fa5]{1,8}罚决字〔\d{4}〕[0-9\-、号\s]+", text)
    if m2:
        return m2.group(0).strip()
    return "见详情公开表"


def extract_authority(title: str) -> str:
    if not title:
        return "广西金融监管部门"
    m = re.search(r"[\u4e00-\u9fa5]{2,6}监管[分]?局", title)
    if m:
        return m.group(0)
    return "广西金融监管部门"


def main():
    print("[*] 开始采集广西监管局及辖区分局行政处罚数据，目标：100 条...")
    all_rows = []

    # 1. 抓取 1635（各监管分局：柳州、钦州、玉林、崇左、梧州等）
    page = 1
    while len(all_rows) < 100 and page <= 10:
        rows = fetch_list_page(1635, page, 20)
        if not rows:
            break
        print(f"[+] 栏目 1635（分局）第 {page} 页获取到 {len(rows)} 条")
        all_rows.extend(rows)
        page += 1

    # 2. 若不足 100 条补充 1634（区局本级）
    page_1634 = 1
    while len(all_rows) < 100 and page_1634 <= 10:
        rows = fetch_list_page(1634, page_1634, 20)
        if not rows:
            break
        print(f"[+] 栏目 1634（区局）第 {page_1634} 页获取到 {len(rows)} 条")
        all_rows.extend(rows)
        page_1634 += 1

    all_rows = all_rows[:100]
    print(f"[*] 成功获取 {len(all_rows)} 条记录，正在整理并导出 Excel...")

    excel_data = []
    for idx, r in enumerate(all_rows, 1):
        title = r.get("docSubtitle") or r.get("docTitle") or ""
        title = title.replace("\n", " ").strip()
        publish_date = (r.get("publishDate") or "")[:10]
        doc_id = r.get("docId")
        doc_num = extract_doc_num(title)
        authority = extract_authority(title)
        detail_url = f"https://www.nfra.gov.cn/branch/guangxi/view/pages/common/ItemDetail.html?docId={doc_id}&itemId=1614"

        pdf_path = r.get("pdfFileUrl")
        pdf_url = f"https://www.nfra.gov.cn{pdf_path}" if pdf_path else "无"
        doc_path = r.get("docFileUrl")
        doc_url = f"https://www.nfra.gov.cn{doc_path}" if doc_path else "无"

        excel_data.append({
            "序号": idx,
            "发文字号（决定书文号）": doc_num,
            "行政处罚信息公开表标题": title,
            "发布日期": publish_date,
            "作出决定机关": authority,
            "文档ID": doc_id,
            "官网详情直达链接": detail_url,
            "官方PDF直链": pdf_url,
            "官方DOC直链": doc_url,
        })

    df = pd.DataFrame(excel_data)
    workspace = Path("data/workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    out1 = workspace / "广西行政处罚_前100条.xlsx"
    out2 = workspace / "广西金融监管局_行政处罚信息公开表_前100条.xlsx"

    df.to_excel(out1, index=False)
    df.to_excel(out2, index=False)

    print(f"[√] 成功生成 Excel 文件：{out1} (共 {len(df)} 行)")
    print(f"[√] 成功生成别名文件：{out2} (共 {len(df)} 行)")


if __name__ == "__main__":
    main()
