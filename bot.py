import os
import sys
import json
import uuid
import time
import threading
import html
from datetime import datetime, timedelta, timezone

MSK_TZ = timezone(timedelta(hours=3))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import telebot
from telebot import types
import importlib

import ai_handler
from ai_handler import send_ai_query, test_ai_key, get_ai_limit_info, get_active_profile
import sheets_runner
from sheets_runner import run_sheets_audit
import forum_runner
from forum_runner import get_overdue_and_urgent_report, get_ga_complaints_report, get_full_forum_report

try:
    import rules_kb
except Exception:
    rules_kb = None

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_TEMPLATES = {
    "gemini": {
        "name": "Google Gemini",
        "type": "gemini",
        "model": "gemini-3.8-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "icon": "🔷"
    },
    "openai": {
        "name": "OpenAI (ChatGPT)",
        "type": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "icon": "🟢"
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "type": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "base_url": "https://api.anthropic.com/v1",
        "icon": "🟣"
    },
    "deepseek": {
        "name": "DeepSeek (TokenWave)",
        "type": "deepseek",
        "model": "deepseek-v4.1-flash",
        "base_url": "https://tokenwave.ru/v1",
        "icon": "🔵"
    },
    "openrouter": {
        "name": "OpenRouter",
        "type": "openrouter",
        "model": "google/gemini-2.0-flash-exp:free",
        "base_url": "https://openrouter.ai/api/v1",
        "icon": "🔀"
    },
    "custom": {
        "name": "Свой API",
        "type": "custom",
        "model": "default",
        "base_url": "",
        "icon": "🌐"
    }
}

def load_config():
    cfg = {}
    local_backup = os.path.join(os.path.dirname(__file__), "config.backup.json")
    if os.path.exists(local_backup) and not os.environ.get("BOT_TOKEN"):
        try:
            with open(local_backup, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
            
    if not cfg and os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        
    # Auto-migration to ai_profiles if needed
    if "ai_profiles" not in cfg:
        cfg["ai_profiles"] = {}
        old_providers = cfg.get("ai_providers", {})
        for k, p in old_providers.items():
            cfg["ai_profiles"][k] = {
                "id": k,
                "name": p.get("name", k),
                "type": k,
                "model": p.get("model", ""),
                "api_key": p.get("api_key", ""),
                "base_url": p.get("base_url", "")
            }
        cfg["active_profile_id"] = cfg.get("active_ai", "gemini")
        
    # Override from environment variables if present
    env_token = os.environ.get("BOT_TOKEN")
    if env_token:
        cfg["bot_token"] = env_token.strip()
    env_admins = os.environ.get("ADMIN_IDS")
    if env_admins:
        try:
            cfg["admin_ids"] = [int(x.strip()) for x in env_admins.split(",") if x.strip()]
        except Exception:
            pass

    # Optional AI keys from environment variables
    env_zveno = os.environ.get("ZVENO_API_KEY")
    if env_zveno:
        for p in cfg.get("ai_profiles", {}).values():
            if "zveno" in p.get("base_url", ""):
                p["api_key"] = env_zveno.strip()
    env_gemini = os.environ.get("GEMINI_API_KEY")
    if env_gemini:
        for p in cfg.get("ai_profiles", {}).values():
            if p.get("type") == "gemini":
                p["api_key"] = env_gemini.strip()
    env_deepseek = os.environ.get("DEEPSEEK_API_KEY")
    if env_deepseek:
        for p in cfg.get("ai_profiles", {}).values():
            if p.get("type") == "deepseek":
                p["api_key"] = env_deepseek.strip()

    # Forum credentials
    env_xf_user = os.environ.get("FORUM_XF_USER")
    if env_xf_user:
        cfg["forum_xf_user"] = env_xf_user.strip()
    elif "forum_xf_user" in cfg:
        os.environ["FORUM_XF_USER"] = cfg["forum_xf_user"]

    env_xf_tfa = os.environ.get("FORUM_XF_TFA_TRUST")
    if env_xf_tfa:
        cfg["forum_xf_tfa_trust"] = env_xf_tfa.strip()
    elif "forum_xf_tfa_trust" in cfg:
        os.environ["FORUM_XF_TFA_TRUST"] = cfg["forum_xf_tfa_trust"]

    # Google Sheets proxy URL
    env_google_proxy = os.environ.get("GOOGLE_PROXY_URL")
    if env_google_proxy:
        cfg["google_proxy_url"] = env_google_proxy.strip()
    elif "google_proxy_url" in cfg:
        os.environ["GOOGLE_PROXY_URL"] = cfg["google_proxy_url"]

    # Background Alerts Settings
    if "auto_alerts_enabled" not in cfg:
        cfg["auto_alerts_enabled"] = True
    if "alert_interval_minutes" not in cfg:
        cfg["alert_interval_minutes"] = 30
    env_alerts = os.environ.get("AUTO_ALERTS_ENABLED")
    if env_alerts is not None:
        cfg["auto_alerts_enabled"] = env_alerts.lower() in ("true", "1", "yes")
    env_interval = os.environ.get("ALERT_INTERVAL_MINUTES")
    if env_interval:
        try:
            cfg["alert_interval_minutes"] = int(env_interval)
        except Exception:
            pass

    return cfg

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()
bot = telebot.TeleBot(config["bot_token"], parse_mode="HTML")

# Safe wrappers for TeleBot to prevent any crash from entity parsing (HTML)
_orig_send_message = bot.send_message
_orig_edit_message_text = bot.edit_message_text
_orig_reply_to = bot.reply_to

def _safe_send_message(chat_id, text, **kwargs):
    try:
        return _orig_send_message(chat_id, text, **kwargs)
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["can't parse entities", "unsupported start tag", "bad request: can't parse", "entity"]):
            kw = dict(kwargs)
            kw["parse_mode"] = None
            return _orig_send_message(chat_id, text, **kw)
        raise e

def _safe_edit_message_text(text, chat_id=None, message_id=None, **kwargs):
    try:
        return _orig_edit_message_text(text, chat_id=chat_id, message_id=message_id, **kwargs)
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["can't parse entities", "unsupported start tag", "bad request: can't parse", "entity"]):
            kw = dict(kwargs)
            kw["parse_mode"] = None
            return _orig_edit_message_text(text, chat_id=chat_id, message_id=message_id, **kw)
        raise e

def _safe_reply_to(message, text, **kwargs):
    try:
        return _orig_reply_to(message, text, **kwargs)
    except Exception as e:
        err_str = str(e).lower()
        if any(x in err_str for x in ["can't parse entities", "unsupported start tag", "bad request: can't parse", "entity"]):
            kw = dict(kwargs)
            kw["parse_mode"] = None
            return _orig_reply_to(message, text, **kw)
        raise e

bot.send_message = _safe_send_message
bot.edit_message_text = _safe_edit_message_text
bot.reply_to = _safe_reply_to

# In-memory user states
user_states = {}

def is_admin(user_id):
    if not user_id:
        return False
    cfg = load_config()
    admins = cfg.get("admin_ids") or [1399524277, 5594041416]
    for a in admins:
        if str(a) == str(user_id):
            return True
    return False

def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, is_persistent=True)
    b_sheets = types.KeyboardButton("📊 Проверить таблицы")
    b_overdue = types.KeyboardButton("🚨 Просрочки на форуме")
    b_ga = types.KeyboardButton("👑 Жалобы ГА")
    b_full_forum = types.KeyboardButton("📑 Полный аудит форума")
    b_ai = types.KeyboardButton("⚙️ Настройки ИИ")
    b_alerts = types.KeyboardButton("🔔 Авто-алерты")
    markup.add(b_sheets, b_overdue)
    markup.add(b_ga, b_full_forum)
    markup.add(b_ai, b_alerts)
    return markup

def get_main_inline_keyboard(user_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Проверить таблицы", callback_data="menu:sheets"),
        types.InlineKeyboardButton("🚨 Просрочки на форуме", callback_data="menu:overdue")
    )
    markup.add(
        types.InlineKeyboardButton("👑 Жалобы ГА", callback_data="menu:ga"),
        types.InlineKeyboardButton("📑 Полный аудит форума", callback_data="menu:full_forum")
    )
    markup.add(
        types.InlineKeyboardButton("⚙️ Настройки ИИ", callback_data="menu:ai"),
        types.InlineKeyboardButton("🔔 Авто-алерты", callback_data="menu:alerts")
    )
    return markup

def build_alerts_settings_content(cfg=None):
    if cfg is None:
        cfg = load_config()
    enabled = cfg.get("auto_alerts_enabled", True)
    interval = cfg.get("alert_interval_minutes", 30)
    admins = cfg.get("admin_ids") or [1399524277, 5594041416]
    
    st_icon = "🟢" if enabled else "🔴"
    st_text = "<b>ВКЛЮЧЕН</b>" if enabled else "<b>ВЫКЛЮЧЕН</b>"
    
    info = (
        "🔔 <b>АВТОМАТИЧЕСКИЙ МОНИТОРИНГ ФОРУМА</b>\n\n"
        f"• Статус фонового сканера: {st_icon} {st_text}\n"
        f"• Периодичность проверки: <b>каждые {interval} мин.</b>\n"
        f"• Получатели оповещений: <b>{len(admins)} админа</b>\n"
        f"• Посл. проверка: <code>{_monitor_status.get('last_check_msk', 'Нет')}</code>\n"
        f"• Статус сканера: <i>{html.escape(str(_monitor_status.get('last_result', 'Ожидание')))}</i>\n\n"
        "<b>Что отслеживается в реальном времени:</b>\n"
        "• 🔴 <b>Просроченные темы</b> (моментально + повтор раз в 2 ч.)\n"
        "• ⏳ <b>Горящие дедлайны</b> (менее 4 ч. и повтор менее 1 ч.)\n"
        "• 👑 <b>Темы «Главному Администратору»</b> (+ повтор раз в 6 ч.)\n\n"
        "<i>💡 Проверка выполняется парсером: расход токенов ИИ = 0.</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    toggle_text = "🔴 Выключить мониторинг" if enabled else "🟢 Включить мониторинг"
    markup.add(types.InlineKeyboardButton(toggle_text, callback_data="toggle_alerts"))
    
    i15 = f"{'✅ ' if interval == 15 else ''}15 мин"
    i30 = f"{'✅ ' if interval == 30 else ''}30 мин"
    i60 = f"{'✅ ' if interval == 60 else ''}60 мин"
    markup.add(
        types.InlineKeyboardButton(i15, callback_data="set_alert_interval:15"),
        types.InlineKeyboardButton(i30, callback_data="set_alert_interval:30"),
        types.InlineKeyboardButton(i60, callback_data="set_alert_interval:60")
    )
    markup.add(types.InlineKeyboardButton("🔍 Проверить форум прямо сейчас", callback_data="check_alerts_now"))
    markup.add(types.InlineKeyboardButton("🔙 Закрыть", callback_data="close_settings"))
    return info, markup

def build_ai_settings_content():
    cfg = load_config()
    active_id, active_prof = get_active_profile(cfg)
    profiles = cfg.get("ai_profiles", {})
    
    has_k = "✅ задан" if active_prof.get("api_key") else "❌ не задан"
    limit_str = get_ai_limit_info(active_prof, cfg) if active_prof.get("api_key") else "❌ Ключ не задан"
    
    t_icon = DEFAULT_TEMPLATES.get(active_prof.get("type", "custom"), {}).get("icon", "🤖")
    
    info = (
        f"⚙️ <b>НАСТРОЙКИ ИИ (Загружено профилей: {len(profiles)})</b>\n\n"
        f"Текущий активный: {t_icon} <b>{active_prof.get('name', 'ИИ')}</b>\n"
        f"🤖 Модель: <code>{active_prof.get('model', '')}</code>\n"
        f"📊 <b>Остаток лимита / Баланс:</b> <code>{limit_str}</code>\n"
        f"🔑 Статус ключа: {has_k}\n\n"
        "<i>Нажмите на профиль ниже для переключения или добавьте новый API:</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # List of all configured profiles
    buttons = []
    for pid, prof in profiles.items():
        is_active = (pid == active_id)
        icon = "🟢 " if is_active else "⚪️ "
        key_icon = "🔑" if prof.get("api_key") else "❌"
        btn_text = f"{icon}{prof.get('name', pid)} [{key_icon}]"
        buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"sel_prof:{pid}"))
        
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i+1])
        else:
            markup.add(buttons[i])
            
    # Management buttons
    markup.add(types.InlineKeyboardButton("➕ Добавить новый API", callback_data="add_new_api_menu"))
    markup.add(types.InlineKeyboardButton("🔄 Обновить остаток лимита", callback_data="refresh_ai_limits"))
    markup.add(
        types.InlineKeyboardButton("✏️ Сменить ключ/модель", callback_data="edit_active_prof"),
        types.InlineKeyboardButton("🗑 Удалить API", callback_data="del_api_menu")
    )
    markup.add(types.InlineKeyboardButton("🔙 Закрыть", callback_data="close_settings"))
    
    return info, markup

def send_long_message(chat_id, text):
    if len(text) <= 4000:
        bot.send_message(chat_id, text, disable_web_page_preview=True)
    else:
        parts = []
        while len(text) > 4000:
            split_pos = text.rfind("\n\n", 0, 4000)
            if split_pos == -1:
                split_pos = 4000
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        parts.append(text)
        for p in parts:
            bot.send_message(chat_id, p, disable_web_page_preview=True)

# /start command
@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔️ Доступ ограничен. Этот бот предназначен только для авторизованных администраторов.")
        return
        
    cfg = load_config()
    _, active_prof = get_active_profile(cfg)
    
    welcome = (
        f"👋 <b>Добро пожаловать, {message.from_user.first_name}!</b>\n\n"
        "Бот готов к выполнению аудита и работе с ИИ:\n"
        "• <b>Таблицы:</b> 3/3 выговоров, красные ячейки, нормы АП и Администрации.\n"
        "• <b>Форум:</b> просрочки, жалобы ГА с выжимкой сути, подфорумы на доработке.\n"
        "• <b>Авто-алерты:</b> фоновое оповещение при горящих дедлайнах (менее 4 ч.) и просрочках.\n"
        f"• <b>Активный ИИ:</b> <code>{active_prof.get('name', 'ИИ')}</code> (можно загружать любое количество API).\n\n"
        "Выберите действие кнопками ниже:"
    )
    # 1. Main message with interactive inline buttons right under text
    bot.send_message(message.chat.id, welcome, reply_markup=get_main_inline_keyboard(message.from_user.id))
    # 2. Pin persistent reply keyboard at the bottom
    bot.send_message(
        message.chat.id,
        "⚡️ <i>Клавиатура быстрого доступа также закреплена внизу экрана:</i>",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@bot.message_handler(commands=['alerts'])
def handle_alerts_cmd(message):
    if not is_admin(message.from_user.id):
        return
    info, markup = build_alerts_settings_content()
    bot.send_message(message.chat.id, info, reply_markup=markup)

@bot.message_handler(commands=['rules', 'rule', 'правила'])
def handle_rules_cmd(message):
    if not is_admin(message.from_user.id):
        return
    if not rules_kb:
        bot.reply_to(message, "⚠️ База правил серверов ещё не загружена на сервер (нужен rules_kb.py и server_rules.json).")
        return
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip()
        num, rule = rules_kb.find_rule_by_keyword(query)
        if rule:
            card = rules_kb.format_rule_card(num, rule)
            bot.reply_to(message, card)
        else:
            bot.reply_to(message, f"❌ Пункт правил по запросу <code>{html.escape(query)}</code> не найден. Попробуйте номер (например: <code>/rules 2.05</code>) или ключевое слово (например: <code>/rules упом родни</code>).")
    else:
        topics = rules_kb.get_forum_topics_summary()
        msg = (
            "📖 <b>База регламентов и правил Black Russia (Сервер №18 AQUA)</b>\n\n"
            "В базу занесены все 14 актуальных тем раздела правил:\n"
        )
        for t in topics[:7]:
            msg += f"• <a href='{t['url']}'>{html.escape(t['title'])}</a>\n"
        msg += "\n💡 <b>Быстрый поиск по регламенту:</b>\n"
        msg += "Отправьте <code>/rules [номер или нарушение]</code>\n"
        msg += "Примеры:\n"
        msg += "• <code>/rules 2.05</code> — OOC/IC обманы\n"
        msg += "• <code>/rules 3.04</code> — Оск/упом родни\n"
        msg += "• <code>/rules 2.22</code> — Стороннее ПО / Читы\n"
        msg += "• <code>/rules 2.28</code> — Покупка / Продажа ИВ\n"
        msg += "• <code>/rules 4.03</code> — Передача аккаунта / ППВ\n"
        msg += "• <code>/rules долг</code> — Невозврат долга (2.57)"
        bot.reply_to(message, msg)

# Text button handlers
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in [
    "📊 Проверить таблицы", "🚨 Просрочки на форуме", "👑 Жалобы ГА", "📑 Полный аудит форума", "⚙️ Настройки ИИ", "🔔 Авто-алерты"
])
def handle_menu_buttons(message):
    chat_id = message.chat.id
    text = message.text
    
    if text == "📊 Проверить таблицы":
        msg = bot.send_message(chat_id, "⏳ Экспортирую и проверяю Google Таблицы, подождите...")
        importlib.reload(sheets_runner)
        report = sheets_runner.run_sheets_audit()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        
    elif text == "🚨 Просрочки на форуме":
        msg = bot.send_message(chat_id, "⏳ Сканирую форум на предмет просрочек и горящих дедлайнов...")
        importlib.reload(forum_runner)
        report = forum_runner.get_overdue_and_urgent_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        
    elif text == "👑 Жалобы ГА":
        msg = bot.send_message(chat_id, "⏳ Загружаю темы с префиксом «Главному Администратору» и выжимку сути...")
        importlib.reload(forum_runner)
        report = forum_runner.get_ga_complaints_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        
    elif text == "📑 Полный аудит форума":
        msg = bot.send_message(chat_id, "⏳ Выполняю полный аудит всех 6 разделов и подразделов форума...")
        importlib.reload(forum_runner)
        report = forum_runner.get_full_forum_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        
    elif text == "⚙️ Настройки ИИ":
        info, markup = build_ai_settings_content()
        bot.send_message(chat_id, info, reply_markup=markup)

    elif text == "🔔 Авто-алерты":
        info, markup = build_alerts_settings_content()
        bot.send_message(chat_id, info, reply_markup=markup)

# Inline Keyboard Callbacks
@bot.callback_query_handler(func=lambda call: is_admin(call.from_user.id))
def handle_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data
    user_id = call.from_user.id
    u_state = user_states.setdefault(user_id, {})
    
    # 0. Main Menu Inline Actions
    if data == "menu:sheets":
        bot.answer_callback_query(call.id, "📊 Аудит таблиц...")
        msg = bot.send_message(chat_id, "⏳ Экспортирую и проверяю Google Таблицы, подождите...")
        importlib.reload(sheets_runner)
        report = sheets_runner.run_sheets_audit()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        return

    elif data == "menu:overdue":
        bot.answer_callback_query(call.id, "🚨 Проверка просрочек...")
        msg = bot.send_message(chat_id, "⏳ Сканирую форум на предмет просрочек и горящих дедлайнов...")
        importlib.reload(forum_runner)
        report = forum_runner.get_overdue_and_urgent_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        return

    elif data == "menu:ga":
        bot.answer_callback_query(call.id, "👑 Жалобы ГА...")
        msg = bot.send_message(chat_id, "⏳ Загружаю темы с префиксом «Главному Администратору» и выжимку сути...")
        importlib.reload(forum_runner)
        report = forum_runner.get_ga_complaints_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        return

    elif data == "menu:full_forum":
        bot.answer_callback_query(call.id, "📑 Полный аудит форума...")
        msg = bot.send_message(chat_id, "⏳ Выполняю полный аудит всех 6 разделов и подразделов форума...")
        importlib.reload(forum_runner)
        report = forum_runner.get_full_forum_report()
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        send_long_message(chat_id, report)
        return

    elif data == "menu:ai":
        bot.answer_callback_query(call.id, "⚙️ Настройки ИИ")
        info, markup = build_ai_settings_content()
        bot.send_message(chat_id, info, reply_markup=markup)
        return

    elif data == "menu:alerts":
        bot.answer_callback_query(call.id, "🔔 Авто-алерты")
        info, markup = build_alerts_settings_content()
        bot.send_message(chat_id, info, reply_markup=markup)
        return

    # 1. Switch active profile
    elif data.startswith("sel_prof:"):
        prof_id = data.split(":", 1)[1]
        cfg = load_config()
        if prof_id in cfg.get("ai_profiles", {}):
            cfg["active_profile_id"] = prof_id
            save_config(cfg)
            p_name = cfg["ai_profiles"][prof_id].get("name", prof_id)
            bot.answer_callback_query(call.id, f"Активный ИИ: {p_name}")
            
        try:
            info, markup = build_ai_settings_content()
            bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        except:
            pass
            
    # 2. Refresh limits
    elif data == "refresh_ai_limits":
        bot.answer_callback_query(call.id, "🔄 Обновляю данные о балансе и лимитах...")
        try:
            info, markup = build_ai_settings_content()
            bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        except:
            pass
            
    # 3. Add new API menu (choose provider type)
    elif data == "add_new_api_menu":
        markup = types.InlineKeyboardMarkup(row_width=2)
        for t_key, t_val in DEFAULT_TEMPLATES.items():
            markup.add(types.InlineKeyboardButton(f"{t_val['icon']} {t_val['name']}", callback_data=f"create_type:{t_key}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings"))
        bot.edit_message_text(
            "➕ <b>ДОБАВЛЕНИЕ НОВОГО API</b>\n\nВыберите провайдера для нового ключа:",
            chat_id,
            call.message.message_id,
            reply_markup=markup
        )
        
    # 4. Selected type for new API
    elif data.startswith("create_type:"):
        p_type = data.split(":", 1)[1]
        t_info = DEFAULT_TEMPLATES.get(p_type, DEFAULT_TEMPLATES["custom"])
        
        if p_type == "custom":
            user_states[user_id] = {
                "action": "wait_custom_name",
                "type": "custom"
            }
            msg = (
                "🌐 <b>Добавление своего API (Custom)</b>\n\n"
                "<b>Шаг 1/4:</b> Введите понятное название для этого профиля\n"
                "(например: <code>Groq Llama 3</code> или <code>Мой Сервер</code>):"
            )
        else:
            user_states[user_id] = {
                "action": "wait_api_name",
                "type": p_type,
                "default_model": t_info["model"],
                "default_base_url": t_info["base_url"]
            }
            msg = (
                f"{t_info['icon']} <b>Добавление API: {t_info['name']}</b>\n\n"
                "<b>Шаг 1/2:</b> Введите понятное название для этого ключа\n"
                f"(например: <code>{t_info['name']} #2</code> или <code>Личный</code>):\n\n"
                "<i>Отправьте <code>-</code>, чтобы назвать автоматически.</i>"
            )
        bot.edit_message_text(msg, chat_id, call.message.message_id)
        
    # 5. Edit active profile menu
    elif data == "edit_active_prof":
        cfg = load_config()
        active_id, active_prof = get_active_profile(cfg)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🔑 Сменить API-ключ", callback_data=f"edit_key:{active_id}"))
        markup.add(types.InlineKeyboardButton("🤖 Сменить модель", callback_data=f"edit_model:{active_id}"))
        markup.add(types.InlineKeyboardButton("🏷 Переименовать профиль", callback_data=f"edit_name:{active_id}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings"))
        
        bot.edit_message_text(
            f"✏️ <b>Редактирование профиля: {active_prof.get('name', active_id)}</b>\n\n"
            f"Текущая модель: <code>{active_prof.get('model', '')}</code>\n\n"
            "Что вы хотите изменить?",
            chat_id,
            call.message.message_id,
            reply_markup=markup
        )
        
    elif data.startswith("edit_key:"):
        prof_id = data.split(":", 1)[1]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id, {})
        user_states[user_id] = {"action": "update_key", "prof_id": prof_id}
        bot.edit_message_text(
            f"🔑 <b>Ввод нового API-ключа для {prof.get('name', prof_id)}</b>\n\n"
            "Отправьте ваш новый ключ следующим сообщением в этот чат.\n\n"
            "<i>🔒 Бот мгновенно удалит сообщение с ключом после получения!</i>",
            chat_id,
            call.message.message_id
        )
        
    elif data.startswith("edit_model:"):
        prof_id = data.split(":", 1)[1]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id, {})
        user_states[user_id] = {"action": "update_model", "prof_id": prof_id}
        bot.edit_message_text(
            f"🤖 <b>Смена модели для {prof.get('name', prof_id)}</b>\n\n"
            f"Текущая модель: <code>{prof.get('model', '')}</code>\n\n"
            "Отправьте новое название модели следующим сообщением (например: <code>gemini-2.0-flash</code>, <code>gpt-4o</code>, <code>deepseek-chat</code>):",
            chat_id,
            call.message.message_id
        )
        
    elif data.startswith("edit_name:"):
        prof_id = data.split(":", 1)[1]
        user_states[user_id] = {"action": "update_name", "prof_id": prof_id}
        bot.edit_message_text(
            "🏷 <b>Переименование профиля</b>\n\nОтправьте новое название для этого профиля:",
            chat_id,
            call.message.message_id
        )
        
    # 6. Delete profile menu
    elif data == "del_api_menu":
        cfg = load_config()
        profiles = cfg.get("ai_profiles", {})
        if len(profiles) <= 1:
            bot.answer_callback_query(call.id, "⚠️ Нельзя удалить единственный оставшийся профиль!", show_alert=True)
            return
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        for pid, prof in profiles.items():
            markup.add(types.InlineKeyboardButton(f"🗑 Удалить: {prof.get('name', pid)}", callback_data=f"confirm_del:{pid}"))
        markup.add(types.InlineKeyboardButton("🔙 Отмена", callback_data="back_to_settings"))
        bot.edit_message_text(
            "🗑 <b>УДАЛЕНИЕ API-ПРОФИЛЯ</b>\n\nВыберите профиль, который хотите удалить:",
            chat_id,
            call.message.message_id,
            reply_markup=markup
        )
        
    elif data.startswith("confirm_del:"):
        prof_id = data.split(":", 1)[1]
        cfg = load_config()
        profiles = cfg.get("ai_profiles", {})
        if prof_id in profiles and len(profiles) > 1:
            del_name = profiles[prof_id].get("name", prof_id)
            del profiles[prof_id]
            # If deleted active profile, reassign
            if cfg.get("active_profile_id") == prof_id:
                cfg["active_profile_id"] = next(iter(profiles))
            save_config(cfg)
            bot.answer_callback_query(call.id, f"Профиль '{del_name}' удалён!")
            
        info, markup = build_ai_settings_content()
        bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        
    # 7. Back to settings
    elif data == "back_to_settings":
        info, markup = build_ai_settings_content()
        bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        
    # Alerts management callbacks
    elif data == "toggle_alerts":
        cfg = load_config()
        curr = cfg.get("auto_alerts_enabled", True)
        cfg["auto_alerts_enabled"] = not curr
        save_config(cfg)
        if cfg["auto_alerts_enabled"]:
            _monitor_wakeup_event.set()
        status_msg = "🟢 Мониторинг включен!" if cfg["auto_alerts_enabled"] else "🔴 Мониторинг выключен!"
        bot.answer_callback_query(call.id, status_msg)
        info, markup = build_alerts_settings_content(cfg)
        try:
            bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
            
    elif data.startswith("set_alert_interval:"):
        new_int = int(data.split(":")[1])
        cfg = load_config()
        cfg["alert_interval_minutes"] = new_int
        save_config(cfg)
        _monitor_wakeup_event.set()
        bot.answer_callback_query(call.id, f"Интервал установлен: {new_int} мин.")
        info, markup = build_alerts_settings_content(cfg)
        try:
            bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
            
    elif data == "check_alerts_now":
        bot.answer_callback_query(call.id, "🔍 Сканирую форум...")
        alerts, _pending = check_for_alerts(force_all=True, commit_state=False)
        if alerts:
            msg_text = "🚨 <b>РЕЗУЛЬТАТ СКАНИРОВАНИЯ ФОРУМА:</b>\n\n" + "\n\n".join(alerts)
        else:
            last_res = _monitor_status.get("last_result", "")
            if "Ошибка" in last_res or "гостевой" in last_res.lower():
                msg_text = f"⚠️ <b>Не удалось просканировать форум:</b>\n<code>{html.escape(last_res)}</code>"
            else:
                msg_text = "✅ <b>Отлично! Просроченных и критически горящих тем на форуме нет.</b>"
        send_long_message(chat_id, msg_text)

    # 8. Close settings
    elif data == "close_settings":
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass

# Catch all text messages
@bot.message_handler(func=lambda m: is_admin(m.from_user.id))
def handle_text_interaction(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    state = user_states.get(user_id)
    
    # --- FLOW: Add standard API ---
    if state and state.get("action") == "wait_api_name":
        p_type = state["type"]
        t_info = DEFAULT_TEMPLATES.get(p_type, DEFAULT_TEMPLATES["custom"])
        
        cfg = load_config()
        profiles = cfg.get("ai_profiles", {})
        
        name = text if text != "-" else f"{t_info['name']} #{len(profiles) + 1}"
        state["name"] = name
        state["action"] = "wait_new_key"
        
        bot.send_message(
            chat_id,
            f"🔑 <b>Шаг 2/2: Отправьте API-ключ для «{name}»</b>:\n\n"
            "<i>🔒 В целях безопасности бот сразу удалит ваше сообщение с ключом после сохранения!</i>"
        )
        return
        
    if state and state.get("action") == "wait_new_key":
        p_type = state["type"]
        name = state["name"]
        model = state.get("default_model", "")
        base_url = state.get("default_base_url", "")
        api_key = text
        
        bot.send_message(chat_id, "⏳ Проверяю валидность ключа...")
        ok, res_msg = test_ai_key(p_type, api_key, base_url, model)
        
        # Delete user's message with key
        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass
            
        cfg = load_config()
        prof_id = f"prof_{uuid.uuid4().hex[:8]}"
        new_prof = {
            "id": prof_id,
            "name": name,
            "type": p_type,
            "model": model,
            "base_url": base_url,
            "api_key": api_key
        }
        cfg.setdefault("ai_profiles", {})[prof_id] = new_prof
        cfg["active_profile_id"] = prof_id
        save_config(cfg)
        user_states.pop(user_id, None)
        
        limit_str = get_ai_limit_info(new_prof, cfg)
        status_line = "✅ Ключ подтверждён!" if ok else f"⚠️ Ключ сохранён ({res_msg})"
        
        bot.send_message(
            chat_id,
            f"🎉 <b>Новый API-профиль «{name}» успешно добавлен и активирован!</b>\n\n"
            f"📌 Статус проверки: {status_line}\n"
            f"🤖 Модель: <code>{model}</code>\n"
            f"📊 <b>Остаток лимита / Баланс:</b> <code>{limit_str}</code>",
            reply_markup=get_main_keyboard(user_id)
        )
        return

    # --- FLOW: Add Custom API ---
    if state and state.get("action") == "wait_custom_name":
        state["name"] = text
        state["action"] = "wait_custom_url"
        bot.send_message(chat_id, "🌐 <b>Шаг 2/4:</b> Отправьте Base URL вашего OpenAI-совместимого сервиса\n(например: <code>https://api.groq.com/openai/v1</code>):")
        return
        
    if state and state.get("action") == "wait_custom_url":
        state["base_url"] = text
        state["action"] = "wait_custom_model"
        bot.send_message(chat_id, "🤖 <b>Шаг 3/4:</b> Отправьте название модели\n(например: <code>llama-3.3-70b-versatile</code> или <code>default</code>):")
        return
        
    if state and state.get("action") == "wait_custom_model":
        state["model"] = text
        state["action"] = "wait_custom_key"
        bot.send_message(chat_id, "🔑 <b>Шаг 4/4:</b> Отправьте API-ключ для этого сервиса (или любой текст, если ключ не требуется):")
        return
        
    if state and state.get("action") == "wait_custom_key":
        api_key = text
        name = state["name"]
        model = state["model"]
        base_url = state["base_url"]
        
        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass
            
        cfg = load_config()
        prof_id = f"prof_{uuid.uuid4().hex[:8]}"
        new_prof = {
            "id": prof_id,
            "name": name,
            "type": "custom",
            "model": model,
            "base_url": base_url,
            "api_key": api_key
        }
        cfg.setdefault("ai_profiles", {})[prof_id] = new_prof
        cfg["active_profile_id"] = prof_id
        save_config(cfg)
        user_states.pop(user_id, None)
        
        limit_str = get_ai_limit_info(new_prof, cfg)
        bot.send_message(
            chat_id,
            f"🎉 <b>Свой API-профиль «{name}» успешно добавлен и активирован!</b>\n\n"
            f"🤖 Модель: <code>{model}</code>\n"
            f"🌐 URL: <code>{base_url}</code>\n"
            f"📊 <b>Статус:</b> <code>{limit_str}</code>",
            reply_markup=get_main_keyboard(user_id)
        )
        return

    # --- FLOW: Update existing profile ---
    if state and state.get("action") == "update_key":
        prof_id = state["prof_id"]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id)
        if prof:
            prof["api_key"] = text
            save_config(cfg)
            try:
                bot.delete_message(chat_id, message.message_id)
            except:
                pass
            limit_str = get_ai_limit_info(prof, cfg)
            bot.send_message(
                chat_id,
                f"✅ <b>Ключ для «{prof.get('name', prof_id)}» успешно обновлён!</b>\n\n"
                f"📊 <b>Остаток лимита / Баланс:</b> <code>{limit_str}</code>",
                reply_markup=get_main_keyboard(user_id)
            )
        user_states.pop(user_id, None)
        return
        
    if state and state.get("action") == "update_model":
        prof_id = state["prof_id"]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id)
        if prof:
            prof["model"] = text
            save_config(cfg)
            bot.send_message(chat_id, f"✅ Модель для «{prof.get('name', prof_id)}» изменена на: <code>{text}</code>", reply_markup=get_main_keyboard(user_id))
        user_states.pop(user_id, None)
        return
        
    if state and state.get("action") == "update_name":
        prof_id = state["prof_id"]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id)
        if prof:
            prof["name"] = text
            save_config(cfg)
            bot.send_message(chat_id, f"✅ Профиль переименован в: <b>{text}</b>", reply_markup=get_main_keyboard(user_id))
        user_states.pop(user_id, None)
        return

    # --- Normal message -> Chat with active AI! ---
    cfg = load_config()
    importlib.reload(ai_handler)
    _, active_prof = ai_handler.get_active_profile(cfg)
    
    bot.send_chat_action(chat_id, "typing")
    
    # Check if user is Toshiro Forester
    if user_id == 1399524277:
        sys_prompt = ai_handler.get_toshiro_admin_system_prompt()
    else:
        sys_prompt = "Ты умный ассистент руководства проекта Black Russia. Помогаешь отвечать на общие вопросы."
        
    ai_prompt = text
    # Auto-fetch forum thread if link is provided
    forum_match = re.search(r'https://forum\.blackrussia\.online/threads/[^\s]+', text)
    if forum_match:
        th_url = forum_match.group(0)
        try:
            from forum_audit import solve_vddos_and_fetch_requests
            th_html = solve_vddos_and_fetch_requests(th_url)
            t_m = re.search(r'<h1 class="p-title-value">(.*?)</h1>', th_html, re.DOTALL)
            th_title = re.sub(r'<[^>]+>', '', t_m.group(1)).strip() if t_m else ""
            a_m = re.search(r'data-author="([^"]+)"', th_html)
            th_author = a_m.group(1) if a_m else ""
            p_m = re.search(r'<article class="message-body[^"]*">(.*?)</article>', th_html, re.DOTALL)
            th_body = re.sub(r'<[^>]+>', ' ', p_m.group(1)).replace('&nbsp;', ' ').strip() if p_m else ""
            th_body = re.sub(r'\s+', ' ', th_body)[:2500]
            
            ai_prompt = (
                f"Тоширо прислал тему с форума: {th_url}\n"
                f"Заголовок: {th_title}\n"
                f"Автор темы: {th_author}\n"
                f"Текст жалобы/обжалования:\n{th_body}\n\n"
                f"Комментарий/вопрос Тоширо: {text}\n\n"
                "Проанализируй данное обжалование по твоим регламентам и правилам, выдай точный вердикт (действие, префикс) и готовый текст ответа для форума."
            )
        except Exception:
            ai_prompt = text

    ai_reply = ai_handler.send_ai_query(
        prompt=ai_prompt,
        config=cfg,
        system_prompt=sys_prompt
    )

    bot.reply_to(message, ai_reply)

# --- Background Monitor & Alert System ---
_notified_threads = {}
_monitor_wakeup_event = threading.Event()
_monitor_status = {
    "last_check_msk": "Ещё не запускалась",
    "last_result": "Ожидание запуска...",
    "last_guest_alert_ts": 0,
}

OVERDUE_REMINDER_SEC = 2 * 3600  # Напоминать о висящей просрочке раз в 2 часа
GA_REMINDER_SEC = 6 * 3600       # Напоминать о теме ГА раз в 6 часов

def _extract_hours_left(t_str):
    if not t_str or "ПРОСРОЧЕНО" in t_str:
        return None
    if " ч." in t_str:
        try:
            return int(t_str.split(" ч.")[0].strip().split()[-1])
        except Exception:
            return None
    if " мин." in t_str:
        return 0
    return None

def check_for_alerts(force_all=False, commit_state=True):
    global _notified_threads
    now_msk = datetime.now(MSK_TZ).strftime("%d.%m %H:%M:%S МСК")
    _monitor_status["last_check_msk"] = now_msk
    
    data = forum_runner.fetch_forum_data(skip_summaries=True, force_refresh=True)
    if not data:
        _monitor_status["last_result"] = "Ошибка: пустой ответ парсера"
        print(f"[Monitor {now_msk}] Ошибка: пустой ответ парсера", flush=True)
        return [], {}
    if data.get("error"):
        err = str(data.get("error"))[:120]
        _monitor_status["last_result"] = f"Ошибка: {err}"
        print(f"[Monitor {now_msk}] Ошибка: {err}", flush=True)
        return [], {}
    if data.get("is_guest"):
        _monitor_status["last_result"] = "⚠️ Гостевой режим (куки форума не сработали)"
        print(f"[Monitor {now_msk}] ⚠️ Форум открылся в гостевом режиме!", flush=True)
        return [], {}
    
    total_threads = sum(
        len(s.get("overdue", [])) + len(s.get("in_progress", []))
        for s in data.get("sections", {}).values()
    )
    if total_threads == 0 and data.get("last_error"):
        err = str(data.get("last_error"))[:120]
        _monitor_status["last_result"] = f"Ошибка сети: {err}"
        print(f"[Monitor {now_msk}] Ошибка сети: {err}", flush=True)
        return [], {}

    now = time.time()
    new_alerts = []
    pending_state = {}
    current_urls = set()
    total_overdue = 0
    
    for sec_id, s in data.get("sections", {}).items():
        sec_name = forum_runner.SECTION_NAMES.get(sec_id, forum_runner.fix_mojibake(s.get("title", sec_id)))
        
        # 1. Overdue (моментально + повторное напоминание каждые 2 часа)
        for ov in s.get("overdue", []):
            url = ov.get("url", "")
            if not url:
                continue
            total_overdue += 1
            current_urls.add(url)
            prev = _notified_threads.get(url)
            is_due = (
                force_all
                or not prev
                or prev.get("type") != "overdue"
                or (now - prev.get("time", 0) >= OVERDUE_REMINDER_SEC)
            )
            if is_due:
                pending_state[url] = {"type": "overdue", "time": now}
                title = html.escape(forum_runner.fix_mojibake(ov.get("title", "Без названия")))
                author = html.escape(forum_runner.fix_mojibake(ov.get("author", "")))
                t_str = ov.get("time_left_str", "")
                prefix = html.escape(forum_runner.fix_mojibake(ov.get("prefix", ""))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                new_alerts.append(
                    f"🔴 <b>[ПРОСРОЧКА] {sec_name}</b>\n"
                    f"  ❌{prefix_badge} <a href='{url}'><b>{title}</b></a>\n"
                    f"  👤 Автор: <code>{author}</code> | 🚨 <b>{t_str}</b>"
                )
                
        # 2. Urgent (< 4 hours, повторная эскалация когда осталось < 1 часа)
        urgent_list = forum_runner.extract_urgent_threads(s.get("in_progress", []), max_hours=4)
        for ug in urgent_list:
            url = ug.get("url", "")
            if not url:
                continue
            current_urls.add(url)
            t_str = ug.get("time_left_str", "")
            h_left = _extract_hours_left(t_str)
            cur_type = "urgent_1h" if (h_left is not None and h_left < 1) else "urgent"
            prev = _notified_threads.get(url)
            is_due = (
                force_all
                or not prev
                or (cur_type == "urgent_1h" and prev.get("type") == "urgent")
            )
            if is_due:
                pending_state[url] = {"type": cur_type, "time": now}
                title = html.escape(forum_runner.fix_mojibake(ug.get("title", "Без названия")))
                author = html.escape(forum_runner.fix_mojibake(ug.get("author", "")))
                prefix = html.escape(forum_runner.fix_mojibake(ug.get("prefix", ""))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                badge = "🔥 <b>[МЕНЕЕ 1 ЧАСА]</b>" if cur_type == "urgent_1h" else "⏳ <b>[ГОРЯЩИЙ ДЕДЛАЙН]</b>"
                new_alerts.append(
                    f"{badge} <b>{sec_name}</b>\n"
                    f"  ⚠️{prefix_badge} <a href='{url}'><b>{title}</b></a>\n"
                    f"  👤 Автор: <code>{author}</code> | ⏱ Осталось: <b>{t_str}</b>"
                )

        # 3. GA Threads (моментально + повтор раз в 6 часов)
        if sec_id == "admin_complaints":
            for ga in s.get("ga_threads", []):
                url = ga.get("url", "")
                if not url:
                    continue
                current_urls.add(url)
                ga_key = f"ga_{url}"
                prev = _notified_threads.get(ga_key)
                is_due = (
                    force_all
                    or not prev
                    or (now - prev.get("time", 0) >= GA_REMINDER_SEC)
                )
                if is_due:
                    pending_state[ga_key] = {"type": "ga", "time": now}
                    title = html.escape(forum_runner.fix_mojibake(ga.get("title", "Без названия")))
                    author = html.escape(forum_runner.fix_mojibake(ga.get("author", "")))
                    t_str = ga.get("time_left_str", "")
                    new_alerts.append(
                        f"👑 <b>[ТЕМА ГА] Жалобы на администрацию</b>\n"
                        f"  ➔ <a href='{url}'><b>{title}</b></a>\n"
                        f"  👤 Автор: <code>{author}</code> | ⏱ Осталось: <b>{t_str}</b>"
                    )

    if commit_state and pending_state:
        _notified_threads.update(pending_state)

    if not force_all:
        stale = [u for u in list(_notified_threads.keys()) if (u.replace("ga_", "") not in current_urls and now - _notified_threads[u]["time"] > 7200)]
        for u in stale:
            _notified_threads.pop(u, None)

    _monitor_status["last_result"] = f"✅ ОК (тем в работе: {total_threads}, просрочек: {total_overdue}, новых алертов: {len(new_alerts)})"
    print(f"[Monitor {now_msk}] {_monitor_status['last_result']}", flush=True)
    return new_alerts, pending_state

def background_forum_monitor():
    time.sleep(10)
    while True:
        try:
            cfg = load_config()
            if cfg.get("auto_alerts_enabled", True):
                alerts, pending_state = check_for_alerts(force_all=False, commit_state=False)
                admins = cfg.get("admin_ids") or [1399524277, 5594041416]
                
                # Если форум перешёл в гостевой режим — предупреждаем админа не чаще раза в 2 часа
                if "Гостевой режим" in _monitor_status.get("last_result", ""):
                    now_ts = time.time()
                    if now_ts - _monitor_status.get("last_guest_alert_ts", 0) > 7200:
                        _monitor_status["last_guest_alert_ts"] = now_ts
                        guest_msg = (
                            "⚠️ <b>Внимание: фоновый мониторинг форума не смог авторизоваться!</b>\n\n"
                            "Форум открывается в режиме гостя — проверьте или обновите куки <code>FORUM_XF_USER</code>."
                        )
                        for aid in admins:
                            try:
                                send_long_message(aid, guest_msg)
                            except Exception:
                                pass
                elif alerts:
                    msg_text = "🚨🚨🚨 <b>АВТО-ОПОВЕЩЕНИЕ ПО ФОРУМУ AQUA!</b> 🚨🚨🚨\n\n" + "\n\n".join(alerts)
                    sent_any = False
                    for aid in admins:
                        try:
                            send_long_message(aid, msg_text)
                            sent_any = True
                            print(f"[Monitor] Алерт успешно доставлен админу {aid}", flush=True)
                        except Exception as e_send:
                            print(f"[Monitor] Не удалось доставить алерт админу {aid}: {e_send}", flush=True)
                    # Засчитываем темы уведомлёнными ТОЛЬКО если хотя бы одному админу доставлено
                    if sent_any and pending_state:
                        _notified_threads.update(pending_state)
        except Exception as e:
            print(f"[Monitor] Критическая ошибка в цикле мониторинга: {e}", flush=True)
            _monitor_status["last_result"] = f"Ошибка цикла: {str(e)[:80]}"
            
        cfg = load_config()
        interval = max(5, cfg.get("alert_interval_minutes", 30)) * 60
        _monitor_wakeup_event.clear()
        _monitor_wakeup_event.wait(timeout=interval)

if __name__ == "__main__":
    print("🤖 Бот AQUA успешно запущен и готов к работе!", flush=True)
    threading.Thread(target=background_forum_monitor, daemon=True).start()
    print("🔔 Фоновый мониторинг форума успешно активирован!", flush=True)
    try:
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
    except Exception as e:
        print(f"❌ Ошибка в polling: {e}", flush=True)
