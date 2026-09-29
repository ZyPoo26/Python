"""
Temel (bilanço) analiz modülü.

Teknik analiz "NE ZAMAN" sorusuna bakar; bu modül "HANGİ ŞİRKET" sorusuna bakar.
yfinance'ten son 4-5 yıllık yıllık + son ~6 çeyreklik finansal tabloları çekip
şu başlıklarda puan (0-100) ve açıklama üretir:

  BORÇ      – Net borç/FAVÖK, borç/özkaynak, cari oran, faiz karşılama,
              borcun yıllar içindeki seyri (artıyor mu, azalıyor mu?)
  KÂRLILIK  – Net/faaliyet marjı, özkaynak kârlılığı (ROE), marj trendi
  BÜYÜME    – Satış ve net kâr büyümesi (yıllık + son çeyrek yıllık bazda)
  NAKİT     – Serbest nakit akışı, kâr kalitesi (faaliyet nakdi / net kâr)
  DEĞERLEME – F/K, PD/DD, FD/FAVÖK (döviz farkı düzeltilmiş)

Ayrıca: sermaye artırımı/sulanma, analist beklentisi ve yaklaşan olaylar
(bilanço tarihi, temettü) toplanır.

ÖNEMLİ: Bazı BIST şirketleri (örn. THYAO) finansallarını USD raporlar ama hisse
TL işlem görür. yfinance'in hazır F/K, PD/DD oranları bu durumda YANLIŞ çıkar.
Bu modül piyasa değerini finansal tablo para birimine çevirip oranları kendisi hesaplar.
"""

import logging
import math
from datetime import datetime, date

import pandas as pd
import yfinance as yf

from config import TR_INFLATION_PCT, get_profile

logger = logging.getLogger(__name__)

_cache: dict[str, dict[str, dict]] = {}


# ─── Yardımcılar ───────────────────────────────────────────────────────────────

def _row(df: pd.DataFrame, *names: str) -> pd.Series | None:
    """Tablodan ilk bulunan satırı (en yeni → en eski sıralı, NaN'sız) döner."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            s = pd.to_numeric(df.loc[n], errors="coerce").dropna()
            if not s.empty:
                return s.sort_index(ascending=False)
    return None


def _first(s: pd.Series | None, i: int = 0) -> float | None:
    if s is None or len(s) <= i:
        return None
    v = float(s.iloc[i])
    return None if math.isnan(v) else v


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def _cagr(new: float | None, old: float | None, years: int) -> float | None:
    if new is None or old is None or old <= 0 or new <= 0 or years <= 0:
        return None
    return ((new / old) ** (1 / years) - 1) * 100


def _ttm(q: pd.Series | None) -> float | None:
    """Son 4 çeyreğin toplamı (yıllıklandırılmış)."""
    if q is None or len(q) < 4:
        return None
    return float(q.iloc[:4].sum())


def _fx_rate(from_cur: str, to_cur: str) -> float | None:
    """1 birim from_cur kaç to_cur eder (örn. USD→TRY ≈ 49)."""
    if not from_cur or not to_cur or from_cur == to_cur:
        return 1.0
    try:
        h = yf.Ticker(f"{from_cur}{to_cur}=X").history(period="5d")
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception as e:
        logger.debug(f"Kur alınamadı {from_cur}{to_cur}: {e}")
    return None


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


# ─── Veri Toplama ──────────────────────────────────────────────────────────────

def collect(ticker: str, market: str | None = None) -> dict | None:
    """Şirketin ham finansal verisini ve hesaplanmış oranlarını toplar."""
    prof = get_profile(market)
    yf_ticker = f"{ticker}{prof['suffix']}" if prof["suffix"] and not ticker.endswith(prof["suffix"]) else ticker
    t = yf.Ticker(yf_ticker)
    try:
        info = t.info or {}
    except Exception as e:
        logger.debug(f"{ticker} info alınamadı: {e}")
        info = {}

    try:
        bs, inc, cf = t.balance_sheet, t.income_stmt, t.cashflow
        qbs, qinc, qcf = t.quarterly_balance_sheet, t.quarterly_income_stmt, t.quarterly_cashflow
    except Exception as e:
        logger.debug(f"{ticker} finansal tablolar alınamadı: {e}")
        return None
    if (inc is None or inc.empty) and (qinc is None or qinc.empty):
        return None

    fin_cur = info.get("financialCurrency") or info.get("currency")
    px_cur = info.get("currency")
    sector = info.get("sector") or ""
    is_financial = sector == "Financial Services" or "Bank" in (info.get("industry") or "") \
        or "Insurance" in (info.get("industry") or "")

    # ── Gelir tablosu (yıllık + çeyreklik) ──
    rev_y = _row(inc, "Total Revenue", "Operating Revenue")
    ni_y = _row(inc, "Net Income Common Stockholders", "Net Income")
    ebitda_y = _row(inc, "EBITDA", "Normalized EBITDA")
    ebit_y = _row(inc, "EBIT", "Operating Income")
    opinc_y = _row(inc, "Operating Income", "EBIT")
    int_y = _row(inc, "Interest Expense", "Interest Expense Non Operating")

    rev_q = _row(qinc, "Total Revenue", "Operating Revenue")
    ni_q = _row(qinc, "Net Income Common Stockholders", "Net Income")
    ebitda_q = _row(qinc, "EBITDA", "Normalized EBITDA")

    # Son 12 ay (TTM) varsa onu, yoksa son yıllığı kullan
    rev = _ttm(rev_q) or _first(rev_y)
    ni = _ttm(ni_q) if _ttm(ni_q) is not None else _first(ni_y)
    ebitda = _ttm(ebitda_q) or _first(ebitda_y)

    # ── Bilanço (en güncel çeyrek öncelikli) ──
    def latest(*names):
        return _first(_row(qbs, *names)) if _first(_row(qbs, *names)) is not None else _first(_row(bs, *names))

    total_debt = latest("Total Debt")
    cash = latest("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    equity = latest("Stockholders Equity", "Common Stock Equity")
    cur_assets = latest("Current Assets")
    cur_liab = latest("Current Liabilities")
    total_assets = latest("Total Assets")
    net_debt = (total_debt - cash) if total_debt is not None and cash is not None else latest("Net Debt")

    debt_hist = _row(bs, "Total Debt")          # yıllık borç seyri
    equity_hist = _row(bs, "Stockholders Equity", "Common Stock Equity")
    shares_hist = _row(bs, "Ordinary Shares Number", "Share Issued")

    # ── Nakit akışı ──
    fcf_y = _row(cf, "Free Cash Flow")
    ocf_y = _row(cf, "Operating Cash Flow")
    fcf_q = _row(qcf, "Free Cash Flow")
    ocf_q = _row(qcf, "Operating Cash Flow")
    fcf = _ttm(fcf_q) if _ttm(fcf_q) is not None else _first(fcf_y)
    ocf = _ttm(ocf_q) if _ttm(ocf_q) is not None else _first(ocf_y)

    # ── Değerleme: piyasa değerini tablo para birimine çevir ──
    mcap = info.get("marketCap")
    fx = _fx_rate(fin_cur, px_cur) if fin_cur and px_cur else 1.0
    mcap_fin = (mcap / fx) if mcap and fx else None
    pe = (mcap_fin / ni) if mcap_fin and ni and ni > 0 else None
    pb = (mcap_fin / equity) if mcap_fin and equity and equity > 0 else None
    ev = (mcap_fin + net_debt) if mcap_fin is not None and net_debt is not None else None
    ev_ebitda = (ev / ebitda) if ev and ebitda and ebitda > 0 else None
    fcf_yield = (fcf / mcap_fin * 100) if fcf is not None and mcap_fin else None

    # ── Oranlar ──
    d = {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": sector,
        "industry": info.get("industry") or "",
        "summary": (info.get("longBusinessSummary") or "")[:600],
        "is_financial": is_financial,
        "fin_currency": fin_cur,
        "price_currency": px_cur,
        "market": prof["market"],
        "last_report": str(qinc.columns.max().date()) if qinc is not None and not qinc.empty else None,

        "revenue_ttm": rev, "net_income_ttm": ni, "ebitda_ttm": ebitda, "fcf_ttm": fcf, "ocf_ttm": ocf,
        "total_debt": total_debt, "cash": cash, "net_debt": net_debt, "equity": equity,

        "net_debt_ebitda": (net_debt / ebitda) if net_debt is not None and ebitda and ebitda > 0 else None,
        "debt_equity": (total_debt / equity) if total_debt is not None and equity and equity > 0 else None,
        "current_ratio": (cur_assets / cur_liab) if cur_assets and cur_liab else None,
        "interest_cover": (_first(ebit_y) / abs(_first(int_y))) if _first(ebit_y) and _first(int_y) else None,
        "equity_ratio": (equity / total_assets * 100) if equity and total_assets else None,

        "net_margin": (ni / rev * 100) if ni is not None and rev else None,
        "op_margin": (_first(opinc_y) / _first(rev_y) * 100) if _first(opinc_y) is not None and _first(rev_y) else None,
        "op_margin_prev": (_first(opinc_y, 1) / _first(rev_y, 1) * 100) if _first(opinc_y, 1) is not None and _first(rev_y, 1) else None,
        "roe": (ni / equity * 100) if ni is not None and equity and equity > 0 else None,

        "rev_growth_y": _pct(_first(rev_y), _first(rev_y, 1)),
        "ni_growth_y": _pct(_first(ni_y), _first(ni_y, 1)),
        "rev_cagr_3y": _cagr(_first(rev_y), _first(rev_y, 3), 3),
        # Son çeyrek, geçen yılın aynı çeyreğine göre (mevsimsellikten arındırılmış)
        "rev_growth_q_yoy": _pct(_first(rev_q), _first(rev_q, 4)),
        "ni_growth_q_yoy": _pct(_first(ni_q), _first(ni_q, 4)),
        "ni_last_q": _first(ni_q),
        "ni_q_year_ago": _first(ni_q, 4),

        "debt_change_3y": _pct(_first(debt_hist), _first(debt_hist, 3)) if debt_hist is not None and len(debt_hist) > 3
                          else _pct(_first(debt_hist), _first(debt_hist, len(debt_hist) - 1)) if debt_hist is not None and len(debt_hist) > 1 else None,
        "debt_years": len(debt_hist) - 1 if debt_hist is not None else 0,
        "debt_hist": [round(v / 1e6) for v in debt_hist.iloc[:5]] if debt_hist is not None else [],
        "equity_change_3y": _pct(_first(equity_hist), _first(equity_hist, 3)) if equity_hist is not None and len(equity_hist) > 3 else None,
        "share_change_3y": _pct(_first(shares_hist), _first(shares_hist, 3)) if shares_hist is not None and len(shares_hist) > 3 else None,
        "fcf_positive_years": int((fcf_y.iloc[:4] > 0).sum()) if fcf_y is not None else None,
        "fcf_years": min(4, len(fcf_y)) if fcf_y is not None else 0,
        "earnings_quality": (ocf / ni) if ocf is not None and ni and ni > 0 else None,

        "pe": pe, "pb": pb, "ev_ebitda": ev_ebitda, "fcf_yield": fcf_yield,
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),   # yfinance bunu zaten yüzde verir

        "analyst_target": info.get("targetMeanPrice"),
        "analyst_rec": info.get("recommendationKey"),
        "analyst_count": info.get("numberOfAnalystOpinions") or 0,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }

    # ── Yaklaşan olaylar (bilanço, temettü) ──
    events = []
    try:
        cal = t.calendar or {}
        today = date.today()
        for ed in (cal.get("Earnings Date") or []):
            if isinstance(ed, date) and ed >= today:
                ev_txt = f"Bilanço açıklaması: {ed.strftime('%d.%m.%Y')} ({(ed - today).days} gün sonra)"
                if cal.get("Earnings Average"):
                    ev_txt += f" — beklenen HBK {cal['Earnings Average']:.2f}"
                events.append({"date": ed, "days": (ed - today).days, "type": "earnings", "text": ev_txt})
                break
        exd = cal.get("Ex-Dividend Date")
        if isinstance(exd, date) and exd >= today:
            events.append({"date": exd, "days": (exd - today).days, "type": "dividend",
                           "text": f"Temettü hak kesimi: {exd.strftime('%d.%m.%Y')}"})
    except Exception as e:
        logger.debug(f"{ticker} takvim alınamadı: {e}")
    d["events"] = events
    d["analyst"] = collect_analyst(t, info)
    return d


# ─── Analist (aracı kurum) görüşü ─────────────────────────────────────────────

# yfinance recommendationMean: 1 = Güçlü AL … 5 = SAT
MIN_ANALYSTS = 3   # bundan az analist varsa "kapsam yok" sayılır, karar etkilenmez


def collect_analyst(t: yf.Ticker, info: dict) -> dict | None:
    """
    Analist konsensüsünü döner. Kapsam yoksa None → karar motoru bu hisseyi
    analist verisi olmadan, diğer kriterlerle normal değerlendirir.
    """
    count = info.get("numberOfAnalystOpinions") or 0
    if count < MIN_ANALYSTS:
        return None
    mean = info.get("recommendationMean")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    tgt = info.get("targetMeanPrice")
    upside = (tgt / price - 1) * 100 if tgt and price else None
    res = {
        "count": count, "mean": None, "consensus": None, "basis": "öneri",
        "target": tgt, "target_high": info.get("targetHighPrice"), "target_low": info.get("targetLowPrice"),
        "upside": upside, "buy": None, "hold": None, "sell": None, "trend": None, "changes": [],
    }

    # AL / TUT / SAT dağılımı ve son 3 aydaki değişim
    try:
        rec = t.recommendations
        if rec is not None and not rec.empty and "period" in rec.columns:
            rec = rec.set_index("period")
            if "0m" in rec.index:
                now = rec.loc["0m"]
                sb, b, h = int(now.get("strongBuy", 0)), int(now.get("buy", 0)), int(now.get("hold", 0))
                se, ss = int(now.get("sell", 0)), int(now.get("strongSell", 0))
                res["buy"], res["hold"], res["sell"] = sb + b, h, se + ss
                total = sb + b + h + se + ss
                if mean is None and total:
                    # yfinance ortalamayı vermediyse dağılımdan hesapla (1=Güçlü AL … 5=SAT)
                    mean = (1 * sb + 2 * b + 3 * h + 4 * se + 5 * ss) / total
                if "-3m" in rec.index:
                    old = rec.loc["-3m"]
                    old_buy = int(old.get("strongBuy", 0) + old.get("buy", 0))
                    diff = res["buy"] - old_buy
                    if diff > 0:
                        res["trend"] = f"AL diyen analist sayısı 3 ayda {old_buy} → {res['buy']} (artıyor)"
                    elif diff < 0:
                        res["trend"] = f"AL diyen analist sayısı 3 ayda {old_buy} → {res['buy']} (azalıyor)"
    except Exception as e:
        logger.debug(f"Analist dağılımı alınamadı: {e}")

    if mean is not None:
        res["mean"] = round(mean, 2)
        consensus = "GÜÇLÜ AL" if mean <= 1.8 else "AL" if mean <= 2.5 else "TUT" if mean <= 3.3 else "SAT"
    elif upside is not None:
        # Öneri dağılımı yoksa sadece ortalama hedef fiyattaki potansiyele bak
        res["basis"] = "hedef fiyat"
        consensus = "AL" if upside >= 20 else "TUT" if upside >= 0 else "SAT"
    else:
        return None
    res["consensus"] = consensus

    # Son not değişiklikleri (çoğunlukla ABD hisselerinde dolu)
    try:
        ud = t.upgrades_downgrades
        if ud is not None and not ud.empty:
            ud = ud.sort_index(ascending=False)
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
            for when, row in ud.iterrows():
                if pd.Timestamp(when).tz_localize(None) < cutoff or len(res["changes"]) >= 3:
                    break
                act = {"up": "not yükseltti", "down": "not düşürdü", "init": "takibe başladı",
                       "main": "notunu korudu", "reit": "notunu teyit etti"}.get(str(row.get("Action")), str(row.get("Action")))
                txt = f"{row.get('Firm')} {act}: {row.get('ToGrade')}"
                if row.get("currentPriceTarget"):
                    txt += f" (hedef {row['currentPriceTarget']:.0f})"
                res["changes"].append(f"{pd.Timestamp(when):%d.%m} {txt}")
    except Exception as e:
        logger.debug(f"Not değişiklikleri alınamadı: {e}")

    res["is_buy"] = consensus in ("GÜÇLÜ AL", "AL") and (upside is None or upside > 0)
    return res


# ─── Puanlama ve Yorum ─────────────────────────────────────────────────────────

def _fmt(v: float | None, suffix: str = "", nd: int = 1) -> str:
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


def evaluate(d: dict) -> dict:
    """
    Ham veriyi 5 başlıkta puanlar (0-100) ve Türkçe artı/eksi maddeleri üretir.
    Her başlık 50 (nötr) puandan başlar; iyi göstergeler ekler, kötüler düşer.
    """
    pros: list[str] = []   # 🟢
    cons: list[str] = []   # 🔴
    story: list[str] = []  # süreç: şirket nereden nereye gidiyor

    fin = d["is_financial"]
    # Enflasyon: TL raporlayan BIST şirketinde nominal büyüme yanıltıcıdır.
    infl = TR_INFLATION_PCT if d["market"] == "BIST" and d["fin_currency"] == "TRY" else 0.0

    # ── 1. BORÇ / FİNANSAL SAĞLAMLIK ──
    debt = 50.0
    if fin:
        er = d["equity_ratio"]
        if er is not None:
            debt += 15 if er >= 12 else (0 if er >= 8 else -20)
            story.append(f"Banka/finans şirketi: özkaynak/aktif %{er:.1f} (borç oranları bankalarda anlamlı değildir)")
    else:
        nde = d["net_debt_ebitda"]
        if nde is not None:
            if nde < 0:
                debt += 30; pros.append(f"Net nakit pozisyonunda (borcundan fazla nakdi var)")
            elif nde < 1.5:
                debt += 20; pros.append(f"Borç yükü düşük: Net borç/FAVÖK {nde:.1f}x")
            elif nde < 3:
                debt += 0
            elif nde < 4.5:
                debt -= 20; cons.append(f"Borç yükü yüksek: Net borç/FAVÖK {nde:.1f}x (3x üstü dikkat)")
            else:
                debt -= 35; cons.append(f"Borç yükü ÇOK yüksek: Net borç/FAVÖK {nde:.1f}x")
        elif d["ebitda_ttm"] is not None and d["ebitda_ttm"] <= 0:
            debt -= 30; cons.append("FAVÖK negatif — şirket faaliyetinden borcunu ödeyecek nakit üretmiyor")

        cr = d["current_ratio"]
        if cr is not None:
            if cr < 0.8:
                debt -= 15; cons.append(f"Kısa vadeli likidite zayıf: cari oran {cr:.2f} (kısa vadeli borç > dönen varlık)")
            elif cr >= 1.5:
                debt += 10
        ic = d["interest_cover"]
        if ic is not None:
            if ic < 1.5:
                debt -= 20; cons.append(f"Faiz karşılama {ic:.1f}x — faaliyet kârı faiz giderini zor karşılıyor")
            elif ic > 6:
                debt += 10

        dc = d["debt_change_3y"]
        if dc is not None and d["debt_years"] >= 2:
            yrs = min(3, d["debt_years"])
            # Borç artışı kendi başına kötü değil; FAVÖK/özkaynak da büyüyorsa normal.
            eq_c = d["equity_change_3y"]
            real_dc = dc - infl * yrs
            if real_dc > 50 and (eq_c is None or dc > eq_c + 20):
                debt -= 15
                story.append(f"Borç son {yrs} yılda %{dc:+.0f} değişti, özkaynaktan hızlı büyüyor → borçlanarak büyüme")
            elif dc < -15:
                debt += 10
                story.append(f"Borç son {yrs} yılda %{dc:+.0f} azaldı → şirket borç azaltıyor (olumlu)")
            else:
                story.append(f"Borç son {yrs} yılda %{dc:+.0f} değişti (ölçülü)")

    # ── 2. KÂRLILIK ──
    prof = 50.0
    nm, roe = d["net_margin"], d["roe"]
    if d["net_income_ttm"] is not None and d["net_income_ttm"] < 0:
        prof -= 35; cons.append("Son 12 ayda ZARAR ediyor")
    elif nm is not None:
        prof += 15 if nm > 15 else (5 if nm > 5 else -5)
    if roe is not None:
        hurdle = infl + 5 if infl else 10   # TL'de ROE enflasyonu geçmeli
        if roe > hurdle + 10:
            prof += 20; pros.append(f"Yüksek özkaynak kârlılığı: ROE %{roe:.0f}")
        elif roe > hurdle:
            prof += 8
        elif roe > 0:
            prof -= 10
            if infl:
                cons.append(f"ROE %{roe:.0f} — enflasyonun (%{infl:.0f}) altında, reelde değer kaybettiriyor")
    om, omp = d["op_margin"], d["op_margin_prev"]
    if om is not None and omp is not None:
        if om - omp > 2:
            prof += 8; story.append(f"Faaliyet marjı genişliyor: %{omp:.1f} → %{om:.1f}")
        elif om - omp < -2:
            prof -= 8; story.append(f"Faaliyet marjı daralıyor: %{omp:.1f} → %{om:.1f}")

    # ── 3. BÜYÜME ──
    grow = 50.0
    rg = d["rev_growth_q_yoy"] if d["rev_growth_q_yoy"] is not None else d["rev_growth_y"]
    if rg is not None:
        real = rg - infl
        if real > 15:
            grow += 20; pros.append(f"Satışlar güçlü büyüyor: %{rg:+.0f} yıllık" + (" (enflasyon üstü)" if infl else ""))
        elif real > 3:
            grow += 8
        elif real < -5:
            grow -= 15; cons.append(f"Satışlar {'reelde ' if infl else ''}küçülüyor: %{rg:+.0f} yıllık"
                                    + (f" (enflasyon %{infl:.0f})" if infl else ""))
    ng = d["ni_growth_q_yoy"]
    ni_q_prev = d.get("ni_q_year_ago")
    if ni_q_prev is not None and ni_q_prev < 0:
        # Negatif tabandan yüzde değişim anlamsız; durumu sözle anlat.
        ng = None
        if (d["ni_last_q"] or 0) > 0:
            grow += 10; story.append("Son çeyrekte, geçen yılın aynı çeyreğindeki zarardan KÂRA geçti")
        elif d["ni_last_q"] is not None:
            story.append("Geçen yıl da bu çeyrekte zarar vardı; zarar sürüyor")
    if ng is not None:
        if ng > 25 and (d["ni_last_q"] or 0) > 0:
            grow += 15; story.append(f"Son çeyrek net kâr geçen yılın aynı çeyreğine göre %{ng:+.0f}")
        elif ng < -30:
            grow -= 15; cons.append(f"Son çeyrek net kâr sert düştü: %{ng:+.0f} (yıllık bazda)")
    if d["rev_cagr_3y"] is not None:
        story.append(f"3 yıllık ortalama satış büyümesi: %{d['rev_cagr_3y']:.0f}/yıl ({d['fin_currency']} bazında)")

    # ── 4. NAKİT AKIŞI ──
    cash_s = 50.0
    if not fin:
        fcf = d["fcf_ttm"]
        if fcf is not None:
            if fcf > 0:
                cash_s += 15
            else:
                cash_s -= 20; cons.append("Serbest nakit akışı negatif — yatırım/borç için dış finansmana muhtaç")
        py, ny = d["fcf_positive_years"], d["fcf_years"]
        if py is not None and ny >= 3:
            if py == ny:
                cash_s += 10; pros.append(f"Son {ny} yılın hepsinde pozitif serbest nakit akışı")
            elif py <= 1:
                cash_s -= 10
        eq = d["earnings_quality"]
        if eq is not None:
            if eq < 0.5:
                cash_s -= 15; cons.append(f"Kâr kalitesi düşük: faaliyet nakdi net kârın sadece {eq:.1f} katı (kâr nakde dönmüyor)")
            elif eq > 1:
                cash_s += 10

    sc = d["share_change_3y"]
    if sc is not None and sc > 15:
        cash_s -= 10
        cons.append(f"Hisse sayısı 3 yılda %{sc:+.0f} arttı (sermaye artırımı → ortak payı sulanıyor)")

    # ── 5. DEĞERLEME ──
    val = 50.0
    pe, pb, eve = d["pe"], d["pb"], d["ev_ebitda"]
    # TL'de enflasyon nedeniyle çarpanlar düşük seyreder; eşikleri market'e göre kaydır.
    pe_cheap, pe_exp = (6, 20) if infl else (15, 35)
    if pe is not None:
        if pe < pe_cheap:
            val += 20; pros.append(f"Ucuz görünüyor: F/K {pe:.1f}")
        elif pe > pe_exp:
            val -= 20; cons.append(f"Pahalı: F/K {pe:.1f}")
    if eve is not None and not fin:
        val += 10 if eve < (5 if infl else 10) else (-10 if eve > (15 if infl else 25) else 0)
    if pb is not None and fin:
        val += 10 if pb < 1.2 else (-10 if pb > 3 else 0)
    fy = d["fcf_yield"]
    if fy is not None and fy > 8:
        val += 10

    # Analist görüşü şirket puanına KATILMAZ; ayrı bir katman olarak kararda kullanılır.
    up = (d.get("analyst") or {}).get("upside")

    scores = {
        "borc": _clamp(debt), "karlilik": _clamp(prof), "buyume": _clamp(grow),
        "nakit": _clamp(cash_s), "degerleme": _clamp(val),
    }
    weights = {"borc": 0.28, "karlilik": 0.24, "buyume": 0.18, "nakit": 0.15, "degerleme": 0.15}
    total = sum(scores[k] * w for k, w in weights.items())

    if total >= 65:
        label, emoji = "SAĞLAM", "🟢"
    elif total >= 45:
        label, emoji = "ORTA", "🟡"
    else:
        label, emoji = "ZAYIF", "🔴"

    return {
        **d,
        "scores": {k: round(v) for k, v in scores.items()},
        "total": round(total),
        "label": label,
        "emoji": emoji,
        "pros": pros,
        "cons": cons,
        "story": story,
        "analyst_upside": up,
        "inflation_adj": infl,
    }


def get_fundamentals(ticker: str, market: str | None = None) -> dict | None:
    """Temel analiz sonucunu döner (gün içi cache'li). Veri yoksa None."""
    today = datetime.now().strftime("%Y-%m-%d")
    for k in list(_cache):
        if k != today:
            del _cache[k]
    _cache.setdefault(today, {})
    key = f"{market or ''}:{ticker}"
    if key in _cache[today]:
        return _cache[today][key]
    res = None
    try:
        raw = collect(ticker, market)
        if raw:
            res = evaluate(raw)
    except Exception as e:
        logger.warning(f"{ticker} temel analiz hatası: {e}")
    _cache[today][key] = res
    return res


def fmt_money(v: float | None, cur: str | None) -> str:
    """Büyük tutarları okunaklı yazar: 19.6 mlr USD."""
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} mlr"
    elif a >= 1e6:
        s = f"{v / 1e6:.0f} mn"
    else:
        s = f"{v:,.0f}"
    return f"{s} {cur or ''}".strip()
