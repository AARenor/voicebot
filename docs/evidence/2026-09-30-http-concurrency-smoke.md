# Production HTTP concurrency smoke — 2026-09-30

This is evidence for the diagnostic HTTP turn path only. It does **not** prove
SIP, LiveKit rooms, agent workers, carrier channels, or phone concurrency.

The command ran inside the production voicebot container. It read the operator
token from the container environment and never printed it.

```python
import asyncio, os, time
import httpx

async def main():
    headers = {"Authorization": "Bearer " + os.environ["OPERATOR_TOKEN"]}
    async with httpx.AsyncClient(timeout=90) as client:
        async def one(i):
            started = time.monotonic()
            response = await client.post(
                "http://127.0.0.1:8000/api/turn",
                headers=headers,
                json={"text": f"Vasta ühe sõnaga: tere. Katse {i}", "language": "et"},
            )
            payload = response.json()
            return {
                "id": i,
                "status": response.status_code,
                "seconds": round(time.monotonic() - started, 2),
                "audio": bool(payload.get("audio_b64")),
                "fallback": payload.get("fallback_used"),
            }

        started = time.monotonic()
        results = await asyncio.gather(*(one(i) for i in range(1, 4)))
        print({"wall_seconds": round(time.monotonic() - started, 2), "results": results})

asyncio.run(main())
```

Sanitized output:

```text
wall_seconds=3.09
id=1 status=200 seconds=1.77 audio=true fallback=false
id=2 status=200 seconds=3.06 audio=true fallback=false
id=3 status=200 seconds=2.07 audio=true fallback=false
```

Acceptance demonstrated: three HTTP requests overlapped and each produced
audio. Remaining gates are listed in
[`../operations/concurrency-and-capacity.md`](../operations/concurrency-and-capacity.md).
