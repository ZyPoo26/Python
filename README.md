# 📊 Borsa Analiz Botu

BIST 100 ve ABD (S&P 500) hisselerini teknik göstergeler, backtest ve haber analiziyle
tarayıp **alım sinyali adaylarını** Telegram'a gönderen bir Python botu.

GitHub Actions ile **7/24 otomatik** çalışır (bilgisayar kapalıyken bile), ayrıca
**interaktif** kullanılabilir: Telegram'a hisse kodu yazarsın, anlık analizini alırsın.

---

## ⚠️ Önemli Uyarı

> Bu yazılım **yatırım tavsiyesi değildir** ve **garantili kâr vaat etmez.**
> Ürettiği sinyaller geçmiş verilere dayalı **karar destek** amaçlıdır; geleceği öngörmez.
> Kısa vadeli fiyat hareketleri tahmin edilemez. Gerçek parayla işlem yapmadan önce
> sinyalleri bir süre kâğıt üzerinde takip edin ve **kendi araştırmanızı yapın.**
> Tüm sorumluluk kullanıcıya aittir.

---

## ✨ Özellikler

- **Karar motoru (yol gösterici):** Teknik + temel + haber + backtest + genel piyasa yönü birleştirilip net karar verilir:
  🟢 AL ADAYI · 🟡 TEMKİNLİ AL · 🟠 SPEKÜLATİF · 👀 İZLE · 🔴 UZAK DUR — ve adım adım **yol haritası** (giriş, pozisyon büyüklüğü, stop, takip edilecek olaylar, tezi bozan koşullar)
- **Temel (bilanço) analiz:** 5 yıllık bilanço + son çeyrekler → borç yükü ve **borcun seyri**, likidite, faiz karşılama, kârlılık/marj trendi, büyüme (TL'de enflasyon düzeltmeli), serbest nakit akışı, sermaye artırımı/sulanma, F/K–PD/DD–FD/FAVÖK (döviz raporlayan şirketlerde kur düzeltmeli), analist hedefi, yaklaşan bilanço/temettü tarihleri
- **Analist görüşü:** Aracı kurum konsensüsü (AL/TUT/SAT dağılımı, ortalama hedef ve potansiyel, son 3 aydaki değişim, not yükseltme/düşürme) + haberlerdeki "hedef fiyat / AL tavsiyesi" yorumları. Analistlerin de AL dediği sinyaller **ayrı grupta ve önce** gösterilir; analist kapsamı olmayan hisseler cezalandırılmaz, diğer kriterlerle aynı şekilde değerlendirilir
- **Anlık önemli haber bildirimi:** Takip listesindeki büyük şirketler + botun son 14 günde öne çıkardığı hisseler için 20 dakikada bir haber kontrolü. Sadece önemli olaylar (iflas/konkordato, soruşturma, birleşme/satın alma, sermaye artırımı, temettü, büyük ihale, bilanço, kredi notu, yönetim değişikliği…) bildirilir; rutin "günlük teknik analiz" haberleri elenir, aynı haber iki kez gelmez, aynı şirket için en fazla 4 saatte bir bildirim gelir (çok kritik haberler hariç)
- **Temel filtre:** Temeli zayıf şirketlerin teknik sinyalleri otomatik elenir (`MIN_FUNDAMENTAL_SCORE_FOR_ALERT`)
- **AI şirket raporu (opsiyonel):** `/rapor THYAO` → Claude internette güncel haber/KAP açıklamalarını tarayıp borç süreci, katalizörler, riskler, senaryolar ve yol haritası yazar (`ANTHROPIC_API_KEY` gerekir)
- **6 göstergeli teknik skor:** Ana trend (MA200), NVI (akıllı para), RSI, MACD, Bollinger ve hacim → 0–6 puan
- **İz süren stop:** Sabit hedef yerine fiyat yükseldikçe yukarı kayan stop (backtest'te sabit hedefe göre belirgin daha iyi)
- **Backtest motoru:** Stratejinin geçmiş performansı — isabet oranı, **komisyon dahil** getiri, **maksimum drawdown**, **Sharpe oranı**, al-tut karşılaştırması
- **Güvenilirlik etiketi:** Her sinyalde 🟢 YÜKSEK / 🟡 ORTA / 🔴 DÜŞÜK (backtest'e dayalı)
- **Haber analizi:** Google News'ten canlı başlık çekip duygu (sentiment) puanlaması (Türkçe + İngilizce)
- **Risk yönetimi:** Pozisyon büyüklüğü ve sektör dağılımı hatırlatmaları
- **İki market:** BIST 100 ve ABD (S&P 500) — ayrı çalışır, otomatik para birimi ($/TL)
- **Telegram:** Otomatik bildirim + interaktif sorgu (hisse kodu yaz, analiz al)

---

## 🚀 Kurulum

```bash
# 1. Gerekli kütüphaneleri yükle
pip install -r borsa_analiz/requirements.txt

# 2. .env dosyasını oluştur (örnekten kopyala)
cp borsa_analiz/.env.example borsa_analiz/.env

# 3. .env içine Telegram bilgilerini yaz:
#    TELEGRAM_BOT_TOKEN=...   (@BotFather'dan alınır)
#    TELEGRAM_CHAT_ID=...     (@userinfobot'tan alınır)
```

---

## 📖 Kullanım

```bash
cd borsa_analiz

# Önemli şirket haberlerini şimdi kontrol et (normalde GitHub Actions 20 dk'da bir yapar)
python main.py --news

# Telegram bağlantısını test et
python main.py --test

# Tek seferlik tarama (tüm listeyi tara, sinyalleri gönder)
python main.py --once

# Belirli hisseleri backtest et
python main.py --backtest THYAO GARAN ASELS

# Sürekli çalış (piyasa saatlerinde saat başı otomatik tarama)
python main.py

# ABD borsasını tara (varsayılan BIST)
MARKET=US python main.py --once
```

### İnteraktif Bot (anlık sorgu)

```bash
python telegram_bot.py
```

Çalışınca Telegram'a şunları yazabilirsin (BIST/ABD otomatik algılanır):

| Yazdığın | Sonuç |
|---|---|
| `THYAO` veya `AAPL` | Karar + şirket sağlığı + teknik + yol haritası |
| `/analiz GARAN` | Aynı şey |
| `/temel ASELS` | Sadece bilanço / borç / kârlılık analizi |
| `/rapor THYAO` | Tam analiz + yapay zekâ detaylı şirket raporu |
| `/tara` | Tüm listeyi tara |
| `/durum` | Bot aktif mi? |
| `/yardim` | Komut listesi |

---

## 🤖 7/24 Otomatik Çalışma (GitHub Actions)

`.github/workflows/` altında iki hazır workflow var:

- `run_bot.yml` → BIST, hafta içi TR 10:00–17:00 saat başı
- `run_bot_us.yml` → ABD, ABD borsa saatlerinde

**Kurulum:**
1. Repo → **Settings → Secrets and variables → Actions**
2. İki secret ekle: `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID`
3. **Settings → Actions → General → Workflow permissions → "Read and write"** seç
4. **Actions** sekmesinden workflow'u etkinleştir

> Not: GitHub Actions cron'u garanti dakik değildir; ±10–30 dk gecikebilir.

---

## 🧠 Sinyal Mantığı

Her hisse 6 göstergeden puan alır:

| Gösterge | Anlamı |
|---|---|
| NVI > EMA | Düşük hacimli günlerde "akıllı para" alıyor (kurumsal birikim) |
| NVI yükseliyor | Birikim ivme kazanıyor |
| RSI ideal bölge | Aşırı satımdan toparlanma |
| MACD | Momentum yukarı dönüyor |
| Bollinger | Fiyat dip bölgesinde |
| Hacim artışı | Hacim + fiyat birlikte yükseliyor |

**3+ puan** alan hisseler "alım sinyali" olarak Telegram'a gönderilir.

---

## 🔒 Güvenlik

- **`.env` dosyasını ASLA commit etmeyin** — token içerir (`.gitignore`'da tanımlı)
- Token'ı sadece **GitHub Secrets** ve lokal `.env`'de tutun
- Token sızarsa `@BotFather` → `/revoke` ile hemen yenileyin

---

## 📁 Proje Yapısı

```
borsa_analiz/
├── main.py              # Orkestratör + zamanlayıcı (--once / --backtest / --test)
├── config.py            # Tüm ayarlar + market profili (BIST/US)
├── scraper.py           # Hisse listesi + yfinance veri çekme
├── analyzer.py          # Teknik göstergeler + ATR stop/hedef
├── backtest.py          # Backtest + güvenilirlik (komisyon, drawdown, Sharpe)
├── news_analyzer.py     # Google News sentiment analizi
├── telegram_notifier.py # Telegram mesaj biçimleme + gönderme
├── telegram_bot.py      # İnteraktif bot (anlık sorgu)
└── requirements.txt
```

---

## 🛠️ Teknolojiler

Python · yfinance · pandas · numpy · BeautifulSoup · Telegram Bot API · GitHub Actions

---

*Bu proje eğitim ve kişisel kullanım amaçlıdır. Yatırım kararlarınızın sorumluluğu size aittir.*
