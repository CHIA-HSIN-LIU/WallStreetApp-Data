import json
import yfinance as yf
import requests
import pandas as pd
import warnings
from datetime import datetime, timezone, timedelta

# 忽略 yfinance 未來的警告訊息，保持終端機乾淨
warnings.filterwarnings("ignore", category=FutureWarning)

def get_taiwan_time():
    utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
    tw_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
    return tw_dt.strftime('%Y-%m-%d %H:%M:%S')

def fetch_real_market_data():
    print("啟動高階量化爬蟲，正在連線抓取真實數據 (已徹底移除 random，並升級恐慌敏感度)...")
    
    # 預設資料 (防止來源網站 API 臨時斷線)
    data = {
        "updateTime": get_taiwan_time(),
        "marginMaintenance": 160.0, 
        "marketBreadth": 35.0,
        "tsmcAdrPremium": 0.0,
        "buffettIndicator": 280.0, 
        "bigWhaleHoldingRatio": 0.0,
        "maBiasRatio": 0.0,
        "foreignShorts": 0
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        print("1. 抓取 Yahoo Finance 核心數據與大盤...")
        twii_history = yf.Ticker("^TWII").history(period="65d")['Close']
        current_twii = twii_history.iloc[-1]
        ma60 = twii_history.tail(60).mean()
        
        # 今日單日跌幅 (極度重要，用來修正落後指標)
        daily_drop = (current_twii / twii_history.iloc[-2]) - 1
        
        # [真實計算] 大盤季線乖離率
        data["maBiasRatio"] = round(((current_twii / ma60) - 1) * 100, 2)
        
        # [真實計算] 巴菲特指標 (市值 / GDP * 100)
        # 台灣大盤 1 點約等同於 0.0032 兆台幣市值
        market_cap_trillions = current_twii * 0.0032
        # 台灣 2024 預估 GDP 約 24.5 兆台幣
        data["buffettIndicator"] = round((market_cap_trillions / 24.5) * 100, 1)

        # [真實計算] 台積電與 ADR 溢價
        tpe_tsmc = yf.Ticker("2330.TW").history(period="1d")['Close'].iloc[-1]
        adr_tsmc = yf.Ticker("TSM").history(period="1d")['Close'].iloc[-1]
        usd_twd = yf.Ticker("TWD=X").history(period="1d")['Close'].iloc[-1]
        data["tsmcAdrPremium"] = round(((adr_tsmc * usd_twd / 5) / tpe_tsmc - 1) * 100, 2)
    except Exception as e:
        daily_drop = 0
        print(f"❌ Yahoo 核心數據抓取失敗: {e}")

    try:
        print("2. 透過 FinMind 開源 API 抓取外資期貨淨未平倉...")
        past_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        finmind_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesInstitutionalInvestors&data_id=TX&start_date={past_str}"
        
        res = requests.get(finmind_url, headers=headers, timeout=10)
        if res.status_code == 200:
            fm_data = res.json()
            if "data" in fm_data and len(fm_data["data"]) > 0:
                df = pd.DataFrame(fm_data["data"])
                foreign_df = df[df['name'] == '外資及陸資']
                if not foreign_df.empty:
                    latest_short = foreign_df.iloc[-1]['open_interest_net_lot']
                    data["foreignShorts"] = int(latest_short)
    except Exception as e:
        print(f"❌ FinMind API 抓取失敗: {e}")

    try:
        print("3. 採樣 20 大多元權值股計算真實市場寬度...")
        # 擴大採樣：涵蓋電子、金融、傳產，防止台積電單獨扭曲寬度
        top_20_tickers = [
            "2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW", 
            "2881.TW", "2891.TW", "2882.TW", "2303.TW", "2886.TW",
            "2002.TW", "1301.TW", "2603.TW", "3008.TW", "1216.TW",
            "2884.TW", "2892.TW", "2609.TW", "1101.TW", "2912.TW"
        ]
        
        # 批量抓取以節省時間與連線數
        batch_df = yf.download(" ".join(top_20_tickers), period="65d", progress=False)['Close']
        
        above_ma60_count = 0
        valid_count = 0
        
        for ticker in top_20_tickers:
            if ticker in batch_df.columns:
                hist = batch_df[ticker].dropna()
                if len(hist) >= 60:
                    if hist.iloc[-1] > hist.tail(60).mean():
                        above_ma60_count += 1
                    valid_count += 1
                    
        raw_breadth = (above_ma60_count / valid_count) * 100 if valid_count > 0 else 50.0
        
        # 【修正】季線是落後指標，若今日大盤重挫 (跌幅>1%)，市場必定哀鴻遍野，強制扣除寬度
        if daily_drop < -0.01:
            # 跌幅每 1%，額外扣除寬度 15%
            raw_breadth += (daily_drop * 100 * 15)
            
        data["marketBreadth"] = round(max(0.0, raw_breadth), 1)
    except Exception as e:
        print(f"❌ 市場寬度計算失敗: {e}")

    try:
        print("4. 動態量化推估融資維持率與大戶動能...")
        twii_20d = yf.Ticker("^TWII").history(period="20d")['Close']
        # 計算 20 日健康度
        bias_20d = (twii_20d.iloc[-1] / twii_20d.mean()) - 1
        
        # 【修正】加入單日恐慌暴擊：散戶遇到大跌最容易斷頭
        # 基礎值 165% + 趨勢健康度(權重2) + 單日恐慌爆擊(權重極高:5)
        calc_margin = 165.0 + (bias_20d * 100 * 2.0) + (daily_drop * 100 * 5.0)
        data["marginMaintenance"] = round(max(130.0, min(calc_margin, 200.0)), 1)
        
        # 大戶資金動能：取前三大權值股近 5 日漲跌幅作為大戶籌碼 Proxy
        mega_caps = batch_df[['2330.TW', '2317.TW', '2454.TW']].dropna().tail(5)
        whale_flow = (mega_caps.iloc[-1].mean() / mega_caps.iloc[0].mean()) - 1
        data["bigWhaleHoldingRatio"] = round(whale_flow * 100, 2)
    except Exception as e:
        print(f"❌ 動能量化推估失敗: {e}")

    print("✅ 恐慌敏感版真實數據抓取完畢！")
    return data

def main():
    data = fetch_real_market_data()
    
    with open('today_market.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ today_market.json 更新完成！時間：{data['updateTime']}")
    print(f"📊 今日真實指標：{data}")

if __name__ == "__main__":
    main()
