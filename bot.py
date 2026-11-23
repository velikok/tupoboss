import os
import sys
import json
import uuid
import time
import threading
import html

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
    import forum_copilot
except Exception:
    forum_copilot = None

try:
    import forum_actions
except Exception:
    forum_actions = None

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

# In-memory user states
user_states = {}

def is_admin(user_id):
    cfg = load_config()
    admins = cfg.get("admin_ids") or [1399524277, 5594041416]
    return user_id in admins

def can_use_copilot(user_id):
    if not user_id:
        return False
    if not is_admin(user_id):
        return False
    if not forum_copilot or not forum_actions:
        return False
    cfg = load_config()
    allowed = cfg.get("copilot_allowed_ids", [1399524277])
    return user_id in allowed

def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    b_sheets = types.KeyboardButton("📊 Проверить таблицы")
    b_overdue = types.KeyboardButton("🚨 Просрочки на форуме")
    b_ga = types.KeyboardButton("👑 Жалобы ГА")
    b_full_forum = types.KeyboardButton("📑 Полный аудит форума")
    b_ai = types.KeyboardButton("⚙️ Настройки ИИ")
    b_alerts = types.KeyboardButton("🔔 Авто-алерты")
    markup.add(b_sheets, b_overdue)
    markup.add(b_ga, b_full_forum)
    if user_id and can_use_copilot(user_id):
        b_copilot = types.KeyboardButton("⚖️ Разбор обжалований")
        markup.add(b_copilot)
    markup.add(b_ai, b_alerts)
    return markup


def build_copilot_card(item):
    info = item["info"]
    verdict = item["verdict"]
    
    title = html.escape(info.get("title", ""))
    author = html.escape(info.get("author", ""))
    url = info.get("url", "")
    category = verdict.get("category", "Разбор")
    explanation = html.escape(verdict.get("explanation", ""))
    reply_text = html.escape(verdict.get("reply_text", ""))
    prefix = verdict.get("prefix", "Без префикса")
    dest = verdict.get("destination_node")
    
    action_desc = f"Префикс: <b>[{prefix}]</b>"
    if dest:
        action_desc += f" ➔ Перенос в раздел <code>{dest}</code>"
    if verdict.get("stick"):
        action_desc += " + Закрепить 📌"
        
    rule_num = verdict.get("rule_num")
    rule_punish = verdict.get("rule_punishment")
    rule_title = verdict.get("rule_title", "")
    rule_block = ""
    if rule_num:
        rule_block = f"📜 <b>Пункт правил:</b> <code>{rule_num}</code> ({html.escape(rule_title[:60])})\n"
        if rule_punish:
            rule_block += f"⚖️ <b>Регламент:</b> <code>{html.escape(rule_punish)}</code>\n"
        rule_block += "\n"

    text = (
        f"⚖️ <b>РАЗБОР ОБЖАЛОВАНИЯ #{info.get('thread_id')}</b>\n\n"
        f"📌 <b>Тема:</b> <a href='{url}'><b>{title}</b></a>\n"
        f"👤 <b>Автор:</b> <code>{author}</code>\n"
        f"🏷 <b>Категория:</b> {category}\n"
        f"{rule_block}"
        f"💡 <b>Анализ:</b> <i>{explanation}</i>\n\n"
        f"📝 <b>Предлагаемый ответ на форум:</b>\n"
        f"<blockquote>{reply_text}</blockquote>\n\n"
        f"🎯 <b>Действие:</b> {action_desc}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🚀 Отправить вердикт на форум", callback_data="cp_exec"))
    markup.add(
        types.InlineKeyboardButton("✏️ Изменить текст", callback_data="cp_edit_text"),
        types.InlineKeyboardButton("🔄 Сменить вердикт", callback_data="cp_change_action")
    )
    markup.add(
        types.InlineKeyboardButton("⏭ Пропустить тему", callback_data="cp_skip"),
        types.InlineKeyboardButton("🔙 Закрыть", callback_data="close_settings")
    )
    return text, markup

def start_copilot_review(chat_id, user_id):
    if not can_use_copilot(user_id):
        return
    u_state = user_states.setdefault(user_id, {})
    seen = u_state.setdefault("copilot_seen", set())
    
    msg = bot.send_message(chat_id, "🔍 Сканирую «Обжалование наказаний» в поисках открытых тем...")
    importlib.reload(forum_copilot)
    item = forum_copilot.get_next_pending_appeal(exclude_thread_ids=seen)
    try:
        bot.delete_message(chat_id, msg.message_id)
    except Exception:
        pass
        
    if not item:
        bot.send_message(
            chat_id,
            "✅ <b>Отлично! В разделе «Обжалование наказаний» нет открытых тем, требующих ответа.</b>",
            reply_markup=get_main_keyboard(user_id)
        )
        return
        
    u_state["active_copilot"] = item
    seen.add(str(item["info"].get("thread_id")))
    
    card_text, markup = build_copilot_card(item)
    bot.send_message(chat_id, card_text, reply_markup=markup, disable_web_page_preview=True)

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
        f"• Получатели оповещений: <b>{len(admins)} админа</b>\n\n"
        "<b>Что отслеживается в реальном времени:</b>\n"
        "• 🔴 <b>Просроченные темы</b> (моментальное оповещение)\n"
        "• ⏳ <b>Горящие дедлайны</b> (осталось менее 4 часов)\n"
        "• 👑 <b>Новые темы «Главному Администратору»</b>\n\n"
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
        "• <b>Авто-алерты:</b> фоновое оповещение при горящих дедлайнах (< 4 ч.) и просрочках.\n"
        f"• <b>Активный ИИ:</b> <code>{active_prof.get('name', 'ИИ')}</code> (можно загружать любое количество API).\n\n"
        "Выберите действие на клавиатуре ниже:"
    )
    bot.send_message(message.chat.id, welcome, reply_markup=get_main_keyboard(message.from_user.id))

@bot.message_handler(commands=['copilot', 'review'])
def handle_copilot_cmd(message):
    if not can_use_copilot(message.from_user.id):
        return
    start_copilot_review(message.chat.id, message.from_user.id)

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
    "📊 Проверить таблицы", "🚨 Просрочки на форуме", "👑 Жалобы ГА", "📑 Полный аудит форума", "⚙️ Настройки ИИ", "🔔 Авто-алерты", "⚖️ Разбор обжалований"
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

    elif text == "⚖️ Разбор обжалований":
        if not can_use_copilot(message.from_user.id):
            bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard(message.from_user.id))
            return
        start_copilot_review(chat_id, message.from_user.id)

# Inline Keyboard Callbacks
@bot.callback_query_handler(func=lambda call: is_admin(call.from_user.id))
def handle_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data
    user_id = call.from_user.id
    
    # 1. Switch active profile
    if data.startswith("sel_prof:"):
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
        bot.answer_callback_query(call.id, f"Интервал установлен: {new_int} мин.")
        info, markup = build_alerts_settings_content(cfg)
        try:
            bot.edit_message_text(info, chat_id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
            
    elif data == "check_alerts_now":
        bot.answer_callback_query(call.id, "🔍 Сканирую форум...")
        alerts = check_for_alerts(force_all=True)
        if alerts:
            msg_text = "🚨 <b>РЕЗУЛЬТАТ СКАНИРОВАНИЯ ФОРУМА:</b>\n\n" + "\n\n".join(alerts)
        else:
            msg_text = "✅ <b>Отлично! Просроченных и критически горящих тем на форуме нет.</b>"
        send_long_message(chat_id, msg_text)


    # --- COPILOT CALLBACKS ---
    elif data in ["cp_exec", "cp_skip", "cp_edit_text", "cp_change_action", "cp_close"] or data.startswith("cp_act:"):
        if not can_use_copilot(user_id):
            bot.answer_callback_query(call.id, "⛔️ Доступ ограничен.", show_alert=True)
            return

        if data == "cp_exec":
            u_state = user_states.get(user_id, {})
        item = u_state.get("active_copilot")
        if not item:
            bot.answer_callback_query(call.id, "⚠️ Данные темы устарели")
            return
            
        bot.answer_callback_query(call.id, "⏳ Применяю вердикт на форуме...")
        try:
            bot.edit_message_text("⏳ <b>Отправляю ответ и выполняю действие на форуме...</b>", chat_id, call.message.message_id)
        except Exception:
            pass
            
        importlib.reload(forum_actions)
        th_id = item["info"].get("thread_id")
        res = forum_actions.execute_copilot_verdict(th_id, item["verdict"])
        
        bot.send_message(chat_id, f"🎉 <b>Результат по теме #{th_id}:</b>\n\n{res}\n\n<i>Перехожу к следующей теме...</i>")
        time.sleep(2)
        start_copilot_review(chat_id, user_id)
        
    elif data == "cp_skip":
        bot.answer_callback_query(call.id, "⏭ Пропускаю тему...")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        start_copilot_review(chat_id, user_id)
        
    elif data == "cp_edit_text":
        u_state = user_states.setdefault(user_id, {})
        u_state["action"] = "wait_copilot_custom_text"
        bot.send_message(
            chat_id,
            "✍️ <b>Введите новый текст ответа для форума следующим сообщением:</b>\n\n"
            "<i>(Или отправьте <code>-</code> для отмены)</i>"
        )
        
    elif data == "cp_change_action":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🟢 Одобрить (сокращение наказания)", callback_data="cp_act:reduce"),
            types.InlineKeyboardButton("🔴 Отказать (наказание выдано верно)", callback_data="cp_act:refuse"),
            types.InlineKeyboardButton("📁 Перенести в тех. раздел (1199)", callback_data="cp_act:tech"),
            types.InlineKeyboardButton("📌 Перенести в жалобы на админов (842)", callback_data="cp_act:admin_move"),
            types.InlineKeyboardButton("❌ Отказать (нет окна бана)", callback_data="cp_act:noban"),
            types.InlineKeyboardButton("🔙 Назад к карточке", callback_data="cp_act:back")
        )
        bot.edit_message_text("🔄 <b>Выберите действие/вердикт для этой темы:</b>", chat_id, call.message.message_id, reply_markup=markup)
        
    elif data.startswith("cp_act:"):
        sub_act = data.split(":", 1)[1]
        u_state = user_states.get(user_id, {})
        item = u_state.get("active_copilot")
        if not item:
            bot.answer_callback_query(call.id, "⚠️ Данные темы устарели")
            return
            
        author = item["info"].get("author", "Игрок")
        greeting = forum_copilot.get_greeting()
        
        if sub_act == "reduce":
            item["verdict"]["action"] = "REPLY_APPROVE"
            item["verdict"]["prefix"] = "Одобрено"
            item["verdict"]["reply_text"] = f"{greeting}, уважаемый(-ая) {author}\n\nВаше обжалование рассмотрено и принято решение о сокращении вашего наказания.\n\nОдобрено."
            item["verdict"]["explanation"] = "Принудительно выбрано сокращение наказания."
            item["verdict"]["destination_node"] = None
        elif sub_act == "refuse":
            item["verdict"]["action"] = "REPLY_CLOSE"
            item["verdict"]["prefix"] = "Отказано"
            item["verdict"]["reply_text"] = f"{greeting}, уважаемый(-ая) {author}\n\nАдминистратор предоставил доказательства.\nНаказание выдано верно.\n\nЗакрыто."
            item["verdict"]["explanation"] = "Принудительно выбран отказ (наказание верно)."
            item["verdict"]["destination_node"] = None
        elif sub_act == "tech":
            item["verdict"]["action"] = "MOVE_TECH"
            item["verdict"]["prefix"] = "На рассмотрении"
            item["verdict"]["destination_node"] = forum_copilot.FORUM_TECH_NODE
            item["verdict"]["reply_text"] = f"{greeting}, уважаемый(-ая) {author}\n\n Ошиблись разделом!\n Переношу вашу тему в раздел жалоб на технических специалистов!\n\nВ ожидании"
            item["verdict"]["explanation"] = "Принудительно выбран перенос в тех. раздел."
        elif sub_act == "admin_move":
            item["verdict"]["action"] = "MOVE_ADMIN_COMPLAINTS"
            item["verdict"]["prefix"] = None
            item["verdict"]["destination_node"] = forum_copilot.FORUM_ADMIN_COMPLAINTS_NODE
            item["verdict"]["reply_text"] = ""
            item["verdict"]["stick"] = True
            item["verdict"]["explanation"] = "Принудительно выбран перенос в жалобы на администрацию без ответа."
        elif sub_act == "noban":
            item["verdict"]["action"] = "REPLY_CLOSE"
            item["verdict"]["prefix"] = "Закрыто"
            item["verdict"]["reply_text"] = "Вы не прикрепили окно бана. Создайте новую тему и прикрепите туда окно бана.\n\nЗакрыто."
            item["verdict"]["explanation"] = "Принудительно выбран отказ (нет окна бана)."
            item["verdict"]["destination_node"] = None
            
        card_text, markup = build_copilot_card(item)
        bot.edit_message_text(card_text, chat_id, call.message.message_id, reply_markup=markup, disable_web_page_preview=True)

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
    
    # --- FLOW: Copilot edit reply text ---
    if state and state.get("action") == "wait_copilot_custom_text":
        item = state.get("active_copilot")
        if text != "-" and item:
            item["verdict"]["reply_text"] = text
            bot.send_message(chat_id, "✅ <b>Текст ответа обновлён!</b>")
            card_text, markup = build_copilot_card(item)
            bot.send_message(chat_id, card_text, reply_markup=markup, disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, "Редактирование текста отменено.")
        state.pop("action", None)
        return

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
    ai_reply = ai_handler.send_ai_query(
        prompt=text,
        config=cfg,
        system_prompt="Ты умный ассистент руководства проекта Black Russia. Помогаешь проверять жалобы, регламенты, анализировать ситуации и отвечать на вопросы."
    )
    bot.reply_to(message, ai_reply)

# --- Background Monitor & Alert System ---
_notified_threads = {}

def check_for_alerts(force_all=False):
    global _notified_threads
    data = forum_runner.fetch_forum_data(skip_summaries=True)
    if not data or data.get("error") or data.get("is_guest"):
        return []
        
    now = time.time()
    new_alerts = []
    current_urls = set()
    
    for sec_id, s in data.get("sections", {}).items():
        sec_name = forum_runner.SECTION_NAMES.get(sec_id, forum_runner.fix_mojibake(s.get("title", sec_id)))
        
        # 1. Overdue
        for ov in s.get("overdue", []):
            url = ov.get("url", "")
            if not url:
                continue
            current_urls.add(url)
            prev = _notified_threads.get(url)
            if force_all or not prev or prev.get("type") != "overdue":
                _notified_threads[url] = {"type": "overdue", "time": now}
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
                
        # 2. Urgent (< 4 hours)
        urgent_list = forum_runner.extract_urgent_threads(s.get("in_progress", []), max_hours=4)
        for ug in urgent_list:
            url = ug.get("url", "")
            if not url:
                continue
            current_urls.add(url)
            if force_all or url not in _notified_threads:
                _notified_threads[url] = {"type": "urgent", "time": now}
                title = html.escape(forum_runner.fix_mojibake(ug.get("title", "Без названия")))
                author = html.escape(forum_runner.fix_mojibake(ug.get("author", "")))
                t_str = ug.get("time_left_str", "")
                prefix = html.escape(forum_runner.fix_mojibake(ug.get("prefix", ""))).strip()
                prefix_badge = f" [🏷 <b>{prefix}</b>]" if prefix else ""
                new_alerts.append(
                    f"⏳ <b>[ГОРЯЩИЙ ДЕДЛАЙН] {sec_name}</b>\n"
                    f"  ⚠️{prefix_badge} <a href='{url}'><b>{title}</b></a>\n"
                    f"  👤 Автор: <code>{author}</code> | ⏱ Осталось: <b>{t_str}</b>"
                )

        # 3. GA Threads
        if sec_id == "admin_complaints":
            for ga in s.get("ga_threads", []):
                url = ga.get("url", "")
                if not url:
                    continue
                current_urls.add(url)
                ga_key = f"ga_{url}"
                if force_all or ga_key not in _notified_threads:
                    _notified_threads[ga_key] = {"type": "ga", "time": now}
                    title = html.escape(forum_runner.fix_mojibake(ga.get("title", "Без названия")))
                    author = html.escape(forum_runner.fix_mojibake(ga.get("author", "")))
                    t_str = ga.get("time_left_str", "")
                    new_alerts.append(
                        f"👑 <b>[ТЕМА ГА] Жалобы на администрацию</b>\n"
                        f"  ➔ <a href='{url}'><b>{title}</b></a>\n"
                        f"  👤 Автор: <code>{author}</code> | ⏱ Осталось: <b>{t_str}</b>"
                    )

    if not force_all:
        stale = [u for u in list(_notified_threads.keys()) if (u.replace("ga_", "") not in current_urls and now - _notified_threads[u]["time"] > 7200)]
        for u in stale:
            _notified_threads.pop(u, None)
            
    return new_alerts

def background_forum_monitor():
    time.sleep(20)
    while True:
        try:
            cfg = load_config()
            if cfg.get("auto_alerts_enabled", True):
                alerts = check_for_alerts(force_all=False)
                if alerts:
                    admins = cfg.get("admin_ids") or [1399524277, 5594041416]
                    msg_text = "🚨🚨🚨 <b>АВТО-ОПОВЕЩЕНИЕ ПО ФОРУМУ AQUA!</b> 🚨🚨🚨\n\n" + "\n\n".join(alerts)
                    for aid in admins:
                        try:
                            send_long_message(aid, msg_text)
                        except Exception as e_send:
                            print(f"Failed to send alert to {aid}: {e_send}", flush=True)
        except Exception as e:
            print(f"Background monitor loop error: {e}", flush=True)
            
        cfg = load_config()
        interval = max(5, cfg.get("alert_interval_minutes", 30)) * 60
        sleep_elapsed = 0
        while sleep_elapsed < interval:
            time.sleep(5)
            sleep_elapsed += 5

if __name__ == "__main__":
    print("🤖 Бот AQUA успешно запущен и готов к работе!", flush=True)
    threading.Thread(target=background_forum_monitor, daemon=True).start()
    print("🔔 Фоновый мониторинг форума успешно активирован!", flush=True)
    try:
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
    except Exception as e:
        print(f"❌ Ошибка в polling: {e}", flush=True)
