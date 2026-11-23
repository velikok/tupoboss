import re
import time
import datetime
import html
import urllib.parse
from forum_audit import solve_vddos_and_fetch_requests
import rules_kb

BASE_URL = "https://forum.blackrussia.online"

TECH_ADMINS = [
    "server", "maestro_astarot", "leo_casion", "dmitry_nagaharas",
    "reymon_yamasaki", "charden_forester", "kumiho_legenda",
    "mommy_crypto", "immi_kalashnikov", "clarence_corner", "senseles_khanate"
]

TECH_REASONS = [
    "покупка ив", "продажа ив", "махинации", "взломан", "трансфер",
    "порча экономики", "покупка игровой валюты", "продажа игровой валюты",
    "ущерб экономике", "махинаци", "продажа вирт", "покупка вирт", "ив"
]

FORUM_APPEALS_NODE = "845"
FORUM_ADMIN_COMPLAINTS_NODE = "842"
FORUM_TECH_NODE = "1199"

def get_greeting():
    # MSK is UTC+3
    now_hour = (time.gmtime().tm_hour + 3) % 24
    if 5 <= now_hour < 12:
        return "Доброе утро"
    elif 12 <= now_hour < 18:
        return "Добрый день"
    elif 18 <= now_hour < 23:
        return "Добрый вечер"
    else:
        return "Доброй ночи"

def extract_first_post_info(thread_url):
    html_text = solve_vddos_and_fetch_requests(thread_url)
    if not html_text:
        return None
        
    # Thread ID
    th_id_m = re.search(r'threads/[^/]+\.(\d+)', thread_url)
    thread_id = th_id_m.group(1) if th_id_m else ""
    
    # Title
    t_match = re.search(r'<h1 class="p-title-value">(.*?)</h1>', html_text, re.DOTALL)
    title = re.sub(r'<[^>]+>', '', t_match.group(1)).strip() if t_match else ""
    
    # Author
    auth_m = re.search(r'data-author="([^"]+)"', html_text)
    author = auth_m.group(1) if auth_m else "Игрок"
    
    # First post body
    post_m = re.search(r'<article class="message-body[^"]*">(.*?)</article>', html_text, re.DOTALL)
    body_html = post_m.group(1) if post_m else ""
    clean_body = re.sub(r'<[^>]+>', ' ', body_html).replace('&nbsp;', ' ').strip()
    clean_body = re.sub(r'\s+', ' ', clean_body)
    
    # Images / Proof links
    image_links = re.findall(r'<img[^>]+src="([^"]+)"', body_html)
    text_links = re.findall(r'href="([^"]+)"', body_html)
    all_links = set(image_links + text_links)
    proof_links = [l for l in all_links if any(d in l.lower() for d in ["imgur", "yapx", "postimg", "ibb.co", "youtube", "youtu.be", "drive.google", "vk.com"])]
    
    # Post timestamp
    time_m = re.search(r'<time[^>]*data-time="(\d+)"', html_text)
    thread_created_ts = int(time_m.group(1)) if time_m else int(time.time())
    
    # Thread prefix if present
    prefix = ""
    pfx_m = re.search(r'<span class="label[^"]*"[^>]*>(.*?)</span>', html_text)
    if pfx_m:
        prefix = re.sub(r'<[^>]+>', '', pfx_m.group(1)).strip()

    # Author user ID
    uid_m = re.search(r'members/[^/]+\.(\d+)', html_text)
    author_uid = uid_m.group(1) if uid_m else None

    return {
        "thread_id": thread_id,
        "url": thread_url,
        "title": title,
        "author": author,
        "author_uid": author_uid,
        "body": clean_body,
        "body_html": body_html,
        "proof_links": proof_links,
        "thread_created_ts": thread_created_ts,
        "prefix": prefix
    }

def analyze_author_history(author_uid):
    if not author_uid:
        return {"total": 0, "nicks": [], "is_single_nick": True}
        
    url = f"{BASE_URL}/search/member?user_id={author_uid}"
    try:
        html_text = solve_vddos_and_fetch_requests(url)
        titles = re.findall(r'<h3 class="contentRow-title">.*?<a [^>]*>(.*?)</a>', html_text, re.DOTALL)
        clean_titles = [re.sub(r'<[^>]+>', '', t).replace('&nbsp;', ' ').strip() for t in titles]
        
        # Extract potential nicknames from titles (e.g. Nick_Name | ...)
        nicks = []
        for t in clean_titles:
            nm = re.search(r'([A-Z][a-z]+_[A-Z][a-z]+)', t)
            if nm:
                nicks.append(nm.group(1).lower())
                
        uniq_nicks = list(set(nicks))
        is_single = len(uniq_nicks) <= 1
        return {
            "total_topics": len(clean_titles),
            "titles": clean_titles[:5],
            "nicks": uniq_nicks,
            "is_single_nick": is_single
        }
    except Exception:
        return {"total": 0, "nicks": [], "is_single_nick": True}

def _generate_verdict_internal(thread_info):
    title_l = thread_info["title"].lower()
    body_l = thread_info["body"].lower()
    author = thread_info["author"]
    greeting = get_greeting()
    
    # --- 1. Check for Tech Admin transfer ---
    is_tech_admin = any(ta in title_l or ta in body_l for ta in TECH_ADMINS)
    is_tech_reason = any(tr in title_l or tr in body_l for tr in TECH_REASONS)
    
    if is_tech_admin and is_tech_reason:
        reply_text = (
            f"{greeting}, уважаемый(-ая) {author}\n\n"
            " Ошиблись разделом!\n"
            " Переношу вашу тему в раздел жалоб на технических специалистов!\n\n"
            "В ожидании"
        )
        return {
            "action": "MOVE_TECH",
            "category": "Технический перенос",
            "destination_node": FORUM_TECH_NODE,
            "prefix": "На рассмотрении",
            "stick": False,
            "reply_text": reply_text,
            "explanation": "Обнаружен ник технического специалиста и техническая причина блокировки. Тема переносится в раздел жалоб на тех. спецов."
        }

    # --- 2. Check for IP ban / Fake ban ---
    if "айпи" in title_l or "айпи" in body_l or "ip" in title_l or "ip" in body_l:
        reply_text = (
            f"{greeting}, уважаемый(-ая) {author}\n\n"
            "Дело в вашем айпи адресе. \n"
            "Попробуйте сменить его на старый с которого вы играли раньше.\n"
            "Смените интернет соединение или же попробуйте использовать впн.\n"
            "Ваш аккаунт не в блокировке\n\n"
            "Закрыто."
        )
        return {
            "action": "REPLY_CLOSE",
            "category": "Блокировка IP / Ложный бан",
            "prefix": "Закрыто",
            "stick": False,
            "reply_text": reply_text,
            "explanation": "Игрок сообщает о блокировке IP-адреса. Аккаунт не забанен, выдана рекомендация сменить IP/VPN."
        }

    # --- 3. Check for NonRP fraud (НонРП обман) ---
    if "обман" in title_l or "обман" in body_l:
        # Check history of author
        auth_hist = analyze_author_history(thread_info.get("author_uid"))
        is_single_nick = auth_hist.get("is_single_nick", True)
        
        # Check if player wants to return / charity
        ready_return = any(w in body_l for w in ["вернуть", "возместить", "отдать", "согласен", "благотворительность"])
        
        # Estimate days since ban (looking for dates in text)
        days_in_ban = 0
        date_matches = re.findall(r'(\d{2})[./-](\d{2})[./-](\d{2,4})', body_l)
        if date_matches:
            try:
                d, m, y = date_matches[0]
                if len(y) == 2:
                    y = "20" + y
                ban_dt = datetime.datetime(int(y), int(m), int(d))
                days_in_ban = (datetime.datetime.now() - ban_dt).days
            except Exception:
                pass

        if ready_return and days_in_ban >= 90 and is_single_nick:
            reply_text = (
                f"{greeting}, уважаемый(-ая) {author}\n\n"
                "Разблокировал ваш аккаунт на 24 часа. Вам необходимо перевести 1.500.000 игровой валюты на благотворительность , после чего отписать в данной теме.\n\n"
                "Одобрено."
            )
            return {
                "action": "REPLY_CHARITY",
                "category": "NonRP Обман (Благотворительность)",
                "prefix": "Одобрено",
                "stick": False,
                "reply_text": reply_text,
                "explanation": f"В бане {days_in_ban} дн. (>=90 дн.), рецидивов нет. Готов к разбану на 24ч под благотворительность."
            }
        elif ready_return:
            reply_text = (
                f"{greeting}, уважаемый(-ая) {author}\n\n"
                "Если вы готовы возместить ущерб обманутой стороне свяжитесь с игроком в любым способом.\n"
                "Для возврата имущества он должен оформить обжалование.\n\n"
                "Закрыто."
            )
            return {
                "action": "REPLY_CLOSE",
                "category": "NonRP Обман (Связь с игроком)",
                "prefix": "Закрыто",
                "stick": False,
                "reply_text": reply_text,
                "explanation": "Готов возместить ущерб: указание связаться с обманутой стороной для совместного обжалования."
            }
        else:
            reply_text = (
                f"{greeting}, уважаемый(-ая) {author}\n\n"
                "Рассмотрев ваше обжалование , могу сказать , что мы не готовы снизить вам срок наказания.\n\n"
                "Закрыто."
            )
            return {
                "action": "REPLY_CLOSE",
                "category": "NonRP Обман (Отказ в снижении)",
                "prefix": "Закрыто",
                "stick": False,
                "reply_text": reply_text,
                "explanation": "Не выполнены условия для снижения наказания за обман."
            }

    # --- 4. Missing ban window / Proofs ---
    if not thread_info.get("proof_links") and any(w in body_l for w in ["разбаньте", "снимите бан", "за что бан", "разбан"]):
        reply_text = (
            f"Вы не прикрепили окно бана. Создайте новую тему и прикрепите туда окно бана.\n\n"
            "Закрыто."
        )
        return {
            "action": "REPLY_CLOSE",
            "category": "Нет окна бана",
            "prefix": "Закрыто",
            "stick": False,
            "reply_text": reply_text,
            "explanation": "В жалобе отсутствуют ссылки на скриншот окна блокировки."
        }

    # --- 5. Soft / Cheats ---
    if any(w in title_l or w in body_l for w in ["стороннее по", "читы", "софт", "аим", "флай"]):
        reply_text = (
            f"{greeting}, уважаемый(-ая) {author}\n\n"
            "Пожалуйста внимательно прочитайте тему «Правила подачи заявки на обжалование наказания»\n"
            "И обратите своё внимание, на данный пункт правил:\n\n"
            "Отказано."
        )
        return {
            "action": "REPLY_CLOSE",
            "category": "Стороннее ПО / Читы",
            "prefix": "Отказано",
            "stick": False,
            "reply_text": reply_text,
            "explanation": "Стороннее ПО не подлежит обжалованию."
        }

    # --- 6. Insult to relatives (Оск родных / Упом) ---
    if "родн" in title_l or "родн" in body_l or "оск" in title_l:
        if any(w in body_l for w in ["простите", "извините", "раскаиваюсь", "больше не повторится", "осознал"]):
            reply_text = (
                f"{greeting}, уважаемый(-ая) {author}\n\n"
                "Ваше обжалование рассмотрено и принято решение о сокращении вашего наказания.\n\n"
                "Одобрено."
            )
            return {
                "action": "REPLY_APPROVE",
                "category": "Оск. родных (Смягчение)",
                "prefix": "Одобрено",
                "stick": False,
                "reply_text": reply_text,
                "explanation": "Игрок искренне раскаивается в содеянном, одобрено сокращение наказания."
            }
        else:
            reply_text = (
                f"{greeting}, уважаемый(-ая) {author}\n\n"
                "Наказание выдано верно,срок блокировки снижен не будет. Впредь не надо вестись на провокации.\n\n"
                "Отказано."
            )
            return {
                "action": "REPLY_CLOSE",
                "category": "Оск. родных (Отказ)",
                "prefix": "Отказано",
                "stick": False,
                "reply_text": reply_text,
                "explanation": "Наказание выдано верно, провокация не является оправданием."
            }

    # --- 7. General reduction case (Слив СМИ, промокоды, мелкие баны) ---
    if any(w in body_l for w in ["прошу прощения", "прошу разбанить", "дайте шанс", "второй шанс", "осознал ошибку"]):
        reply_text = (
            f"{greeting}, уважаемый(-ая) {author}\n\n"
            "Ваше обжалование рассмотрено и принято решение о сокращении вашего наказания.\n\n"
            "Одобрено."
        )
        return {
            "action": "REPLY_APPROVE",
            "category": "Смягчение наказания",
            "prefix": "Одобрено",
            "stick": False,
            "reply_text": reply_text,
            "explanation": "Типовой случай раскаяния, готово решение о сокращении срока."
        }

    # --- Fallback: Manual Review ---
    return {
        "action": "MANUAL",
        "category": "Требуется ручное решение",
        "prefix": "Закрыто",
        "stick": False,
        "reply_text": f"{greeting}, уважаемый(-ая) {author}\n\n",
        "explanation": "Нестандартная тема или жалоба на администрацию. Рекомендуется ввести ответ вручную или открыть тему."
    }

def generate_verdict(thread_info):
    verdict = _generate_verdict_internal(thread_info)
    title = thread_info.get("title", "")
    body = thread_info.get("body", "")
    rule_num, rule_obj = rules_kb.find_rule_by_keyword(f"{title} {body}")
    if rule_num and rule_obj:
        verdict["rule_num"] = rule_num
        verdict["rule_punishment"] = rule_obj.get("punishment", "")
        verdict["rule_title"] = rule_obj.get("title", "")
    return verdict

def get_next_pending_appeal(exclude_thread_ids=None):
    if exclude_thread_ids is None:
        exclude_thread_ids = set()
    url = f"{BASE_URL}/forums/Обжалование-наказаний.{FORUM_APPEALS_NODE}/"
    html_text = solve_vddos_and_fetch_requests(url)
    if not html_text:
        return None
        
    parts = html_text.split('<div class="structItem structItem--thread')
    for p in parts[1:]:
        if "is-redirect" in p or "is-deleted" in p or "structItem-status--locked" in p:
            continue
        m = re.search(r'<a href="(/threads/[^"]+)"[^>]*>(.*?)</a>', p)
        if not m:
            continue
        rel_url = m.group(1).split("/unread")[0]
        th_id_m = re.search(r'threads/[^/]+\.(\d+)', rel_url)
        th_id = th_id_m.group(1) if th_id_m else None
        if not th_id or str(th_id) in exclude_thread_ids:
            continue
            
        pref_m = re.search(r'<span class="label[^"]*"[^>]*>(.*?)</span>', p)
        prefix = re.sub(r'<[^>]+>', '', pref_m.group(1)).strip() if pref_m else ""
        if prefix in ["Закрыто", "Отказано", "Одобрено"]:
            continue
            
        full_url = BASE_URL + rel_url if rel_url.startswith("/") else rel_url
        info = extract_first_post_info(full_url)
        if info:
            verdict = generate_verdict(info)
            return {"info": info, "verdict": verdict}
            
    return None

