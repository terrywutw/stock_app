import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os

# 網頁配置
st.set_page_config(page_title="Terry 的投資決策系統", layout="wide")

# --- 0. 自動記憶功能 (JSON 存取) ---
CONFIG_FILE = "stock_config_v4.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "loan_amount": 208,
        "cur_2330": 1, "cur_0050": 30, "cur_0052": 33,
        "pledged_2330": 1, "pledged_0050": 30, "pledged_0052": 33
    }

def save_config(config_dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_dict, f)

init_data = load_config()

# 強制 CSS 修飾：紅漲綠跌
st.markdown("""
    <style>
    [data-testid="stMetricDelta"] svg { display: none; }
    span[data-testid="stMetricDelta"] { color: #ff0000 !important; }
    div[data-testid="stMetricDelta"] > div { color: #00ad00 !important; }
    .ma-container { 
        background-color: #f8f9fa; 
        padding: 10px; 
        border-radius: 8px; 
        border: 1px solid #e9ecef;
        margin-top: 5px;
    }
    .ma-row { font-size: 0.82rem; margin-bottom: 2px; border-bottom: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 左側邊欄：決策參數區 ---
with st.sidebar:
    st.header("📋 決策參數設定")
    
    with st.expander("💰 資金與現有持股", expanded=True):
        loan = st.number_input("目前總借款金額 (萬元)", value=init_data["loan_amount"])
        st.write("**目前持有總張數：**")
        c2330 = st.number_input("2330 持股 (張)", value=init_data["cur_2330"])
        c0050 = st.number_input("0050 持股 (張)", value=init_data["cur_0050"])
        c0052 = st.number_input("0052 持股 (張)", value=init_data["cur_0052"])

    with st.expander("🛡️ 質押現況", expanded=True):
        p2330 = st.number_input("已質押 2330 (張)", value=init_data["pledged_2330"])
        p0050 = st.number_input("已質押 0050 (張)", value=init_data["pledged_0050"])
        p0052 = st.number_input("已質押 0052 (張)", value=init_data["pledged_0052"])

    if st.button("💾 儲存並記憶目前參數"):
        save_config({
            "loan_amount": loan, "cur_2330": c2330, "cur_0050": c0050, "cur_0052": c0052,
            "pledged_2330": p2330, "pledged_0050": p0050, "pledged_0052": p0052
        })
        st.success("✅ 設定已記憶！")

    st.divider()
    with st.expander("🏹 加碼模擬測試", expanded=False):
        buy_2330 = st.number_input("加碼 2330", value=0)
        buy_0050 = st.number_input("加碼 0050", value=0)
        buy_0052 = st.number_input("加碼 0052", value=0)
        is_add_pledge = st.toggle("買入後是否馬上質押？", value=True)
        is_use_loan = st.toggle("是否動用質押借款買入？", value=False)

# --- 2. 數據處理核心 (90天 & 均線) ---
@st.cache_data(ttl=300)
def get_market_data():
    tickers = {"大盤": "^TWII", "2330": "2330.TW", "0050": "0050.TW", "0052": "0052.TW"}
    all_df = {}
    for name, sym in tickers.items():
        df = yf.Ticker(sym).history(period="350d").sort_index(ascending=True)
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA10'] = df['Close'].rolling(10).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA240'] = df['Close'].rolling(240).mean()
        df['VMA5'] = df['Volume'].rolling(5).mean()
        df['漲跌點數'] = df['Close'].diff()
        df['漲跌幅%'] = (df['漲跌點數'] / df['Close'].shift(1)) * 100
        df['總成交金額(億)'] = (df['Close'] * df['Volume']) / 100000000
        # 買賣力道估計
        rng = df['High'] - df['Low']
        df['買盤比例%'] = ((df['Close'] - df['Low']) / rng * 100).fillna(50)
        df['賣盤比例%'] = 100 - df['買盤比例%']
        df_sorted = df.sort_index(ascending=False).copy()
        df_sorted.index = df_sorted.index.strftime('%Y-%m-%d')
        all_df[name] = df_sorted
    return all_df

try:
    market_data = get_market_data()
    p2330_curr = market_data['2330']['Close'].iloc[0]
    p0050_curr = market_data['0050']['Close'].iloc[0]
    p0052_curr = market_data['0052']['Close'].iloc[0]
    buy_cost = (buy_2330 * p2330_curr + buy_0050 * p0050_curr + buy_0052 * p0052_curr) * 1000 / 10000
except:
    st.error("數據更新中或抓取失敗。")
    st.stop()

# --- 3. 儀表板區域 ---
st.title("🛡️ 專業投資質押戰情室")
order = ["大盤", "2330", "0050", "0052"]
m_cols = st.columns(4)

for i, name in enumerate(order):
    df = market_data[name]
    curr = df.iloc[0]
    price = curr['Close']
    with m_cols[i]:
        st.metric(name, f"{price:.2f}", f"{curr['漲跌幅%']:+.2f}%")
        st.markdown("<div class='ma-container'>", unsafe_allow_html=True)
        ma_cfg = [("5日", curr['MA5']), ("10日", curr['MA10']), ("月線", curr['MA20']), ("季線", curr['MA60']), ("年線", curr['MA240'])]
        for ma_label, ma_val in ma_cfg:
            diff = price - ma_val
            pct = (diff / ma_val) * 100
            clr = "red" if diff >= 0 else "green"
            st.markdown(f"<div class='ma-row'><b>{ma_label}</b> {ma_val:.1f} <span style='color:{clr}'>({diff:+.1f}, {pct:+.2f}%)</span></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# 維持率計算
def calc_r(ln, p2, n2, p5, n5, p52, n52):
    v = (p2 * n2 + p5 * n5 + p52 * n52) * 1000 / 10000
    return (v / ln) * 100 if ln > 0 else 0

m_now = calc_r(loan, p2330_curr, p2330, p0050_curr, p0050, p0052_curr, p0052)
sim_ln = loan + (buy_cost if is_use_loan else 0)
sim_n2 = p2330 + buy_2330 if is_add_pledge else p2330
sim_n5 = p0050 + buy_0050 if is_add_pledge else p0050
sim_n52 = p0052 + buy_0052 if is_add_pledge else p0052
m_after = calc_r(sim_ln, p2330_curr, sim_n2, p0050_curr, sim_n5, p0052_curr, sim_n52)

c1, c2, c3 = st.columns(3)
c1.metric("目前維持率", f"{m_now:.2f}%")
c2.metric("加碼模擬後維持率", f"{m_after:.2f}%", f"{m_after - m_now:+.2f}%")
with c3:
    if m_after > 180: st.success("風險等級：安全")
    else: st.error("風險等級：危險")

# --- 4. AI 分別顯示個股分析 ---
st.subheader("🤖 AI 個股量價即時分析")
ai_cols = st.columns(3)
for i, name in enumerate(["2330", "0050", "0052"]):
    df = market_data[name]
    curr = df.iloc[0]
    vol_r = curr['Volume'] / curr['VMA5']
    with ai_cols[i]:
        with st.container(border=True):
            st.markdown(f"### {name}")
            if curr['Close'] > curr['Open'] and vol_r > 1.1:
                st.write("🟢 **量價齊揚**：多頭攻擊，買盤積極且出量，趨勢強勢。")
            elif curr['Close'] < curr['Open'] and vol_r > 1.1:
                st.write("🔴 **帶量下殺**：賣壓沉重，內盤摜壓明顯，建議守好支撐。")
            elif vol_r < 0.8:
                st.write("🟡 **量縮盤整**：動能不足，進入窄幅震盪，觀察均線支撐。")
            else:
                st.write("⚖️ **常態波動**：量能平穩，多空力道拉鋸中。")
            st.progress(curr['買盤比例%']/100, text=f"買盤力道: {curr['買盤比例%']:.1f}%")

# --- 5. 90天明細 (大盤優先) ---
st.divider()
st.subheader("📅 近 90 天交易明細")
t_tabs = st.tabs(["大盤 (^TWII)", "2330 台積電", "0050 元大50", "0052 富邦科技"])
t_order = ["大盤", "2330", "0050", "0052"]

for i, tab in enumerate(t_tabs):
    with tab:
        target = t_order[i]
        df_show = market_data[target][['Open', 'Close', '漲跌點數', '漲跌幅%', 'Volume', '總成交金額(億)', '賣盤比例%', '買盤比例%']].head(90)
        st.dataframe(df_show.style.format({
            'Open': '{:.2f}', 'Close': '{:.2f}', '漲跌點數': '{:+.2f}', '漲跌幅%': '{:+.2f}%', 
            'Volume': '{:,.0f}', '總成交金額(億)': '{:.1f}', '賣盤比例%': '{:.1f}%', '買盤比例%': '{:.1f}%'
        }).map(lambda v: 'color:red' if isinstance(v,float) and v>0 else ('color:green' if isinstance(v,float) and v<0 else ''), subset=['漲跌點數', '漲跌幅%']), use_container_width=True, height=500)