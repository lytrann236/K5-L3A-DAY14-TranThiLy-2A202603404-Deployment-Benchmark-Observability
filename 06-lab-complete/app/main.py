"""
Production AI Agent — Part 6 Final Project.

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "extra_fields", {}))
        return json.dumps(entry, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [handler]
logger.setLevel(settings.log_level)
logger.propagate = False


def log(event: str, **fields) -> None:
    logger.info(event, extra={"extra_fields": fields})


# ── Lifespan: khởi động và tắt an toàn (tiêu chí 11) ──
# uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` và thoát với exit code 0. Không tự đăng ký handler
# SIGTERM riêng để khỏi ghi đè handler của uvicorn.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd)
    yield
    log("shutdown", detail="SIGTERM received, in-flight requests finished")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log("request", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


# ── Xử lý lỗi: trả JSON rõ ràng, không lộ stack trace ──
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "error": "Invalid request body",
        "hint": 'Send JSON: {"question": "..."} (1-2000 characters)',
    })


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, exc: redis.RedisError):
    log("redis_unavailable", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log("unhandled_error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ── Endpoints ──
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 200 khi Redis kết nối được, 503 khi không."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)           # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                      # 402 khi hết DAILY_BUDGET_USD

    answer = llm_ask(body.question)

    # Mock LLM không trả số token → ước lượng ~2 token mỗi từ
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    cost = record_cost(input_tokens, output_tokens)
    log("ask", question_length=len(body.question), cost_usd=round(cost, 8))

    return {"question": body.question, "answer": answer}
