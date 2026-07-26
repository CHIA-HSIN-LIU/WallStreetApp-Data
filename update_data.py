import json
import random
from datetime import datetime, timezone, timedelta

def get_taiwan_time():
    # 取得台灣時區 (UTC+8) 的當前時間
    utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
    tw_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
    return tw_dt.strftime('%Y-%m-%d %H:%M:%S')

def generate_market_data():
    # 這裡未來會換成你爬取網頁的真實數據
    # 現在先用隨機數據模擬，以證明 GitHub Actions 每次都有確實執行更新
    return {
        "updateTime": get_taiwan_time(),
        "marginMaintenance": round(random.uniform(130, 180), 1),
        "marketBreadth": round(random.uniform(20, 80), 1),
        "tsmcAdrPremium": round(random.uniform(-5, 20), 1),
        "buffettIndicator": round(random.uniform(140, 210), 1),
        "bigWhaleHoldingRatio": round(random.uniform(-3, 3), 1),
        "maBiasRatio": round(random.uniform(-8, 8), 1),
        "foreignShorts": random.randint(2000, 20000)
    }

def main():
    data = generate_market_data()
    
    # 將數據寫入 JSON 檔案
    with open('today_market.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 成功更新市場數據！時間：{data['updateTime']}")

if __name__ == "__main__":
    main()