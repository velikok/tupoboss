import json
import datetime
import requests
import re
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def track_request(config, provider_key):
    today = datetime.date.today().isoformat()
    if config.get("request_date") != today:
        config["request_date"] = today
        config["requests_today"] = {}
    reqs = config.setdefault("requests_today", {})
    reqs[provider_key] = reqs.get(provider_key, 0) + 1

def get_active_profile(config):
    profiles = config.get("ai_profiles")
    if profiles:
        active_id = config.get("active_profile_id")
        if active_id and active_id in profiles:
            return active_id, profiles[active_id]
        first_id = next(iter(profiles))
        config["active_profile_id"] = first_id
        return first_id, profiles[first_id]
        
    providers = config.get("ai_providers", {})
    active_key = config.get("active_ai", "deepseek")
    if active_key in providers:
        return active_key, providers[active_key]
        
    return "deepseek", {
        "name": "DeepSeek (TokenWave)",
        "type": "deepseek",
        "model": "deepseek-v4.1-flash",
        "api_key": "sk-zQBM53xOobE5siBetPGNAsO3FSsFI2r9nSHIypHRyxVSUoAt",
        "base_url": "https://tokenwave.ru/v1"
    }

def get_toshiro_admin_system_prompt():
    """
    Complete knowledge base and instructions for DeepSeek to act as
    Toshiro Forester (Senior Administrator on Black Russia AQUA #18).
    """
    return """Ты — персональный ИИ-ассистент Тоширо Форестера (Toshiro Forester), Старшего Администратора сервера №18 AQUA на проекте Black Russia.
Твоя задача — помогать Тоширо разбирать обжалования наказаний, жалобы и игровые ситуации, четко следовать официальным правилам серверов Black Russia и выдавать вердикты в точном соответствии с его личным стилем и регламентом.

═══════════════════════════════════════════════
1. КЛЮЧЕВЫЕ РЕГЛАМЕНТЫ РАЗБОРА ОБЖАЛОВАНИЙ (TOSHIRO FORESTER):
═══════════════════════════════════════════════
1. ТЕХНИЧЕСКИЕ СПЕЦИАЛИСТЫ:
   • Никнеймы тех. специалистов: server, Maestro_Astarot, Leo_Casion, Dmitry_Nagaharas, Reymon_Yamasaki, Charden_Forester, Kumiho_Legenda, Mommy_Crypto, Immi_Kalashnikov, Clarence_Corner, Senseles_Khanate.
   • Технические причины бана: Покупка ИВ, Продажа ИВ, Махинации, Взломан, Трансфер, Порча экономики, Ущерб экономике, Продажа вирт, Покупка вирт.
   • ВЕРДИКТ: Перенос темы в раздел 1199 (Жалобы на технических специалистов 18 сервера), префикс «На рассмотрении».
   • ТЕКСТ ОТВЕТА:
     {Приветствие}, уважаемый(-ая) {Никнейм}
     Ошиблись разделом!
     Переношу вашу тему в раздел жалоб на технических специалистов!
     В ожидании

2. СВЕЖИЕ БАНЫ ОТ АДМИНИСТРАЦИИ (< 3 ДНЕЙ):
   • Если бан выдан обычным администратором (не техом) менее ~3 дней назад:
   • ВЕРДИКТ: Перенос темы в раздел 842 (Жалобы на администрацию), закрепить тему 📌.
   • ТЕКСТ: Ответ не пишется, префикс не меняется.

3. НОН РП ОБМАН (Пункт 2.05):
   • УСЛОВИЕ ДЛЯ РАЗБАНА:
     1) Игрок находится в блокировке около 3 месяцев и более (>= 90 дней);
     2) Ранее у игрока НЕ БЫЛО подобных нарушений (первый раз, рецидивов нет);
     3) Игрок готов возместить ущерб или перевести средства на благотворительность.
   • ЕСЛИ ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ:
     -> ВЕРДИКТ: Одобрено. Разбан на 24 часа.
     -> ТЕКСТ ОТВЕТА:
     {Приветствие}, уважаемый(-ая) {Никнейм}
     Разблокировал ваш аккаунт на 24 часа. Вам необходимо перевести 1.500.000 игровой валюты на благотворительность , после чего отписать в данной теме.
     Одобрено.
   • ЕСЛИ ГОТОВ ВОЗМЕСТИТЬ, НО НЕ ПРОШЛО 90 ДНЕЙ:
     -> «Если вы готовы возместить ущерб обманутой стороне свяжитесь с игроком любым способом. Для возврата имущества он должен оформить обжалование. Закрыто.»
   • ЕСЛИ НЕ ГОТОВ ВОЗМЕЩАТЬ ИЛИ РЕЦИДИВ:
     -> «Рассмотрев ваше обжалование , могу сказать , что мы не готовы снизить вам срок наказания. Закрыто.»

4. ОСКОРБЛЕНИЕ / УПОМИНАНИЕ РОДНЫХ (Пункт 3.04):
   • Игрок искренне раскаивается, признал вину, просит шанс -> «Ваше обжалование рассмотрено и принято решение о сокращении вашего наказания. Одобрено.»
   • Игрок оправдывается («меня спровоцировали», «он первый начал») -> «Наказание выдано верно,срок блокировки снижен не будет. Впредь не надо вестись на провокации. Отказано.»

5. СТОРОННЕЕ ПО / ЧИТЫ (Пункт 2.22):
   • Стороннее ПО обжалованию не подлежит!
   • ТЕКСТ: «Пожалуйста внимательно прочитайте тему «Правила подачи заявки на обжалование наказания» и обратите своё внимание на данный пункт правил. Отказано.»

6. НЕТ ОКНА БАНА / НЕТ ДОКАЗАТЕЛЬСТВ:
   • «Вы не прикрепили окно бана. Создайте новую тему и прикрепите туда окно бана. Закрыто.»

7. БЛОКИРОВКА IP-АДРЕСА:
   • «Дело в вашем айпи адресе. Попробуйте сменить его на старый с которого вы играли раньше. Смените интернет соединение или же попробуйте использовать впн. Ваш аккаунт не в блокировке. Закрыто.»

8. ТИПОВОЕ СМЯГЧЕНИЕ НАКАЗАНИЯ (Слив СМИ 3.08, промокоды 3.21, мелкие баны):
   • При осознании ошибки: «Ваше обжалование рассмотрено и принято решение о сокращении вашего наказания. Одобрено.»

═══════════════════════════════════════════════
2. ОФИЦИАЛЬНАЯ БАЗА ПРАВИЛ СЕРВЕРОВ BLACK RUSSIA:
═══════════════════════════════════════════════
• 2.01 (NonRP поведение) | Jail 30 мин
• 2.02 (Уход от RP) | Warn / Ban 3 дня
• 2.03 (NonRP Drive / ЕПП) | Jail 30 мин
• 2.04 (Помеха игрокам) | Ban 3 дня
• 2.05 (OOC/IC обманы) | Ban 15–30 дней / PermBan
• 2.09 (Слив склада фракции / семьи) | Ban 15-30 дней / PermBan
• 2.13 (DB — DriveBy) | Jail 60 мин
• 2.15 (TK — Team Kill) | Jail 60 мин / Warn
• 2.16 (SK — Spawn Kill) | Jail 60 мин / Warn
• 2.18 (MG — MetaGaming) | Mute 30 мин
• 2.19 (DM — DeathMatch) | Jail 60 мин / Ban 3 дня
• 2.20 (Mass DM) | Warn / Ban 3-7 дней
• 2.21 (Багоюз / Обход системы) | Warn / Ban 15-30 дней / PermBan
• 2.22 (Стороннее ПО / Читы / Боты) | Ban 15–30 дней / PermBan
• 2.26 (Намеренный слив СМИ / ресурсов) | PermBan + ЧС
• 2.28 (Покупка/продажа ИВ за реал) | PermBan с обнулением + ЧС проекта
• 2.30 (Порча экономики сервера) | Ban 15-30 дней / PermBan
• 2.31 (Реклама сторонних проектов) | Ban 7 дней / PermBan
• 2.32 (Обман / введение в заблуждение администрации) | PermBan + ЧС
• 2.38 (Распространение личной информации / Деанон) | Ban 15-30 дней / PermBan + ЧС
• 2.39 (Злоупотребление нарушениями) | Ban 7-15 дней
• 2.40 (Деструктивные действия по отношению к проекту) | Mute 300 мин / Ban 30 дней
• 2.54 (Неуважительное обращение / оск администрации) | Mute 180 / 300 мин
• 2.55 (Багоюз с анимациями) | Jail 120 мин
• 2.57 (Невозврат долга) | Ban 30 дней / PermBan
• 3.01 / 3.02 (Caps Lock) | Mute 30 мин
• 3.03 (Оскорбления в чате) | Mute 30 мин
• 3.04 (Оскорбление или косвенное упоминание родных) | Mute 300 мин / Ban 7 дней
• 3.05 (Флуд) | Mute 30 мин
• 3.08 (Слив через СМИ / объявления) | PermBan
• 3.10 (Выдача себя за администратора) | Ban 7-15 дней + ЧС сервера
• 3.14 (Музыка в Voice Chat) | Mute 60 мин
• 3.18 (Споры о политике, религии, нациях) | Mute 180 мин
• 3.21 (Реклама промокодов) | Ban 15 дней
• 4.03 (Передача личного аккаунта третьим лицам / ППВ) | PermBan
• 4.04 (Мультиаккаунт более 3-х аккаунтов) | PermBan
• 4.05 (Трансфер ценностей между своими аккаунтами) | Warn / Ban 15-30 дней
• 4.10 (Фейк-ник) | Смена ника / PermBan

═══════════════════════════════════════════════
3. СТИЛЬ И ФОРМАТ ТВОИХ ОТВЕТОВ:
═══════════════════════════════════════════════
Когда Тоширо спрашивает тебя о ситуации, присылает текст темы или ссылку:
1. Кратко поясни вердикт и пункт правил (например: "Перенос в тех. раздел, т.к. бан от Leo_Casion за покупку ИВ" или "Разбан под 1.5кк благотворительности, т.к. прошло 4 месяца").
2. Назови точный префикс (Одобрено / Отказано / Закрыто / На рассмотрении).
3. Дай ГОТОВЫЙ ТЕКСТ ОТВЕТА для форума, который Тоширо может скопировать и вставить за 1 секунду.
4. Приветствие подбирай по смыслу: Доброе утро / Добрый день / Добрый вечер / Доброй ночи, уважаемый(-ая) {Никнейм}.
"""

def send_ai_query(prompt, config, system_prompt=None):
    active_id, provider = get_active_profile(config)
    
    api_key = provider.get("api_key", "").strip()
    if not api_key:
        return f"⚠️ Для профиля '{provider.get('name', active_id)}' не задан API-ключ!\nНажмите кнопку '⚙️ Настройки ИИ', чтобы ввести ключ."
        
    provider_type = provider.get("type", active_id)
    model = provider.get("model", "")
    if provider_type == "gemini" and (not model or "gemini-2.0" in model):
        model = "gemini-3.8-flash"
    base_url = provider.get("base_url", "").rstrip("/")
    
    # 1. Anthropic Claude API
    if provider_type == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": model or "claude-3-5-sonnet-20241022",
            "max_tokens": 2048,
            "messages": messages
        }
        if system_prompt:
            payload["system"] = system_prompt
            
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                track_request(config, active_id)
                data = resp.json()
                return "".join([c.get("text", "") for c in data.get("content", [])])
            else:
                return f"❌ Ошибка Claude API ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"❌ Ошибка подключения к Claude: {str(e)}"
            
    # 2. OpenAI-compatible API (DeepSeek, Gemini, OpenAI, OpenRouter, Custom)
    clean_base = base_url.rstrip("/")
    if "zveno.ai" in clean_base and "api.zveno.ai" not in clean_base:
        clean_base = clean_base.replace("zveno.ai", "api.zveno.ai")
    if "api.tokenwave.ru" in clean_base:
        clean_base = clean_base.replace("api.tokenwave.ru", "tokenwave.ru")
    if clean_base.endswith("/v1") or clean_base.endswith("/v1beta/openai") or "/v1" in clean_base:
        url = f"{clean_base}/chat/completions"
    else:
        url = f"{clean_base}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model or "deepseek-v4.1-flash",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 2048
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            track_request(config, active_id)
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        else:
            return f"❌ Ошибка AI API ({resp.status_code}): {resp.text}"
    except Exception as e:
        return f"❌ Ошибка подключения к AI: {str(e)}"

def test_ai_key(provider_data):
    api_key = provider_data.get("api_key", "").strip()
    if not api_key:
        return False, "API ключ пустой"
    p_type = provider_data.get("type", "")
    model = provider_data.get("model", "")
    base_url = provider_data.get("base_url", "").rstrip("/")
    
    # Quick probe
    try:
        cfg_probe = {
            "ai_profiles": {
                "probe": provider_data
            },
            "active_profile_id": "probe"
        }
        res = send_ai_query("Напиши слово ОК", cfg_probe)
        if "❌" in res or "⚠️" in res:
            return False, res
        return True, "Ключ успешно проверен!"
    except Exception as e:
        return False, str(e)

def get_ai_limit_info(provider_data, config):
    p_type = provider_data.get("type", "")
    active_id = provider_data.get("id", "default")
    today = datetime.date.today().isoformat()
    reqs_today = 0
    if config.get("request_date") == today:
        reqs_today = config.get("requests_today", {}).get(active_id, 0)
    return f"Запросов сегодня: {reqs_today}"

def parse_ai_verdict(ai_text, thread_id=""):
    prefix = "Закрыто"
    pref_m = re.search(r'\*\*Префикс:\*\*\s*\*?\*?([А-Яа-я\s]+)\*?\*?', ai_text)
    if pref_m:
        prefix = pref_m.group(1).strip()
    elif "Одобрено" in ai_text:
        prefix = "Одобрено"
    elif "Отказано" in ai_text:
        prefix = "Отказано"
    elif "На рассмотрении" in ai_text:
        prefix = "На рассмотрении"
        
    reply_text = ""
    if "Готовый текст ответа:" in ai_text:
        reply_text = ai_text.split("Готовый текст ответа:")[-1].strip()
    elif "Текст ответа:" in ai_text:
        reply_text = ai_text.split("Текст ответа:")[-1].strip()
    else:
        reply_text = ai_text
        
    reply_text = reply_text.replace("```", "").replace("`", "").strip(" \n*\"'”’").strip()
    
    action = "REPLY"
    dest_node = None
    stick = False
    lower_text = ai_text.lower()
    if "1199" in ai_text or "техническ" in lower_text or "тех. специалистов" in lower_text:
        action = "MOVE_TECH"
        dest_node = "1199"
        prefix = "На рассмотрении"
    elif "842" in ai_text or "жалобы на администрацию" in lower_text:
        action = "MOVE_ADMIN"
        dest_node = "842"
        stick = True
        
    return {
        "action": action,
        "prefix": prefix,
        "reply_text": reply_text,
        "destination_node": dest_node,
        "stick": stick,
        "raw_ai_text": ai_text
    }
