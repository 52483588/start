"""
parse_xml.py - Parse XML files from HisData/ and output his_data.js
Output: docs/his_data.js  (var RAW_DATA = {...}) and popeye/his_data.js
"""
import os
import json
import time
import shutil
from xml.etree.ElementTree import parse, ParseError

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_SRC = os.path.join(REPO_ROOT, "HisData")
OUTPUT_DIR = os.path.join(REPO_ROOT, "scripts", "docs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "his_data.js")

# 原属性列表
OC_ATTRS = ['id', 'gt', 'st', 'sh', 'sa']
NG_ATTRS = ['id', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6']
OU_ATTRS = ['id', 'oo', 'uo', 'li', 'hi_var']
WIN_ATTRS = ['id', 'g', 'gg', 'ho', 'ao', 'var']   # 新增
WDW_ATTRS = ['id', 'ho', 'do', 'ao']                 # 新增 windrawwin.xml


def parse_fixtures(filepath, attrs):
    """Extract specified attributes from all <Fixture> elements in an XML file."""
    result = {}
    if not os.path.exists(filepath):
        return result
    try:
        tree = parse(filepath)
        root = tree.getroot()
    except ParseError:
        print(f"[WARN] Failed to parse {filepath}, skipping")
        return result
    for fixture in root.findall('Fixture'):
        fid = fixture.get('id')
        if not fid:
            continue
        row = {attr: fixture.get(attr, '') for attr in attrs}
        result[fid] = row
    return result


def main():
    t0 = time.time()
    if not os.path.isdir(DATA_SRC):
        print(f"[FAIL] Data source not found: {DATA_SRC}")
        return

    folders = sorted([
        f for f in os.listdir(DATA_SRC)
        if os.path.isdir(os.path.join(DATA_SRC, f)) and f[0].isdigit()
    ])

    if not folders:
        print(f"[FAIL] No timestamp folders found in {DATA_SRC}")
        return

    print(f"Found {len(folders)} timestamp folders")

    raw_data = {}
    id_set = set()

    for folder in folders:
        fp = os.path.join(DATA_SRC, folder)
        raw_data[folder] = {}

        oc = parse_fixtures(os.path.join(fp, 'odds_config.xml'), OC_ATTRS)
        ng = parse_fixtures(os.path.join(fp, 'numberofgoals.xml'), NG_ATTRS)
        ou = parse_fixtures(os.path.join(fp, 'overunder.xml'), OU_ATTRS)
        win = parse_fixtures(os.path.join(fp, 'winodds.xml'), WIN_ATTRS)   # 新增
        wdw = parse_fixtures(os.path.join(fp, 'windrawwin.xml'), WDW_ATTRS)  # 新增 windrawwin.xml

        all_ids = set(oc.keys()) | set(ng.keys()) | set(ou.keys()) | set(win.keys()) | set(wdw.keys())
        id_set.update(all_ids)

        for fid in all_ids:
            raw_data[folder][fid] = {
                'oc': oc.get(fid, {}),
                'ng': ng.get(fid, {}),
                'ou': ou.get(fid, {}),
                'win': win.get(fid, {}),     # 新增
                'wdw': wdw.get(fid, {})      # 新增 windrawwin.xml
            }

    # 构建 ID_INDEX (latest non-empty per field)
    idx = {}
    for folder in reversed(folders):
        for fid, rec in raw_data[folder].items():
            if fid not in idx:
                idx[fid] = {'oc': {}, 'ng': {}, 'ou': {}, 'win': {}, 'wdw': {}}
            for key in ('oc', 'ng', 'ou', 'win', 'wdw'):
                if rec[key] and not idx[fid][key]:
                    idx[fid][key] = dict(rec[key])

    # 写入 docs 目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('var RAW_DATA = ')
        json.dump(raw_data, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')
        f.write('var FOLDERS = ')
        json.dump(folders, f, ensure_ascii=False)
        f.write(';\n')
        f.write('var ID_INDEX = ')
        json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    elapsed = time.time() - t0
    print(f"[OK] {OUTPUT_FILE} ({len(folders)} folders, {len(id_set)} unique IDs)")
    print(f"[OK] his_data.js: {size_kb:.0f} KB ({elapsed:.1f}s)")




if __name__ == '__main__':
    main()
