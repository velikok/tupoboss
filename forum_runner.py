import os
import time
import subprocess
import json
import html

local_script = os.path.join(os.path.dirname(__file__), "forum_audit.py")
FORUM_AUDIT_SCRIPT = local_script if os.path.exists(local_script) else os.path.expanduser(r"~/.gemini/config/skills/forum-audit/scripts/forum_audit.py")

SECTION_NAMES = {
    "appeals": "Обжалование наказаний",
    "admin_complaints": "Жалобы на администрацию",
    "player_complaints": "Жалобы на игроков",
    "rp_situations": "РП-ситуации (+ доработка)",
    "rp_biographies": "РП-биографии (+ доработка)",
    "rp_organizations": "Неофициальные RP-организации (+ доработка)"
}

_cache = {}
CACHE_TTL = 90 # seconds

def fix_mojibake(s):
    if not s or not isinstance(s, str):
        return s
    if any(x in s for x in ["Р–", "Р°", "Рѕ", "РЅ", "Рё", "СЂ", "РІ", "Рє", "Рј", "Рћ", "Рќ", "Р”"]):
        try:
            return s.encode("windows-1251").decode("utf-8")
        except Exception:
            pass
    return s

def fetch_forum_data(section=None, skip_summaries=True):
    now = time.time()
    cache_key = f"{section}_{skip_summaries}"
    if cache_key in _cache:
        cached_data, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return cached_data
            
    cmd = ["python", FORUM_AUDIT_SCRIPT]
    if section:
        cmd.extend(["--section", section])
    if skip_summaries:
        cmd.append("--skip-summaries")
        
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=150)
        idx = res.stdout.find('{')
        if idx != -1:
            data = json.loads(res.stdout[idx:])
            # Only cache if data actually contains threads
            has_threads = any(
                len(s.get("in_progress", [])) > 0 or len(s.get("overdue", [])) > 0
                for s in data.get("sections", {}).values()
            )
            if has_threads:
                _cache[cache_key] = (data, now)
            return data
        return None
    except Exception as e:
        print("Forum fetch error:", e)
        return None

def extract_urgent_threads(in_prog_list, max_hours=5):
    urgent_list = []
    for it in in_prog_list:
        t_str = it.get("time_left_str", "")
        if " ч." in t_str:
            try:
                h = int(t_str.split(" ч.")[0].strip().split()[-1])
                if h < max_hours:
                    urgent_list.append(it)
            except:
                pass
        elif " мин." in t_str and " ч." not in t_str:
            urgent_list.append(it)
    return urgent_list

def get_overdue_and_urgent_report():
    data = fetch_forum_data(skip_summaries=True)
    if not data:
        return "❌ Не удалось получить данные с форума. Попробуйте позже."
        
    has_overdue = False
    section_blocks = []
    
    for sec_id, s in data.get("sections", {}).items():
        name = SECTION_NAMES.get(sec_id, fix_mojibake(s.get("title", sec_id)))
        overdue_list = s.get("overdue", [])
        urgent_list = extract_urgent_threads(s.get("in_progress", []))
                
        if overdue_list or urgent_list:
            has_overdue = True
            sec_lines = []
            if overdue_list:
                sec_lines.append(f"📁 🔴 <b>{name} (ПРОСРОЧЕНО: {len(overdue_list)}):</b>")
            else:
                sec_lines.append(f"📁 ⏳ <b>{name} (ГОРЯЩИХ: {len(urgent_list)}):</b>")
                
            for ov in overdue_list:
                title = html.escape(fix_mojibake(ov.get('title', 'Без названия')))
                author = html.escape(fix_mojibake(ov.get('author', '')))
                url = ov.get('url', '')
                t_str = ov.get('time_left_str', '')
                prefix = html.escape(fix_mojibake(ov.get('prefix', ''))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                sec_lines.append(f"  🔴 <b>[ПРОСРОЧЕНО]</b>{prefix_badge} <a href='{url}'><b>{title}</b></a>")
                sec_lines.append(f"     👤 Автор: <code>{author}</code> | 🚨 <b>{t_str}</b>")
            for ug in urgent_list:
                title = html.escape(fix_mojibake(ug.get('title', 'Без названия')))
                author = html.escape(fix_mojibake(ug.get('author', '')))
                url = ug.get('url', '')
                t_str = ug.get('time_left_str', '')
                prefix = html.escape(fix_mojibake(ug.get('prefix', ''))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                sec_lines.append(f"  ⏳ <b>[СРОЧНО]</b>{prefix_badge} <a href='{url}'><b>{title}</b></a>")
                sec_lines.append(f"     👤 Автор: <code>{author}</code> | ⏱ Осталось: <b>{t_str}</b>")
            section_blocks.append("\n".join(sec_lines))
            
    if has_overdue:
        header = "🚨🚨🚨 <b>ВНИМАНИЕ! ОБНАРУЖЕНЫ ПРОСРОЧКИ НА ФОРУМЕ!</b> 🚨🚨🚨\n"
        return header + "\n\n".join(section_blocks)
    elif section_blocks:
        header = "⏳ <b>ГОРЯЩИЕ ТЕМЫ НА ФОРУМЕ (ДО 5 ЧАСОВ ДО ДЕДЛАЙНА)</b>\n"
        return header + "\n\n".join(section_blocks)
    else:
        return "✅ <b>Отлично! Просроченных и критически горящих тем сейчас нет.</b>"

def get_ga_complaints_report():
    data = fetch_forum_data(section="admin_complaints", skip_summaries=False)
    if not data:
        return "❌ Не удалось получить данные с форума. Попробуйте позже."
        
    admin_sec = data.get("sections", {}).get("admin_complaints", {})
    ga_threads = admin_sec.get("ga_threads", [])
    
    if not ga_threads:
        return "👑 <b>Жалобы Главному Администратору:</b>\n\nТемы с префиксом 'Главному администратору' сейчас отсутствуют."
        
    lines = [f"👑 <b>ТЕМЫ «ГЛАВНОМУ АДМИНИСТРАТОРУ» ({len(ga_threads)}):</b>\n"]
    for idx, t in enumerate(ga_threads, 1):
        title = html.escape(fix_mojibake(t.get('title', 'Без названия')))
        author = html.escape(fix_mojibake(t.get('author', '')))
        url = t.get('url', '')
        t_left = t.get('time_left_str', '')
        
        is_overdue = t.get("is_overdue", False) or "просроч" in t_left.lower()
        is_urgent = False
        if not is_overdue:
            if " ч." in t_left:
                try:
                    h = int(t_left.split(" ч.")[0].strip().split()[-1])
                    if h < 5:
                        is_urgent = True
                except:
                    pass
            elif " мин." in t_left and " ч." not in t_left:
                is_urgent = True
                
        if is_overdue:
            prefix_badge = "🔴 <b>[ПРОСРОЧЕНО]</b> "
            status_line = f"🚨 <b>СТАТУС: 🔴 ПРОСРОЧЕНО ({t_left})</b>"
        elif is_urgent:
            prefix_badge = "⏳ <b>[СРОЧНО]</b> "
            status_line = f"⏳ <b>Осталось: {t_left}</b>"
        else:
            prefix_badge = "👑 "
            status_line = f"⏱ Осталось: {t_left}"
            
        lines.append(f"<b>{idx}. {prefix_badge}<a href='{url}'>{title}</a></b>")
        lines.append(f"👤 Автор: <code>{author}</code> | {status_line}")
        summary = html.escape(fix_mojibake(t.get("summary", "").strip()))
        if summary:
            lines.append(f"📝 <i>Суть:</i> {summary}")
        lines.append("")
        
    return "\n".join(lines)

def get_full_forum_report():
    data = fetch_forum_data(skip_summaries=True)
    if not data:
        return "❌ Не удалось получить данные с форума. Попробуйте позже."
        
    total_overdue = sum(len(s.get("overdue", [])) for s in data.get("sections", {}).values())
    total_urgent = sum(len(extract_urgent_threads(s.get("in_progress", []))) for s in data.get("sections", {}).values())
    
    if total_overdue > 0:
        lines = [f"🚨 <b>ПОЛНЫЙ СРЕЗ ПО РАЗДЕЛАМ ФОРУМА — 🔴 НАЙДЕНО ПРОСРОЧЕК: {total_overdue}!</b>\n"]
    elif total_urgent > 0:
        lines = [f"⏳ <b>ПОЛНЫЙ СРЕЗ ПО РАЗДЕЛАМ ФОРУМА — ⚠️ ГОРЯЩИХ ТЕМ: {total_urgent}</b>\n"]
    else:
        lines = ["✅ <b>ПОЛНЫЙ СРЕЗ ПО РАЗДЕЛАМ ФОРУМА (ПРОСРОЧЕК НЕТ)</b>\n"]
    
    for sec_id, s in data.get("sections", {}).items():
        name = SECTION_NAMES.get(sec_id, fix_mojibake(s.get("title", sec_id)))
        overdue_list = s.get("overdue", [])
        in_prog_list = s.get("in_progress", [])
        urgent_list = extract_urgent_threads(in_prog_list)
        ga_cnt = len(s.get("ga_threads", []))
        
        if overdue_list:
            lines.append(f"🔴 <b>{name}</b> (дедлайн {s.get('deadline_hours')} ч.) — 🚨 <b>ПРОСРОЧЕНО: {len(overdue_list)}</b>")
            lines.append(f"  • В работе / на рассмотрении: <b>{len(in_prog_list)}</b>")
            lines.append(f"  • 🔴 <b>ПРОСРОЧЕННЫЕ ТЕМЫ:</b>")
            for ov in overdue_list:
                title = html.escape(fix_mojibake(ov.get('title', 'Без названия')))
                url = ov.get('url', '')
                t_str = ov.get('time_left_str', '')
                author = html.escape(fix_mojibake(ov.get('author', '')))
                author_part = f" [<code>{author}</code>]" if author else ""
                prefix = html.escape(fix_mojibake(ov.get('prefix', ''))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                lines.append(f"    ❌{prefix_badge} <a href='{url}'><b>{title}</b></a>{author_part} ➔ 🔴 <b>{t_str}</b>")
        elif urgent_list:
            lines.append(f"⏳ <b>{name}</b> (дедлайн {s.get('deadline_hours')} ч.) — ⚠️ <b>СРОЧНЫХ: {len(urgent_list)}</b>")
            lines.append(f"  • В работе / на рассмотрении: <b>{len(in_prog_list)}</b>")
        else:
            lines.append(f"🟢 <b>{name}</b> (дедлайн {s.get('deadline_hours')} ч.)")
            lines.append(f"  • В работе / на рассмотрении: <b>{len(in_prog_list)}</b>")
            lines.append("  • ✅ Просрочек нет")
                
        if urgent_list:
            lines.append(f"  • ⏳ <b>СКОРО ИСТЕКАЕТ ({len(urgent_list)}):</b>")
            for ug in urgent_list:
                title = html.escape(fix_mojibake(ug.get('title', 'Без названия')))
                url = ug.get('url', '')
                t_str = ug.get('time_left_str', '')
                author = html.escape(fix_mojibake(ug.get('author', '')))
                author_part = f" [<code>{author}</code>]" if author else ""
                prefix = html.escape(fix_mojibake(ug.get('prefix', ''))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                lines.append(f"    ⚠️{prefix_badge} <a href='{url}'><b>{title}</b></a>{author_part} ➔ ⏳ осталось <b>{t_str}</b>")
                
        if ga_cnt > 0:
            lines.append(f"  • 👑 Префикс ГА: <b>{ga_cnt}</b>")
            
        lines.append("")
        
    return "\n".join(lines)
