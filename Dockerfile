FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ ./tools/
COPY workflows/ ./workflows/
COPY app.py .
COPY .streamlit/ ./.streamlit/

RUN mkdir -p .tmp logs

# 修复 akshare 1.18.x 中部分美股符号的 read-only index 赋值 bug
RUN python3 -c "\
import importlib.util, sys; \
spec = importlib.util.find_spec('akshare.stock.stock_us_sina'); \
f = open(spec.origin); c = f.read(); f.close(); \
old = 'new_range.index.values[0] = pd.to_datetime(str(data_df.index.date[0]))'; \
new = 'idx_vals = new_range.index.values.copy()\n            idx_vals[0] = pd.to_datetime(str(data_df.index.date[0]))\n            new_range.index = idx_vals'; \
out = c.replace(old, new) if old in c else c; \
f = open(spec.origin, 'w'); f.write(out); f.close(); \
print('akshare patch applied' if old in c else 'akshare already patched')"

CMD ["python3", "tools/scheduler.py"]
