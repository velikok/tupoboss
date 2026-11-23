import re
import json
import time
from forum_audit import solve_vddos_and_fetch_requests, get_fast_session

BASE_URL = "https://forum.blackrussia.online"

PREFIX_MAP = {
    "Без префикса": 0,
    "Важно": 1,
    "На рассмотрении": 2,
    "Отказано": 4,
    "Решено": 6,
    "Закрыто": 7,
    "Одобрено": 8,
    "Рассмотрено": 9,
    "Команде проекта": 10,
    "Специальному администратору": 11,
    "Главному администратору": 12,
    "Тех. специалисту": 13,
    "Ожидание": 14
}

def get_thread_csrf_and_title(thread_id):
    url = f"{BASE_URL}/threads/{thread_id}/"
    html = solve_vddos_and_fetch_requests(url)
    if not html:
        return None, None
        
    m = re.search(r'data-csrf="([^"]+)"', html)
    if not m:
        m = re.search(r'name="_xfToken" value="([^"]+)"', html)
    token = m.group(1) if m else None
    
    t_match = re.search(r'<h1 class="p-title-value">(.*?)</h1>', html, re.DOTALL)
    title = re.sub(r'<[^>]+>', '', t_match.group(1)).strip() if t_match else ""
    
    return token, title

def send_reply(thread_id, reply_text):
    s = get_fast_session()
    if s is None:
        return False, "Сессия форума не инициализирована"
        
    csrf, _ = get_thread_csrf_and_title(thread_id)
    if not csrf:
        return False, "Не удалось получить _xfToken (CSRF)"
        
    post_url = f"{BASE_URL}/threads/{thread_id}/add-reply"
    
    # Format newlines into paragraphs or break lines for XenForo editor
    paragraphs = [f"<p>{line.strip()}</p>" if line.strip() else "<p><br></p>" for line in reply_text.split("\n")]
    msg_html = "".join(paragraphs)
    
    payload = {
        "message_html": msg_html,
        "_xfToken": csrf,
        "_xfResponseType": "json",
        "_xfWithData": "1"
    }
    
    try:
        resp = s.post(post_url, data=payload, timeout=20)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("status") == "ok":
                return True, "Ответ успешно опубликован на форуме!"
            elif "errors" in res_json:
                return False, f"Ошибка форума: {res_json['errors']}"
            return True, "Ответ отправлен"
        else:
            return False, f"HTTP ошибка {resp.status_code}"
    except Exception as e:
        return False, f"Исключение при отправке ответа: {e}"

def move_thread(thread_id, target_node_id, prefix_id=None, title=None):
    s = get_fast_session()
    if s is None:
        return False, "Сессия форума не инициализирована"
        
    csrf, cur_title = get_thread_csrf_and_title(thread_id)
    if not csrf:
        return False, "Не удалось получить _xfToken"
        
    post_url = f"{BASE_URL}/threads/{thread_id}/move"
    payload = {
        "target_node_id": str(target_node_id),
        "title": title or cur_title,
        "prefix_id": str(prefix_id) if prefix_id is not None else "0",
        "_xfToken": csrf,
        "_xfResponseType": "json",
        "_xfWithData": "1"
    }
    
    try:
        resp = s.post(post_url, data=payload, timeout=20)
        if resp.status_code == 200:
            return True, f"Тема успешно перенесена в раздел {target_node_id}!"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Ошибка при переносе: {e}"

def update_thread_status(thread_id, prefix_id=None, open_status=None, sticky=None):
    s = get_fast_session()
    if s is None:
        return False, "Сессия форума не инициализирована"
        
    csrf, title = get_thread_csrf_and_title(thread_id)
    if not csrf:
        return False, "Не удалось получить _xfToken"
        
    post_url = f"{BASE_URL}/threads/{thread_id}/quick-update"
    payload = {
        "_xfToken": csrf,
        "_xfResponseType": "json",
        "_xfWithData": "1"
    }
    
    if prefix_id is not None:
        payload["prefix_id"] = str(prefix_id)
    if open_status is not None:
        payload["discussion_open"] = "1" if open_status else "0"
    if sticky is not None:
        payload["sticky"] = "1" if sticky else "0"
        
    try:
        resp = s.post(post_url, data=payload, timeout=20)
        if resp.status_code == 200:
            return True, "Статус темы обновлен"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Ошибка при обновлении статуса: {e}"

def execute_copilot_verdict(thread_id, verdict_data):
    action = verdict_data.get("action")
    prefix_name = verdict_data.get("prefix")
    prefix_id = PREFIX_MAP.get(prefix_name, 0)
    reply_text = verdict_data.get("reply_text")
    dest_node = verdict_data.get("destination_node")
    stick = verdict_data.get("stick", False)
    
    results = []
    
    # 1. Post reply if exists
    if reply_text and reply_text.strip():
        ok, msg = send_reply(thread_id, reply_text)
        results.append(f"Ответ: {'✅' if ok else '❌'} {msg}")
        time.sleep(1.5)
        
    # 2. Move thread if required
    if action in ["MOVE_TECH", "MOVE_ADMIN_COMPLAINTS"] and dest_node:
        ok, msg = move_thread(thread_id, dest_node, prefix_id=prefix_id)
        results.append(f"Перенос: {'✅' if ok else '❌'} {msg}")
        time.sleep(1.5)
        
    # 3. Update prefix and open/close status
    open_status = False if action in ["REPLY_CLOSE", "REPLY_APPROVE", "REPLY_CHARITY"] else None
    if prefix_id or open_status is not None or stick:
        ok, msg = update_thread_status(thread_id, prefix_id=prefix_id, open_status=open_status, sticky=stick)
        results.append(f"Статус/Префикс: {'✅' if ok else '❌'} {msg}")
        
    return "\n".join(results)
