#!/usr/bin/env python3
"""
クライアント情報収集
client_config.py に定義された対象クライアント企業について、
Google News・各社IR・日経電子版・Financial Timesから関連ニュースを収集し、
Claude APIで要約・重要度判定・実務影響ポイントを生成してメール送信する。

既存の fetch_rss.py / RSS Daily Collector とは完全に独立して動作する
（キャッシュファイル・送信メールともに別系統）。
"""
import sys
import re
import io
import html
import json
import hashlib
import difflib
import smtplib
import ssl
import urllib.parse
import urllib.request
import feedparser
import anthropic
import pypdf
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from pathlib import Path

from config import EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_TO, ANTHROPIC_API_KEY, NIKKEI_COOKIE, FT_COOKIE
from client_config import CLIENTS

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEEN_FILE = Path(__file__).parent / "client_seen_articles.json"
SEEN_EXPIRE_DAYS = 30
DELIVERED_CACHE_FILE = Path(__file__).parent / "client_delivered_articles_cache.json"
TITLE_SIMILARITY_THRESHOLD = 0.9

SUMMARY_MAX_CHARS = 200
_BODY_MAX_CHARS = 3000
_BODY_MIN_CHARS = 300
_FETCH_TIMEOUT = 8
_PDF_MAX_BYTES = 5 * 1024 * 1024
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

def _make_ssl_context():
    """証明書チェーン検証・ホスト名検証は維持したまま、Python 3.13+ で既定有効化された
    VERIFY_X509_STRICT のみを外す。ローカル環境のアンチウイルス製品（Norton等）が
    HTTPS検査のため独自CA証明書を挿入している場合、その証明書のBasic Constraints
    拡張の形式不備（critical未設定）でハンドシェイクが失敗する既知の問題への対処。
    GitHub Actions等クリーンな証明書環境では実質無害（該当フラグが立っていれば外すだけ）。"""
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx

_SSL_CONTEXT = _make_ssl_context()

# ---------------------------------------------------------------
# Google News RSS URL 生成
# ---------------------------------------------------------------
_GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

def gnews(query, lang="en"):
    params = (dict(hl="ja", gl="JP", ceid="JP:ja") if lang == "ja"
              else dict(hl="en-US", gl="US", ceid="US:en"))
    return _GNEWS_BASE.format(query=urllib.parse.quote(query), **params)

# ---------------------------------------------------------------
# クライアントごとの収集ソース定義
# ---------------------------------------------------------------
def build_sources(client):
    name = client["name"]
    sources = [
        {"type": "gnews", "url": gnews(name, lang="ja"), "label": f"{name}（Google News 日本語）"},
        {"type": "gnews", "url": gnews(name, lang="en"), "label": f"{name}（Google News 英語）"},
        {"type": "gnews", "url": gnews(f"site:nikkei.com {name}", lang="ja"), "label": f"{name}（日経電子版）"},
        {"type": "gnews", "url": gnews(f"site:ft.com {name}", lang="en"), "label": f"{name}（Financial Times）"},
    ]
    if client.get("ir_rss"):
        sources.append({"type": "rss", "url": client["ir_rss"], "label": f"{name}（IR公式RSS）"})
    elif client.get("news_list_url"):
        sources.append({"type": "scrape", "url": client["news_list_url"], "label": f"{name}（IR/ニュース一覧）"})
    return sources

# ---------------------------------------------------------------
# Cookie付き記事本文取得（日経電子版・Financial Times の会員限定本文向け）
# ---------------------------------------------------------------
def _cookie_for(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    if host.endswith("nikkei.com") and NIKKEI_COOKIE:
        return NIKKEI_COOKIE
    if host.endswith("ft.com") and FT_COOKIE:
        return FT_COOKIE
    return None

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

def _extract_pdf_text(raw):
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""

def fetch_article_body(url):
    """記事URLから本文テキストを取得。失敗・ペイウォール時はNoneを返す。
    日経電子版／Financial Times のURLかつ対応するCookieが設定されている場合のみ、
    ログインセッションCookieを付与して会員限定本文の取得を試みる。
    IR開示PDF（適時開示等）へのリンクの場合はPDF本文を抽出する。"""
    try:
        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf",
            "Accept-Language": "ja,en;q=0.9",
        }
        cookie = _cookie_for(url)
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT, context=_SSL_CONTEXT) as resp:
            ct = resp.headers.get("Content-Type", "")
            is_pdf = "application/pdf" in ct or url.lower().endswith(".pdf")
            if not is_pdf and "text/html" not in ct:
                return None
            raw = resp.read(_PDF_MAX_BYTES if is_pdf else 512 * 1024)

        if is_pdf:
            body = _extract_pdf_text(raw)
        else:
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
# IR/ニュース一覧ページのスクレイピング（公式RSSがない企業向け）
# ---------------------------------------------------------------
# ナビゲーションメニューのリンクを拾わないよう、ページ内の「日付表記の直後に
# 現れるリンク」だけを記事エントリとみなす（多くのIRニュース一覧は
# 日付＋タイトルリンクの繰り返し構造になっているため）。
_DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})")
_ANCHOR_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_TO_ANCHOR_WINDOW = 600

def scrape_news_list(list_url, max_items=15):
    """公式RSSがない企業のIR/ニュース一覧ページから、お知らせ・PDFへのリンクを抽出する。
    ページ構造に依存しないベストエフォートの実装のため、サイト改修時は挙動が変わりうる。"""
    try:
        req = urllib.request.Request(
            list_url, headers={"User-Agent": _UA, "Accept-Language": "ja,en;q=0.9"}
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT, context=_SSL_CONTEXT) as resp:
            raw = resp.read(1024 * 1024)
            charset = resp.headers.get_content_charset("utf-8")
        html_str = raw.decode(charset, errors="replace")
    except Exception as e:
        print(f"    ニュース一覧取得エラー: {e}")
        return []

    list_netloc = urllib.parse.urlsplit(list_url).netloc
    items = []
    seen_links = set()
    for date_m in _DATE_RE.finditer(html_str):
        window = html_str[date_m.end(): date_m.end() + _DATE_TO_ANCHOR_WINDOW]
        anchor_m = _ANCHOR_RE.search(window)
        if not anchor_m:
            continue
        text = html.unescape(_TAG_RE.sub(" ", anchor_m.group(2)))
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) < 6:
            continue
        link = urllib.parse.urljoin(list_url, anchor_m.group(1))
        if urllib.parse.urlsplit(link).netloc != list_netloc:
            continue
        if link in seen_links:
            continue
        seen_links.add(link)
        y, mo, d = date_m.groups()
        published = f"{y}-{int(mo):02d}-{int(d):02d}"
        items.append({"title": text, "link": link, "published": published})
        if len(items) >= max_items:
            break
    return items

# ---------------------------------------------------------------
# 要旨テキストのクリーニング
# ---------------------------------------------------------------
def clean_summary(raw, max_chars=SUMMARY_MAX_CHARS):
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text or "（要旨なし）"

# ---------------------------------------------------------------
# 既読・配信済み管理（fetch_rss.py とは別ファイルで完全分離）
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

def mark_seen(articles: list, seen: dict):
    now = datetime.now().isoformat()
    for a in articles:
        seen[a["link"]] = now

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

def append_delivered(articles: list, cache: dict, delivered_date: str):
    delivered_entries = cache.setdefault("delivered", [])
    for a in articles:
        delivered_entries.append({
            "url":            a.get("link", ""),
            "title":          a.get("title", ""),
            "delivered_date": delivered_date,
        })

# ---------------------------------------------------------------
# Claude API による要約・重要度判定・実務影響ポイント生成
# ---------------------------------------------------------------
_ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

_CLIENT_SYSTEM_TEMPLATE = """あなたはクライアント企業担当者向けに、企業ニュースを要約し実務上の重要度を判定するアシスタントです。

【対象クライアント】
{name}（コア事業：{core_business}）

以下を必ずJSON形式で出力してください。

{{"summary": "（400文字以内の日本語要旨）", "importance": "高" または "中" または "低", "impact": "（実務影響ポイントを100文字程度で）"}}

【要旨のルール】
- 400文字以内の日本語でまとめる
- 日本語以外は日本語に翻訳する
- 前置きや説明は不要

【重要度の基準】
高: 業績・決算、M&A・資本業務提携、新製品・新技術、規制・許認可動向、経営陣交代、大型受注・契約など、クライアント対応に直結する重大な変化
中: 事業動向として把握しておくべき情報（競合動向、業界一般ニュース等）
低: 参考程度、コア事業との関連性が薄い情報

【実務影響ポイント】
このニュースが自社（クライアント担当者）の提案・リスク管理・関係構築にどう影響しうるかを簡潔に記載する。"""

def ai_analyze_client(client, title, content):
    if not _ai_client:
        return None
    system = _CLIENT_SYSTEM_TEMPLATE.format(name=client["name"], core_business=client["core_business"])
    prompt = f"タイトル: {title}\n\n内容: {content or '（内容なし）'}"
    try:
        response = _ai_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            summary = str(data.get("summary", "")).strip()
            importance = str(data.get("importance", "中")).strip()
            if importance not in ("高", "中", "低"):
                importance = "中"
            impact = str(data.get("impact", "")).strip()
            return summary, importance, impact
        return raw, "中", ""
    except Exception as e:
        return f"（要旨生成エラー: {e}）", "中", ""

# ---------------------------------------------------------------
# 記事取得
# ---------------------------------------------------------------
def fetch_source(client, source, days=30, max_items=8, delivered_cache=None, seen=None):
    cutoff = datetime.now() - timedelta(days=days)
    candidates = []

    if source["type"] in ("gnews", "rss"):
        try:
            parsed = feedparser.parse(
                source["url"],
                handlers=[urllib.request.HTTPSHandler(context=_SSL_CONTEXT)],
            )
        except Exception as e:
            print(f"エラー: {e}")
            return []
        for entry in parsed.entries:
            pub = entry.get("published_parsed")
            if pub and datetime(*pub[:6]) < cutoff:
                continue
            link = entry.get("link", "")
            if not link:
                continue
            title = entry.get("title", "（タイトルなし）")
            if source["type"] == "gnews":
                # Google News経由のみ、会社名バリエーションに一致しない結果をノイズとして除外
                text = (title + " " + entry.get("summary", "")).lower()
                if not any(kw.lower() in text for kw in client["name_keywords"]):
                    continue
            candidates.append({
                "title": title,
                "link": link,
                "published": entry.get("published", "日付不明"),
                "rss_summary": clean_summary(entry.get("summary", "")),
            })
            if len(candidates) >= max_items:
                break
    else:  # scrape
        for it in scrape_news_list(source["url"], max_items=max_items):
            candidates.append({
                "title": it["title"],
                "link": it["link"],
                "published": it["published"],
                "rss_summary": "",
            })

    if not candidates:
        return []

    if seen is not None:
        candidates = [c for c in candidates if c["link"] not in seen]
    if delivered_cache is not None:
        candidates = [
            c for c in candidates
            if not is_already_delivered(c, delivered_cache.get("delivered", []))
        ]
    if not candidates:
        return []

    with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as executor:
        bodies = list(executor.map(fetch_article_body, [c["link"] for c in candidates]))

    results = []
    for c, body in zip(candidates, bodies):
        content = body if body else c["rss_summary"]
        analysis = ai_analyze_client(client, c["title"], content)
        if analysis:
            summary, importance, impact = analysis
        else:
            summary, importance, impact = (c["rss_summary"] or "（要旨なし）"), "中", ""
        fetch_tag = "（全文取得）" if body else "（概要のみ）"
        results.append({
            "client":     client["name"],
            "source":     source["label"],
            "title":      c["title"],
            "link":       c["link"],
            "published":  c["published"],
            "summary":    summary + fetch_tag,
            "importance": importance,
            "impact":     impact,
            "article_id": hashlib.md5(c["link"].encode()).hexdigest()[:10],
        })
    return results

# ---------------------------------------------------------------
# HTML メール生成
# ---------------------------------------------------------------
_IMPORTANCE_COLORS = {"高": "#c0392b", "中": "#d69e2e", "低": "#95a5a6"}
_IMPORTANCE_ORDER  = {"高": 3, "中": 2, "低": 1}

def build_client_html(all_articles, generated_at):
    high_articles = [a for a in all_articles if a["importance"] == "高"]

    high_html = ""
    if high_articles:
        rows = ""
        for a in high_articles:
            rows += f"""
            <tr>
              <td style="padding:10px 16px; border-bottom:1px solid #f6dede;">
                <div style="font-size:11px; color:#c0392b; font-weight:bold;">
                  {html.escape(a['client'])} ／ {html.escape(a['source'])}
                </div>
                <div style="font-size:14px; font-weight:bold; margin:4px 0;">
                  <a href="{a['link']}" style="color:#1a1a1a; text-decoration:none;">{html.escape(a['title'])}</a>
                </div>
                <div style="font-size:12px; color:#666;">{html.escape(a['summary'])}</div>
              </td>
            </tr>"""
        high_html = f"""
        <tr>
          <td style="background:#c0392b; color:#fff; padding:10px 16px; font-size:13px; font-weight:bold;">
            重要度「高」— 即時確認推奨（{len(high_articles)}件）
          </td>
        </tr>
        {rows}
        <tr><td style="height:16px;"></td></tr>"""

    by_client = {}
    for a in all_articles:
        by_client.setdefault(a["client"], []).append(a)

    sections_html = ""
    for client_name, articles in by_client.items():
        articles = sorted(articles, key=lambda x: _IMPORTANCE_ORDER.get(x["importance"], 0), reverse=True)
        items_html = ""
        for a in articles:
            color = _IMPORTANCE_COLORS.get(a["importance"], "#718096")
            impact_html = (
                f'<div style="font-size:11px; color:#1e3a5f; margin-top:4px;">'
                f'<b>実務影響:</b> {html.escape(a["impact"])}</div>'
            ) if a.get("impact") else ""
            items_html += f"""
            <tr>
              <td style="padding:12px 16px; border-bottom:1px solid #eee; vertical-align:top;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                  <div style="font-size:11px; color:#666;">{html.escape(a['source'])}</div>
                  <div style="font-size:11px; color:{color}; font-weight:bold;">重要度: {a['importance']}</div>
                </div>
                <div style="font-size:14px; font-weight:bold; margin-bottom:6px;">
                  <a href="{a['link']}" style="color:#1a1a1a; text-decoration:none;">{html.escape(a['title'])}</a>
                </div>
                <div style="font-size:12px; color:#666;">{html.escape(a['summary'])}</div>
                {impact_html}
                <div style="font-size:11px; color:#999; margin-top:6px;">{html.escape(a['published'])}</div>
              </td>
            </tr>"""
        sections_html += f"""
        <tr>
          <td style="background:#1e3a5f; color:#fff; padding:10px 16px; font-size:13px; font-weight:bold; letter-spacing:0.5px;">
            {html.escape(client_name)}
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
        <tr>
          <td style="background:#0d1b2a; padding:24px 24px 20px; color:#fff;">
            <div style="font-size:20px; font-weight:bold;">クライアント情報レポート</div>
            <div style="font-size:12px; color:#aaa; margin-top:6px;">
              {generated_at} 生成 ／ 全 {len(all_articles)} 件
            </div>
          </td>
        </tr>
        <tr><td style="padding:16px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {high_html}
            {sections_html}
          </table>
        </td></tr>
        <tr>
          <td style="background:#f0f0f0; padding:12px 24px;
                     font-size:11px; color:#999; text-align:center;">
            RSS Collector — クライアント情報自動収集
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
    ai_mode = "有効（claude-haiku-4-5）" if _ai_client else "無効（APIキー未設定）"
    cookie_status = f"日経={'設定済' if NIKKEI_COOKIE else '未設定'} / FT={'設定済' if FT_COOKIE else '未設定'}"
    print(f"クライアント情報収集 開始: {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print(f"AI要旨生成: {ai_mode}")
    print(f"Cookie設定: {cookie_status}\n")

    seen = load_seen()
    delivered_cache = load_delivered_cache()

    all_articles = []
    for client in CLIENTS:
        print(f"\n▼ {client['name']}")
        print("-" * 60)
        for source in build_sources(client):
            print(f"  取得中: {source['label']} ...", end=" ", flush=True)
            articles = fetch_source(client, source, delivered_cache=delivered_cache, seen=seen)
            all_articles.extend(articles)
            print(f"{len(articles)} 件")

    print(f"\n{'=' * 60}")
    print(f"  合計 {len(all_articles)} 件")
    print(f"{'=' * 60}\n")

    if not all_articles:
        print("新着記事がないためメール送信をスキップします。")
        return

    for a in all_articles:
        print(f"\n[{a['client']}] {a['title']}")
        print(f"  ソース  : {a['source']}")
        print(f"  重要度  : {a['importance']}")
        print(f"  要旨    : {a['summary']}")
        if a.get("impact"):
            print(f"  実務影響: {a['impact']}")
        print(f"  リンク  : {a['link']}")

    generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    today        = datetime.now().strftime("%Y/%m/%d")
    html_body    = build_client_html(all_articles, generated_at)
    subject      = f"クライアント情報レポート - {today}"

    print(f"\nメール送信中: {subject}")
    try:
        send_email(html_body, subject)
        print("送信完了")
    except Exception as e:
        print(f"送信失敗: {e}")
        raise

    mark_seen(all_articles, seen)
    save_seen(seen)
    append_delivered(all_articles, delivered_cache, datetime.now().strftime("%Y-%m-%d"))
    save_delivered_cache(delivered_cache)

if __name__ == "__main__":
    main()
