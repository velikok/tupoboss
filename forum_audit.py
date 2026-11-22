#!/usr/bin/env python3
"""
Black Russia Forum Audit Script
Monitors:
1. Обжалование наказаний (845) - 3 days
2. Жалобы на администрацию (842) - 2 days (+ 'Главному администратору' summaries)
3. Жалобы на игроков (844) - 2 days
4. РП-ситуации (823) + Ситуации на доработке (847) - 24 hours
5. РП-биографии (824) + Биографии на доработке (850) - 24 hours
6. Неофициальные rp-организации (821) + Организации на доработке (840) - 24 hours
"""

import sys
import os
import re
import json
import time
import argparse
import subprocess
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import shutil

def get_chrome_path():
    env_chrome = os.environ.get("CHROME_BIN") or os.environ.get("CHROME_PATH")
    if env_chrome and os.path.exists(env_chrome):
        return env_chrome
    if sys.platform != "win32":
        for p in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
            found = shutil.which(p)
            if found:
                return found
        return "/usr/bin/chromium"
    return r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CHROME_PATH = get_chrome_path()
USER_DATA = os.environ.get("FORUM_PROFILE_DIR", os.path.join(os.path.dirname(__file__), "forum_profile"))
if not os.path.exists(USER_DATA) and sys.platform == "win32":
    fallback = os.path.expanduser(r"~/.gemini/config/forum_profile")
    if os.path.exists(fallback):
        USER_DATA = fallback

SECTIONS_CONFIG = [
    {
        "id": "appeals",
        "title": "Обжалование наказаний",
        "urls": ["https://forum.blackrussia.online/forums/Обжалование-наказаний.845/"],
        "deadline_hours": 72, # 3 days
        "target_prefix_ids": ["2", "14"], # На рассмотрении, Ожидание
        "target_prefix_names": ["на рассмотрении", "ожидание", "в ожидании"],
        "check_ga": False
    },
    {
        "id": "admin_complaints",
        "title": "Жалобы на администрацию",
        "urls": ["https://forum.blackrussia.online/forums/Жалобы-на-администрацию.842/"],
        "deadline_hours": 48, # 2 days
        "target_prefix_ids": ["2", "14"], # На рассмотрении, Ожидание
        "target_prefix_names": ["на рассмотрении", "ожидание", "в ожидании"],
        "check_ga": True
    },
    {
        "id": "player_complaints",
        "title": "Жалобы на игроков",
        "urls": ["https://forum.blackrussia.online/forums/Жалобы-на-игроков.844/"],
        "deadline_hours": 48, # 2 days
        "target_prefix_ids": ["2", "14"], # На рассмотрении, Ожидание
        "target_prefix_names": ["на рассмотрении", "ожидание", "в ожидании"],
        "check_ga": False
    },
    {
        "id": "rp_situations",
        "title": "РП-ситуации",
        "urls": [
            "https://forum.blackrussia.online/forums/РП-ситуации.823/",
            "https://forum.blackrussia.online/forums/Ситуации-на-доработке.847/"
        ],
        "deadline_hours": 24, # 1 day
        "target_prefix_ids": ["14"], # Ожидание
        "target_prefix_names": ["ожидание", "в ожидании"],
        "check_ga": False
    },
    {
        "id": "rp_biographies",
        "title": "РП-биографии",
        "urls": [
            "https://forum.blackrussia.online/forums/РП-биографии.824/",
            "https://forum.blackrussia.online/forums/Биографии-на-доработке.850/"
        ],
        "deadline_hours": 24, # 1 day
        "target_prefix_ids": ["14"], # Ожидание
        "target_prefix_names": ["ожидание", "в ожидании"],
        "check_ga": False
    },
    {
        "id": "rp_organizations",
        "title": "Неофициальные rp-организации",
        "urls": [
            "https://forum.blackrussia.online/forums/Неофициальные-rp-организации.821/",
            "https://forum.blackrussia.online/forums/Организации-на-доработке.840/"
        ],
        "deadline_hours": 24, # 1 day
        "target_prefix_ids": ["14"], # Ожидание
        "target_prefix_names": ["ожидание", "в ожидании"],
        "check_ga": False
    }
]

def fetch_html(url, budget=1200, retries=2):
    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        f"--user-data-dir={USER_DATA}",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--mute-audio",
        "--blink-settings=imagesEnabled=false",
        "--disable-remote-fonts",
        "--disable-extensions",
        f"--virtual-time-budget={budget}",
        "--dump-dom",
        url
    ]
    for attempt in range(retries):
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=14)
            raw = res.stdout
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("windows-1251", errors="ignore")
                
            if "Р–" in text or "Р°" in text or "Рѕ" in text or "РЅ" in text:
                try:
                    text = text.encode("windows-1251").decode("utf-8")
                except Exception:
                    pass
            return text
        except Exception:
            if attempt == retries - 1:
                return ""
            time.sleep(0.5)
    return ""

def fetch_thread_summary(thread_url):
    html = fetch_html(thread_url, budget=800)
    if not html:
        return "Не удалось загрузить содержимое темы."
    m = re.search(r'<article class="message-body[^"]*"[^>]*>[\s\S]*?<div class="bbWrapper">([\s\S]*?)</div>', html)
    if m:
        text = re.sub(r'<br\s*/?>', ' ', m.group(1))
        text = re.sub(r'<[^>]+>', '', text).strip()
        text = re.sub(r'\s+', ' ', text)
        if len(text) > 250:
            text = text[:247] + "..."
        if "Р–" in text or "Р°" in text or "Рѕ" in text or "РЅ" in text:
            try:
                text = text.encode("windows-1251").decode("utf-8")
            except Exception:
                pass
        return text
    return "Содержимое первого сообщения не найдено."

def parse_threads_from_html(html, section_cfg, now_ts, fetch_summaries=True):
    results = {
        "overdue": [],
        "in_progress": [],
        "ga_threads": []
    }
    
    parts = html.split('<div class="structItem structItem--thread')
    if len(parts) <= 1:
        return results

    for p in parts[1:]:
        # 0. Skip deleted and redirect/moved threads
        tag_header = p[:p.find('>')] if '>' in p else p[:200]
        if "is-deleted" in tag_header or "structItem--deleted" in tag_header:
            continue
        if "is-redirect" in tag_header or "structItem--redirect" in tag_header:
            continue
        if "structItem-status--deleted" in p or "deletionNotice" in p or "deletion-notice" in p:
            continue
        if re.search(r'title=["\'](?:Удалено|Deleted)["\']', p):
            continue
        if re.search(r'class="[^"]*fa-trash[^"]*"', p):
            continue

        # 1. Thread URL & Title
        thread_match = re.search(r'<a href="(/threads/[^"]+)"[^>]*>([\s\S]*?)</a>', p)
        if not thread_match:
            continue
            
        thread_href = thread_match.group(1).split("/unread")[0]
        thread_url = "https://forum.blackrussia.online" + thread_href if thread_href.startswith("/") else thread_href
        if not thread_url.endswith("/"):
            thread_url += "/"
        title = re.sub(r'<[^>]+>', '', thread_match.group(2)).strip()
        if title.lower().startswith("[удалено]") or title.lower().startswith("(удалено)"):
            continue
        
        # 2. Author
        author_match = re.search(r'data-author="([^"]+)"', p)
        author = author_match.group(1) if author_match else "Неизвестно"
        
        # 3. Prefix
        prefix_match = re.search(r'prefix_id=(\d+)[^"]*"[^>]*>([\s\S]*?)</a>', p)
        p_name = ""
        p_id = ""
        raw_prefix = ""
        if prefix_match:
            p_id = prefix_match.group(1)
            raw_prefix = re.sub(r'<[^>]+>', '', prefix_match.group(2)).strip()
            p_name = raw_prefix.lower()
        else:
            label_match = re.search(r'<span class="label[^"]*"[^>]*>([\s\S]*?)</span>', p)
            if label_match:
                raw_prefix = re.sub(r'<[^>]+>', '', label_match.group(1)).strip()
                p_name = raw_prefix.lower()
            
        is_ga = (p_id == "12" or "главному администратору" in p_name)
        is_target_prefix = False
        
        if p_id in section_cfg["target_prefix_ids"]:
            is_target_prefix = True
        else:
            for t_name in section_cfg["target_prefix_names"]:
                if t_name in p_name:
                    is_target_prefix = True
                    break
                    
        if not is_target_prefix and not is_ga:
            continue
            
        # 4. Date and time creation
        time_match = re.search(r'<time[^>]*class="[^"]*u-dt"[^>]*data-time="(\d+)"', p)
        if not time_match:
            time_match = re.search(r'<time[^>]*data-time="(\d+)"', p)
        created_ts = int(time_match.group(1)) if time_match else now_ts
            
        # 5. Deadline calculation
        deadline_sec = section_cfg["deadline_hours"] * 3600
        deadline_ts = created_ts + deadline_sec
        diff_sec = deadline_ts - now_ts
        
        if diff_sec > 0:
            hours = int(diff_sec // 3600)
            mins = int((diff_sec % 3600) // 60)
            time_left_str = f"{hours} ч. {mins} мин."
            is_overdue = False
        else:
            over_sec = abs(diff_sec)
            over_hours = int(over_sec // 3600)
            over_mins = int((over_sec % 3600) // 60)
            time_left_str = f"ПРОСРОЧЕНО на {over_hours} ч. {over_mins} мин."
            is_overdue = True
            
        item = {
            "title": title,
            "url": thread_url,
            "author": author,
            "prefix": raw_prefix.capitalize() if raw_prefix else p_name.capitalize(),
            "prefix_id": p_id,
            "created_timestamp": created_ts,
            "deadline_hours": section_cfg["deadline_hours"],
            "time_left_str": time_left_str,
            "is_overdue": is_overdue,
            "is_ga": is_ga
        }
        
        if is_ga and section_cfg.get("check_ga"):
            # Fetch summary for up to 5 GA threads
            if fetch_summaries and len(results["ga_threads"]) < 5:
                item["summary"] = fetch_thread_summary(thread_url)
            else:
                item["summary"] = ""
            results["ga_threads"].append(item)
            
        if is_overdue:
            results["overdue"].append(item)
        else:
            results["in_progress"].append(item)
            
    return results

def run_full_audit(section_filter=None, fetch_summaries=True):
    now_ts = int(time.time())
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sections": {}
    }
    
    for sec in SECTIONS_CONFIG:
        if section_filter and sec["id"] != section_filter:
            continue
            
        sec_result = {
            "title": sec["title"],
            "deadline_hours": sec["deadline_hours"],
            "overdue": [],
            "in_progress": [],
            "ga_threads": []
        }
        for u in sec["urls"]:
            sec["current_url"] = u
            html = fetch_html(u)
            if not html:
                continue
            parsed = parse_threads_from_html(html, sec, now_ts, fetch_summaries=fetch_summaries)
            sec_result["overdue"].extend(parsed["overdue"])
            sec_result["in_progress"].extend(parsed["in_progress"])
            sec_result["ga_threads"].extend(parsed["ga_threads"])
            
        # Deduplicate by URL
        for key in ["overdue", "in_progress", "ga_threads"]:
            unique_items = []
            seen_urls = set()
            for it in sec_result[key]:
                if it["url"] not in seen_urls:
                    seen_urls.add(it["url"])
                    unique_items.append(it)
            sec_result[key] = unique_items
            
        report["sections"][sec["id"]] = sec_result
        
    return report

def main():
    parser = argparse.ArgumentParser(description="Black Russia Forum Audit")
    parser.add_argument("--section", type=str, default=None, help="Filter to specific section id")
    parser.add_argument("--skip-summaries", action="store_true", help="Do not fetch individual thread summaries")
    args = parser.parse_args()
    
    report = run_full_audit(section_filter=args.section, fetch_summaries=not args.skip_summaries)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
