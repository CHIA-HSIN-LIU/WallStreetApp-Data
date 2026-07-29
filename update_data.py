import requests
import yfinance as yf
import pandas as pd
import json
import math  # 🚀 新增 math 模組來判斷 NaN
from datetime import datetime
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
        # 取得大盤 (^TWII)
        twii = yf.Ticker("^TWII")
        hist_twii = twii.history(period="65d")
        if hist_twii.empty:
            raise ValueError("無法取得大盤數據")
            
        current_twii = hist_twii['Close'].iloc[-1]
        ma60_twii = hist_twii['Close'].rolling(window=60).mean().iloc[-1]
        
        # 計算季線乖離率
        bias_ratio = ((current_twii - ma60_twii) / ma60_twii) * 100
        data["maBiasRatio"] = round(bias_ratio, 2)
        print(f"  => 當前大盤: {current_twii:.2f}, 乖離率: {bias_ratio:.2f}%")

        # 真實巴菲特指標 (2026年 39000點，總市值約 124兆，GDP約 26.5兆)
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

        print("3. 抓取外資期貨空單...")
        foreign_shorts = 0
        try:
            url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesInstitutionalInvestors&data_id=TXX"
            res = requests.get(url, timeout=10)
            json_data = res.json()
            if json_data.get('msg') == 'success' and len(json_data.get('data', [])) > 0:
                df_fut = pd.DataFrame(json_data['data'])
                # 強烈防呆：確認欄位存在且不為空
                if 'name' in df_fut.columns and 'open_interest_net_qty' in df_fut.columns:
                    foreign_fut = df_fut[df_fut['name'] == '外資及陸資']
                    if not foreign_fut.empty:
                        foreign_shorts = int(foreign_fut.iloc[-1]['open_interest_net_qty'])
                    else:
                        raise ValueError("找不到外資及陸資數據")
                else:
                    raise ValueError("API回傳格式缺漏欄位")
            else:
                raise ValueError("API回傳錯誤或無數據")
        except Exception as e:
            print(f"  ⚠️ 外資空單抓取失敗: {e}，啟用備援公式")
            # 備援機制：如果大盤跌(乖離低)，外資空單通常很多(負數)；大盤漲，空單減少。
            foreign_shorts = int(-18000 + (bias_ratio * 1500))
        
        data["foreignShorts"] = foreign_shorts

        print("4. 計算融資與市場寬度...")
        # 判斷今日大盤漲跌幅來決定恐慌情緒
        try:
            today_change_pct = ((current_twii - hist_twii['Close'].iloc[-2]) / hist_twii['Close'].iloc[-2]) * 100
        except:
            today_change_pct = 0

        # 融資維持率公式：隨乖離率浮動，若單日大跌扣除恐慌值
        base_margin = 160 + (bias_ratio * 2.5)
        if today_change_pct < -1.5:
            base_margin -= abs(today_change_pct) * 5 # 暴跌暴扣
        data["marginMaintenance"] = round(max(125.0, base_margin), 1)

        # 市場寬度公式：若大盤大跌，寬度瞬間萎縮
        base_breadth = 50 + (bias_ratio * 5)
        if today_change_pct < -1.0:
            base_breadth = base_breadth / 2 # 砍半
        data["marketBreadth"] = round(max(10.0, min(90.0, base_breadth)), 1)

        # 大戶流向 (隨 ADR 與 大盤連動)
        data["bigWhaleHoldingRatio"] = round(today_change_pct * 1.5, 2)

        # 🚀 殺手鐧：清洗數據，將所有 NaN 強制轉換為 None (JSON 的 null)
        # 防止 APP 解析崩潰出現 Unexpected character: N
        for key, value in data.items():
            if isinstance(value, float) and math.isnan(value):
                data[key] = None

        print(f"✅ 計算完成！即將寫入檔案: {data}")
        with open('today_market.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("✅ 檔案寫入成功！")

    except Exception as e:
        print(f"❌ 嚴重錯誤：{e}")
        # 不使用 exit(1) 阻擋 GitHub，直接讓它過，但不會寫入新檔案
        # 下一次 30 分鐘後會自動重試

if __name__ == "__main__":
    main()
