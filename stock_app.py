"""
Terry 投資戰情室 v12 - 優化版
優化重點：
1. 修正 CSS delta 顏色（改用 delta_color 參數）
2. 股票設定集中管理（STOCKS dict）
3. 批次下載市場資料（效能優化）
4. 加碼模擬邏輯完整接上計算
5. 維持率警示色
6. except 範圍縮小，錯誤不再被靜默吞掉
7. holdings dict 取代 zip，提高可讀性
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os

# ─────────────────────────────────────────────
# 0. 全域設定：所有股票集中管理，新增股票只改這裡
# ─────────────────────────────────────────────
STOCKS = {
    "2330":   {"label": "台積電",          "symbol": "2330.TW",   "pledge_rate": 0.6},
    "0050":   {"label": "元大50",          "symbol": "0050.TW",   "pledge_rate": 0.7},
    "0052":   {"label": "富邦科技",        "symbol": "0052.TW",   "pledge_rate": 0.6},
    "00981A": {"label": "統一增長主動型",  "symbol": "00981A.TW", "pledge_rate": 0.5},
}
INDEX_SYMBOL = {"大盤": "^TWII"}

# 維持率警示閾值
MARGIN_DANGER  = 130   # 紅色
MARGIN_WARNING = 160   # 橙色

# ─────────────────────────────────────────────
# 1. 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(page_title="Terry 投資戰情室", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
/* 移除預設 metric delta svg 箭頭 */
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

/* 模擬結果卡片 */
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

/* 維持率顏色 */
.margin-danger  { color: #ff4d4d !important; }
.margin-warning { color: #ffa94d !important; }
.margin-safe    { color: #51cf66 !important; }

/* Sidebar 小標 */
.sidebar-label { font-size: 0.78rem; color: #8fa8c8; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 2. 設定檔讀寫（更安全的錯誤處理）
# ─────────────────────────────────────────────
CONFIG_FILE = "stock_config_v12.json"

def _default_config() -> dict:
    base = {"loan_amount": 208}
    for k in STOCKS:
        base[f"cur_{k}"]      = 0
        base[f"pledged_{k}"]  = 0
    return base

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 補齊新增股票的預設值
            defaults = _default_config()
            defaults.update(data)
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
# 3. 左側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📋 決策參數設定")

    with st.expander("💰 資金與現有持股", expanded=True):
        loan = st.number_input("目前總借款金額 (萬元)", value=float(init["loan_amount"]), step=1.0)
        st.markdown("<p class='sidebar-label'>目前持有總張數</p>", unsafe_allow_html=True)
        cur = {k: st.number_input(f"{k} {STOCKS[k]['label']}", value=int(init.get(f"cur_{k}", 0)), key=f"cur_{k}") for k in STOCKS}

    with st.expander("🛡️ 質押現況", expanded=True):
        pledged = {k: st.number_input(f"已質押 {k}", value=int(init.get(f"pledged_{k}", 0)), key=f"p_{k}") for k in STOCKS}

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
# 4. 市場資料（批次下載）
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_market_data() -> dict[str, pd.DataFrame]:
    """批次下載所有標的，計算均線、技術指標後回傳 dict。"""
    all_symbols = {**{k: v["symbol"] for k, v in STOCKS.items()}, **INDEX_SYMBOL}
    # 反轉成 symbol → name
    sym_to_name = {v: k for k, v in all_symbols.items()}
    symbols = list(all_symbols.values())

    # 批次下載（單次 API 呼叫）
    raw = yf.download(symbols, period="350d", group_by="ticker", auto_adjust=True, progress=False)

    result = {}
    for sym, name in sym_to_name.items():
        try:
            if len(symbols) == 1:
                df = raw.copy()
            else:
                df = raw[sym].copy()
            df = df.dropna(subset=["Close"]).sort_index(ascending=True)

            for m in [5, 10, 20, 60, 120, 240]:
                df[f"MA{m}"] = df["Close"].rolling(m).mean()
            df["VMA5"]        = df["Volume"].rolling(5).mean()
            df["漲跌點"]       = df["Close"].diff()
            df["幅%"]          = (df["漲跌點"] / df["Close"].shift(1)) * 100
            df["成交金額(億)"] = (df["Close"] * df["Volume"]) / 1e8
            rng = df["High"] - df["Low"]
            df["買%"] = ((df["Close"] - df["Low"]) / rng.replace(0, pd.NA) * 100).fillna(50)

            df_out = df.sort_index(ascending=False).copy()
            df_out.index = df_out.index.strftime("%Y-%m-%d")
            result[name] = df_out
        except Exception as e:
            st.warning(f"⚠️ 無法取得 {name}（{sym}）資料：{e}")

    return result

with st.spinner("🔄 正在載入市場資料..."):
    data = get_market_data()

# 最新收盤價
prices: dict[str, float] = {}
for k in STOCKS:
    if k in data:
        prices[k] = float(data[k]["Close"].iloc[0])
    else:
        prices[k] = 0.0

# ─────────────────────────────────────────────
# 5. 維持率計算（通用函式）
# ─────────────────────────────────────────────
def calc_margin(pledged_qty: dict, loan_amt: float) -> tuple[float, float]:
    """回傳 (質押市值萬元, 維持率%)"""
    val = sum(prices.get(k, 0) * qty for k, qty in pledged_qty.items()) * 1000 / 1e4
    margin = (val / loan_amt * 100) if loan_amt > 0 else float("inf")
    return val, margin

def margin_css_class(m: float) -> str:
    if m < MARGIN_DANGER:  return "margin-danger"
    if m < MARGIN_WARNING: return "margin-warning"
    return "margin-safe"

def margin_emoji(m: float) -> str:
    if m < MARGIN_DANGER:  return "🔴"
    if m < MARGIN_WARNING: return "🟠"
    return "🟢"

# ─────────────────────────────────────────────
# 6. 主儀表板標題列
# ─────────────────────────────────────────────
st.title("🛡️ 投資戰情室")
st.markdown(f"<p style='font-size:0.82rem;color:#8fa8c8;margin-top:-10px;'>資料每 5 分鐘自動更新 · 維持率警示：🟠 &lt; {MARGIN_WARNING}%&nbsp;&nbsp;🔴 &lt; {MARGIN_DANGER}%</p>", unsafe_allow_html=True)

# 行情卡
order = ["大盤"] + list(STOCKS.keys())
m_cols = st.columns(len(order))

for i, name in enumerate(order):
    if name not in data:
        m_cols[i].warning(f"{name} 無資料")
        continue
    curr = data[name].iloc[0]
    p    = float(curr["Close"])
    pct  = float(curr["幅%"])
    # delta_color="inverse" → 正值顯示紅色（漲），負值顯示綠色（跌），符合台股慣例
    with m_cols[i]:
        label = STOCKS[name]["label"] if name in STOCKS else "加權指數"
        st.metric(
            f"{name} {label}" if name != "大盤" else "大盤 加權指數",
            f"{p:,.2f}",
            f"{pct:+.2f}%",
            delta_color="inverse",   # ✅ 修正：正確的台股紅漲綠跌
        )
        # 均線表
        st.markdown("<div class='ma-container'>", unsafe_allow_html=True)
        for lab, key in [("5日","MA5"),("10日","MA10"),("月線","MA20"),("季線","MA60"),("半年","MA120"),("年線","MA240")]:
            ma_v = curr.get(key, None)
            if pd.isna(ma_v) or ma_v is None:
                continue
            diff = p - ma_v
            pct2 = diff / ma_v * 100
            clr  = "#ff4d4d" if diff >= 0 else "#51cf66"
            st.markdown(
                f"<div class='ma-row'>"
                f"<b style='color:#000000'>{lab}</b> "
                f"<span style='color:#000000'>{ma_v:.1f}</span> "
                f"<span style='color:{clr}'>({diff:+.1f}, {pct2:+.2f}%)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# 7. 維持率區塊
# ─────────────────────────────────────────────
st.subheader("📊 維持率總覽")
val_now, m_now = calc_margin(pledged, loan)

# 加碼後模擬
pledged_after = {k: pledged[k] + (buy[k] if is_add_pledge else 0) for k in STOCKS}
buy_cost = sum(prices.get(k, 0) * buy[k] for k in STOCKS) * 1000 / 1e4   # 萬元
loan_after = loan + (buy_cost if is_use_loan else 0)
val_after, m_after = calc_margin(pledged_after, loan_after)
delta_margin = m_after - m_now

r1, r2, r3, r4 = st.columns(4)

with r1:
    cls = margin_css_class(m_now)
    st.markdown(f"""
    <div class='sim-card'>
        <div class='sim-title'>{margin_emoji(m_now)} 目前維持率</div>
        <div class='sim-value <span class="{cls}">{m_now:.2f}%</span>'><span class="{cls}">{m_now:.2f}%</span></div>
        <div class='sim-sub'>質押市值 {val_now:,.1f} 萬 ／ 借款 {loan:,.0f} 萬</div>
    </div>""", unsafe_allow_html=True)

with r2:
    cls2 = margin_css_class(m_after)
    sign = "+" if delta_margin >= 0 else ""
    st.markdown(f"""
    <div class='sim-card'>
        <div class='sim-title'>🏹 加碼後模擬維持率</div>
        <div class='sim-value'><span class="{cls2}">{m_after:.2f}%</span></div>
        <div class='sim-sub'>變動 {sign}{delta_margin:.2f}% ／ 借款 {loan_after:,.0f} 萬</div>
    </div>""", unsafe_allow_html=True)

with r3:
    total_cur  = sum(cur[k] * prices.get(k, 0) for k in STOCKS) * 1000 / 1e4
    total_buy  = buy_cost
    st.markdown(f"""
    <div class='sim-card'>
        <div class='sim-title'>💼 持股總市值</div>
        <div class='sim-value'>{total_cur:,.1f} <span style='font-size:1rem;color:#8fa8c8'>萬</span></div>
        <div class='sim-sub'>加碼需資金 {total_buy:,.1f} 萬</div>
    </div>""", unsafe_allow_html=True)

with r4:
    # 距離危險線還差多少
    safe_val   = loan * (MARGIN_DANGER / 100) * 1e4 / 1000   # 質押張數換算
    buffer_pct = m_now - MARGIN_DANGER
    st.markdown(f"""
    <div class='sim-card'>
        <div class='sim-title'>🔐 距危險線緩衝</div>
        <div class='sim-value'>{buffer_pct:+.2f}<span style='font-size:1rem;color:#8fa8c8'>%</span></div>
        <div class='sim-sub'>危險線 {MARGIN_DANGER}%，警示線 {MARGIN_WARNING}%</div>
    </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 8. 加碼模擬明細（只在有輸入時顯示）
# ─────────────────────────────────────────────
has_buy = any(buy[k] > 0 for k in STOCKS)
if has_buy:
    st.subheader("🏹 加碼模擬明細")
    sim_rows = []
    for k in STOCKS:
        if buy[k] == 0:
            continue
        p_k   = prices.get(k, 0)
        cost  = p_k * buy[k] * 1000 / 1e4
        new_pledged = pledged[k] + (buy[k] if is_add_pledge else 0)
        sim_rows.append({
            "股票": f"{k} {STOCKS[k]['label']}",
            "加碼張數": buy[k],
            "現價": f"{p_k:,.2f}",
            "加碼成本(萬)": f"{cost:,.2f}",
            "原質押張": pledged[k],
            "加碼後質押張": new_pledged,
        })
    if sim_rows:
        st.dataframe(pd.DataFrame(sim_rows), use_container_width=True, hide_index=True)

    col_info = st.columns(3)
    col_info[0].info(f"📌 買入方式：{'動用質押借款' if is_use_loan else '自有資金'}")
    col_info[1].info(f"📌 買入後質押：{'是' if is_add_pledge else '否'}")
    col_info[2].info(f"📌 總加碼成本：{buy_cost:,.2f} 萬元")

st.divider()

# ─────────────────────────────────────────────
# 9. 近 90 天明細
# ─────────────────────────────────────────────
st.subheader("📅 近 90 天明細")
tab_names = ["大盤 (^TWII)"] + [f"{k} {STOCKS[k]['label']}" for k in STOCKS]
tab_keys  = ["大盤"] + list(STOCKS.keys())
tabs = st.tabs(tab_names)

for tab, key in zip(tabs, tab_keys):
    with tab:
        if key not in data:
            st.warning("資料暫時無法取得")
            continue
        cols_show = [c for c in ["Open","Close","漲跌點","幅%","Volume","MA20","MA60","MA120","買%"] if c in data[key].columns]
        df_show = data[key][cols_show].head(90)

        fmt = {
            "Open": "{:.2f}", "Close": "{:.2f}",
            "漲跌點": "{:+.2f}", "幅%": "{:+.2f}%",
            "Volume": "{:,.0f}",
            "MA20": "{:.1f}", "MA60": "{:.1f}", "MA120": "{:.1f}",
            "買%": "{:.1f}%",
        }
        active_fmt = {k: v for k, v in fmt.items() if k in df_show.columns}

        styled = (
            df_show.style
            .format(active_fmt)
            .map(
                lambda v: "color:#ff4d4d" if isinstance(v, float) and v > 0
                     else ("color:#51cf66" if isinstance(v, float) and v < 0 else ""),
                subset=[c for c in ["漲跌點","幅%"] if c in df_show.columns],
            )
        )
        st.dataframe(styled, use_container_width=True)
