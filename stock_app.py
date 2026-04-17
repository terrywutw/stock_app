"""
投資戰情室 v13 - 精簡優化版
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os

# 自動載入 .env（若存在）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv 未安裝時略過，改用介面輸入

# ─────────────────────────────────────────────
# 0. 全域設定
# ─────────────────────────────────────────────
STOCKS = {
    "2330":   {"label": "台積電",         "symbol": "2330.TW",   "pledge_rate": 0.6},
    "0050":   {"label": "元大50",         "symbol": "0050.TW",   "pledge_rate": 0.7},
    "0052":   {"label": "富邦科技",       "symbol": "0052.TW",   "pledge_rate": 0.6},
    "00981A": {"label": "統一增長主動型", "symbol": "00981A.TW", "pledge_rate": 0.5},
}
INDEX_SYMBOL   = {"大盤": "^TWII"}
MARGIN_DANGER  = 130
MARGIN_WARNING = 160
CONFIG_FILE    = "stock_config_v13.json"

# ─────────────────────────────────────────────
# 1. 頁面設定 & CSS
# ─────────────────────────────────────────────
st.set_page_config(page_title="投資戰情室", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
[data-testid="stMetricDelta"] svg { display: none !important; }

.ma-container {
    background-color: #f0f3f8;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid #dce3ee;
    margin-top: 6px;
}
.ma-row {
    font-size: 0.80rem;
    margin-bottom: 3px;
    padding-bottom: 3px;
    border-bottom: 1px solid #dce3ee;
    color: #000000;
    font-weight: 500;
}
.ma-row:last-child { border-bottom: none; margin-bottom: 0; }

.sim-card {
    background: linear-gradient(135deg, #1a2540, #0f1928);
    border: 1px solid #2d4a7a;
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 10px;
}
.sim-title { color: #7eb3ff; font-size: 0.85rem; margin-bottom: 4px; }
.sim-value { color: #ffffff; font-size: 1.6rem; font-weight: 700; }
.sim-sub   { color: #8fa8c8; font-size: 0.78rem; margin-top: 2px; }

.margin-danger  { color: #ff4d4d !important; }
.margin-warning { color: #ffa94d !important; }
.margin-safe    { color: #51cf66 !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 2. 設定檔
# ─────────────────────────────────────────────
def _default_config() -> dict:
    base = {"loan_amount": 208}
    for k in STOCKS:
        base[f"cur_{k}"]     = 0
        base[f"pledged_{k}"] = 0
    return base

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults = _default_config()
            defaults.update(saved)
            return defaults
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            st.warning(f"⚠️ 設定檔讀取異常：{e}，已套用預設值。")
    return _default_config()

def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        st.error(f"❌ 儲存失敗：{e}")

init = load_config()

# ─────────────────────────────────────────────
# 3. 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📋 決策參數設定")

    with st.expander("💰 資金與現有持股", expanded=True):
        loan = st.number_input("目前總借款金額 (萬元)", value=float(init["loan_amount"]), step=1.0)
        st.markdown("<p style='font-size:0.78rem;color:#8fa8c8'>目前持有總張數</p>", unsafe_allow_html=True)
        cur = {
            k: st.number_input(f"{k} {STOCKS[k]['label']}", value=int(init.get(f"cur_{k}", 0)), key=f"cur_{k}")
            for k in STOCKS
        }

    with st.expander("🛡️ 質押現況", expanded=True):
        pledged = {
            k: st.number_input(f"已質押 {k}", value=int(init.get(f"pledged_{k}", 0)), key=f"p_{k}")
            for k in STOCKS
        }

    if st.button("💾 儲存並記憶目前參數", use_container_width=True):
        cfg = {"loan_amount": loan}
        for k in STOCKS:
            cfg[f"cur_{k}"]     = cur[k]
            cfg[f"pledged_{k}"] = pledged[k]
        save_config(cfg)
        st.success("✅ 參數已存檔！")

    st.divider()

    with st.expander("🏹 加碼模擬測試", expanded=True):
        buy = {k: st.number_input(f"加碼 {k}", value=0, key=f"b_{k}") for k in STOCKS}
        is_add_pledge = st.toggle("買入後是否馬上質押？", value=True)
        is_use_loan   = st.toggle("是否動用質押借款買入？", value=False)

# ─────────────────────────────────────────────
# 4. 市場資料（yfinance 批次下載）
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_market_data() -> dict:
    all_symbols = {**{k: v["symbol"] for k, v in STOCKS.items()}, **INDEX_SYMBOL}
    sym_to_name = {v: k for k, v in all_symbols.items()}
    symbols     = list(all_symbols.values())
    raw = yf.download(symbols, period="350d", group_by="ticker", auto_adjust=True, progress=False)

    result = {}
    for sym, name in sym_to_name.items():
        try:
            df = raw[sym].copy() if len(symbols) > 1 else raw.copy()
            df = df.dropna(subset=["Close"]).sort_index(ascending=True)

            for m in [5, 10, 20, 60, 120, 240]:
                df[f"MA{m}"] = df["Close"].rolling(m).mean()

            df["漲跌點"] = df["Close"].diff()
            df["幅%"]    = (df["漲跌點"] / df["Close"].shift(1)) * 100

            rng = df["High"] - df["Low"]
            df["買盤%"] = ((df["Close"] - df["Low"]) / rng.replace(0, pd.NA) * 100).fillna(50)
            df["賣盤%"] = 100 - df["買盤%"]
            df["買%"]   = df["買盤%"]

            df_out = df.sort_index(ascending=False).copy()
            df_out.index = df_out.index.strftime("%Y-%m-%d")
            result[name] = df_out
        except Exception as e:
            st.warning(f"⚠️ 無法取得 {name}（{sym}）：{e}")

    return result

with st.spinner("🔄 正在載入市場資料..."):
    data = get_market_data()

prices: dict = {
    k: float(data[k]["Close"].iloc[0]) if k in data else 0.0
    for k in STOCKS
}

# ─────────────────────────────────────────────
# 5. 維持率工具函式
# ─────────────────────────────────────────────
def calc_margin(pledged_qty: dict, loan_amt: float):
    val    = sum(prices.get(k, 0) * qty for k, qty in pledged_qty.items()) * 1000 / 1e4
    margin = (val / loan_amt * 100) if loan_amt > 0 else float("inf")
    return val, margin

def margin_css(m: float) -> str:
    if m < MARGIN_DANGER:  return "margin-danger"
    if m < MARGIN_WARNING: return "margin-warning"
    return "margin-safe"

def margin_emoji(m: float) -> str:
    if m < MARGIN_DANGER:  return "🔴"
    if m < MARGIN_WARNING: return "🟠"
    return "🟢"

# ─────────────────────────────────────────────
# 6. 主標題
# ─────────────────────────────────────────────
st.title("🛡️ 投資戰情室")
st.markdown(
    f"<p style='font-size:0.82rem;color:#8fa8c8;margin-top:-10px;'>"
    f"資料每 5 分鐘自動更新 · 維持率警示：🟠 &lt; {MARGIN_WARNING}%&nbsp;&nbsp;🔴 &lt; {MARGIN_DANGER}%</p>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# 7. 行情卡
# ─────────────────────────────────────────────
order  = ["大盤"] + list(STOCKS.keys())
m_cols = st.columns(len(order))

for i, name in enumerate(order):
    if name not in data:
        m_cols[i].warning(f"{name} 無資料")
        continue
    curr  = data[name].iloc[0]
    p     = float(curr["Close"])
    pct   = float(curr["幅%"])
    label = STOCKS[name]["label"] if name in STOCKS else "加權指數"
    title = f"{name} {label}" if name != "大盤" else "大盤 加權指數"

    with m_cols[i]:
        st.metric(title, f"{p:,.2f}", f"{pct:+.2f}%", delta_color="inverse")

        st.markdown("<div class='ma-container'>", unsafe_allow_html=True)
        for lab, mkey in [("5日","MA5"),("10日","MA10"),("月線","MA20"),("季線","MA60"),("半年","MA120"),("年線","MA240")]:
            ma_v = curr.get(mkey)
            if ma_v is None or pd.isna(ma_v):
                continue
            diff = p - ma_v
            pct2 = diff / ma_v * 100
            clr  = "#ff4d4d" if diff >= 0 else "#51cf66"
            st.markdown(
                f"<div class='ma-row'>"
                f"<b style='color:#000'>{lab}</b> "
                f"<span style='color:#000'>{ma_v:.1f}</span> "
                f"<span style='color:{clr}'>({diff:+.1f}, {pct2:+.2f}%)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# 7.5  情勢分析（規則判斷 + Gemini AI）
# ─────────────────────────────────────────────
st.subheader("🤖 情勢分析")

# ── 量價分類閾值 ──────────────────────────────
def classify_chg(pct: float) -> tuple:
    """漲跌幅分類，回傳 (等級, emoji, 說明)"""
    abs_p = abs(pct)
    if pct > 0:
        if abs_p < 0.5:   return ("微漲", "🟡", "漲幅不明顯")
        elif abs_p < 2.0: return ("小漲", "🟢", "溫和上漲")
        else:             return ("大漲", "🚀", "強勢上攻")
    elif pct < 0:
        if abs_p < 0.5:   return ("微跌", "🟡", "跌幅不明顯")
        elif abs_p < 2.0: return ("小跌", "🔴", "溫和下跌")
        else:             return ("大跌", "💥", "急殺破位")
    else:
        return ("平盤", "⬜", "無方向")

def classify_vol(vol_ratio: float) -> tuple:
    """成交量比（今日/5日均量）分類，回傳 (等級, 說明)"""
    if vol_ratio < 0.7:   return ("小量", "量縮")
    elif vol_ratio < 1.3: return ("中量", "量平")
    else:                 return ("大量", "量增")

# 量價組合對照表：(漲跌等級, 量級) → (訊號, 建議)
SIGNAL_MAP = {
    # ── 漲勢 ──
    ("大漲", "大量"): ("🔥 強勢突破",   "主力積極買入，可考慮追進或持有，注意追高風險"),
    ("大漲", "中量"): ("✅ 健康上漲",   "漲勢穩健，可持有，回測均線可加碼"),
    ("大漲", "小量"): ("⚠️ 量縮急漲",   "漲勢恐難持續，可能為軋空，謹慎追高"),
    ("小漲", "大量"): ("📈 量增緩漲",   "資金流入但分歧，觀察是否能繼續放量突破"),
    ("小漲", "中量"): ("😊 溫和上漲",   "多方略佔優勢，可持有，等待量能擴大"),
    ("小漲", "小量"): ("😴 量縮微揚",   "動能不足，持有觀望，不宜追買"),
    ("微漲", "大量"): ("🤔 量增價滯",   "多空拉鋸，大量無法推升，需留意轉弱風險"),
    ("微漲", "中量"): ("😐 盤整偏多",   "方向不明，等待突破確認再行動"),
    ("微漲", "小量"): ("💤 縮量盤整",   "觀望氣氛濃，暫時按兵不動"),
    # ── 跌勢 ──
    ("大跌", "大量"): ("🚨 急殺出逃",   "恐慌性拋售，短線避險，等止跌訊號再承接"),
    ("大跌", "中量"): ("🔻 中量重跌",   "跌勢明確，宜減碼或停損，不宜抄底"),
    ("大跌", "小量"): ("❓ 量縮急跌",   "可能為洗盤，但破支撐則需停損"),
    ("小跌", "大量"): ("⚡ 量增下跌",   "賣壓偏重，短線偏空，等買盤回穩"),
    ("小跌", "中量"): ("📉 溫和下跌",   "多空均衡偏空，持股控制倉位"),
    ("小跌", "小量"): ("🧊 量縮小跌",   "賣壓不重，可能為回檔整理，留意反彈"),
    ("微跌", "大量"): ("⚠️ 量增價滯跌", "大量無法守平，需留意後續走弱"),
    ("微跌", "中量"): ("😑 盤整偏空",   "方向不明偏弱，觀望"),
    ("微跌", "小量"): ("💤 縮量盤跌",   "氣氛冷清，等待方向"),
    # ── 平盤 ──
    ("平盤", "大量"): ("🤷 大量平盤",   "多空激烈拉鋸，方向待確認"),
    ("平盤", "中量"): ("😶 平盤整理",   "無明顯方向，暫時觀望"),
    ("平盤", "小量"): ("💤 縮量平盤",   "市場冷清，等待催化劑"),
}

# ── 規則判斷主體 ────────────────────────────
rule_cols = st.columns(len(order))
for i, name in enumerate(order):
    if name not in data:
        continue
    curr      = data[name].iloc[0]
    prev      = data[name].iloc[1] if len(data[name]) > 1 else curr
    p         = float(curr["Close"])
    pct       = float(curr["幅%"])
    buy_p     = float(curr["買盤%"])
    label     = STOCKS[name]["label"] if name in STOCKS else "加權指數"

    # 量比（今日 vs 5日均量）
    vol_today = float(curr.get("Volume", 0))
    vol_ma5   = float(data[name]["Volume"].iloc[1:6].mean()) if len(data[name]) >= 6 else vol_today
    vol_ratio = vol_today / vol_ma5 if vol_ma5 > 0 else 1.0

    chg_level, chg_emoji, chg_desc = classify_chg(pct)
    vol_level, vol_desc            = classify_vol(vol_ratio)
    signal, advice = SIGNAL_MAP.get((chg_level, vol_level), ("❔ 資料不足", "請人工判斷"))

    # 買盤強弱
    if buy_p >= 70:   buy_desc, buy_clr = "買盤強勢", "#ff4d4d"
    elif buy_p >= 50: buy_desc, buy_clr = "買盤略強", "#ff9900"
    elif buy_p >= 30: buy_desc, buy_clr = "賣盤略強", "#51cf66"
    else:             buy_desc, buy_clr = "賣盤強勢", "#1a7a3f"

    with rule_cols[i]:
        st.markdown(f"""
        <div style='background:#fff;border:1px solid #dce3ee;border-radius:10px;padding:14px;'>
            <div style='font-weight:700;font-size:0.95rem;color:#1a2540;margin-bottom:8px;'>
                {chg_emoji} {name} {label}
            </div>
            <div style='font-size:1.3rem;font-weight:700;color:{"#ff4d4d" if pct>=0 else "#51cf66"};'>
                {pct:+.2f}%
            </div>
            <div style='font-size:0.82rem;color:#555;margin:4px 0;'>
                {chg_level} × {vol_level}（量比 {vol_ratio:.1f}x）
            </div>
            <div style='font-size:0.88rem;font-weight:600;margin:6px 0;color:#1a2540;'>
                {signal}
            </div>
            <div style='font-size:0.80rem;color:#444;border-top:1px solid #eee;padding-top:6px;margin-top:4px;'>
                💡 {advice}
            </div>
            <div style='margin-top:8px;background:#eee;border-radius:4px;height:8px;'>
                <div style='width:{buy_p:.0f}%;background:{buy_clr};height:8px;border-radius:4px;'></div>
            </div>
            <div style='font-size:0.75rem;color:{buy_clr};margin-top:3px;'>
                {buy_desc} {buy_p:.1f}%
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── Gemini AI 深度分析 ──────────────────────
st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

# API Key 設定
_env_key = os.getenv("GEMINI_API_KEY", "")
if "gemini_key" not in st.session_state:
    st.session_state.gemini_key = _env_key

if not _env_key:
    with st.expander("🔑 設定 Gemini API Key（選填，可使用 AI 深度分析）", expanded=False):
        key_input = st.text_input(
            "Gemini API Key",
            value=st.session_state.gemini_key,
            type="password",
            placeholder="貼上你的 API Key，或在 .env 設定 GEMINI_API_KEY=...",
        )
        if key_input:
            st.session_state.gemini_key = key_input
            st.success("✅ API Key 已設定")
else:
    st.caption("🔐 Gemini API Key 已從 `.env` 自動載入")

def build_market_summary() -> str:
    lines = []
    for name in order:
        if name not in data:
            continue
        df5   = data[name].head(5)
        curr  = df5.iloc[0]
        label = STOCKS[name]["label"] if name in STOCKS else "加權指數"
        p     = float(curr["Close"])
        chg   = float(curr["幅%"])
        buy_p = float(curr["買盤%"])
        sel_p = float(curr["賣盤%"])
        vol_today = float(curr.get("Volume", 0))
        vol_ma5   = float(data[name]["Volume"].iloc[1:6].mean()) if len(data[name]) >= 6 else vol_today
        vol_ratio = vol_today / vol_ma5 if vol_ma5 > 0 else 1.0
        chg_level, _, _ = classify_chg(chg)
        vol_level, _    = classify_vol(vol_ratio)

        ma_status = []
        for mkey, mlab in [("MA5","5日"),("MA20","月線"),("MA60","季線"),("MA120","半年線"),("MA240","年線")]:
            ma_v = curr.get(mkey)
            if ma_v is not None and not pd.isna(ma_v):
                status = "上方" if p > ma_v else "下方"
                ma_status.append(f"{mlab}{status}({ma_v:.1f})")

        recent = " / ".join(f"{float(r['幅%']):+.2f}%" for _, r in df5.iterrows())
        lines.append(
            f"【{name} {label}】\n"
            f"  收盤：{p:,.2f}　漲跌：{chg:+.2f}%（{chg_level}）\n"
            f"  成交量比5日均量：{vol_ratio:.1f}倍（{vol_level}）\n"
            f"  近5日漲跌：{recent}\n"
            f"  買盤：{buy_p:.1f}%　賣盤：{sel_p:.1f}%\n"
            f"  均線位置：{', '.join(ma_status) if ma_status else '資料不足'}\n"
        )
    return "\n".join(lines)

def call_gemini(summary: str, api_key: str) -> str:
    import urllib.request as _ur, json as _js
    prompt = (
        "你是一位專業台股分析師，擅長技術分析與籌碼分析。\n"
        "請根據以下資料，針對每個標的綜合分析量價關係、買賣盤力道、均線結構，\n"
        "並給出明確操作建議（買進／持有／觀望／減碼／賣出）。\n"
        "最後整體評估大盤與持股組合風險。\n"
        "語氣專業簡潔，繁體中文，每個標的 3-4 句，整體評估 2-3 句。\n\n"
        f"{summary}"
    )
    url  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    body = _js.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.4},
    }).encode()
    try:
        req  = _ur.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        resp = _ur.urlopen(req, timeout=30)
        result = _js.loads(resp.read())
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        try:
            err_body = e.read().decode() if hasattr(e, "read") else str(e)
            err_json = _js.loads(err_body)
            return f"⚠️ Gemini 錯誤：{err_json.get('error', {}).get('message', err_body)}"
        except Exception:
            return f"⚠️ 呼叫失敗：{e}"

ai_c1, ai_c2 = st.columns([1, 4])
with ai_c1:
    run_ai = st.button("🔍 Gemini 深度分析", type="primary", disabled=not st.session_state.gemini_key)
with ai_c2:
    if st.session_state.gemini_key:
        st.caption("點擊按鈕，Gemini 將進行更深入的綜合判斷與建議")
    else:
        st.caption("設定 Gemini API Key 後可啟用 AI 深度分析（上方規則判斷無需 Key）")

if run_ai:
    summary = build_market_summary()
    with st.spinner("🤖 Gemini 正在深度分析..."):
        analysis = call_gemini(summary, st.session_state.gemini_key)
    st.markdown(
        f"<div style='background:#f8faff;border:1px solid #d0dff5;border-radius:10px;"
        f"padding:18px 22px;font-size:0.92rem;line-height:1.8;color:#1a2540;margin-top:12px;'>"
        f"{analysis.replace(chr(10), '<br>')}</div>",
        unsafe_allow_html=True,
    )

st.divider()

# ─────────────────────────────────────────────
# 8. 維持率總覽
# ─────────────────────────────────────────────
st.subheader("📊 維持率總覽")

val_now, m_now     = calc_margin(pledged, loan)
pledged_after      = {k: pledged[k] + (buy[k] if is_add_pledge else 0) for k in STOCKS}
buy_cost           = sum(prices.get(k, 0) * buy[k] for k in STOCKS) * 1000 / 1e4
loan_after         = loan + (buy_cost if is_use_loan else 0)
val_after, m_after = calc_margin(pledged_after, loan_after)
delta_m            = m_after - m_now
buffer_pct         = m_now - MARGIN_DANGER
total_cur          = sum(cur[k] * prices.get(k, 0) for k in STOCKS) * 1000 / 1e4
sign               = "+" if delta_m >= 0 else ""

cards = [
    (margin_emoji(m_now), "目前維持率",
     f'<span class="{margin_css(m_now)}">{m_now:.2f}%</span>',
     f"質押市值 {val_now:,.1f} 萬 ／ 借款 {loan:,.0f} 萬"),
    ("🏹", "加碼後模擬維持率",
     f'<span class="{margin_css(m_after)}">{m_after:.2f}%</span>',
     f"變動 {sign}{delta_m:.2f}% ／ 借款 {loan_after:,.0f} 萬"),
    ("💼", "持股總市值",
     f"{total_cur:,.1f} <span style='font-size:1rem;color:#8fa8c8'>萬</span>",
     f"加碼需資金 {buy_cost:,.1f} 萬"),
    ("🔐", "距危險線緩衝",
     f'{buffer_pct:+.2f}<span style="font-size:1rem;color:#8fa8c8">%</span>',
     f"危險線 {MARGIN_DANGER}%，警示線 {MARGIN_WARNING}%"),
]

for col, (emoji, title, val_html, sub) in zip(st.columns(4), cards):
    col.markdown(f"""
    <div class='sim-card'>
        <div class='sim-title'>{emoji} {title}</div>
        <div class='sim-value'>{val_html}</div>
        <div class='sim-sub'>{sub}</div>
    </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 9. 加碼模擬明細
# ─────────────────────────────────────────────
if any(buy[k] > 0 for k in STOCKS):
    st.subheader("🏹 加碼模擬明細")
    sim_rows = [
        {
            "股票":         f"{k} {STOCKS[k]['label']}",
            "加碼張數":     buy[k],
            "現價":         f"{prices.get(k,0):,.2f}",
            "加碼成本(萬)": f"{prices.get(k,0) * buy[k] * 1000 / 1e4:,.2f}",
            "原質押張":     pledged[k],
            "加碼後質押張": pledged[k] + (buy[k] if is_add_pledge else 0),
        }
        for k in STOCKS if buy[k] > 0
    ]
    st.dataframe(pd.DataFrame(sim_rows), width="stretch", hide_index=True)
    ci = st.columns(3)
    ci[0].info(f"📌 買入方式：{'動用質押借款' if is_use_loan else '自有資金'}")
    ci[1].info(f"📌 買入後質押：{'是' if is_add_pledge else '否'}")
    ci[2].info(f"📌 總加碼成本：{buy_cost:,.2f} 萬元")

st.divider()

# ─────────────────────────────────────────────
# 10. 近 90 天明細
# ─────────────────────────────────────────────
st.subheader("📅 近 90 天明細")

COL_MAP = {"Open":"開盤", "Close":"收盤", "漲跌點":"漲跌點", "幅%":"幅%", "買盤%":"買盤%", "賣盤%":"賣盤%"}
FMT     = {"開盤":"{:.2f}", "收盤":"{:.2f}", "漲跌點":"{:+.2f}", "幅%":"{:+.2f}%", "買盤%":"{:.1f}%", "賣盤%":"{:.1f}%"}

tab_names = ["大盤 (^TWII)"] + [f"{k} {STOCKS[k]['label']}" for k in STOCKS]
tab_keys  = ["大盤"] + list(STOCKS.keys())

for tab, key in zip(st.tabs(tab_names), tab_keys):
    with tab:
        if key not in data:
            st.warning("資料暫時無法取得")
            continue

        df_base = data[key]
        df_show = df_base[[c for c in COL_MAP if c in df_base.columns]].rename(columns=COL_MAP).head(90)
        df_show.index.name = None

        active_fmt = {k: v for k, v in FMT.items() if k in df_show.columns}
        color_cols = [c for c in ["漲跌點", "幅%"] if c in df_show.columns]

        styled = df_show.style.format(active_fmt, na_rep="—")
        if color_cols:
            styled = styled.map(
                lambda v: "color:#ff4d4d" if isinstance(v, float) and v > 0
                     else ("color:#51cf66" if isinstance(v, float) and v < 0 else ""),
                subset=color_cols,
            )
        st.dataframe(styled, width="stretch")
