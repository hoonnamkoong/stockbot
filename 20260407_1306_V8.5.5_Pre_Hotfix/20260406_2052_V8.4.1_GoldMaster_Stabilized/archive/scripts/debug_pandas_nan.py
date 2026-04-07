
import pandas as pd
import numpy as np
import json

df = pd.DataFrame({
    'a': [1, 2, np.nan],
    'b': ['x', 'y', np.nan],
    'c': [1.1, np.nan, 3.3]
})

print("Original:")
print(df)

df_fixed = df.where(pd.notnull(df), None)
print("\nFixed:")
print(df_fixed)

records = df_fixed.to_dict('records')
print("\nRecords:")
print(records)

print("\nJSON Dump:")
print(json.dumps(records))
