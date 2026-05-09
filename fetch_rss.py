import sys
import feedparser
import urllib.parse
import re
import html
import smtplib
import ssl
import json
import hashlib
import anthropic
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

def ai_summarize(title, raw_summary):
    if not _ai_client:
        return None, None
    try:
        prompt = f"タイトル: {title}\n\n内容: {raw_summary or '（内容なし）'}"
        response = _ai_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=700,
            system=_SYSTEM_PROMPT,
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
            return summary, score
        return raw, None
    except Exception as e:
        return f"（要旨生成エラー: {e}）", None

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
# 記事取得
# ---------------------------------------------------------------
def matches_filter(entry):
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw.lower() in text for kw in FILTER_KEYWORDS)

def fetch_feed(feed, days=30, max_per_feed=5):
    cutoff = datetime.now() - timedelta(days=days)
    try:
        parsed = feedparser.parse(feed["url"])
    except Exception as e:
        print(f"  エラー: {e}")
        return []

    results = []
    for entry in parsed.entries:
        pub = entry.get("published_parsed")
        if pub:
            pub_dt = datetime(*pub[:6])
            if pub_dt < cutoff:
                continue

        if not matches_interest(entry):
            continue

        title       = entry.get("title", "（タイトルなし）")
        link        = entry.get("link", "")
        raw_summary = entry.get("summary", "")
        rss_summary = clean_summary(raw_summary)
        ai_summary, score = ai_summarize(title, rss_summary)
        article_id  = hashlib.md5(link.encode()).hexdigest()[:10]

        results.append({
            "source":     feed["name"],
            "category":   feed["category"],
            "title":      title,
            "link":       link,
            "published":  entry.get("published", "日付不明"),
            "summary":    ai_summary if ai_summary else rss_summary,
            "score":      score,
            "article_id": article_id,
        })

        if len(results) >= max_per_feed:
            break

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

    for feed in FEEDS:
        print(f"取得中: {feed['name']} ...", end=" ", flush=True)
        articles = fetch_feed(feed)
        all_articles.extend(articles)
        print(f"{len(articles)} 件")

    new_articles = filter_new(all_articles, seen)

    print(f"\n{'=' * 60}")
    print(f"  合計 {len(all_articles)} 件取得 / 新着 {len(new_articles)} 件")
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
        print(f"\n  [{article['source']}]")
        print(f"  タイトル   : {article['title']}")
        print(f"  関連性     : {score_str}")
        print(f"  日付       : {article['published']}")
        print(f"  要旨       : {article['summary']}")
        print(f"  リンク     : {article['link']}")

    # カテゴリでグループ分け
    HOBBY_CATEGORIES = {"ギター", "グルメ", "乗馬", "オーディオ"}
    work_articles  = [a for a in all_articles if a["category"] not in HOBBY_CATEGORIES]
    hobby_articles = [a for a in all_articles if a["category"] in HOBBY_CATEGORIES]

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

    if sent_articles:
        mark_seen(sent_articles, seen)
        save_seen(seen)

if __name__ == "__main__":
    main()
