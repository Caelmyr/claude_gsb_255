"""验证「调优预览」与「正式运行」分离：预览不写历史、不进正式结果列表。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from app import create_app

app = create_app()
client = app.test_client()

# -- 准备一张测试图 -----------------------------------------------------------
img = Image.new("RGB", (320, 240))
px = img.load()
for y in range(240):
    for x in range(320):
        px[x, y] = (x % 256, y % 256, (x + y) % 256)
buf = io.BytesIO()
img.save(buf, "PNG")
buf.seek(0)

r = client.post("/api/images", data={"files": (buf, "verify.png")},
                content_type="multipart/form-data")
image_id = r.get_json()["saved"][0]["id"]

def counts():
    h = client.get("/api/history").get_json()["history"]
    res = client.get("/api/results").get_json()["results"]
    return len(h), len(res)

h0, r0 = counts()
print(f"基线: history={h0} results={r0}")

# -- 模拟拖滑杆：连续多次预览（不同参数） -------------------------------------
ok = True
for amount in (10, 25, 40, 55, 70):
    resp = client.post("/api/preview", json={
        "image_id": image_id,
        "nodes": [{"id": "t1", "type": "brightness", "params": {"amount": amount}, "inputs": []}],
    })
    ct = resp.headers.get("Content-Type", "")
    assert resp.status_code == 200 and ct.startswith("image/png"), (resp.status_code, ct)
    assert len(resp.data) > 1000, "预览图内容异常"
print("5 次预览均返回 image/png ✔")

h1, r1 = counts()
assert (h1, r1) == (h0, r0), f"预览污染了历史/结果: history {h0}->{h1}, results {r0}->{r1}"
print(f"预览后: history={h1} results={r1} —— 均未增长 ✔")

# -- 同参数再次预览应命中进程内缓存 -------------------------------------------
resp = client.post("/api/preview", json={
    "image_id": image_id,
    "nodes": [{"id": "t1", "type": "brightness", "params": {"amount": 70}, "inputs": []}],
})
assert resp.headers.get("X-Cache-Hit") == "1", dict(resp.headers)
print("重复参数预览 X-Cache-Hit=1 ✔")

# -- 预览错误路径 -------------------------------------------------------------
resp = client.post("/api/preview", json={"image_id": image_id})
assert resp.status_code == 400 and "error" in resp.get_json()
resp = client.post("/api/preview", json={"image_id": "no-such", "nodes": []})
assert resp.status_code == 404 and "error" in resp.get_json()
resp = client.post("/api/preview", json={
    "image_id": image_id,
    "nodes": [{"id": "t1", "type": "no-such-node", "params": {}, "inputs": []}],
})
assert resp.status_code == 400 and "error" in resp.get_json()
print("错误路径（缺参数 400 / 图像不存在 404 / 非法节点 400）✔")

# -- 正式运行仍然写历史、进结果列表 -------------------------------------------
resp = client.post("/api/run", json={
    "image_id": image_id,
    "nodes": [{"id": "t1", "type": "brightness", "params": {"amount": 70}, "inputs": []}],
    "pipeline_name": "正式运行",
})
body = resp.get_json()
assert resp.status_code == 200 and body.get("result_id"), body
h2, r2 = counts()
assert h2 == h1 + 1 and r2 == r1 + 1, f"正式运行未记录: history {h1}->{h2}, results {r1}->{r2}"
entry = client.get("/api/history").get_json()["history"][0]
assert entry["pipeline_name"] == "正式运行", entry["pipeline_name"]
print(f"正式运行: history {h1}->{h2}, results {r1}->{r2}，最新历史为「正式运行」 ✔")

print("\n全部验证通过 ✔")
