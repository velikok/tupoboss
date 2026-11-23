#!/usr/bin/env python3
"""
AQUA Sheets Audit Script
Checks:
- Support Agents and Administration for 3/3 reprimands
- Support Agents and Administration for red cell highlight
- Support Agents: current month sheet (e.g. Ноябрь 2026) last norm date & full completion
- Administration: current week sheet (e.g. 16.11.2026-22.11.2026) last norm date & full completion
"""

import sys
import os
import re
import json
import zipfile
import tempfile
import subprocess
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

SUPPORT_SPREADSHEET_ID = "1LFBWLLJ3Wl7vkzn8Fh4H6QVKhexMZ41VGaBRaOVEYhs"
ADMIN_SPREADSHEET_ID = "1gce8NCNe6pw7Gti3QAr-C1EeQn4kiVwv6xRaj09mziM"

def excel_date_to_str(serial):
    try:
        f = float(serial)
        base = datetime(1899, 12, 30)
        dt = base + timedelta(days=f)
        return dt.strftime("%d.%m.%Y")
    except:
        return str(serial)

def parse_xlsx_sheets(z):
    ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    
    wb_rels = {}
    if 'xl/_rels/workbook.xml.rels' in z.namelist():
        rels_tree = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        for rel in rels_tree:
            wb_rels[rel.attrib.get('Id')] = 'xl/' + rel.attrib.get('Target').lstrip('/')
    
    wb_tree = ET.fromstring(z.read('xl/workbook.xml'))
    sheets = {}
    for s in wb_tree.findall('.//main:sheet', ns):
        s_name = s.attrib.get('name')
        r_id = s.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        sheet_path = wb_rels.get(r_id)
        sheets[s_name] = sheet_path
        
    shared_strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        ss_tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in ss_tree.findall('.//main:si', ns):
            texts = [t.text for t in si.findall('.//main:t', ns) if t.text]
            shared_strings.append(''.join(texts))
    
    styles_tree = ET.fromstring(z.read('xl/styles.xml'))
    fills = []
    for fill in styles_tree.findall('.//main:fill', ns):
        pat = fill.find('main:patternFill', ns)
        if pat is not None:
            fg = pat.find('main:fgColor', ns)
            bg = pat.find('main:bgColor', ns)
            fg_rgb = fg.attrib.get('rgb') if fg is not None else None
            bg_rgb = bg.attrib.get('rgb') if bg is not None else None
            fills.append({'fg': fg_rgb, 'bg': bg_rgb})
        else:
            fills.append({})
    
    fonts = []
    for font in styles_tree.findall('.//main:font', ns):
        col = font.find('main:color', ns)
        col_rgb = col.attrib.get('rgb') if col is not None else None
        fonts.append({'color': col_rgb})
    
    cell_xfs = []
    for xf in styles_tree.findall('.//main:cellXfs/main:xf', ns):
        fill_id = int(xf.attrib.get('fillId', 0))
        font_id = int(xf.attrib.get('fontId', 0))
        cell_xfs.append({'fillId': fill_id, 'fontId': font_id})
        
    return sheets, shared_strings, fills, fonts, cell_xfs

def read_sheet_cells(z, sheet_rel, shared_strings, fills, fonts, cell_xfs):
    ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheet_tree = ET.fromstring(z.read(sheet_rel))
    rows = {}
    for row in sheet_tree.findall('.//main:row', ns):
        r_idx = int(row.attrib.get('r'))
        rows[r_idx] = {}
        for c in row.findall('main:c', ns):
            r_coord = c.attrib.get('r')
            col_letters = ''.join([ch for ch in r_coord if ch.isalpha()])
            col_num = 0
            for ch in col_letters:
                col_num = col_num * 26 + (ord(ch.upper()) - ord('A') + 1)
            
            s_idx = int(c.attrib.get('s', 0))
            t_type = c.attrib.get('t')
            v_elem = c.find('main:v', ns)
            val = v_elem.text if v_elem is not None else None
            if t_type == 's' and val is not None and int(val) < len(shared_strings):
                val = shared_strings[int(val)]
            elif t_type == 'inlineStr':
                is_elem = c.find('.//main:t', ns)
                val = is_elem.text if is_elem is not None else None
            
            fill_info = fills[cell_xfs[s_idx]['fillId']] if s_idx < len(cell_xfs) and cell_xfs[s_idx]['fillId'] < len(fills) else {}
            font_info = fonts[cell_xfs[s_idx]['fontId']] if s_idx < len(cell_xfs) and cell_xfs[s_idx]['fontId'] < len(fonts) else {}
            
            rows[r_idx][col_num] = {
                'coord': r_coord,
                'val': val,
                'fill': fill_info,
                'font': font_info
            }
    return rows

def is_red(color_str):
    if not color_str:
        return False
    clean_hex = str(color_str).upper()
    if len(clean_hex) == 8:
        clean_hex = clean_hex[2:]
    if len(clean_hex) != 6:
        return False
    try:
        r = int(clean_hex[0:2], 16)
        g = int(clean_hex[2:4], 16)
        b = int(clean_hex[4:6], 16)
        known_reds = ['EA9999', 'E06666', 'CC0000', 'FF0000', 'F4CCCC', 'E6B8AF', 'DD7E6B', 'FF4C4C', 'FF5B5B', 'E53935']
        if clean_hex in known_reds:
            return True
        if r > 180 and g < 130 and b < 130:
            return True
        if r > 220 and g < 180 and b < 180 and (r - max(g, b) > 30):
            return True
        return False
    except:
        return False

def export_sheet(spreadsheet_id, output_path):
    possible_bins = [
        r"C:\Users\velik\.gemini\antigravity\plugin_data\gsheets\bin\gsheets-986250228.exe",
        r"C:\Users\velik\.gemini\antigravity\bin\gsheets.cmd",
        "gsheets.cmd",
        "gsheets"
    ]
    gsheets_bin = "gsheets"
    for b in possible_bins:
        if os.path.exists(b):
            gsheets_bin = b
            break

    cmd = [gsheets_bin, "readonly", "export", spreadsheet_id, output_path, "--format", "xlsx"]
    res = subprocess.run(cmd, capture_output=True, text=True, shell=(os.name == 'nt'))
    if res.returncode != 0:
        raise RuntimeError(f"Failed to export {spreadsheet_id}: {res.stderr}")

def run_audit(support_xlsx, admin_xlsx, today=None):
    if today is None:
        today = datetime.now()
        
    report = {
        "timestamp": today.strftime("%Y-%m-%d %H:%M:%S"),
        "support": {},
        "admin": {}
    }
    
    # 1. SUPPORT
    with zipfile.ZipFile(support_xlsx, 'r') as z_sup:
        sup_sheets, ss_sup, fills_sup, fonts_sup, xfs_sup = parse_xlsx_sheets(z_sup)
        
        ap_sheet_rel = sup_sheets.get("Таблица АП")
        if ap_sheet_rel:
            rows_ap = read_sheet_cells(z_sup, ap_sheet_rel, ss_sup, fills_sup, fonts_sup, xfs_sup)
            rep_3_agents = []
            red_agents = []
            for r_idx in sorted(rows_ap.keys()):
                r_data = rows_ap[r_idx]
                nick = r_data.get(1, {}).get('val')
                if not nick:
                    continue
                rep_val = r_data.get(7, {}).get('val')
                if rep_val and '3 из 3' in str(rep_val):
                    rep_3_agents.append({"row": r_idx, "nick": nick, "val": str(rep_val)})
                
                is_row_red = False
                for c_idx, c_info in r_data.items():
                    fg = c_info.get('fill', {}).get('fg')
                    bg = c_info.get('fill', {}).get('bg')
                    font_c = c_info.get('font', {}).get('color')
                    if is_red(fg) or is_red(bg) or is_red(font_c):
                        is_row_red = True
                        break
                if is_row_red:
                    red_agents.append({"row": r_idx, "nick": nick})
                    
            report["support"]["reprimand_3_3"] = rep_3_agents
            report["support"]["red_highlighted"] = red_agents
        
        month_names_ru = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", 
                          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        cur_month_title = f"{month_names_ru[today.month - 1]} {today.year}"
        nov_sheet_rel = sup_sheets.get(cur_month_title) or sup_sheets.get("Ноябрь 2026")
        if nov_sheet_rel:
            rows_nov = read_sheet_cells(z_sup, nov_sheet_rel, ss_sup, fills_sup, fonts_sup, xfs_sup)
            header = rows_nov.get(1, {})
            header_dates = {}
            for c in range(5, 35):
                val = header.get(c, {}).get('val')
                if val:
                    header_dates[c] = excel_date_to_str(val)
                    
            agent_rows = [r for r in sorted(rows_nov.keys()) if r > 1 and rows_nov[r].get(1, {}).get('val') and '_' in str(rows_nov[r].get(1, {}).get('val'))]
            
            dates_stat = []
            last_fully_set_date = None
            last_partially_set_date = None
            
            for c, d_str in sorted(header_dates.items()):
                filled = 0
                new_cnt = 0
                just_started = 0
                empty = 0
                missing_nicks = []
                for r in agent_rows:
                    nick = rows_nov[r].get(1, {}).get('val')
                    v = rows_nov[r].get(c, {}).get('val')
                    if v is None or str(v).strip() == '':
                        empty += 1
                        missing_nicks.append(nick)
                    elif str(v).strip().upper() == 'NEW':
                        new_cnt += 1
                        missing_nicks.append(nick)
                    elif 'Только встал' in str(v):
                        just_started += 1
                    else:
                        filled += 1
                        
                is_full = (filled > 0 and new_cnt == 0 and empty == 0)
                if is_full:
                    last_fully_set_date = d_str
                if filled > 0:
                    last_partially_set_date = d_str
                    
                dates_stat.append({
                    "date": d_str,
                    "filled": filled,
                    "total": len(agent_rows),
                    "new": new_cnt,
                    "just_started": just_started,
                    "empty": empty,
                    "is_full": is_full,
                    "missing": missing_nicks
                })
                
            report["support"]["month_sheet"] = {
                "title": cur_month_title,
                "last_fully_set_date": last_fully_set_date,
                "last_active_date": last_partially_set_date,
                "stats": dates_stat
            }
        
    # 2. ADMIN
    with zipfile.ZipFile(admin_xlsx, 'r') as z_adm:
        adm_sheets, ss_adm, fills_adm, fonts_adm, xfs_adm = parse_xlsx_sheets(z_adm)
        
        adm_main_rel = adm_sheets.get("Администрация AQUA")
        if adm_main_rel:
            rows_adm = read_sheet_cells(z_adm, adm_main_rel, ss_adm, fills_adm, fonts_adm, xfs_adm)
            rep_3_admins = []
            red_admins = []
            for r_idx in sorted(rows_adm.keys()):
                r_data = rows_adm[r_idx]
                nick = r_data.get(1, {}).get('val') or r_data.get(2, {}).get('val')
                if not nick:
                    continue
                
                rep_3 = False
                for c_idx, c_info in r_data.items():
                    v = str(c_info.get('val', ''))
                    if '3 из 3' in v or '3/3' in v:
                        rep_3 = True
                        break
                if rep_3:
                    rep_3_admins.append({"row": r_idx, "nick": nick})
                    
                is_row_red = False
                for c_idx, c_info in r_data.items():
                    fg = c_info.get('fill', {}).get('fg')
                    bg = c_info.get('fill', {}).get('bg')
                    font_c = c_info.get('font', {}).get('color')
                    if is_red(fg) or is_red(bg) or is_red(font_c):
                        is_row_red = True
                        break
                if is_row_red and '_' in str(nick):
                    role = r_data.get(3, {}).get('val', '')
                    rep_col = r_data.get(10, {}).get('val', '')
                    red_admins.append({"row": r_idx, "nick": nick, "role": role, "reprimands": rep_col})
                    
            report["admin"]["reprimand_3_3"] = rep_3_admins
            report["admin"]["red_highlighted"] = red_admins
            
        # Find current calendar week sheet (e.g. 16.11.2026-22.11.2026)
        week_sheet_title = None
        for s_title in adm_sheets.keys():
            m = re.match(r'(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})', s_title.strip())
            if m:
                try:
                    d_start = datetime.strptime(m.group(1), "%d.%m.%Y")
                    d_end = datetime.strptime(m.group(2), "%d.%m.%Y")
                    if d_start.date() <= today.date() <= d_end.date():
                        week_sheet_title = s_title
                        break
                except Exception:
                    continue
                    
        if not week_sheet_title:
            for s_title in adm_sheets.keys():
                if re.match(r'\d{2}\.\d{2}\.\d{4}-\d{2}\.\d{2}\.\d{4}', s_title.strip()):
                    week_sheet_title = s_title
                    break
                    
        if week_sheet_title:
            week_rel = adm_sheets.get(week_sheet_title)
            rows_w = read_sheet_cells(z_adm, week_rel, ss_adm, fills_adm, fonts_adm, xfs_adm)
            header = rows_w.get(1, {})
            week_dates = {}
            for c in range(6, 13):
                v = header.get(c, {}).get('val')
                if v:
                    week_dates[c] = excel_date_to_str(v)
                    
            admin_rows = [r for r in sorted(rows_w.keys()) if r > 1 and rows_w[r].get(1, {}).get('val') and '_' in str(rows_w[r].get(1, {}).get('val'))]
            
            week_stats = []
            last_full_week_date = None
            for c, d_str in sorted(week_dates.items()):
                filled = 0
                empty = 0
                for r in admin_rows:
                    v = rows_w[r].get(c, {}).get('val')
                    if v is not None and str(v).strip() != '':
                        filled += 1
                    else:
                        empty += 1
                is_full = (filled >= len(admin_rows) - 2)
                if is_full:
                    last_full_week_date = d_str
                week_stats.append({
                    "date": d_str,
                    "filled": filled,
                    "total": len(admin_rows),
                    "empty": empty,
                    "is_full": is_full
                })
                
            report["admin"]["current_week"] = {
                "title": week_sheet_title,
                "last_fully_set_date": last_full_week_date,
                "stats": week_stats
            }
        
    return report

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Audit AQUA Spreadsheets")
    parser.add_argument("--support", help="Path to exported Support Agents xlsx", required=True)
    parser.add_argument("--admin", help="Path to exported Administration xlsx", required=True)
    args = parser.parse_args()
    
    report = run_audit(args.support, args.admin)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()