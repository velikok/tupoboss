import os
import sys
import time
import subprocess
import json
import tempfile
import concurrent.futures

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import requests

SUPPORT_ID = "1LFBWLLJ3Wl7vkzn8Fh4H6QVKhexMZ41VGaBRaOVEYhs"
ADMIN_ID = "1gce8NCNe6pw7Gti3QAr-C1EeQn4kiVwv6xRaj09mziM"

local_audit = os.path.join(os.path.dirname(__file__), "audit.py")
AUDIT_SCRIPT = local_audit if os.path.exists(local_audit) else os.path.expanduser(r"~/.gemini/config/skills/aqua-audit/scripts/audit.py")

_sheets_cache = {}
SHEETS_CACHE_TTL = 60 # seconds

def _export_single_sheet(sheet_id, output_path, timeout=60):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        r = requests.get(url, timeout=25, allow_redirects=True)
        if r.status_code == 200 and r.content[:2] == b'PK':
            with open(output_path, "wb") as f:
                f.write(r.content)
            return None
    except Exception:
        pass
    cmd = ["gsheets.cmd", "readonly", "export", sheet_id, output_path, "--format", "xlsx"]
    return subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=timeout)

def run_sheets_audit():
    now = time.time()
    if "latest_report" in _sheets_cache:
        cached_text, cached_at = _sheets_cache["latest_report"]
        if now - cached_at < SHEETS_CACHE_TTL:
            return cached_text

    temp_dir = tempfile.gettempdir()
    support_xlsx = os.path.join(temp_dir, "tg_support.xlsx")
    admin_xlsx = os.path.join(temp_dir, "tg_admin.xlsx")
    
    # 1. Parallel Export of both spreadsheets
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(_export_single_sheet, SUPPORT_ID, support_xlsx, 60)
            fut2 = executor.submit(_export_single_sheet, ADMIN_ID, admin_xlsx, 60)
            fut1.result()
            fut2.result()
    except Exception as e:
        return f"❌ Ошибка экспорта таблиц: {e}"
        
    if not os.path.exists(support_xlsx) or not os.path.exists(admin_xlsx):
        return (
            "❌ <b>Не удалось скачать Google Таблицы на сервере (Ошибка 401: Ограниченный доступ).</b>\n\n"
            "Таблицы защищены приватностью Google. Чтобы бот на сервере мог их читать:\n"
            "1. Откройте обе таблицы в браузере.\n"
            "2. В правом верхнем углу нажмите <b>«Поделиться» / «Настройки доступа»</b>.\n"
            "3. Измените «Ограниченный доступ» на <b>«Все, у кого есть ссылка: Читатель»</b>.\n\n"
            "После этого бот сможет загружать таблицы напрямую без авторизации!"
        )
        
    # 2. Audit script
    audit_cmd = ["python", AUDIT_SCRIPT, "--support", support_xlsx, "--admin", admin_xlsx]
    try:
        res = subprocess.run(audit_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30)
        if res.returncode != 0:
            return f"❌ Ошибка парсера таблиц: {res.stderr}"
        data = json.loads(res.stdout)
    except Exception as e:
        return f"❌ Ошибка обработки данных: {e}"
        
    # 3. Format message
    lines = ["📊 <b>ОТЧЕТ ПО GOOGLE ТАБЛИЦАМ (AQUA)</b>\n"]
    
    # Support
    lines.append("👥 <b>АГЕНТЫ ПОДДЕРЖКИ:</b>")
    rep_sup = data.get("support", {}).get("reprimand_3_3", [])
    if rep_sup:
        lines.append(f"🚨 <b>Сотрудники с 3/3 выговорами ({len(rep_sup)}):</b>")
        for it in rep_sup:
            lines.append(f"  • {it['nick']} (стр. {it['row']})")
    else:
        lines.append("✅ Сотрудников с 3/3 выговорами нет.")
        
    red_sup = data.get("support", {}).get("red_highlighted", [])
    if red_sup:
        lines.append(f"🔴 <b>Покрашенные в красный ({len(red_sup)}):</b>")
        for it in red_sup:
            lines.append(f"  • {it['nick']}")
    else:
        lines.append("✅ Покрашенных в красный сотрудников нет.")
        
    month_st = data.get("support", {}).get("month_sheet", {})
    last_full_m = month_st.get("last_fully_set_date") or "Нет данных"
    lines.append(f"📅 <b>Лист месяца:</b> {month_st.get('title', '')}")
    lines.append(f"  • Норма выставлена <b>полностью</b> за: <b>{last_full_m}</b>")
    
    # Recent partial days
    stats_m = month_st.get("stats", [])
    recent_partial = [s for s in stats_m if not s.get("is_full") and s.get("filled", 0) > 0]
    if recent_partial:
        lines.append("  • <i>Частично выставлено:</i>")
        for p in recent_partial[-3:]:
            lines.append(f"    - {p['date']}: {p['filled']}/{p['total']} (не выставлено у {p.get('new', 0)})")
            
    lines.append("\n👑 <b>АДМИНИСТРАЦИЯ:</b>")
    rep_adm = data.get("admin", {}).get("reprimand_3_3", [])
    if rep_adm:
        lines.append(f"🚨 <b>Администраторы с 3/3 выговорами ({len(rep_adm)}):</b>")
        for it in rep_adm:
            lines.append(f"  • {it['nick']} (стр. {it['row']})")
    else:
        lines.append("✅ Администраторов с 3/3 выговорами нет.")
        
    red_adm = data.get("admin", {}).get("red_highlighted", [])
    if red_adm:
        lines.append(f"🔴 <b>Покрашенные в красный ({len(red_adm)}):</b>")
        for it in red_adm:
            lines.append(f"  • <b>{it['nick']}</b> ({it.get('role', '')}) — выговоры: {it.get('reprimands', '-')}")
    else:
        lines.append("✅ Покрашенных в красный администраторов нет.")
        
    week_st = data.get("admin", {}).get("current_week", {})
    last_full_w = week_st.get("last_fully_set_date") or "Нет данных"
    lines.append(f"📅 <b>Лист текущей недели:</b> {week_st.get('title', '')}")
    lines.append(f"  • Норма выставлена <b>полностью</b> за: <b>{last_full_w}</b>")
    
    stats_w = week_st.get("stats", [])
    recent_w = [s for s in stats_w if not s.get("is_full") and s.get("filled", 0) > 0]
    if recent_w:
        lines.append("  • <i>Частично выставлено:</i>")
        for p in recent_w[-3:]:
            lines.append(f"    - {p['date']}: {p['filled']}/{p['total']} (пусто: {p.get('empty', 0)})")
            
    final_report = "\n".join(lines)
    _sheets_cache["latest_report"] = (final_report, now)
    return final_report
