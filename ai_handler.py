import json
import datetime
import requests

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
    active_key = config.get("active_ai", "gemini")
    if active_key in providers:
        return active_key, providers[active_key]
        
    return "default", {
        "name": "Google Gemini",
        "type": "gemini",
        "model": "gemini-3.8-flash",
        "api_key": "",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"
    }

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
            
    # 2. OpenAI-compatible API (Gemini, OpenAI, DeepSeek, OpenRouter, Custom)
    clean_base = base_url.rstrip("/")
    if "zveno.ai" in clean_base and "api.zveno.ai" not in clean_base:
        clean_base = clean_base.replace("zveno.ai", "api.zveno.ai")
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
    
    MODEL_ALIASES = {
        "nvidia: nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nemotron": "nvidia/nemotron-3-ultra-550b-a55b:free",
    }
    target_model = MODEL_ALIASES.get(model.lower().strip(), model)

    payload = {
        "model": target_model,
        "messages": messages
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp_text = resp.text.strip()
        is_html = resp_text.startswith("<") or "<!doctype" in resp_text.lower() or "<html" in resp_text.lower()
        
        # If model_not_found, try alternate :free suffix
        if resp.status_code == 404 and "model_not_found" in resp_text:
            alt_m = target_model.replace(":free", "") if ":free" in target_model else f"{target_model}:free"
            alt_payload = dict(payload, model=alt_m)
            alt_m_resp = requests.post(url, headers=headers, json=alt_payload, timeout=60)
            if alt_m_resp.status_code == 200:
                resp = alt_m_resp
                resp_text = resp.text.strip()
                is_html = False

        # If returned HTML or not 200, try fallback between /v1/chat/completions and /chat/completions
        if (resp.status_code != 200 or is_html) and "/v1/" in url:
            alt_url = url.replace("/v1/chat/completions", "/chat/completions")
            alt_resp = requests.post(alt_url, headers=headers, json=payload, timeout=60)
            alt_text = alt_resp.text.strip()
            alt_is_html = alt_text.startswith("<") or "<!doctype" in alt_text.lower() or "<html" in alt_text.lower()
            if alt_resp.status_code == 200 and not alt_is_html:
                resp = alt_resp
                resp_text = alt_text
                is_html = False
        elif (resp.status_code != 200 or is_html) and "/v1/" not in url:
            alt_url = url.replace("/chat/completions", "/v1/chat/completions")
            alt_resp = requests.post(alt_url, headers=headers, json=payload, timeout=60)
            alt_text = alt_resp.text.strip()
            alt_is_html = alt_text.startswith("<") or "<!doctype" in alt_text.lower() or "<html" in alt_text.lower()
            if alt_resp.status_code == 200 and not alt_is_html:
                resp = alt_resp
                resp_text = alt_text
                is_html = False

        if is_html:
            return f"❌ Сервер ИИ вернул HTML-страницу (код {resp.status_code}) вместо JSON-ответа.\nПроверьте правильность URL эндпоинта или модели в настройках бота."

        if resp.status_code == 200:
            track_request(config, active_id)
            try:
                data = resp.json()
            except Exception:
                return f"❌ Сервер ИИ вернул не JSON (код 200):\n{resp_text[:250]}"
                
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return "Получен пустой ответ от модели."
        else:
            return f"❌ Ошибка API ({resp.status_code}): {resp_text[:300]}"
    except Exception as e:
        return f"❌ Ошибка подключения к ИИ: {str(e)}"

def test_ai_key(provider_key, api_key, base_url, model):
    if not api_key:
        return False, "Ключ пустой."
        
    if provider_key == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model or "claude-3-5-sonnet-20241022",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "ping"}]
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                return True, "Ключ успешно проверен!"
            return False, f"Ошибка {resp.status_code}: {resp.text}"
        except Exception as e:
            return False, str(e)
            
    if provider_key == "gemini" and (not model or "gemini-2.0" in model):
        model = "gemini-3.8-flash"

    clean_base = base_url.rstrip("/")
    if "zveno.ai" in clean_base and "api.zveno.ai" not in clean_base:
        clean_base = clean_base.replace("zveno.ai", "api.zveno.ai")
    if clean_base.endswith("/v1") or clean_base.endswith("/v1beta/openai") or "/v1" in clean_base:
        url = f"{clean_base}/chat/completions"
    else:
        url = f"{clean_base}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    MODEL_ALIASES = {
        "nvidia: nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia nemotron 3 ultra": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nemotron": "nvidia/nemotron-3-ultra-550b-a55b:free",
    }
    target_model = MODEL_ALIASES.get((model or "").lower().strip(), model or "gpt-4o")

    payload = {
        "model": target_model,
        "messages": [{"role": "user", "content": "ping"}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp_text = resp.text.strip()
        is_html = resp_text.startswith("<") or "<!doctype" in resp_text.lower()
        if (resp.status_code != 200 or is_html) and "/v1/" in url:
            alt_url = url.replace("/v1/chat/completions", "/chat/completions")
            alt_resp = requests.post(alt_url, headers=headers, json=payload, timeout=15)
            alt_text = alt_resp.text.strip()
            if alt_resp.status_code == 200 and not (alt_text.startswith("<") or "<!doctype" in alt_text.lower()):
                resp = alt_resp
                resp_text = alt_text
                is_html = False
        elif (resp.status_code != 200 or is_html) and "/v1/" not in url:
            alt_url = url.replace("/chat/completions", "/v1/chat/completions")
            alt_resp = requests.post(alt_url, headers=headers, json=payload, timeout=15)
            alt_text = alt_resp.text.strip()
            if alt_resp.status_code == 200 and not (alt_text.startswith("<") or "<!doctype" in alt_text.lower()):
                resp = alt_resp
                resp_text = alt_text
                is_html = False

        if is_html:
            return False, f"Сервер вернул HTML вместо API (код {resp.status_code}). Проверьте URL."
        if resp.status_code == 200:
            return True, "Ключ успешно проверен!"
        return False, f"Ошибка {resp.status_code}: {resp_text[:200]}"
    except Exception as e:
        return False, str(e)

def get_ai_limit_info(arg1, arg2=None, arg3=None):
    if isinstance(arg1, dict):
        provider_info = arg1
        provider_key = provider_info.get("type", "gemini")
        config = arg2
    elif isinstance(arg1, str) and isinstance(arg2, dict):
        provider_key = arg2.get("type", arg1)
        provider_info = arg2
        config = arg3
    else:
        return "❌ Неверный профиль"

    api_key = provider_info.get("api_key", "").strip()
    if not api_key:
        return "❌ Ключ не задан"
        
    base_url = provider_info.get("base_url", "").rstrip("/")
    model = provider_info.get("model", "")
    
    # 1. DeepSeek
    if provider_key == "deepseek":
        try:
            r = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                for b in data.get("balance_infos", []):
                    total = b.get("total_balance", "0")
                    curr = b.get("currency", "CNY")
                    try:
                        if float(total) > 0:
                            return f"💰 {total} {curr}"
                    except:
                        pass
                return "💰 0.00 CNY"
            elif r.status_code == 401:
                return "❌ Неверный ключ"
            return f"⚠️ Статус {r.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    # 2. OpenRouter
    if provider_key == "openrouter":
        try:
            r = requests.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5
            )
            if r.status_code == 200:
                d = r.json().get("data", {})
                limit = d.get("limit")
                usage = d.get("usage", 0)
                is_free = d.get("is_free_tier", False)
                if limit is not None:
                    left = max(0.0, float(limit) - float(usage))
                    return f"💰 ${left:.2f} (из ${float(limit):.2f})"
                
                # Check credits
                r2 = requests.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=5
                )
                if r2.status_code == 200:
                    c = r2.json().get("data", {})
                    tot = float(c.get("total_credits", 0))
                    used = float(c.get("total_usage", 0))
                    left = max(0.0, tot - used)
                    if left > 0:
                        return f"💰 ${left:.2f} USD"
                    if is_free:
                        return "🆓 Free Tier (Бесплатно)"
                    return f"💰 ${left:.2f} USD"
                return "🆓 Free Tier (Бесплатно)"
            elif r.status_code == 401:
                return "❌ Неверный ключ"
            return f"⚠️ Статус {r.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    # 3. OpenAI
    if provider_key == "openai":
        try:
            r_sub = requests.get(
                "https://api.openai.com/v1/dashboard/billing/credit_grants",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=4
            )
            if r_sub.status_code == 200:
                tot = r_sub.json().get("total_available", 0)
                return f"💰 ${float(tot):.2f} USD"
                
            # Lightweight probe
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": model or "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1
            }
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=5
            )
            if resp.status_code == 200:
                rem = resp.headers.get("x-ratelimit-remaining-requests")
                lim = resp.headers.get("x-ratelimit-limit-requests")
                if rem and lim:
                    return f"⚡️ {rem}/{lim} RPM (активен)"
                return "🟢 Активен (Pay-as-you-go)"
            elif resp.status_code == 401:
                return "❌ Неверный ключ"
            elif resp.status_code == 429:
                return "⚠️ Превышен лимит (Quota exceeded)"
            return f"⚠️ Статус {resp.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    # 4. Anthropic
    if provider_key == "anthropic":
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": model or "claude-3-5-sonnet-20241022",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}]
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                rem = resp.headers.get("anthropic-ratelimit-requests-remaining")
                lim = resp.headers.get("anthropic-ratelimit-requests-limit")
                if rem and lim:
                    return f"⚡️ {rem}/{lim} RPM (активен)"
                return "🟢 Активен (Pay-as-you-go)"
            elif resp.status_code == 401:
                return "❌ Неверный ключ"
            elif resp.status_code == 429:
                return "⚠️ Превышен лимит (Quota exceeded)"
            return f"⚠️ Статус {resp.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    # 5. Gemini
    if provider_key == "gemini":
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                # Gemini free tier default limit is 15 RPM / 1500 RPD
                today_reqs = (config or {}).get("requests_today", {}).get("gemini", 0)
                left_rpd = max(0, 1500 - today_reqs)
                return f"⚡️ 15 RPM | {left_rpd}/1500 RPD сегодня"
            elif resp.status_code in (400, 401, 403):
                return "❌ Неверный ключ"
            elif resp.status_code == 429:
                return "⚠️ Лимит исчерпан (429)"
            return f"⚠️ Статус {resp.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    # 6. Custom
    if provider_key == "custom":
        clean_base = base_url.rstrip("/")
        if "zveno.ai" in clean_base and "api.zveno.ai" not in clean_base:
            clean_base = clean_base.replace("zveno.ai", "api.zveno.ai")
        if not clean_base.endswith("/v1"):
            clean_base = f"{clean_base}/v1"
        try:
            r = requests.get(f"{clean_base}/user/balance", headers={"Authorization": f"Bearer {api_key}"}, timeout=3)
            if r.status_code == 200:
                return f"💰 {r.text[:25]}"
            r2 = requests.get(f"{clean_base}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=3)
            if r2.status_code == 200:
                return "🟢 Сервис онлайн"
            elif r2.status_code == 401:
                return "❌ Неверный ключ"
            return f"⚠️ Статус {r2.status_code}"
        except Exception:
            return "⚠️ Ошибка сети"
            
    return "Неизвестно"
