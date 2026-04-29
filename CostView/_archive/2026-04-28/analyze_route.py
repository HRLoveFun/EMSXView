import sqlite3
import pandas as pd
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = 'c:/Users/hrchen/Documents/EMSX/CostView/data/raw_fills.db'

def analyze_single_route():
    conn = sqlite3.connect(DB_PATH)
    
    query = """
    SELECT 
        FillId,
        DateTimeOfFill,
        StrategyType,
        Broker,
        FillShares
    FROM raw_fills
    WHERE OrderId = '5158361' AND RouteId = '2'
    ORDER BY DateTimeOfFill
    """
    
    df = pd.read_sql(query, conn)
    
    print("Detailed Sequence:")
    pd.set_option('display.max_rows', 100)
    pd.set_option('display.width', 1000)
    print(df)
    
    conn.close()

if __name__ == "__main__":
    analyze_single_route()
