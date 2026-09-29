"""
Telegram bot modülü.
Bot token ve chat ID .env dosyasından okunur.
"""

import html
import requests
import logging
from datetime import datetime
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MAX_POSITIONS, MAX_SECTOR_PCT,
    MIN_SCORE_TO_BUY_ALERT, MIN_SCORE_TO_WATCH_ALERT,
    EXIT_MODE,
    get_profile,
)

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """Telegram HTML için kaçış (tırnakları olduğu gibi bırakır)."""
    return html.escape(str(text), quote=False)

TELEGRAM_LIMIT = 4000   # Telegram üst sınırı 4096; biraz pay bırakıyoruz


def fmt_price(value: float, market: str | None = None) -> str:
    """Fiyatı market para birimiyle biçimler: '$297.53' veya '142.20 TL'."""
    prof = get_profile(market)
    if prof["currency_prefix"]:
        return f"{prof['currency']}{value:.2f}"
    return f"{value:.2f} {prof['currency']}"


def _split(text: str) -> list[str]:
    """Uzun mesajı satır sınırlarından parçalara böler."""
    if len(text) <= TELEGRAM_LIMIT:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > TELEGRAM_LIMIT:          # tek satır bile uzunsa sert kes
            parts.append(cur + line[:TELEGRAM_LIMIT - len(cur)])
            line, cur = line[TELEGRAM_LIMIT - len(cur):], ""
        if len(cur) + len(line) + 1 > TELEGRAM_LIMIT:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def send_message(text: str) -> bool:
    """Telegram'a mesaj gönderir (gerekirse parçalayarak). Başarılıysa True döner."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID .env dosyasında tanımlı değil!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    ok = True
    for part in _split(text):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": part, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 400:
                # HTML biçimi bozuksa mesajı kaybetmemek için düz metin olarak tekrar dene
                logger.warning(f"Telegram HTML hatası, düz metin deneniyor: {resp.text[:200]}")
                payload.pop("parse_mode")
                resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Telegram mesaj gönderilemedi: {e}")
            ok = False
    return ok


def _score_bar(score: int, max_score: int) -> str:
    filled = "█" * score
    empty = "░" * (max_score - score)
    return f"{filled}{empty} {score}/{max_score}"


def _check_icon(val: bool) -> str:
    return "✅" if val else "❌"


def _pillar_bar(v: int) -> str:
    n = round(v / 20)
    return "▰" * n + "▱" * (5 - n)


def format_fundamentals(fund: dict, detailed: bool = True) -> list[str]:
    """Temel analiz bölümü (satır listesi)."""
    from fundamentals import fmt_money
    s = fund["scores"]
    cur = fund["fin_currency"]
    lines = [
        f"── 🏦 Şirket Sağlığı: {fund['emoji']} <b>{fund['label']}</b> ({fund['total']}/100) ──",
        f"💳 Borç      {_pillar_bar(s['borc'])} {s['borc']}",
        f"💰 Kârlılık  {_pillar_bar(s['karlilik'])} {s['karlilik']}",
        f"🚀 Büyüme    {_pillar_bar(s['buyume'])} {s['buyume']}",
        f"💵 Nakit     {_pillar_bar(s['nakit'])} {s['nakit']}",
        f"🏷️ Değerleme {_pillar_bar(s['degerleme'])} {s['degerleme']}",
    ]
    if detailed:
        def f(v, suf="", nd=1):
            return "—" if v is None else f"{v:.{nd}f}{suf}"
        if fund["is_financial"]:
            lines.append(f"F/K {f(fund['pe'])} · PD/DD {f(fund['pb'], nd=2)} · ROE %{f(fund['roe'], nd=0)}")
        else:
            lines += [
                f"Toplam borç {fmt_money(fund['total_debt'], cur)} · Nakit {fmt_money(fund['cash'], cur)}",
                f"Net borç/FAVÖK {f(fund['net_debt_ebitda'], 'x')} · Cari oran {f(fund['current_ratio'], nd=2)}"
                f" · Faiz karşılama {f(fund['interest_cover'], 'x')}",
                f"F/K {f(fund['pe'])} · PD/DD {f(fund['pb'], nd=2)} · FD/FAVÖK {f(fund['ev_ebitda'])}"
                f" · ROE %{f(fund['roe'], nd=0)}",
            ]
        if fund.get("debt_hist") and len(fund["debt_hist"]) > 1:
            hist = " → ".join(f"{v:,}" for v in reversed(fund["debt_hist"]))
            lines.append(f"Borç seyri (yıllık, mn {cur}): {hist}")
        if cur and fund.get("price_currency") and cur != fund["price_currency"]:
            lines.append(f"<i>Not: Finansallar {cur} raporlanıyor, oranlar kur farkı düzeltilerek hesaplandı.</i>")
    for p in fund["pros"][:4]:
        lines.append(f"🟢 {_esc(p)}")
    for c in fund["cons"][:4]:
        lines.append(f"🔴 {_esc(c)}")
    if detailed:
        for st in fund["story"][:4]:
            lines.append(f"📜 {_esc(st)}")
    return lines


def format_analyst(fund: dict | None, news: dict | None = None) -> list[str]:
    """Analist / aracı kurum görüşü bölümü. Veri yoksa bunu açıkça söyler."""
    an = (fund or {}).get("analyst")
    calls = (news or {}).get("broker_calls", [])
    if not an and not calls:
        return ["── 🗣️ Analist Görüşü ──", "➖ Analist kapsamı yok (karar diğer kriterlerle verildi)"]
    lines = ["── 🗣️ Analist Görüşü ──"]
    if an:
        icon = {"GÜÇLÜ AL": "🟢🟢", "AL": "🟢", "TUT": "🟡", "SAT": "🔴"}[an["consensus"]]
        basis = f"ort. puan {an['mean']}/5" if an.get("mean") is not None else "hedef fiyata göre"
        lines.append(f"{icon} Konsensüs: <b>{an['consensus']}</b> ({an['count']} analist, {basis})")
        if an.get("buy") is not None:
            lines.append(f"   AL {an['buy']} · TUT {an['hold']} · SAT {an['sell']}")
        if an.get("target"):
            rng = ""
            if an.get("target_low") and an.get("target_high"):
                rng = f" (aralık {an['target_low']:.2f} – {an['target_high']:.2f})"
            up = f" → %{an['upside']:+.0f}" if an.get("upside") is not None else ""
            lines.append(f"🎯 Ortalama hedef {an['target']:.2f}{up}{rng}")
        if an.get("trend"):
            lines.append(f"📈 {_esc(an['trend'])}")
        for c in an.get("changes", [])[:3]:
            lines.append(f"   • {_esc(c)}")
    for title, d in calls[:2]:
        mark = {"+": "🟢", "-": "🔴"}.get(d, "⚪")
        lines.append(f"{mark} <i>{_esc(title[:90])}</i>")
    return lines


def format_decision(decision: dict) -> list[str]:
    lines = [f"🧭 <b>KARAR: {decision['emoji']} {decision['verdict']}</b>"]
    for r in decision["reasons"]:
        lines.append(f"   • {_esc(r)}")
    for w in decision["warnings"]:
        lines.append(f"   ⚠️ {_esc(w)}")
    return lines


def format_plan(decision: dict) -> list[str]:
    lines = ["── 🗺️ Yol Haritası ──"]
    for i, step in enumerate(decision["plan"], 1):
        lines.append(f"{i}. {_esc(step)}")
    return lines


def format_buy_signal(result: dict, reliability: dict | None = None, news: dict | None = None,
                      market: str | None = None, fund: dict | None = None,
                      decision: dict | None = None, regime: dict | None = None,
                      header: str | None = None) -> str:
    """Tek hisse için tam analiz kartı: karar → şirket sağlığı → teknik → plan."""
    checks = result["checks"]
    score = result["score"]
    max_score = result["max_score"]
    label = get_profile(market)["label"]
    name = f" — {_esc(fund['name'])}" if fund else ""

    if header is None:
        emoji = "🔥" if score >= 5 else ("📈" if score >= MIN_SCORE_TO_BUY_ALERT else "🔎")
        header = f"{emoji} <b>[{label}] {'ALIM SİNYALİ' if score >= MIN_SCORE_TO_BUY_ALERT else 'ANALİZ'}: {result['ticker']}</b>{name}"

    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 Fiyat: <b>{fmt_price(result['price'], market)}</b>"
        f"  (52h: {fmt_price(result['low_52w'], market)} – {fmt_price(result['high_52w'], market)})",
    ]
    if decision:
        lines += [""] + format_decision(decision)

    if fund:
        lines += [""] + format_fundamentals(fund, detailed=True)
    lines += [""] + format_analyst(fund, news)

    lines += ["", f"── 📊 Teknik Görünüm: {_score_bar(score, max_score)} ──"]
    if reliability:
        lines.append(f"🎖️ Geçmiş başarı: {reliability['emoji']} <b>{reliability['label']}</b>")
        lines.append(f"   <i>{_esc(reliability['detail'])}</i>")
    lines += [
        f"{_check_icon(checks['trend_ok'])} Ana trend (MA200 üstü)",
        f"{_check_icon(checks['nvi_bullish'])} Akıllı para (NVI)",
        f"{_check_icon(checks['rsi_signal'])} RSI {result['rsi']}",
        f"{_check_icon(checks['macd_signal'])} MACD",
        f"{_check_icon(checks['bb_signal'])} Bollinger dip bölgesi",
        f"{_check_icon(checks['vol_signal'])} Hacim {result['vol_ratio']:.1f}x",
        f"📅 10g momentum {result['momentum_10d']:+.1f}% · kısa trend {result['trend']}",
    ]
    if regime:
        lines.append(f"🌍 {_esc(regime['text'])}")

    if news and news.get("total_headlines", 0) > 0:
        lines.append(f"📰 Haber havası: {news['emoji']} <b>{news['label']}</b> (+{news['positive']}/-{news['negative']})")
        for title, direction in news.get("examples", [])[:2]:
            mark = "🟢" if direction == "+" else "🔴"
            lines.append(f"   {mark} <i>{_esc(title[:80])}</i>")

    lines += [""]
    if decision:
        lines += format_plan(decision)
    else:
        stop_txt = "ilk stop (iz süren)" if EXIT_MODE == "trailing" else "stop"
        lines += [
            f"🛑 {stop_txt}: {fmt_price(result['stop_loss'], market)} ({result['stop_pct']:+.1f}%)",
            f"🎯 referans hedef: {fmt_price(result['target'], market)} ({result['target_pct']:+.1f}%)",
        ]
    lines += [
        f"💼 Aynı anda en fazla {MAX_POSITIONS} hisse · tek sektöre en fazla %{MAX_SECTOR_PCT}",
        "",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "⚠️ <i>Bilgi amaçlıdır, yatırım tavsiyesi değildir. Stop-loss'a mutlaka uy.</i>",
    ]
    return "\n".join(lines)


def format_fund_only(fund: dict, market: str | None = None) -> str:
    """/temel komutu: sadece şirket sağlığı raporu."""
    label = get_profile(market)["label"]
    lines = [
        f"🏦 <b>[{label}] TEMEL ANALİZ: {fund['ticker']}</b> — {_esc(fund['name'])}",
        f"<i>{_esc(fund['sector'])} / {_esc(fund['industry'])}"
        f" · son finansal: {fund.get('last_report') or '—'}</i>",
        "━━━━━━━━━━━━━━━━━━━━",
    ] + format_fundamentals(fund, detailed=True)
    lines += [""] + format_analyst(fund)
    if fund.get("events"):
        lines += ["", "🗓️ <b>Yaklaşan olaylar</b>"] + [f"• {e['text']}" for e in fund["events"]]
    if fund.get("inflation_adj"):
        lines.append(f"\n<i>TL büyüme/ROE, %{fund['inflation_adj']:.0f} enflasyonla kıyaslandı (config: TR_INFLATION_PCT).</i>")
    return "\n".join(lines)


def format_watch_signal(result: dict, market: str | None = None) -> str:
    checks = result["checks"]
    lines = [
        f"👀 <b>İZLE: {result['ticker']}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 Fiyat       : {fmt_price(result['price'], market)}",
        f"📊 Sinyal Puanı: {_score_bar(result['score'], result['max_score'])}",
        f"📉 NVI         : {'Birikim var ✅' if checks['nvi_bullish'] else 'Birikim yok ❌'}",
        f"📊 RSI         : {result['rsi']}",
        f"📅 Momentum 10g: {result['momentum_10d']:+.2f}%",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    ]
    return "\n".join(lines)


def format_summary(results: list[dict], total_scanned: int, regime: dict | None = None,
                   filtered: list[tuple[str, str]] | None = None,
                   analysts: dict[str, dict | None] | None = None) -> str:
    """analysts: {ticker: analist dict | None} — sinyalleri analist görüşüne göre gruplar."""
    buy_signals = [r for r in results if r["score"] >= MIN_SCORE_TO_BUY_ALERT]
    watch_signals = [r for r in results if r["score"] == MIN_SCORE_TO_WATCH_ALERT]
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    lines = [
        f"📊 <b>[{get_profile()['label']}] BORSA ANALİZ RAPORU</b>",
        f"🕐 {now}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if regime:
        lines.append(f"🌍 {_esc(regime['text'])}")
    lines += [
        f"🔍 Taranan hisse    : {total_scanned}",
        f"📈 Teknik sinyal    : {len(buy_signals)} hisse",
        f"👀 İzleme listesi   : {len(watch_signals)} hisse",
        "",
    ]
    if buy_signals:
        analysts = analysts or {}
        backed = [r for r in buy_signals if (analysts.get(r["ticker"]) or {}).get("is_buy")]
        others = [r for r in buy_signals if r not in backed]

        def row(r):
            an = analysts.get(r["ticker"])
            if not an:
                tag = " · analist kapsamı yok"
            else:
                tag = f" · analist {an['consensus']} ({an['count']})"
                if an["consensus"] in ("GÜÇLÜ AL", "AL") and not an.get("is_buy"):
                    tag += ", fiyat hedefi aşmış"
            return f"  • <b>{r['ticker']}</b> {_score_bar(r['score'], r['max_score'])} — {fmt_price(r['price'])}{tag}"

        if backed:
            lines.append("✅ <b>Analistlerin de AL dediği sinyaller:</b>")
            lines += [row(r) for r in backed[:6]]
        if others:
            lines.append("🔥 <b>Diğer teknik sinyaller:</b>" if backed else "🔥 <b>En güçlü teknik sinyaller:</b>")
            lines += [row(r) for r in others[:6]]
    if filtered:
        lines.append("")
        lines.append("🚫 <b>Temeli zayıf olduğu için elenen sinyaller:</b>")
        for t, why in filtered[:5]:
            lines.append(f"  • {t}: {_esc(why)}")
    lines += [
        "",
        "⚠️ <i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>",
    ]
    return "\n".join(lines)
