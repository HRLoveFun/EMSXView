#!/usr/bin/env python3
"""诊断 Odd Lot 问题 - 直接调用后端 API 获取订单数据"""

import requests
import json

# 配置
BASE_URL = "http://localhost:3000"

def test_api():
    """测试登录并获取订单数据"""
    
    # 1. 尝试登录
    login_data = {
        "username": "admin",
        "password": "admin"
    }
    
    try:
        # 尝试常见登录方式
        resp = requests.post(f"{BASE_URL}/api/auth/login", json=login_data, timeout=5)
        print(f"Login status: {resp.status_code}")
        if resp.status_code == 200:
            token = resp.json().get("data", {}).get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
        else:
            headers = {}
    except Exception as e:
        print(f"Login error: {e}")
        headers = {}
    
    # 2. 获取订单数据
    try:
        resp = requests.get(f"{BASE_URL}/api/orders", headers=headers, timeout=10)
        print(f"\nOrders API status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            orders = data.get("data", [])
            
            print(f"\nTotal orders: {len(orders)}")
            
            # 分析 exchange 字段
            exchanges = {}
            us_jp_orders = []
            
            for o in orders[:20]:  # 只看前20个
                exch = o.get("exchange", "N/A")
                exchanges[exch] = exchanges.get(exch, 0) + 1
                
                if exch and exch.upper() in ("US", "JP", "NYSE", "NASDAQ"):
                    us_jp_orders.append({
                        "id": o.get("id"),
                        "symbol": o.get("symbol"),
                        "exchange": exch,
                        "quantity": o.get("quantity"),
                        "isOddLot": o.get("isOddLot"),
                    })
            
            print(f"\n=== Exchange 分布 ===")
            for exch, count in sorted(exchanges.items(), key=lambda x: -x[1]):
                print(f"  {exch}: {count}")
            
            print(f"\n=== 前10个 US/JP 订单 ===")
            for o in us_jp_orders[:10]:
                print(f"  ID={o['id']}, Symbol={o['symbol']}, Exch={o['exchange']}, Qty={o['quantity']}, isOddLot={o['isOddLot']}")
                
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Orders API error: {e}")
    
    # 3. 获取 round lot sizes (如果可用)
    try:
        resp = requests.get(f"{BASE_URL}/api/debug/round-lot-sizes", headers=headers, timeout=5)
        print(f"\nRound Lot API status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            round_lot_data = data.get("data", {})
            print(f"Round lot cache keys ({len(round_lot_data.get('round_lot_sizes', {}))}): {list(round_lot_data.get('round_lot_sizes', {}).keys())[:10]}")
            
            # 检查 US 股票的 round lot
            us_tickers = [o.get("symbol") for o in us_jp_orders if o.get("symbol", "").endswith("US Equity")]
            print(f"\n=== US 股票 Round Lot 状态 ===")
            for ticker in us_tickers[:5]:
                rl = round_lot_data.get("round_lot_sizes", {}).get(ticker, "NOT_CACHED")
                print(f"  {ticker}: {rl}")
    except Exception as e:
        print(f"Round Lot API error: {e}")
    
    # 4. 手动计算 isOddLot
    print(f"\n=== 手动验证 isOddLot ===")
    for o in us_jp_orders[:10]:
        qty = o.get("quantity", 0)
        # 假设 round lot = 100
        is_odd_100 = (qty % 100) != 0
        print(f"  {o['symbol']}: Qty={qty}, %100={qty%100}, isOddLot(100)={is_odd_100}, Backend={o['isOddLot']}")
    
    # 5. 手动查询 COST 的 round lot
    print(f"\n=== 手动查询 COST US Equity 的 Round Lot ===")
    try:
        resp = requests.post(f"{BASE_URL}/api/debug/query-round-lot?ticker=COST%20US%20Equity", headers=headers, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
