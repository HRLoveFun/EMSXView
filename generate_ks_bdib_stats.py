"""生成 KS exchange 的 raw_bdib 按交易日统计 Excel.

输出: 每个有 BDIB 数据的交易日, 及其当天唯一 equ_ticker 数量.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from DataPipeline.config import Config


def generate_ks_bdib_stats(output_path: Path | str | None = None) -> Path:
    """查询 raw_bdib.db 中 exchange=KS 的交易日维度唯一 ticker 统计并导出 Excel."""
    db_path = Config.RAW_BDIB_DB
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "ks_bdib_ticker_stats.xlsx"
    else:
        output_path = Path(output_path)

    # 使用 pandas 直接读取 SQLite 查询结果
    conn = sqlite3.connect(str(db_path))
    query = """
        SELECT
            order_as_of_date AS trade_date,
            COUNT(DISTINCT equ_ticker) AS unique_ticker_count
        FROM raw_bdib
        WHERE equ_ticker LIKE '% KS Equity'
        GROUP BY order_as_of_date
        ORDER BY order_as_of_date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    # 添加合计行
    total_row = pd.DataFrame({
        "trade_date": ["合计"],
        "unique_ticker_count": [df["unique_ticker_count"].sum()],
    })
    df_with_total = pd.concat([df, total_row], ignore_index=True)

    # 写入 Excel
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_with_total.to_excel(writer, sheet_name="KS_BDIB_Stats", index=False)

        # 简单格式化: 列宽自适应
        worksheet = writer.sheets["KS_BDIB_Stats"]
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except Exception:
                    pass
            adjusted_width = min(max_length + 2, 30)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    return output_path


if __name__ == "__main__":
    output = generate_ks_bdib_stats()
    print(f"Generated: {output}")
    print(f"Size: {output.stat().st_size / 1024:.1f} KB")
