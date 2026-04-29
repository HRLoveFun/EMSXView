import sqlite3
import pandas as pd
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = 'c:/Users/hrchen/Documents/EMSX/CostView/data/raw_fills.db'

def verify_single_route():
    conn = sqlite3.connect(DB_PATH)
    
    # query to get the raw data from April 2026
    query = """
    SELECT 
        OrderId, 
        RouteId, 
        StrategyType, 
        Broker, 
        TraderName,
        Amount,
        COUNT(FillId) as fill_count
    FROM raw_fills
    WHERE NyOrderCreateAsOfDateTime LIKE '2026-04%' OR source_date LIKE '202604%'
    GROUP BY OrderId, RouteId, StrategyType, Broker, TraderName, Amount
    """
    
    df = pd.read_sql(query, conn)
    
    if df.empty:
        print("No April 2026 data found in raw_fills.")
        return
    
    agg_df = df.groupby(['OrderId', 'RouteId']).agg(
        unique_strategies=('StrategyType', 'nunique'),
        unique_brokers=('Broker', 'nunique'),
        unique_traders=('TraderName', 'nunique'),
        unique_amounts=('Amount', 'nunique'),
        total_fills=('fill_count', 'sum')
    ).reset_index()
    
    multi_strategy = agg_df[agg_df['unique_strategies'] > 1]
    multi_broker = agg_df[agg_df['unique_brokers'] > 1]
    
    print(f"\nTotal (OrderId, RouteId) routes in April 2026: {len(agg_df)}")
    print(f"Routes with multiple StrategyTypes: {len(multi_strategy)}")
    print(f"Routes with multiple Brokers: {len(multi_broker)}")
    
    if not multi_strategy.empty:
        print("\n--- Example: Same Route with Multiple StrategyTypes ---")
        sample = multi_strategy.head(10)
        for _, row in sample.iterrows():
            order_id = row['OrderId']
            route_id = row['RouteId']
            print(f"\nOrderId: {order_id}, RouteId: {route_id}")
            
            detail = df[(df['OrderId'] == order_id) & (df['RouteId'] == route_id)]
            for _, d_row in detail.iterrows():
                print(f"  -> Strategy: {d_row['StrategyType']}, Broker: {d_row['Broker']}, Amount: {d_row['Amount']}, Fills: {d_row['fill_count']}")
                
    if not multi_broker.empty:
        print("\n--- Example: Same Route with Multiple Brokers ---")
        sample = multi_broker.head(10)
        for _, row in sample.iterrows():
            order_id = row['OrderId']
            route_id = row['RouteId']
            print(f"\nOrderId: {order_id}, RouteId: {route_id}")
            
            detail = df[(df['OrderId'] == order_id) & (df['RouteId'] == route_id)]
            for _, d_row in detail.iterrows():
                print(f"  -> Broker: {d_row['Broker']}, Strategy: {d_row['StrategyType']}, Fills: {d_row['fill_count']}")
                
    conn.close()

if __name__ == "__main__":
    verify_single_route()
