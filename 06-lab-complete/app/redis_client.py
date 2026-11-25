"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- redis.from_url() chỉ tạo client, CHƯA mở kết nối → app vẫn khởi động được khi Redis chưa có.
- Timeout ngắn để /ready trả 503 nhanh khi Redis chết, thay vì treo request.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """True nếu ping được Redis, False nếu không kết nối được (dùng cho GET /ready)."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
