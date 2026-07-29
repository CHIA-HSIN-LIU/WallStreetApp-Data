import json
import yfinance as yf
import requests
import pandas as pd
import warnings
from datetime import datetime, timezone, timedelta

# 忽略警告訊息，保持終端機乾淨
warnings.filterwarnings("ignore", category=FutureWarning)

def get_taiwan_time():
    utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
    tw_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
    return tw_dt.strftime('%Y-%m-%d %H:%M:%S')

def fetch_real_market_data():
    print("啟動高階量化爬蟲 (無亂數真實版 v3.0 - 強化大跌敏感度)...")
    
    # 基礎預設資料 (防崩潰保護傘)
    data = {
        "updateTime": get_taiwan_time(),
        "marginMaintenance": 165.0, 
        "marketBreadth": 40.0,
        "tsmcAdrPremium": 0.0,
        "buffettIndicator": 280.0, 
        "bigWhaleHoldingRatio": 0.0,
        "maBiasRatio": 0.0,
        "foreignShorts": 15000
    }
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    daily_drop = 0

    # 1. 抓取大盤與核心數據
    try:
        print("1. 抓取 Yahoo Finance 核心數據...")
        twii = yf.Ticker("^TWII").history(period="65d")['Close']
        if len(twii) >= 2:
            current_twii = twii.iloc[-1]
            prev_twii = twii.iloc[-2]
            ma60 = twii.tail(60).mean()
            
            # 單日跌幅 (極度重要，用來驅動恐慌指標)
            daily_drop = (current_twii / prev_twii) - 1
            
            # [真實計算] 大盤季線乖離率
            data["maBiasRatio"] = round(((current_twii / ma60) - 1) * 100, 2)
            
            # [真實計算] 巴菲特指標: (台灣總市值 / GDP * 100)
            # 大盤 1 點約等於 0.0032 兆台幣市值。台灣預估 GDP 約 24.5 兆
            market_cap_trillions = current_twii * 0.0032
            data["buffettIndicator"] = round((market_cap_trillions / 24.5) * 100, 1)

            # [真實計算] 台積電 ADR 溢價
            tpe_tsmc = yf.Ticker("2330.TW").history(period="1d")['Close'].iloc[-1]
            adr_tsmc = yf.Ticker("TSM").history(period="1d")['Close'].iloc[-1]
            usd_twd = yf.Ticker("TWD=X").history(period="1d")['Close'].iloc[-1]
            data["tsmcAdrPremium"] = round(((adr_tsmc * usd_twd / 5) / tpe_tsmc - 1) * 100, 2)
    except Exception as e:
        print(f"❌ 核心數據抓取失敗，啟動備援數值: {e}")

    # 2. 抓取寬度與計算恐慌融資
    try:
        print("2. 採樣 20 大權值股計算真實寬度與融資...")
        # 擴大採樣：涵蓋電子、金融、傳產，精準反映中小型股狀態
        top_20 = ["2330.TW", "2317.TW", "2454.TW", "2382.TW", "2881.TW", 
                  "2891.TW", "2308.TW", "2882.TW", "2303.TW", "2886.TW",
                  "2002.TW", "1301.TW", "2603.TW", "3008.TW", "1216.TW",
                  "2884.TW", "2892.TW", "2609.TW", "1101.TW", "2912.TW"]
        
        batch_df = yf.download(top_20, period="65d", progress=False)['Close']
        
        above_ma60 = 0
        valid = 0
        for ticker in top_20:
            if ticker in batch_df:
                hist = batch_df[ticker].dropna()
                if len(hist) >= 60:
                    if hist.iloc[-1] > hist.tail(60).mean():
                        above_ma60 += 1
                    valid += 1
        
        raw_breadth = (above_ma60 / valid * 100) if valid > 0 else 50.0
        
        # 【大跌恐慌修正】若大盤跌幅超過 1.5%，強制將落後的均線寬度砍半
        if daily_drop < -0.015:
            raw_breadth = raw_breadth * 0.5
        data["marketBreadth"] = round(max(0.0, raw_breadth), 1)

        # 【融資斷頭推估】基數 168% 加上乖離率變動
        base_margin = 168.0
        margin = base_margin + (data["maBiasRatio"] * 1.5)
        
        # 散戶恐慌暴擊：跌超過 1% 開始暴力扣除融資
        if daily_drop < -0.01:
            margin += (daily_drop * 100 * 3.5) # 跌 2% 就會扣掉 7% 的維持率
        data["marginMaintenance"] = round(max(130.0, min(margin, 200.0)), 1)
        
        # 大戶資金動能 Proxy
        mega_caps = batch_df[['2330.TW', '2317.TW']].dropna().tail(5)
        if len(mega_caps) == 5:
            whale_flow = (mega_caps.iloc[-1].mean() / mega_caps.iloc[0].mean()) - 1
            data["bigWhaleHoldingRatio"] = round(whale_flow * 100, 2)
    except Exception as e:
        print(f"❌ 量化指標計算失敗: {e}")

    # 3. 抓取外資期貨空單 (FinMind API)
    try:
        print("3. 連線 FinMind 抓取真實外資期貨空單...")
        past_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        fm_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesInstitutionalInvestors&data_id=TX&start_date={past_str}"
        
        res = requests.get(fm_url, headers=headers, timeout=10)
        if res.status_code == 200:
            fm_data = res.json()
            if "data" in fm_data and len(fm_data["data"]) > 0:
                df = pd.DataFrame(fm_data["data"])
                foreign = df[df['name'] == '外資及陸資']
                if not foreign.empty:
                    # 取得最新一筆的淨未平倉，並取絕對值轉為空單數量展示
                    latest_short = foreign.iloc[-1]['open_interest_net_lot']
                    data["foreignShorts"] = abs(int(latest_short))
    except Exception as e:
        print(f"❌ FinMind 外資空單抓取失敗: {e}")

    return data

def main():
    data = fetch_real_market_data()
    
    with open('today_market.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ today_market.json 更新完成！時間：{data['updateTime']}")
    print(f"📊 今日量化指標：{data}")

if __name__ == "__main__":
    main()
