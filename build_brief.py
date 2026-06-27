#!/usr/bin/env python3
"""
近未来監査プロフェッション研究会 — 素材検討表ビルダー
research_queries.py の各命題でGoogle Newsを検索し、
AI評価した素材検討表をHTMLメールで送信する。
"""
import sys
import json
import re
import html
import difflib
import urllib.parse
import urllib.request
import smtplib
import ssl
import feedparser
import anthropic
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html.parser import HTMLParser

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_TO, ANTHROPIC_API_KEY
from research_queries import ADDITIONAL_SEARCH_QUERIES, EXCLUDED_TITLES, SESSION_EXECUTION_ORDER

# ---------------------------------------------------------------
# Google News RSS
# ---------------------------------------------------------------
_GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

def gnews(query, lang="en"):
    p = (dict(hl="ja", gl="JP", ceid="JP:ja") if lang == "ja"
         else dict(hl="en-US", gl="US", ceid="US:en"))
    return _GNEWS_BASE.format(query=urllib.parse.quote(query), **p)

# ---------------------------------------------------------------
# AI クライアント
# ---------------------------------------------------------------
_ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

_BRIEF_SYS_TEMPLATE = """\
あなたは近未来監査プロフェッション研究会の素材検討アシスタントです。
下記命題に照らして記事を評価し、素材検討表の各フィールドをJSON形式で出力してください。

【命題テーマ】
{theme}

【命題の意図】
{intent}

【基本優先度】
{priority}（この水準を基準に記事内容で上下調整する）

【出力形式（JSON）】
{{
  "core_argument": "3〜5行で「〜が〜を示している」という事実記述に徹すること",
  "usage": "A" または "B" または "A+B",
  "summary_proposal": "サマリー活用提案（セッション番号・現在起きていること/近未来仮説/適応課題のどの位置かを明記）",
  "question_proposal": "設問活用提案（A型[知識確認]/B型[即答体験]の別と具体的な問いの文案）",
  "priority": "★" または "★★" または "★★★",
  "priority_note": "基本優先度からの調整理由（変更なければ空文字）"
}}

【用途の判断基準】
A（サマリー素材）: 研究会で「現在起きていること」を示す根拠として提示する
B（設問素材）: 参加者への問いかけ・議論の起点として機能する
A+B: 両方に活用可能\
"""

def ai_analyze_brief(title, content, query):
    if not _ai:
        return None
    system = _BRIEF_SYS_TEMPLATE.format(
        theme=query["theme"],
        intent=query["intent"],
        priority=query["priority"],
    )
    try:
        resp = _ai.messages.create(
            model="claude-haiku-4-5",
            max_tokens=900,
            system=system,
            messages=[{"role": "user", "content": f"タイトル: {title}\n\n内容: {content or '（内容なし）'}"}],
        )
        raw = resp.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"    AI評価エラー: {e}")
    return None

# ---------------------------------------------------------------
# 記事本文取得
# ---------------------------------------------------------------
_BODY_MAX = 3000
_BODY_MIN = 300
_FETCH_TIMEOUT = 8

class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "nav", "header", "footer",
                       "aside", "noscript", "iframe", "form"})

    def __init__(self):
        super().__init__()
        self._depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth == 0:
            t = data.strip()
            if t:
                self._parts.append(t)

    def get_text(self):
        return " ".join(self._parts)

def fetch_article_body(url):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ja,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                return None
            raw = resp.read(512 * 1024)
            charset = resp.headers.get_content_charset("utf-8")
        html_str = raw.decode(charset, errors="replace")
        parser = _TextExtractor()
        parser.feed(html_str)
        body = re.sub(r"\s+", " ", parser.get_text()).strip()
        if len(body) < _BODY_MIN:
            return None
        return body[:_BODY_MAX]
    except Exception:
        return None

# ---------------------------------------------------------------
# 除外チェック
# ---------------------------------------------------------------
def is_excluded(title):
    t = title.lower()
    for ex in EXCLUDED_TITLES:
        e = ex.lower()
        if e in t:
            return True
        if difflib.SequenceMatcher(None, t, e).ratio() >= 0.6:
            return True
    return False

# ---------------------------------------------------------------
# 記事取得（命題ごと）
# ---------------------------------------------------------------
def fetch_brief_articles(query, days=180, max_per_kw=5, max_total=12):
    cutoff = datetime.now() - timedelta(days=days)
    seen_links = set()
    candidates = []

    for keyword in query["keywords"]:
        if len(candidates) >= max_total:
            break
        lang = "ja" if re.search(r'[぀-鿿]', keyword) else "en"
        url = gnews(keyword, lang=lang)
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"    RSS取得エラー [{keyword[:40]}]: {e}")
            continue

        kw_count = 0
        for entry in parsed.entries:
            if kw_count >= max_per_kw or len(candidates) >= max_total:
                break
            link = entry.get("link", "")
            if link in seen_links:
                continue
            pub = entry.get("published_parsed")
            if pub and datetime(*pub[:6]) < cutoff:
                continue
            title = entry.get("title", "")
            if is_excluded(title):
                print(f"    除外: {title[:60]}")
                continue
            seen_links.add(link)
            candidates.append({
                "title": title,
                "link": link,
                "published": entry.get("published", "日付不明"),
                "rss_summary": entry.get("summary", ""),
            })
            kw_count += 1

    return candidates

# ---------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------
_PRIORITY_COLORS = {"★★★": "#c0392b", "★★": "#e67e22", "★": "#7f8c8d"}
_USAGE_BG = {"A+B": "#1a6b3c", "A": "#1a3a6b", "B": "#6b1a1a"}

def _e(s):
    return html.escape(str(s or ""))

def _article_row(no, article, analysis, query):
    priority = analysis.get("priority", query["priority"]) if analysis else query["priority"]
    pc = _PRIORITY_COLORS.get(priority, "#7f8c8d")
    usage = analysis.get("usage", "A") if analysis else "—"
    uc = _USAGE_BG.get(usage, "#444")
    core = _e(analysis.get("core_argument", "（AI評価なし）")) if analysis else "（AI評価不可）"
    summary_p = _e(analysis.get("summary_proposal", "")) if analysis else ""
    question_p = _e(analysis.get("question_proposal", "")) if analysis else ""
    p_note = _e(analysis.get("priority_note", "")) if analysis else ""

    p_note_html = (
        f'<tr><td style="padding:4px 0 0;vertical-align:top;">'
        f'<span style="font-size:10px;font-weight:bold;color:#c0392b;">優先調整</span></td>'
        f'<td style="padding:4px 0 0;font-size:11px;color:#c0392b;">{p_note}</td></tr>'
    ) if p_note else ""

    return f"""
<tr style="border-top:2px solid #e8e8e8;">
  <td style="padding:12px 8px;vertical-align:top;width:56px;text-align:center;">
    <div style="font-size:10px;color:#999;font-family:monospace;">{_e(no)}</div>
    <div style="font-size:14px;font-weight:bold;color:{pc};margin-top:3px;">{_e(priority)}</div>
    <div style="background:{uc};color:#fff;font-size:10px;font-weight:bold;
                padding:2px 4px;border-radius:3px;margin-top:4px;">{_e(usage)}</div>
    <div style="font-size:10px;color:#aaa;margin-top:4px;font-weight:bold;">{_e(query.get('tag',''))}</div>
  </td>
  <td style="padding:12px 8px;vertical-align:top;">
    <div style="font-size:13px;font-weight:bold;margin-bottom:3px;">
      <a href="{article['link']}" style="color:#1a1a2e;text-decoration:none;">{_e(article['title'])}</a>
    </div>
    <div style="font-size:11px;color:#aaa;margin-bottom:10px;">{_e(article['published'])}</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding-bottom:6px;vertical-align:top;width:70px;">
          <span style="font-size:10px;font-weight:bold;color:#555;">核心論点</span>
        </td>
        <td style="padding-bottom:6px;font-size:12px;color:#333;line-height:1.6;">{core}</td>
      </tr>
      <tr>
        <td style="padding-bottom:6px;vertical-align:top;">
          <span style="font-size:10px;font-weight:bold;color:#555;">サマリー活用</span>
        </td>
        <td style="padding-bottom:6px;font-size:12px;color:#444;">{summary_p}</td>
      </tr>
      <tr>
        <td style="padding-bottom:6px;vertical-align:top;">
          <span style="font-size:10px;font-weight:bold;color:#555;">設問活用</span>
        </td>
        <td style="padding-bottom:6px;font-size:12px;color:#444;">{question_p}</td>
      </tr>
      {p_note_html}
      <tr>
        <td style="vertical-align:top;padding-top:6px;">
          <span style="font-size:10px;font-weight:bold;color:#bbb;">幹事メモ</span>
        </td>
        <td style="padding-top:6px;font-size:12px;border-bottom:1px dashed #ddd;
                   min-height:18px;color:#ddd;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td>
      </tr>
    </table>
  </td>
</tr>"""

def _query_block(query, articles_with_analysis):
    label = _e(query["label"])
    theme = _e(query["theme"])
    tag = _e(query.get("tag", ""))
    base_priority = _e(query["priority"])

    rows_html = ""
    for idx, (article, analysis) in enumerate(articles_with_analysis):
        prefix = query["label"].split(":")[0].strip()
        no = f"{prefix}-{idx+1:03d}"
        rows_html += _article_row(no, article, analysis, query)

    if not rows_html:
        rows_html = '<tr><td colspan="2" style="padding:12px;color:#aaa;font-size:12px;">（該当記事なし）</td></tr>'

    return f"""
<tr>
  <td colspan="2" style="background:#2c3e50;color:#fff;padding:9px 14px;">
    <span style="font-size:11px;color:#95a5a6;">{label}</span>
    <span style="font-size:12px;font-weight:bold;margin-left:8px;">{theme}</span>
    <span style="float:right;font-size:11px;color:#95a5a6;">基本優先度 {base_priority}　タグ {tag}</span>
  </td>
</tr>
{rows_html}
<tr><td colspan="2" style="height:20px;"></td></tr>"""

def build_brief_html(session_results, generated_at, total_articles):
    sections_html = ""
    for session_label, queries_results in session_results:
        queries_html = ""
        for query, articles_with_analysis in queries_results:
            queries_html += _query_block(query, articles_with_analysis)

        if not queries_html:
            continue

        sl = _e(str(session_label))
        sections_html += f"""
<tr>
  <td colspan="2" style="background:#1a1a2e;color:#fff;padding:13px 16px;">
    <div style="font-size:15px;font-weight:bold;">
      第{sl}回セッション 補強素材
    </div>
  </td>
</tr>
{queries_html}"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#efefef;
             font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#efefef;padding:24px 0;">
    <tr><td align="center">
      <table width="720" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:6px;overflow:hidden;
                    box-shadow:0 1px 4px rgba(0,0,0,0.12);">
        <!-- ヘッダー -->
        <tr>
          <td colspan="2" style="background:#1a1a2e;padding:22px 24px;color:#fff;">
            <div style="font-size:11px;color:#7f8c8d;letter-spacing:1px;">
              近未来監査プロフェッション研究会
            </div>
            <div style="font-size:20px;font-weight:bold;margin-top:4px;">
              素材検討表
            </div>
            <div style="font-size:11px;color:#95a5a6;margin-top:6px;">
              {_e(generated_at)} 生成 ／ 全 {total_articles} 件
            </div>
          </td>
        </tr>
        <!-- 凡例 -->
        <tr>
          <td colspan="2" style="padding:10px 16px;background:#f8f8f8;
                                  border-bottom:1px solid #e0e0e0;">
            <span style="font-size:11px;color:#666;">
              用途：
              <span style="background:#1a3a6b;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;">A</span> サマリー素材
              <span style="background:#6b1a1a;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;margin-left:6px;">B</span> 設問素材
              <span style="background:#1a6b3c;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;margin-left:6px;">A+B</span> 両用
              &nbsp;&nbsp;|&nbsp;&nbsp;
              優先度：
              <span style="color:#c0392b;font-weight:bold;">★★★</span> 最優先
              <span style="color:#e67e22;font-weight:bold;margin-left:6px;">★★</span> 推奨
              <span style="color:#7f8c8d;font-weight:bold;margin-left:6px;">★</span> 参考
            </span>
          </td>
        </tr>
        <!-- 本文 -->
        <tr><td colspan="2" style="padding:0 14px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {sections_html}
          </table>
        </td></tr>
        <!-- フッター -->
        <tr>
          <td colspan="2" style="background:#f0f0f0;padding:12px 24px;
                                  font-size:11px;color:#aaa;text-align:center;">
            RSS Collector — 近未来監査プロフェッション研究会 素材検討表 自動生成
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
_PRIORITY_RANK = {"★★★": 3, "★★": 2, "★": 1}

def main():
    print(f"素材検討表ビルダー 開始: {datetime.now().strftime('%Y/%m/%d %H:%M')}\n")

    # 命題をセッション別に整理
    queries_by_session: dict = {}
    for q in ADDITIONAL_SEARCH_QUERIES:
        queries_by_session.setdefault(q["session"], []).append(q)

    session_results = []
    total_articles  = 0

    for session in SESSION_EXECUTION_ORDER:
        queries = queries_by_session.get(session, [])
        if not queries:
            continue

        print(f"{'='*60}")
        print(f"  セッション {session}")
        print(f"{'='*60}")

        queries_results = []
        for query in queries:
            print(f"\n  命題: {query['label']}")
            candidates = fetch_brief_articles(query)
            print(f"  候補: {len(candidates)} 件")

            if not candidates:
                queries_results.append((query, []))
                continue

            # 記事本文を並列取得
            with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as ex:
                bodies = list(ex.map(fetch_article_body, [c["link"] for c in candidates]))

            # AI 評価
            articles_with_analysis = []
            for c, body in zip(candidates, bodies):
                content = body if body else c["rss_summary"][:500]
                analysis = ai_analyze_brief(c["title"], content, query)
                articles_with_analysis.append((c, analysis))
                p = analysis.get("priority", "?") if analysis else "?"
                u = analysis.get("usage", "?") if analysis else "?"
                print(f"    [{p}][{u}] {c['title'][:60]}")

            # 優先度でソート（★★★ → ★★ → ★）
            articles_with_analysis.sort(
                key=lambda x: _PRIORITY_RANK.get(
                    x[1].get("priority", "★") if x[1] else "★", 1),
                reverse=True,
            )
            queries_results.append((query, articles_with_analysis))
            total_articles += len(articles_with_analysis)

        session_results.append((session, queries_results))

    print(f"\n{'='*60}")
    print(f"  合計 {total_articles} 件")
    print(f"{'='*60}\n")

    if total_articles == 0:
        print("記事が見つかりませんでした。")
        return

    generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    today        = datetime.now().strftime("%Y/%m/%d")
    html_body    = build_brief_html(session_results, generated_at, total_articles)
    subject      = f"【研究会 素材検討表】{today} — {total_articles}件"

    print(f"メール送信中: {subject}")
    try:
        send_email(html_body, subject)
        print("送信完了")
    except Exception as e:
        print(f"送信失敗: {e}")
        raise

if __name__ == "__main__":
    main()
