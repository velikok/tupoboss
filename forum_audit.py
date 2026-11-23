
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

try:
    import requests
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    HAS_FAST_ENGINE = True
except ImportError:
    HAS_FAST_ENGINE = False

DEFAULT_XF_USER = "208737%2CHfBa3p5I774lhDq9QWBmFhQT2w8HZgMkNO8XoDJK"
DEFAULT_XF_TFA_TRUST = "o_OiivtH8DhJ12SPSI5kWt5-T-T3gXVg"

def get_forum_credentials():
    xf_user = os.environ.get("FORUM_XF_USER")
    xf_tfa = os.environ.get("FORUM_XF_TFA_TRUST")
    base_dir = os.path.dirname(__file__)
    for cfg_name in ["config.backup.json", "config.json"]:
        p = os.path.join(base_dir, cfg_name)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not xf_user and "forum_xf_user" in data:
                        xf_user = data["forum_xf_user"]
                    if not xf_tfa and "forum_xf_tfa_trust" in data:
                        xf_tfa = data["forum_xf_tfa_trust"]
            except Exception:
                pass
    if not xf_user:
        xf_user = DEFAULT_XF_USER
    if not xf_tfa:
        xf_tfa = DEFAULT_XF_TFA_TRUST
    return xf_user, xf_tfa

_requests_session = None

def get_fast_session():
    global _requests_session
    if _requests_session is not None:
        return _requests_session
    if not HAS_FAST_ENGINE:
        return None
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    xf_user, xf_tfa = get_forum_credentials()
    if xf_user:
        s.cookies.set("xf_user", xf_user, domain="forum.blackrussia.online")
    if xf_tfa:
        s.cookies.set("xf_tfa_trust", xf_tfa, domain="forum.blackrussia.online")
    _requests_session = s
    return _requests_session

def solve_vddos_and_fetch_requests(url, timeout=20):
    s = get_fast_session()
    if s is None:
        return ""
    for _ in range(2):
        try:
            r = s.get(url, timeout=timeout)
            text = r.text
            if 'w3-include-html="/5s.html"' in text or "slowAES" in text:
                hex_matches = re.findall(r'"([a-f0-9]{32})"', text)
                if len(hex_matches) >= 3:
                    key = bytes.fromhex(hex_matches[0])
                    iv = bytes.fromhex(hex_matches[1])
                    ct = bytes.fromhex(hex_matches[2])
                    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
                    r3actlb = (cipher.decryptor().update(ct) + cipher.decryptor().finalize()).hex()
                    s.cookies.set("R3ACTLB", r3actlb, domain="forum.blackrussia.online")
                    continue
            return text
        except Exception:
            time.sleep(0.5)
    return ""

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
        "deadline_hours": 72,
        "target_prefix_ids": ["2", "14"],
        "target_prefix_names": ["на рассмотрении", "ожидание", "в ожидании"],
        "check_ga": False
    },
    {
        "id": "admin_complaints",
        "title": "Жалобы на администрацию",
        "urls": ["https://forum.blackrussia.online/forums/Жалобы-на-администрацию.842/"],
        "deadline_hours": 48,
        "target_prefix_ids": ["2", "14"],
        "target_prefix_names": ["на рассмотрении", "ожидание", "в ожидании"],
        "check_ga": True
    },
    {
        "id": "player_complaints",
        "title": "Жалобы на игроков",
        "urls": ["https://forum.blackrussia.online/forums/Жалобы-на-игроков.844/"],
        "deadline_hours": 48,
        "target_prefix_ids": ["2", "14"],
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
        "deadline_hours": 24,
        "target_prefix_ids": ["14"],
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
        "deadline_hours": 24,
        "target_prefix_ids": ["14"],
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
        "deadline_hours": 24,
        "target_prefix_ids": ["14"],
        "target_prefix_names": ["ожидание", "в ожидании"],
        "check_ga": False
    }
]

def fetch_html_chrome(url, budget=1200, retries=2):
    if not CHROME_PATH or not os.path.exists(CHROME_PATH):
        return ""
    cmd = [
        CHROME_PATH, "--headless=new", "--no-sandbox", "--disable-setuid-sandbox",
        f"--user-data-dir={USER_DATA}", "--disable-gpu", "--disable-software-rasterizer",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-sync", "--disable-translate",
        "--metrics-recording-only", "--mute-audio", "--blink-settings=imagesEnabled=false",
        "--disable-remote-fonts", "--disable-extensions", f"--virtual-time-budget={budget}",
        "--dump-dom", url
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

def fetch_html(url, budget=1200, retries=2):
    if HAS_FAST_ENGINE:
        fast_text = solve_vddos_and_fetch_requests(url)
        if fast_text and any(x in fast_text for x in ["structItem", "bbWrapper", "message-body", "emptyThreadList"]):
            return fast_text
    return fetch_html_chrome(url, budget=budget, retries=retries)

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
    results = {"overdue": [], "in_progress": [], "ga_threads": []}
    parts = html.split('<div class="structItem structItem--thread')
    if len(parts) <= 1:
        return results

    for p in parts[1:]:
        tag_header = p[:p.find('>')] if '>' in p else p[:200]
        if "is-deleted" in tag_header or "structItem--deleted" in tag_header:
            continue
        if "is-redirect" in tag_header or "structItem--redirect" in tag_header:
            continue
        if "structItem-status--deleted" in p or "deletionNotice" in p or "deletion-notice" in p:
            continue
        if re.search(r'title=["\'](?:Удалено|Deleted)["\']', p):
            continue

        prefix_id = None
        prefix_title = ""
        m_prefix = re.search(r'label--primary\s+label--prefix(\d+)[^"]*"[^>]*>([\s\S]*?)</span>', p)
        if m_prefix:
            prefix_id = m_prefix.group(1).strip()
            raw_title = m_prefix.group(2).strip()
            prefix_title = re.sub(r'<[^>]+>', '', raw_title).strip()
            
        m_title = re.search(r'<div class="structItem-title"[^>]*>[\s\S]*?<a href="([^"]*)"[^>]*data-tp-primary="on"[^>]*>([\s\S]*?)</a>', p)
        if not m_title:
            m_title = re.search(r'<div class="structItem-title"[^>]*>[\s\S]*?<a href="([^"]*threads/[^"]*)"[^>]*>([\s\S]*?)</a>', p)
        if not m_title:
            continue
            
        raw_url = m_title.group(1)
        raw_thread_title = m_title.group(2).strip()
        thread_title = re.sub(r'<[^>]+>', '', raw_thread_title).strip()
        
        thread_url = raw_url if raw_url.startswith("http") else "https://forum.blackrussia.online" + raw_url
        if not thread_url.endswith("/"):
            thread_url += "/"
            
        author = "Неизвестно"
        m_author = re.search(r'data-xf-init="member-tooltip"[^>]*>([\s\S]*?)</a>', p)
        if m_author:
            author = re.sub(r'<[^>]+>', '', m_author.group(1)).strip()
        else:
            m_author_struct = re.search(r'<a href="[^"]*members/[^"]*"[^>]*class="username"[^>]*>([\s\S]*?)</a>', p)
            if m_author_struct:
                author = re.sub(r'<[^>]+>', '', m_author_struct.group(1)).strip()

        created_ts = None
        m_time = re.search(r'<time[^>]*data-time="(\d+)"', p)
        if m_time:
            created_ts = int(m_time.group(1))
        else:
            m_time_dt = re.search(r'<time[^>]*datetime="([^"]+)"', p)
            if m_time_dt:
                try:
                    dt_str = m_time_dt.group(1)
                    clean_dt = dt_str[:19]
                    created_ts = int(datetime.strptime(clean_dt, "%Y-%m-%dT%H:%M:%S").timestamp())
                except:
                    pass
                    
        if not created_ts:
            continue

        deadline_seconds = section_cfg["deadline_hours"] * 3600
        time_elapsed = now_ts - created_ts
        time_left_sec = deadline_seconds - time_elapsed
        is_overdue = time_left_sec <= 0
        
        if is_overdue:
            overdue_sec = abs(time_left_sec)
            ov_hours = overdue_sec // 3600
            ov_mins = (overdue_sec % 3600) // 60
            time_left_str = f"ПРОСРОЧЕНО на {ov_hours} ч. {ov_mins} мин."
        else:
            left_hours = time_left_sec // 3600
            left_mins = (time_left_sec % 3600) // 60
            time_left_str = f"{left_hours} ч. {left_mins} мин."

        is_ga = False
        if prefix_id == "12" or "главному администратору" in prefix_title.lower():
            is_ga = True
            
        is_target_prefix = False
        if prefix_id and prefix_id in section_cfg["target_prefix_ids"]:
            is_target_prefix = True
        elif prefix_title and prefix_title.lower() in section_cfg["target_prefix_names"]:
            is_target_prefix = True

        thread_data = {
            "title": thread_title,
            "url": thread_url,
            "author": author,
            "prefix": prefix_title or "Без префикса",
            "prefix_id": prefix_id,
            "created_timestamp": created_ts,
            "deadline_hours": section_cfg["deadline_hours"],
            "time_left_str": time_left_str,
            "is_overdue": is_overdue,
            "is_ga": is_ga
        }

        if section_cfg.get("check_ga") and is_ga:
            if fetch_summaries:
                thread_data["summary"] = fetch_thread_summary(thread_data["url"])
            results["ga_threads"].append(thread_data)

        if is_target_prefix or (section_cfg.get("check_ga") and is_ga):
            if is_overdue:
                results["overdue"].append(thread_data)
            else:
                results["in_progress"].append(thread_data)

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