import json, os, re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_JSON = os.path.join(BASE_DIR, "server_rules.json")
RULES_INDEX_JSON = os.path.join(BASE_DIR, "server_rules_index.json")

# In-memory storage
_SERVER_RULES = {}
_RULES_INDEX = {}

def load_rules():
    global _SERVER_RULES, _RULES_INDEX
    if os.path.exists(RULES_JSON):
        try:
            with open(RULES_JSON, "r", encoding="utf-8") as f:
                _SERVER_RULES = json.load(f)
        except Exception as e:
            print(f"[rules_kb] Error loading rules: {e}")
    if os.path.exists(RULES_INDEX_JSON):
        try:
            with open(RULES_INDEX_JSON, "r", encoding="utf-8") as f:
                _RULES_INDEX = json.load(f)
        except Exception as e:
            print(f"[rules_kb] Error loading rules index: {e}")

load_rules()

# Precise mapping of Black Russia violation keywords to official rule clauses
KEYWORD_TO_RULE = {
    # NonRP & Fraud
    "nonrp обман": "2.05",
    "нонрп обман": "2.05",
    "скам": "2.05",
    "обман": "2.05",
    "долг": "2.57",
    "невозврат долга": "2.57",
    "уход от рп": "2.02",
    "уход от rp": "2.02",
    "уход": "2.02",
    "nonrp drive": "2.03",
    "нонрп драйв": "2.03",
    "епп": "2.03",
    "помеха": "2.04",
    "nonrp": "2.01",
    "нонрп": "2.01",
    
    # Combat & Rules of Play
    "масс дм": "2.20",
    "mass dm": "2.20",
    "dm": "2.19",
    "дм": "2.19",
    "db": "2.13",
    "дб": "2.13",
    "tk": "2.15",
    "тк": "2.15",
    "sk": "2.16",
    "ск": "2.16",
    "mg": "2.18",
    "мг": "2.18",

    # Bagouz & Cheats
    "багоюз": "2.21",
    "баг": "2.21",
    "читы": "2.22",
    "софт": "2.22",
    "читер": "2.22",
    "стороннее по": "2.22",
    "по": "2.22",
    "бот": "2.22",
    "анимка": "2.55",

    # Sliv
    "слив склада": "2.09",
    "слив сми": "3.08",
    "слив": "2.26",

    # Economy & Currency
    "покупка ив": "2.28",
    "продажа ив": "2.28",
    "покупка вирт": "2.28",
    "продажа вирт": "2.28",
    "ив": "2.28",
    "порча экономики": "2.30",
    "порча эко": "2.30",
    "трансфер": "4.05",
    
    # Accounts & PPV
    "ппв": "4.03",
    "продажа аккаунта": "4.03",
    "покупка аккаунта": "4.03",
    "передача аккаунта": "4.03",
    "взлом": "4.03",
    "мультиаккаунт": "4.04",
    "твинк": "4.04",

    # Chat Violations
    "оскорбление родных": "3.04",
    "оскорбление родни": "3.04",
    "упоминание родных": "3.04",
    "упоминание родни": "3.04",
    "оск родных": "3.04",
    "оск родни": "3.04",
    "упом родных": "3.04",
    "упом родни": "3.04",
    "оск род": "3.04",
    "упом род": "3.04",
    "родных": "3.04",
    "родни": "3.04",
    "родня": "3.04",
    "оск адм": "2.54",
    "неуважение": "2.54",
    "капс": "3.02",
    "caps": "3.02",
    "флуд": "3.05",
    "flood": "3.05",
    "оскорбление": "3.03",
    "мат": "3.23",
    "политика": "3.18",
    "реклама": "2.31",
    "музыка": "3.14",
    "выдача себя за адм": "3.10",
    
    # Other
    "деанон": "2.38",
    "фейк": "4.10",
    "ник": "4.08"
}

def get_rule_clause(clause_num: str):
    """Returns rule info dict for a given clause number, e.g. '2.05'"""
    if not _RULES_INDEX:
        load_rules()
    clause_num = clause_num.strip()
    return _RULES_INDEX.get(clause_num)

def find_rule_by_keyword(query: str):
    """Finds matching rule based on violation keyword or rule number with robust prioritization"""
    if not _RULES_INDEX:
        load_rules()
    q_clean = query.strip().lower()
    words = set(re.findall(r'\b[\w\.]+\b', q_clean))
    
    # 1. Exact clause number (e.g. '2.05' or '3.04')
    m_num = re.search(r'\b(\d+\.\d+)\b', q_clean)
    if m_num and m_num.group(1) in _RULES_INDEX:
        return m_num.group(1), _RULES_INDEX[m_num.group(1)]

    # 2. Keyword dictionary lookup sorted by length descending to match specific phrases first
    sorted_kw = sorted(KEYWORD_TO_RULE.keys(), key=lambda x: len(x), reverse=True)
    for kw in sorted_kw:
        num = KEYWORD_TO_RULE[kw]
        if ' ' in kw:
            if kw in q_clean:
                return num, _RULES_INDEX.get(num)
        else:
            if kw in words or re.search(r'(?:\b|^)' + re.escape(kw) + r'(?:\b|$)', q_clean):
                return num, _RULES_INDEX.get(num)

    # 3. Full-text search
    for num, item in _RULES_INDEX.items():
        if q_clean in item['title'].lower():
            return num, item

    return None, None

def format_rule_card(num: str, rule: dict) -> str:
    """Formats a rule clause for Telegram display"""
    title = rule.get('title', '')
    punishment = rule.get('punishment', '')
    full_text = rule.get('full_text', '')
    
    msg = f"📜 <b>Пункт правил сервера {num}</b>\n\n"
    msg += f"<b>Формулировка:</b>\n<i>{full_text}</i>\n\n"
    if punishment:
        msg += f"⚖️ <b>Регламент наказания:</b>\n<code>{punishment}</code>\n"
    return msg

def get_forum_topics_summary():
    """Returns list of topics parsed from 'Общие правила серверов'"""
    if not _SERVER_RULES:
        load_rules()
    topics = []
    for title, data in _SERVER_RULES.items():
        topics.append({
            'title': title,
            'url': data.get('url', ''),
            'posts': data.get('total_posts', 0)
        })
    return topics
