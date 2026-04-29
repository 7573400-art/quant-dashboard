import FinanceDataReader as fdr
import json
print("Downloading KRX List...")
df = fdr.StockListing('KRX')
krx_map = dict(zip(df['Code'], df['Name']))
with open("krx_mapping.json", "w", encoding="utf-8") as f:
    json.dump(krx_map, f, ensure_ascii=False)
print("Saved to krx_mapping.json")
