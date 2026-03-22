import sys
sys.path.append("/home/sajithindra/Projects/ryuk.ai")

import pickletools
import io

filepath = "/home/sajithindra/Projects/ryuk.ai/failed_payload.pkl"
try:
    with open(filepath, "rb") as f:
        data = f.read()
except Exception as e:
    print(f"File read error: {e}")
    sys.exit(1)

outpath = "/home/sajithindra/Projects/ryuk.ai/failed_payload_dis.txt"
with open(outpath, "w") as f:
    pickletools.dis(data, out=f)
    
print(f"Disassembly written to {outpath}")

