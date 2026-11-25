"""
Rate limiting (tiêu chí 7) — sliding window 60 giây, state trong Redis.

Mỗi API key có một sorted set trong Redis: member = request, score = thời điểm (giây).
  1. ZREMRANGEBYSCORE: xoá request cũ hơn 60 giây
  2. ZCARD: đếm request còn trong cửa sổ
  3. Đủ giới hạn → 429 + Retry-After; chưa đủ → ZADD request mới, EXPIRE 60 giây
Vì state nằm trong Redis nên mọi worker/instance dùng chung, restart agent không mất.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Không lưu key thật trong Redis — chỉ lưu bản băm
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    limit = settings.rate_limit_per_minute

    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zcard(bucket)
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit, "window_seconds": WINDOW_SECONDS},
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    pipe = r.pipeline()
    pipe.zadd(bucket, {f"{now}:{uuid.uuid4().hex}": now})
    pipe.expire(bucket, WINDOW_SECONDS)
    pipe.execute()
