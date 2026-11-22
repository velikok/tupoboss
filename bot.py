import os
import sys
import json
import uuid
import time

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
        "name": "DeepSeek",
        "type": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
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
    return user_id in cfg.get("admin_ids", [])

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    b_sheets = types.KeyboardButton("📊 Проверить таблицы")
    b_overdue = types.KeyboardButton("🚨 Просрочки на форуме")
    b_ga = types.KeyboardButton("👑 Жалобы ГА")
    b_full_forum = types.KeyboardButton("📑 Полный аудит форума")
    b_ai = types.KeyboardButton("⚙️ Настройки ИИ")
    markup.add(b_sheets, b_overdue)
    markup.add(b_ga, b_full_forum)
    markup.add(b_ai)
    return markup

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
        f"• <b>Активный ИИ:</b> <code>{active_prof.get('name', 'ИИ')}</code> (можно загружать любое количество API).\n\n"
        "Выберите действие на клавиатуре ниже:"
    )
    bot.send_message(message.chat.id, welcome, reply_markup=get_main_keyboard())

# Text button handlers
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in [
    "📊 Проверить таблицы", "🚨 Просрочки на форуме", "👑 Жалобы ГА", "📑 Полный аудит форума", "⚙️ Настройки ИИ"
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
            reply_markup=get_main_keyboard()
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
            reply_markup=get_main_keyboard()
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
                reply_markup=get_main_keyboard()
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
            bot.send_message(chat_id, f"✅ Модель для «{prof.get('name', prof_id)}» изменена на: <code>{text}</code>", reply_markup=get_main_keyboard())
        user_states.pop(user_id, None)
        return
        
    if state and state.get("action") == "update_name":
        prof_id = state["prof_id"]
        cfg = load_config()
        prof = cfg.get("ai_profiles", {}).get(prof_id)
        if prof:
            prof["name"] = text
            save_config(cfg)
            bot.send_message(chat_id, f"✅ Профиль переименован в: <b>{text}</b>", reply_markup=get_main_keyboard())
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

if __name__ == "__main__":
    print("🤖 Бот AQUA успешно запущен и готов к работе!", flush=True)
    try:
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
    except Exception as e:
        print(f"❌ Ошибка в polling: {e}", flush=True)
