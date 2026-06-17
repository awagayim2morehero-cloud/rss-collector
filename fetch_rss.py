import sys
import feedparser
import urllib.parse
import urllib.request
import re
import html
import smtplib
import ssl
import json
import hashlib
import difflib
import anthropic
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from pathlib import Path
from config import EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_TO, ANTHROPIC_API_KEY, INTEREST_KEYWORDS
try:
    from config import FEEDBACK_URL
except ImportError:
    FEEDBACK_URL = ""

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUMMARY_MAX_CHARS = 200
SEEN_FILE = Path(__file__).parent / "seen_articles.json"
SEEN_EXPIRE_DAYS = 60  # この日数を超えた記録は自動削除
AI_SUMMARY_MAX_CHARS = 500

DELIVERED_CACHE_FILE = Path(__file__).parent / "delivered_articles_cache.json"
TITLE_SIMILARITY_THRESHOLD = 0.9  # タイトル類似度がこれ以上なら重複とみなす

# ---------------------------------------------------------------
# フィルタリングキーワード（直接RSSの絞り込みに使用）
# ---------------------------------------------------------------
FILTER_KEYWORDS = [
    "AI", "人工知能", "ガバナンス", "governance", "risk", "リスク",
    "board", "取締役", "regulation", "規制", "compliance",
    "generative", "生成AI", "agentic", "oversight", "director",
]

# ---------------------------------------------------------------
# Google News RSS URL 生成
# ---------------------------------------------------------------
_GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

def gnews(query, lang="en"):
    if lang == "ja":
        params = dict(hl="ja", gl="JP", ceid="JP:ja")
    else:
        params = dict(hl="en-US", gl="US", ceid="US:en")
    return _GNEWS_BASE.format(query=urllib.parse.quote(query), **params)

# ---------------------------------------------------------------
# RSSソース定義
# filter=True  → キーワード絞り込みあり（全記事配信フィード向け）
# filter=False → Google Newsはクエリ自体で絞り込み済みのため不要
# ---------------------------------------------------------------
FEEDS = [
    # --- 直接RSSフィード（全記事配信 → キーワードフィルタあり）
    {
        "name": "Harvard Law School Forum on Corporate Governance",
        "category": "学術",
        "url": "https://corpgov.law.harvard.edu/feed/",
        "filter": True,
    },
    {
        "name": "金融庁（FSA）",
        "category": "規制当局",
        "url": "https://www.fsa.go.jp/fsaNewsListAll_rss2.xml",
        "filter": True,
    },
    {
        "name": "McKinsey Insights",
        "category": "プロファーム",
        "url": "https://www.mckinsey.com/insights/rss",
        "filter": True,
    },

    # --- 趣味：ギター（ルシアー・掘り出し物）
    {
        "name": "Ervin Somogyi",
        "category": "ギター",
        "url": gnews('"Ervin Somogyi" guitar'),
        "filter": False,
    },
    {
        "name": "Tom Sands Guitar",
        "category": "ギター",
        "url": gnews('"Tom Sands" guitar luthier'),
        "filter": False,
    },
    {
        "name": "アコースティックギター 中古・掘り出し物",
        "category": "ギター",
        "url": gnews('acoustic guitar luthier handmade "for sale" Somogyi OR Sands OR boutique'),
        "filter": False,
    },
    # --- 趣味：ギター（新製品・発売情報）
    {
        "name": "Gibson Jimmy Page モデル",
        "category": "ギター",
        "url": gnews('Gibson "Jimmy Page" guitar release 2026'),
        "filter": False,
    },
    # --- 趣味：東京グルメ
    {
        "name": "東京 新進気鋭シェフ",
        "category": "グルメ",
        "url": gnews("東京 新進気鋭 シェフ レストラン", lang="ja"),
        "filter": False,
    },
    {
        "name": "東京 新店・注目レストラン",
        "category": "グルメ",
        "url": gnews("東京 新店 レストラン シェフ 2026", lang="ja"),
        "filter": False,
    },
    {
        "name": "Tokyo New Restaurant",
        "category": "グルメ",
        "url": gnews('Tokyo new restaurant chef opening 2026'),
        "filter": False,
    },

    # --- 趣味：乗馬
    {
        "name": "乗馬 外乗・旅行",
        "category": "乗馬",
        "url": gnews("乗馬 外乗 旅行 評判", lang="ja"),
        "filter": False,
    },
    {
        "name": "乗馬 中級者以上",
        "category": "乗馬",
        "url": gnews("乗馬 中級者 クラブ 評判", lang="ja"),
        "filter": False,
    },
    # --- 趣味：オーディオ（専門サイト直接RSS）
    {
        "name": "PHILE WEB",
        "category": "オーディオ",
        "url": "https://www.phileweb.com/rss.php",
        "filter": True,
    },
    {
        "name": "AV Watch",
        "category": "オーディオ",
        "url": "https://av.watch.impress.co.jp/data/rss/1.0/avw/feed.rdf",
        "filter": True,
    },
    # --- 趣味：オーディオ（Google News補完）
    {
        "name": "LINN オーディオ",
        "category": "オーディオ",
        "url": gnews("LINN オーディオ ネットワーク 音質", lang="ja"),
        "filter": False,
    },
    {
        "name": "LINN Audio (English)",
        "category": "オーディオ",
        "url": gnews("LINN audio network streaming sound quality"),
        "filter": False,
    },

    # --- 近未来監査プロフェッション研究会
    # ①監査品質・オペレーション
    {
        "name": "IAASB / PCAOB 動向",
        "category": "研究会",
        "url": gnews('IAASB OR PCAOB "audit quality" AI "professional skepticism" OR ISA'),
        "filter": False,
    },
    {
        "name": "AI監査・Continuous Auditing",
        "category": "研究会",
        "url": gnews('"continuous auditing" OR "AI audit" "automation bias" OR hallucination OR "audit documentation"'),
        "filter": False,
    },
    # ②成長・マーケット
    {
        "name": "AIガバナンス保証・ISO 42001",
        "category": "研究会",
        "url": gnews('"AI governance assurance" OR "ISO 42001" audit certification assurance'),
        "filter": False,
    },
    {
        "name": "EU AI Act 監査影響",
        "category": "研究会",
        "url": gnews('"EU AI Act" audit assurance accountant compliance'),
        "filter": False,
    },
    {
        "name": "新業務領域・監査報酬",
        "category": "研究会",
        "url": gnews('"real-time assurance" OR "new assurance services" OR "audit fees" AI 2025 OR 2026'),
        "filter": False,
    },
    # ③監査人の役割
    {
        "name": "プロフェッショナルジャッジメント・人間AI協働",
        "category": "研究会",
        "url": gnews('"professional judgment" auditor AI "human-AI" OR "auditor role" 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "IIA Standards 2025",
        "category": "研究会",
        "url": gnews('IIA "internal audit" AI standards guidance 2025 OR 2026'),
        "filter": False,
    },
    # ④人財
    {
        "name": "監査人スキル・AIリテラシー",
        "category": "研究会",
        "url": gnews('"auditor skills" OR "audit data strategist" OR "AI literacy" "skill gap" audit'),
        "filter": False,
    },
    # ⑤リスクマネジメント
    {
        "name": "期待ギャップ・監査責任",
        "category": "研究会",
        "url": gnews('"expectation gap" OR "audit liability" OR "duty of care" auditor AI'),
        "filter": False,
    },
    {
        "name": "AIリスク・当局検査",
        "category": "研究会",
        "url": gnews('auditor "AI risk" "data security" OR "regulatory inspection" 2025 OR 2026'),
        "filter": False,
    },
    # 日本語
    {
        "name": "監査法人AI動向（日本語）",
        "category": "研究会",
        "url": gnews('監査法人 AI 職業的懐疑心 OR 調書 OR 監査品質 OR 自動化バイアス', lang="ja"),
        "filter": False,
    },
    {
        "name": "金融庁 監査モニタリング（日本語）",
        "category": "研究会",
        "url": gnews('金融庁 監査 モニタリング AIリスク OR 監査品質', lang="ja"),
        "filter": False,
    },
    {
        "name": "EU AI法・ISO42001 監査（日本語）",
        "category": "研究会",
        "url": gnews('EU AI法 OR ISO42001 監査 保証業務', lang="ja"),
        "filter": False,
    },

    # --- ⓪ AIの破壊的変化・俯瞰的考察
    {
        "name": "MIT Technology Review (AI)",
        "category": "研究会",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "filter": True,
    },
    {
        "name": "知識労働・プロフェッションの変容",
        "category": "研究会",
        "url": gnews('"future of professions" OR "knowledge work" AI cognitive automation 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "AI本質論（哲学・民主主義・社会）",
        "category": "研究会",
        "url": gnews('"AI and democracy" OR "epistemic crisis" OR "AI ethics" "future of expertise" OR "human judgment" 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "Stanford HAI / AI社会インパクト",
        "category": "研究会",
        "url": gnews('"Stanford HAI" OR "Stanford Human-Centered AI" "artificial intelligence" future society 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "HBR AIと組織・人材変革",
        "category": "研究会",
        "url": gnews('"Harvard Business Review" AI "future of work" OR "human judgment" OR "disruption of professions" 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "WEF Future of Jobs",
        "category": "研究会",
        "url": gnews('World Economic Forum "future of jobs" OR "future of work" AI skills disruption 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "労働の未来・スキル変革",
        "category": "研究会",
        "url": gnews('"skill obsolescence" OR "organizational transformation" OR "redefining talent" AI "future of work" 2025 OR 2026'),
        "filter": False,
    },
    {
        "name": "AIと知的活動の変容（日本語）",
        "category": "研究会",
        "url": gnews('AI 知識労働 OR プロフェッション OR 認知的労働 OR 人間固有 OR 判断 OR 創造性 変容', lang="ja"),
        "filter": False,
    },

    # --- Google News RSS（クエリで絞り込み済み）
    {
        "name": "PwC",
        "category": "プロファーム",
        "url": gnews('PwC "corporate governance" AI risk board'),
        "filter": False,
    },
    {
        "name": "EY（Ernst & Young）",
        "category": "プロファーム",
        "url": gnews('EY Ernst Young "AI governance" board risk'),
        "filter": False,
    },
    {
        "name": "KPMG",
        "category": "プロファーム",
        "url": gnews('KPMG "corporate governance" AI board risk'),
        "filter": False,
    },
    {
        "name": "Deloitte（DTT）",
        "category": "プロファーム",
        "url": gnews('Deloitte "AI governance" risk board directors'),
        "filter": False,
    },
    {
        "name": "WEF（世界経済フォーラム）",
        "category": "国際機関",
        "url": gnews('World Economic Forum "AI governance" risk regulation'),
        "filter": False,
    },
    {
        "name": "経済産業省（METI）",
        "category": "規制当局",
        "url": gnews("経済産業省 AIガバナンス リスク", lang="ja"),
        "filter": False,
    },
    {
        "name": "SEC（米国証券取引委員会）",
        "category": "規制当局",
        "url": gnews('SEC "corporate governance" AI regulation disclosure'),
        "filter": False,
    },
]

# ---------------------------------------------------------------
# 興味キーワードによる絞り込み
# ---------------------------------------------------------------
def matches_interest(entry):
    text = (
        entry.get("title", "") + " " + entry.get("summary", "")
    ).lower()
    return any(kw.lower() in text for kw in INTEREST_KEYWORDS)

# ---------------------------------------------------------------
# 既読記事の管理（重複送信防止）
# ---------------------------------------------------------------
def load_seen():
    if not SEEN_FILE.exists():
        return {}
    with open(SEEN_FILE, encoding="utf-8-sig") as f:
        return json.load(f)

def save_seen(seen: dict):
    cutoff = (datetime.now() - timedelta(days=SEEN_EXPIRE_DAYS)).isoformat()
    pruned = {url: ts for url, ts in seen.items() if ts >= cutoff}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)

def filter_new(articles: list, seen: dict) -> list:
    return [a for a in articles if a["link"] not in seen]

def mark_seen(articles: list, seen: dict):
    now = datetime.now().isoformat()
    for a in articles:
        seen[a["link"]] = now

# ---------------------------------------------------------------
# 配信済み記事キャッシュ（再ピックアップ防止）
# ---------------------------------------------------------------
def load_delivered_cache():
    if not DELIVERED_CACHE_FILE.exists():
        return {"delivered": []}
    try:
        with open(DELIVERED_CACHE_FILE, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return {"delivered": []}
    if not isinstance(data, dict) or not isinstance(data.get("delivered"), list):
        return {"delivered": []}
    return data

def save_delivered_cache(cache: dict):
    with open(DELIVERED_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def _url_domain_path(url):
    parts = urllib.parse.urlsplit(url or "")
    return (parts.netloc.lower(), parts.path.rstrip("/"))

def _title_similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()

def is_already_delivered(article, delivered_entries):
    """URL一致・タイトル一致・タイトル類似度90%以上・URL（ドメイン＋パス）一致のいずれかで重複判定"""
    title = article.get("title", "")
    link = article.get("link", "")
    link_domain_path = _url_domain_path(link) if link else None
    for entry in delivered_entries:
        e_url = entry.get("url", "")
        e_title = entry.get("title", "")
        if link and e_url and link == e_url:
            return True
        if link_domain_path and e_url:
            e_domain_path = _url_domain_path(e_url)
            if e_domain_path[0] and link_domain_path == e_domain_path:
                return True
        if title and e_title:
            if title == e_title or _title_similarity(title, e_title) >= TITLE_SIMILARITY_THRESHOLD:
                return True
    return False

def filter_undelivered(articles: list, cache: dict) -> list:
    delivered_entries = cache.get("delivered", [])
    return [a for a in articles if not is_already_delivered(a, delivered_entries)]

def append_delivered(articles: list, cache: dict, delivered_date: str):
    delivered_entries = cache.setdefault("delivered", [])
    for a in articles:
        delivered_entries.append({
            "url":            a.get("link", ""),
            "title":          a.get("title", ""),
            "delivered_date": delivered_date,
        })

# ---------------------------------------------------------------
# Claude API による AI 要旨生成 + 関連性スコア（1回のAPI呼び出し）
# ---------------------------------------------------------------
_ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

_KEYWORDS_STR = "、".join(INTEREST_KEYWORDS[:20])  # プロンプトに代表キーワードを含める

_SYSTEM_PROMPT = f"""あなたは記事の要旨をまとめ、関連性を評価するアシスタントです。
以下の2つを必ずJSON形式で出力してください。

【出力形式】
{{"summary": "（500文字以内の日本語要旨）", "score": （1〜5の整数）}}

【要旨のルール】
- 500文字以内の日本語でまとめる
- 日本語以外は日本語に翻訳する
- 前置きや説明は不要

【関連性スコアの基準】
ユーザーの主な関心領域: {_KEYWORDS_STR}…

5: 関心領域に直結する重要な内容（最新動向・発表・研究）
4: 関心領域に明確に関連する内容
3: 関心領域に部分的に関連する内容
2: 関連性は薄いが参考になりうる内容
1: ほぼ関連なし"""

_HOBBY_SYSTEM_PROMPT = """あなたは記事の要旨をまとめ、内容の充実度を評価するアシスタントです。
以下の2つを必ずJSON形式で出力してください。

【出力形式】
{"summary": "（500文字以内の日本語要旨）", "score": （1〜5の整数）}

【要旨のルール】
- 500文字以内の日本語でまとめる
- 日本語以外は日本語に翻訳する
- 前置きや説明は不要

【スコアの基準】
5: 非常に具体的で有益な情報（新製品・イベント・レビュー等）
4: 興味深い情報
3: 参考になる情報
2: 情報量が少ない・やや関連性が薄い
1: 情報がほとんどない"""

_HOBBY_CATEGORIES = {"ギター", "グルメ", "乗馬", "オーディオ"}
_AUDIT_CATEGORIES = {"研究会"}

_AUDIT_SYSTEM_PROMPT = """あなたは監査プロフェッション・AI・内部統制、およびAIが社会・知的活動に与える本質的変化に関する記事を評価するアシスタントです。
以下の3つを必ずJSON形式で出力してください。

【出力形式】
{"summary": "（500文字以内の日本語要旨）", "score": （1〜5の整数）, "domains": "（該当領域番号）"}

【要旨のルール】
- 500文字以内の日本語でまとめる
- 日本語以外は日本語に翻訳する
- 前置きや説明は不要

【領域タグ（domainsフィールド）】
以下6領域のうち該当するものを番号で記載（例: "⓪③"、複数可）
⓪AIの破壊的変化・俯瞰的考察: 知識労働の変容、認知的労働の自動化、プロフェッションの未来、人間固有の判断と創造性、AIと民主主義、AIの倫理・哲学・社会的影響、情報の真実性と信頼、労働の未来、スキルの陳腐化、組織変革の本質論。「本質論・概念論・将来予測」を扱う記事に付与する。
①監査品質・オペレーション: AI監査、調書作成AI、職業的懐疑心、自動化バイアス、ISA500、不正リスク、ハルシネーション、監査品質、Continuous Audit
②成長・マーケット: AIガバナンス保証、ISO42001、EU AI Act、新業務領域、監査報酬、リアルタイム保証
③監査人の役割: プロフェッショナルジャッジメント、Advice Insight Foresight、AIと人間の協働、IIA標準
④人財: 監査人スキル、人材育成、AIリテラシー、スキルギャップ、IIA能力フレームワーク
⑤リスクマネジメント: 期待ギャップ、注意義務、AIリスク、データセキュリティ、監査責任、当局検査
該当領域がない場合は "" を返す。

【重要度スコアの基準】
◆ ⓪領域の場合:
5: 著名識者・主要機関（MIT/Stanford/WEF/HBR等）による、複数テーマに活用できる本質的・俯瞰的提言
4: AIの本質的変化に関する有用な考察・論考・将来予測
3: 参考程度に使える俯瞰的考察
2: 抽象度が低い、または特定製品・企業動向が中心の内容
1: 監査・プロフェッション・知識労働との関連がほぼない記事

◆ ①〜⑤領域の場合:
5: 複数領域に直接影響する基準改訂・主要機関（IAASB/IIA/PCAOB/EU/NIST等）の提言
4: 特定領域に直接関連する有用情報
3: 参考情報として使える可能性がある情報
2: 監査との接続が薄い一般ITニュース・関連性が低い情報
1: 企業財務・決算情報、または監査プロフェッションへの直接言及がない政治・経済ニュース

【スコアを2以下に抑える条件（上記基準より優先して適用）】
以下のいずれかに該当する記事は、領域タグの有無にかかわらずスコアを2以下とする：
- AI活用の一事例紹介にとどまり、プロフェッションとしての問いを開かない記事（例: 特定企業のAI導入効果の報告、業務効率化事例）
- 特定業界・企業の業務効率化事例で、監査プロフェッションへの示唆が間接的なもの
- 規制・手続きの変更報告で、プロフェッションの役割・価値・リスクの本質的変化に関わらないもの（例: 特定国の手続き変更、イベント・セミナーの告知）
- 一般的なAIニュースで、監査・保証・プロフェッションへの接続が明示されていないもの"""

def ai_summarize(title, raw_summary, category=None):
    if not _ai_client:
        return None, None, None
    try:
        if category in _AUDIT_CATEGORIES:
            system = _AUDIT_SYSTEM_PROMPT
        elif category in _HOBBY_CATEGORIES:
            system = _HOBBY_SYSTEM_PROMPT
        else:
            system = _SYSTEM_PROMPT
        prompt = f"タイトル: {title}\n\n内容: {raw_summary or '（内容なし）'}"
        response = _ai_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # JSON部分を抽出してパース
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            summary = str(data.get("summary", "")).strip()
            score   = int(data.get("score", 3))
            score   = max(1, min(5, score))
            domains = str(data.get("domains", "")).strip() if category in _AUDIT_CATEGORIES else None
            return summary, score, domains
        return raw, None, None
    except Exception as e:
        return f"（要旨生成エラー: {e}）", None, None

# ---------------------------------------------------------------
# 要旨テキストのクリーニング
# ---------------------------------------------------------------
def clean_summary(raw, max_chars=SUMMARY_MAX_CHARS):
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)   # HTMLタグ除去
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text or "（要旨なし）"

# ---------------------------------------------------------------
# 記事本文取得（ウェブスクレイピング）
# ---------------------------------------------------------------
_BODY_MAX_CHARS = 3000   # AIに渡す本文の最大文字数
_BODY_MIN_CHARS = 300    # これ未満はペイウォール等とみなしフォールバック
_FETCH_TIMEOUT  = 8      # 1記事あたりのタイムアウト（秒）

class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "nav", "header", "footer",
                       "aside", "noscript", "iframe", "form"})

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self):
        return " ".join(self._parts)

def fetch_article_body(url):
    """記事URLから本文テキストを取得。失敗・ペイウォール時はNoneを返す。"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ja,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                return None
            raw = resp.read(512 * 1024)  # 512KB上限
            charset = resp.headers.get_content_charset("utf-8")

        html_str = raw.decode(charset, errors="replace")
        parser = _TextExtractor()
        parser.feed(html_str)
        body = re.sub(r"\s+", " ", parser.get_text()).strip()

        if len(body) < _BODY_MIN_CHARS:
            return None
        return body[:_BODY_MAX_CHARS]
    except Exception:
        return None

# ---------------------------------------------------------------
# 記事取得
# ---------------------------------------------------------------
def matches_filter(entry):
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw.lower() in text for kw in FILTER_KEYWORDS)

def fetch_feed(feed, days=30, max_per_feed=5, delivered_cache=None):
    cutoff = datetime.now() - timedelta(days=days)
    try:
        parsed = feedparser.parse(feed["url"])
    except Exception as e:
        print(f"  エラー: {e}")
        return []

    # Step 1: フィルタリングして候補記事を収集
    candidates = []
    for entry in parsed.entries:
        pub = entry.get("published_parsed")
        if pub:
            pub_dt = datetime(*pub[:6])
            if pub_dt < cutoff:
                continue
        if not matches_interest(entry):
            continue
        link = entry.get("link", "")
        candidates.append({
            "title":       entry.get("title", "（タイトルなし）"),
            "link":        link,
            "published":   entry.get("published", "日付不明"),
            "rss_summary": clean_summary(entry.get("summary", "")),
            "article_id":  hashlib.md5(link.encode()).hexdigest()[:10],
        })
        if len(candidates) >= max_per_feed:
            break

    if not candidates:
        return []

    # Step 1.5: 配信済みキャッシュと照合し、配信済み記事を除外
    if delivered_cache is not None:
        candidates = [
            c for c in candidates
            if not is_already_delivered(c, delivered_cache.get("delivered", []))
        ]
        if not candidates:
            return []

    # Step 2: 記事本文を並列取得
    with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as executor:
        bodies = list(executor.map(fetch_article_body, [c["link"] for c in candidates]))

    # Step 3: AI要旨生成 + フォールバック処理
    results = []
    for c, body in zip(candidates, bodies):
        content = body if body else c["rss_summary"]
        ai_summary, score, domains = ai_summarize(c["title"], content, feed["category"])
        fetch_tag = "（全文取得）" if body else "（概要のみ）"
        display_summary = (ai_summary if ai_summary else c["rss_summary"]) + fetch_tag

        results.append({
            "source":     feed["name"],
            "category":   feed["category"],
            "title":      c["title"],
            "link":       c["link"],
            "published":  c["published"],
            "summary":    display_summary,
            "score":      score,
            "domains":    domains,
            "article_id": c["article_id"],
        })

    return results

# ---------------------------------------------------------------
# HTML メール生成
# ---------------------------------------------------------------
def _feedback_html(article_id, title):
    if not article_id or not FEEDBACK_URL:
        return ""
    t = urllib.parse.quote(title[:80])
    base = f"{FEEDBACK_URL}?id={article_id}&t={t}&r="
    btn  = (
        "background:none;border:1px solid {c};border-radius:4px;"
        "color:{c};font-size:11px;padding:2px 7px;cursor:pointer;"
        "text-decoration:none;margin-left:4px;"
    )
    return (
        f'<div style="white-space:nowrap;">'
        f'<a href="{base}3" style="{btn.format(c="#2d7a2d")}">✅ 参考になった</a>'
        f'<a href="{base}2" style="{btn.format(c="#888")}">➖ 普通</a>'
        f'<a href="{base}1" style="{btn.format(c="#c0392b")}">❌ 関連なし</a>'
        f'</div>'
    )

def _score_html(score):
    if score is None:
        return ""
    colors = {5: "#e53e3e", 4: "#dd6b20", 3: "#d69e2e", 2: "#718096", 1: "#cbd5e0"}
    labels = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}
    c = colors.get(score, "#718096")
    l = labels.get(score, "")
    return (
        f'<div style="font-size:12px; color:{c}; font-weight:bold; '
        f'white-space:nowrap;" title="関連性スコア {score}/5">{l}</div>'
    )

THEMES = {
    "work": {
        "header_bg":    "#1a1a2e",
        "header_title": "企業ガバナンス &amp; AI リスク情報レポート",
    },
    "hobby": {
        "header_bg":    "#2d4a1e",
        "header_title": "趣味情報レポート",
    },
    "audit": {
        "header_bg":    "#1e2d4a",
        "header_title": "近未来監査プロフェッション研究会 情報レポート",
    },
}

def build_html(all_articles, generated_at, theme="work"):
    category_colors = {
        "学術":         "#1a6b3c",
        "規制当局":     "#1a3a6b",
        "プロファーム": "#6b3a1a",
        "国際機関":     "#4a1a6b",
        "ギター":       "#8b4513",
        "グルメ":       "#b5472a",
        "乗馬":         "#5a7a2a",
        "オーディオ":   "#2a5a7a",
        "研究会":       "#1e3a5f",
    }
    default_color = "#444444"

    rows_by_category = {}
    for a in all_articles:
        rows_by_category.setdefault(a["category"], []).append(a)

    sections_html = ""
    for category, articles in rows_by_category.items():
        color = category_colors.get(category, default_color)
        items_html = ""
        for a in articles:
            score      = a.get("score")
            score_html = _score_html(score)
            fb_html    = _feedback_html(a.get("article_id", ""), a["title"])
            domains    = a.get("domains", "")
            domain_html = (
                f'<div style="font-size:12px; color:#1e3a5f; font-weight:bold; margin-bottom:4px;">'
                f'【領域タグ】{html.escape(domains)}</div>'
            ) if domains else ""
            items_html += f"""
            <tr>
              <td style="padding:12px 16px; border-bottom:1px solid #eee; vertical-align:top;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                  <div style="font-size:11px; color:{color}; font-weight:bold;">
                    {html.escape(a['source'])}
                  </div>
                  {score_html}
                </div>
                <div style="font-size:14px; font-weight:bold; margin-bottom:6px;">
                  <a href="{a['link']}" style="color:#1a1a1a; text-decoration:none;">
                    {html.escape(a['title'])}
                  </a>
                </div>
                {domain_html}
                <div style="font-size:12px; color:#666; margin-bottom:6px;">
                  {html.escape(a['summary'])}
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
                  <div style="font-size:11px; color:#999;">{html.escape(a['published'])}</div>
                  {fb_html}
                </div>
              </td>
            </tr>"""

        sections_html += f"""
        <tr>
          <td style="background:{color}; color:#fff; padding:10px 16px;
                     font-size:13px; font-weight:bold; letter-spacing:0.5px;">
            {html.escape(category)}
          </td>
        </tr>
        {items_html}
        <tr><td style="height:16px;"></td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f4f4f4; font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4; padding:24px 0;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="background:#fff; border-radius:6px; overflow:hidden;
                    box-shadow:0 1px 4px rgba(0,0,0,0.1);">
        <!-- ヘッダー -->
        <tr>
          <td style="background:{THEMES[theme]['header_bg']}; padding:24px 24px 20px; color:#fff;">
            <div style="font-size:20px; font-weight:bold;">
              {THEMES[theme]['header_title']}
            </div>
            <div style="font-size:12px; color:#aaa; margin-top:6px;">
              {generated_at} 生成 ／ 全 {len(all_articles)} 件
            </div>
          </td>
        </tr>
        <!-- 記事一覧 -->
        <tr><td style="padding:16px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {sections_html}
          </table>
        </td></tr>
        <!-- フッター -->
        <tr>
          <td style="background:#f0f0f0; padding:12px 24px;
                     font-size:11px; color:#999; text-align:center;">
            RSS Collector — 自動配信
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

# ---------------------------------------------------------------
# メール送信
# ---------------------------------------------------------------
def send_email(html_body, subject):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.sendmail(EMAIL_ADDRESS, EMAIL_TO, msg.as_string())

# ---------------------------------------------------------------
# メイン
# ---------------------------------------------------------------
def main():
    all_articles = []

    ai_mode = "有効（claude-haiku-4-5）" if _ai_client else "無効（APIキー未設定）"
    print(f"AI要旨生成: {ai_mode}\n")

    seen = load_seen()
    delivered_cache = load_delivered_cache()
    is_monday = datetime.now().weekday() == 0  # 0 = Monday

    for feed in FEEDS:
        # 研究会フィードは月曜日のみ取得
        if feed["category"] in _AUDIT_CATEGORIES and not is_monday:
            continue
        print(f"取得中: {feed['name']} ...", end=" ", flush=True)
        max_per = 10 if feed["category"] in _AUDIT_CATEGORIES else 5
        articles = fetch_feed(feed, max_per_feed=max_per, delivered_cache=delivered_cache)
        all_articles.extend(articles)
        print(f"{len(articles)} 件")

    new_articles = filter_new(all_articles, seen)
    new_articles = filter_undelivered(new_articles, delivered_cache)

    print(f"\n{'=' * 60}")
    print(f"  合計 {len(all_articles)} 件取得 / 新着（未配信） {len(new_articles)} 件")
    print(f"{'=' * 60}\n")

    if not new_articles:
        print("新着記事がないためメール送信をスキップします。")
        return

    all_articles = new_articles

    current_category = None
    for article in all_articles:
        if article["category"] != current_category:
            current_category = article["category"]
            print(f"\n▼ {current_category}")
            print("-" * 60)

        score     = article.get("score")
        score_str = f"{'★' * score}{'☆' * (5 - score)} ({score}/5)" if score else "－"
        domains   = article.get("domains", "")
        print(f"\n  [{article['source']}]")
        print(f"  タイトル   : {article['title']}")
        print(f"  関連性     : {score_str}")
        if domains:
            print(f"  領域タグ   : 【{domains}】")
        print(f"  日付       : {article['published']}")
        print(f"  要旨       : {article['summary']}")
        print(f"  リンク     : {article['link']}")

    # カテゴリでグループ分け
    work_articles  = [a for a in all_articles if a["category"] not in _HOBBY_CATEGORIES and a["category"] not in _AUDIT_CATEGORIES]
    hobby_articles = [a for a in all_articles if a["category"] in _HOBBY_CATEGORIES]
    audit_articles = [a for a in all_articles if a["category"] in _AUDIT_CATEGORIES]

    # 研究会：⓪記事（★★★★以上、上限5件）＋ ①〜⑤記事（★★★以上、残枠）
    zero_articles = sorted(
        [a for a in audit_articles
         if "⓪" in (a.get("domains") or "") and (a.get("score") or 0) >= 4],
        key=lambda x: x.get("score") or 0,
        reverse=True,
    )[:5]
    domain_articles = sorted(
        [a for a in audit_articles
         if "⓪" not in (a.get("domains") or "") and (a.get("score") or 0) >= 3],
        key=lambda x: x.get("score") or 0,
        reverse=True,
    )[:15 - len(zero_articles)]
    audit_filtered = zero_articles + domain_articles

    generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    today        = datetime.now().strftime("%Y/%m/%d")
    sent_articles = []

    print(f"\nメールを送信中...")

    if work_articles:
        subject  = f"【ガバナンス情報】{today} — {len(work_articles)}件"
        html_body = build_html(work_articles, generated_at, theme="work")
        try:
            send_email(html_body, subject)
            sent_articles.extend(work_articles)
            print(f"  ガバナンス ({len(work_articles)}件) → 送信完了")
        except Exception as e:
            print(f"  ガバナンス → 送信失敗: {e}")
    else:
        print(f"  ガバナンス → 新着なし")

    if hobby_articles:
        subject  = f"【趣味情報】{today} — {len(hobby_articles)}件"
        html_body = build_html(hobby_articles, generated_at, theme="hobby")
        try:
            send_email(html_body, subject)
            sent_articles.extend(hobby_articles)
            print(f"  趣味情報 ({len(hobby_articles)}件) → 送信完了")
        except Exception as e:
            print(f"  ギター・グルメ → 送信失敗: {e}")
    else:
        print(f"  趣味情報 → 新着なし")

    if is_monday:
        if audit_filtered:
            subject  = f"【研究会情報】{today} — {len(audit_filtered)}件"
            html_body = build_html(audit_filtered, generated_at, theme="audit")
            try:
                send_email(html_body, subject)
                sent_articles.extend(audit_filtered)
                print(f"  研究会情報 ({len(audit_filtered)}件) → 送信完了")
            except Exception as e:
                print(f"  研究会情報 → 送信失敗: {e}")
        else:
            print(f"  研究会情報 → 掲載記事なし（★★★以上 0件）")
    else:
        print(f"  研究会情報 → 週次配信のため本日はスキップ（月曜日に配信）")

    if sent_articles:
        mark_seen(sent_articles, seen)
        save_seen(seen)
        append_delivered(sent_articles, delivered_cache, datetime.now().strftime("%Y-%m-%d"))
        save_delivered_cache(delivered_cache)

if __name__ == "__main__":
    main()
