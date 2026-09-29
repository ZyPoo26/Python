"""
Yapay zekâ ile detaylı şirket raporu (opsiyonel).

Botun topladığı tüm veriyi (bilanço, borç seyri, teknik görünüm, haberler,
karar motorunun sonucu) Claude'a verir; Claude isterse internette güncel
haber / KAP açıklaması / şirket duyurusu arar ve Türkçe bir rapor yazar:
şirket ne yapıyor, borç süreci, kârlılık, yaklaşan katalizörler, riskler,
senaryolar ve somut yol haritası.

ANTHROPIC_API_KEY tanımlı değilse bu modül devre dışıdır; bot yine çalışır.
"""

import html
import json
import logging

from config import ANTHROPIC_API_KEY, AI_MODEL, AI_WEB_SEARCH, AI_MAX_SEARCHES, get_profile

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """Telegram HTML için kaçış (tırnakları olduğu gibi bırakır)."""
    return html.escape(str(text), quote=False)

SYSTEM = """Sen bireysel yatırımcıya hisse analizi yapan, dürüst ve temkinli bir Türk finans analistisin.
Kullanıcı bir botun topladığı yapılandırılmış veriyi (JSON) ve haber başlıklarını verecek.

Kurallar:
- Sayıları SADECE verilen veriden ya da internette bulduğun kaynaklardan al. Rakam uydurma. Emin değilsen "veri yok" de.
- Verilen tutarlar "fin_currency" para birimindedir; hisse fiyatı "price_currency" cinsindendir. Bunları karıştırma.
- BIST şirketlerinde TL bazlı büyümeyi enflasyonla (inflation_adj alanı) kıyasla; nominal büyümeyi reel büyüme gibi sunma.
- Web araması yapabiliyorsan: şirketin son 6 aydaki önemli gelişmelerini (borçlanma/tahvil ihracı, borç yapılandırma,
  sermaye artırımı, yatırım, ihale, dava, yönetim değişikliği, KAP açıklamaları, sektör/regülasyon haberleri) ara.
- Bu bir yatırım tavsiyesi değildir; kesin kazanç vaadi ve "kesin yükselir" gibi ifadeler kullanma. Olasılık ve senaryo dili kullan.
- Botun kararına (advisor.verdict) katılmıyorsan nedenini açıkça yaz.

Çıktı: Telegram'da okunacak DÜZ METİN (Markdown, HTML, tablo YOK). En fazla ~3000 karakter. Başlıkları emoji ile ayır:
🏢 Şirket ne yapıyor (2-3 cümle)
💳 Borç ve finansal sağlık — süreç (borç nereden nereye geldi, nasıl finanse ediliyor, risk var mı)
📈 Kârlılık ve büyüme — süreç
🗓️ Önümüzdeki dönem: yaklaşan olaylar ve katalizörler
⚠️ Başlıca riskler
🔮 Senaryolar (olumlu / baz / olumsuz — her biri 1-2 cümle, ne olursa hangisi gerçekleşir)
🧭 Yol haritası (somut: şimdi ne yapılmalı, hangi seviye/olay takip edilmeli, ne olursa fikir değiştirilmeli)
En sonda kullandığın dış kaynakları kısa ad olarak listele (varsa)."""


def is_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _payload(ticker: str, tech: dict, fund: dict | None, news: dict | None,
             decision: dict, regime: dict | None, market: str | None) -> str:
    def clean(d):
        if d is None:
            return None
        out = {}
        for k, v in d.items():
            if isinstance(v, float):
                out[k] = round(v, 3)
            elif isinstance(v, (str, int, bool, list, dict)) or v is None:
                out[k] = v
        return out

    fund_c = clean(fund)
    if fund_c and fund:
        fund_c["events"] = [e["text"] for e in fund.get("events", [])]
    data = {
        "ticker": ticker,
        "market": get_profile(market)["label"],
        "fundamentals": fund_c,
        "technical": clean({k: v for k, v in tech.items() if k != "checks"}),
        "technical_checks": tech.get("checks"),
        "market_regime": regime,
        "news_headlines": [t for t, _ in (news or {}).get("examples", [])] + (news or {}).get("all_titles", []),
        "advisor": decision,
    }
    return json.dumps(data, ensure_ascii=False, default=str)


def generate_report(ticker: str, tech: dict, fund: dict | None, news: dict | None,
                    decision: dict, regime: dict | None = None, market: str | None = None) -> str | None:
    """Claude'dan Türkçe detaylı rapor ister. Hata/devre dışıysa None döner."""
    if not is_enabled():
        return None
    import anthropic

    prof = get_profile(market)
    name = (fund or {}).get("name", ticker)
    where = "KAP (kap.org.tr) ve Türk finans haber siteleri" if not prof["is_us"] else "SEC filings ve finans haber siteleri"
    prompt = (
        f"{name} ({ticker}, {prof['label']}) için rapor yaz. Güncel gelişmeler için {where} kaynaklarına bak.\n\n"
        f"Botun topladığı veri:\n{_payload(ticker, tech, fund, news, decision, regime, market)}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {}
    if AI_WEB_SEARCH:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": AI_MAX_SEARCHES}]

    messages = [{"role": "user", "content": prompt}]
    try:
        resp = None
        # Web araması uzun sürerse API "pause_turn" ile döner; aynı konuşmayı sürdürüyoruz.
        for _ in range(4):
            with client.beta.messages.stream(
                model=AI_MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **kwargs,
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                continue
            break
    except anthropic.AuthenticationError:
        logger.error("ANTHROPIC_API_KEY geçersiz.")
        return "⚠️ AI raporu alınamadı: ANTHROPIC_API_KEY geçersiz."
    except anthropic.RateLimitError:
        return "⚠️ AI raporu alınamadı: istek limiti aşıldı, biraz sonra tekrar dene."
    except anthropic.APIStatusError as e:
        logger.error(f"AI raporu API hatası: {e.status_code} {e.message}")
        return f"⚠️ AI raporu alınamadı (API hatası {e.status_code})."
    except anthropic.APIConnectionError:
        return "⚠️ AI raporu alınamadı: bağlantı hatası."

    if resp is None or resp.stop_reason == "refusal":
        return "⚠️ AI bu rapor isteğini yanıtlamadı."
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        return None
    return f"🤖 <b>AI Şirket Raporu: {_esc(name)}</b>\n━━━━━━━━━━━━━━━━━━━━\n{_esc(text)}"
