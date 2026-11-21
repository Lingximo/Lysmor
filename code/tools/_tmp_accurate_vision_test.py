import asyncio, json, time, websockets, pathlib

async def main():
    tok = pathlib.Path(r"D:\你的数据目录\gate_token.txt").read_text(encoding="utf-8").strip()
    url = f"ws://127.0.0.1:8003/ws?sid=visiontest&nomem=1&t={tok}"
    t0 = time.time()
    async with websockets.connect(url, max_size=20_000_000) as ws:
        await ws.send(json.dumps({"text": "你看看这个"}, ensure_ascii=False))
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=40)
            except asyncio.TimeoutError:
                print("TIMEOUT", round(time.time() - t0, 2))
                break
            if isinstance(raw, bytes):
                print("BIN", len(raw), round(time.time() - t0, 2))
                continue
            data = json.loads(raw)
            print(data.get("type"), round(time.time() - t0, 2), str(data)[:220])
            if data.get("type") == "reply":
                break

asyncio.run(main())
