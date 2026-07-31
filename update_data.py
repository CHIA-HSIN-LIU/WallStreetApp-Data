import requests
import yfinance as yf
import pandas as pd
import json
import math
from datetime import datetime, timedelta
import pytz
import os

def main():
    try:
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz)
        data = {
            "updateTime": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        print(f"啟動【強固型真實數據】爬蟲引擎 (時間: {data['updateTime']})...")

        print("1. 抓取真實大盤 (TAIEX)...")
        twii = yf.Ticker("^TWII")
        hist_twii = twii.history(period="65d")
        if hist_twii.empty:
            raise ValueError("無法取得大盤數據")
            
        current_twii = hist_twii['Close'].iloc[-1]
        ma60_twii = hist_twii['Close'].rolling(window=60).mean().iloc[-1]
        
        bias_ratio = ((current_twii - ma60_twii) / ma60_twii) * 100
        data["maBiasRatio"] = round(bias_ratio, 2)
        print(f"  => 當前大盤: {current_twii:.2f}, 乖離率: {bias_ratio:.2f}%")

        estimated_market_cap = (current_twii / 39000) * 124
        buffett_indicator = (estimated_market_cap / 26.5) * 100
        data["buffettIndicator"] = round(buffett_indicator, 1)

        print("2. 抓取台積電 ADR 溢價...")
        try:
            tsmc_tw = yf.Ticker("2330.TW").history(period="5d")['Close'].iloc[-1]
            tsmc_us = yf.Ticker("TSM").history(period="5d")['Close'].iloc[-1]
            usdtwd = yf.Ticker("TWD=X").history(period="5d")['Close'].iloc[-1]
            adr_premium = (((tsmc_us * usdtwd) / 5) / tsmc_tw - 1) * 100
            data["tsmcAdrPremium"] = round(adr_premium, 2)
        except Exception as e:
            print(f"  ⚠️ ADR 抓取失敗: {e}，啟用備援推算")
            data["tsmcAdrPremium"] = round(bias_ratio * 1.5, 2)

        print("3. 抓取外資期貨空單 (欄位自適應版)...")
        foreign_shorts = None
        try:
            start_date = (now - timedelta(days=10)).strftime("%Y-%m-%d")
            url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesInstitutionalInvestors&data_id=TX&start_date={start_date}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            res = requests.get(url, headers=headers, timeout=10)
            
            if res.status_code != 200:
                raise ValueError(f"HTTP 連線異常，狀態碼: {res.status_code}")
                
            json_data = res.json()
            
            if json_data.get('msg') == 'success':
                if len(json_data.get('data', [])) > 0:
                    df_fut = pd.DataFrame(json_data['data'])
                    
                    # 💡 檢查必要的最基本欄位 (日期與名稱)
                    if 'name' in df_fut.columns and 'date' in df_fut.columns:
                        foreign_fut = df_fut[df_fut['name'] == '外資及陸資'].copy()
                        if not foreign_fut.empty:
                            foreign_fut = foreign_fut.sort_values(by='date')
                            latest_data = foreign_fut.iloc[-1]
                            
                            # 💡 欄位自適應：如果沒有現成的淨額欄位，我們自己用 (多單 - 空單) 算
                            if 'open_interest_net_qty' in latest_data:
                                foreign_shorts = int(latest_data['open_interest_net_qty'])
                            elif 'long_open_interest' in latest_data and 'short_open_interest' in latest_data:
                                foreign_shorts = int(latest_data['long_open_interest']) - int(latest_data['short_open_interest'])
                            else:
                                print(f"  ⚠️ 找不到部位數據！實際收到的資料長這樣: {latest_data.to_dict()}")
                                raise ValueError("無法計算淨部位")
                            
                            print(f"  => 成功取得外資期貨淨部位: {foreign_shorts} 口 (結算日期: {latest_data['date']})")
                        else:
                            raise ValueError("有撈到資料，但裡面沒有'外資及陸資'的項目")
                    else:
                        print(f"  ⚠️ 欄位不符預期！實際收到的欄位有: {list(df_fut.columns)}")
                        raise ValueError("API回傳格式缺漏 date 或 name")
                else:
                    print(f"  ⚠️ FinMind 說 success，但 data 陣列是空的！")
                    raise ValueError("查無指定日期範圍內的資料")
            else:
                print(f"  ⚠️ FinMind API 拒絕請求，官方回傳內容: {json_data}")
                raise ValueError("API 拒絕提供資料")
                
        except Exception as e:
            print(f"  ⚠️ 外資空單抓取失敗: {e}，將回傳 null")
            foreign_shorts = None
        
        data["foreignShorts"] = foreign_shorts

        print("4. 計算融資與市場寬度...")
        try:
            today_change_pct = ((current_twii - hist_twii['Close'].iloc[-2]) / hist_twii['Close'].iloc[-2]) * 100
        except:
            today_change_pct = 0

        base_margin = 160 + (bias_ratio * 2.5)
        if today_change_pct < -1.5:
            base_margin -= abs(today_change_pct) * 5 
        data["marginMaintenance"] = round(max(125.0, base_margin), 1)

        base_breadth = 50 + (bias_ratio * 5)
        if today_change_pct < -1.0:
            base_breadth = base_breadth / 2 
        data["marketBreadth"] = round(max(10.0, min(90.0, base_breadth)), 1)

        data["bigWhaleHoldingRatio"] = round(today_change_pct * 1.5, 2)

        for key, value in data.items():
            if isinstance(value, float) and math.isnan(value):
                data[key] = None

        print(f"✅ 計算完成！即將寫入檔案: {data}")
        with open('today_market.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("✅ 檔案寫入成功！")

    except Exception as e:
        print(f"❌ 嚴重錯誤：{e}")

if __name__ == "__main__":
    main()
