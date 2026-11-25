# Mission Answers — Day 14

## Part 1 — Localhost vs Production

### Exercise 1.1 · Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret**: `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL` có cả mật khẩu `password123` nằm trong code → push lên GitHub là lộ key.
2. **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thật, log in `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` → ai đọc được log là có key.
3. **Không quản lý cấu hình**: `DEBUG = True`, `MAX_TOKENS = 500` cố định trong code, muốn đổi phải sửa code và deploy lại.
4. **Dùng `print()` thay vì logging có cấu trúc**: không có mức log, không có thời gian, không parse được bằng công cụ gom log.
5. **Không có health check** (`/health`, `/ready`): agent treo hay crash thì nền tảng không biết để khởi động lại hoặc ngừng chuyển request vào.
6. **Port và host cố định**: `host="localhost"`, `port=8000`. Trong container phải nghe `0.0.0.0`; Railway/Render cấp cổng qua biến `PORT`.
7. **`reload=True`**: chế độ tự nạp lại code chỉ dùng khi dev, tốn tài nguyên và không ổn định khi chạy thật.
8. **Không xử lý tắt an toàn (SIGTERM)**: tắt container là cắt ngang request đang chạy.

### Exercise 1.2 · Chạy bản develop

```
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Nó chạy được, nhưng chưa sẵn sàng production: log server in ra cả API key (`[DEBUG] Using key: sk-hardcoded-...`), không có health check, chỉ nghe ở `localhost:8000`.

### Exercise 1.3 · So sánh develop và production

```
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":11.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:41:06.967903+00:00"}
$ curl http://localhost:8000/ready
{"ready":true}
```

Server nghe ở `0.0.0.0:8000` (không phải `localhost`). Log không in secret, chỉ cảnh báo `OPENAI_API_KEY not set — using mock LLM`.

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code | Đọc từ biến môi trường (`config.py`, `.env`) | Đổi cấu hình theo môi trường không cần sửa code; secret không nằm trong git |
| Secret | Ghi trong code và in ra log | Từ env, không log | Tránh lộ key qua GitHub hoặc qua log |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness) | Nền tảng biết khi nào restart container, khi nào chuyển request vào |
| Logging | `print()` | JSON có cấu trúc, không log secret | Dễ tìm kiếm, lọc theo trường trong Loki/Datadog |
| Shutdown | Đột ngột | Graceful: `lifespan` + xử lý SIGTERM | Request đang chạy được hoàn thành trước khi tắt |
| Host/Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud |
| Input | Query string, không kiểm tra | JSON, câu hỏi rỗng → 422 | Trả lỗi rõ ràng thay vì xử lý dữ liệu sai |


## Part 2 — Docker

### Exercise 2.1 · Đọc `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python đầy đủ (theo comment trong file khoảng 1 GB), có sẵn cả công cụ build.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó đều chạy trong thư mục này của container.
3. **Vì sao `COPY requirements.txt` trước `COPY app.py`:** Docker build theo từng lớp và cache lại lớp nào không đổi. Khi chỉ sửa `app.py` mà `requirements.txt` giữ nguyên, Docker dùng lại lớp `pip install` đã cache, build lại chỉ vài giây. Nếu copy code trước rồi mới `pip install`, mỗi lần sửa code đều phải cài lại toàn bộ thư viện.
4. **CMD và ENTRYPOINT:** cả hai là lệnh chạy khi container khởi động. `CMD ["python", "app.py"]` là lệnh mặc định, **bị thay thế** nếu gõ thêm lệnh sau `docker run my-agent:develop …`. `ENTRYPOINT` là lệnh **cố định**; phần gõ thêm chỉ được nối vào làm tham số. Thường dùng `ENTRYPOINT` cho chương trình chính, `CMD` cho tham số mặc định.

### Exercise 2.2 · Build và chạy bản develop

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run --rm -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ docker images my-agent:develop
IMAGE              ID             DISK USAGE   CONTENT SIZE
my-agent:develop   53d49fbff1a3       1.67GB          415MB
```

Lần build đầu mất ~478 s, gần hết là để tải base image `python:3.11` (lớp lớn nhất 227 MB).

### Exercise 2.3 · Multi-stage `02-docker/production/Dockerfile`

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài thêm công cụ build (`gcc`, `libpq-dev`) rồi `pip install --user` các thư viện vào `/root/.local`. Stage này chỉ dùng để **cài đặt**, không đem đi deploy.
- **Stage 2 (`runtime`):** bắt đầu lại từ `python:3.11-slim` sạch, chỉ chép sang **thư viện đã cài** (`COPY --from=builder /root/.local …`), code `main.py` và `utils/mock_llm.py`. Ngoài ra tạo user thường `appuser` (không chạy bằng root), có `HEALTHCHECK` gọi `/health`, chạy `uvicorn` với 2 worker.
- **Vì sao image nhỏ hơn:** (1) base `slim` thay cho bản Python đầy đủ; (2) `gcc`, `libpq-dev` và cache apt chỉ nằm ở stage builder, **không có mặt trong image cuối**; (3) `--no-cache-dir` không lưu cache pip. Image cuối chỉ còn thứ cần để **chạy**.

```
$ docker images | grep my-agent
my-agent:advanced   10ea4b94a7ae   265MB    57.5MB
my-agent:develop    53d49fbff1a3   1.67GB   415MB
```

| Image | DISK USAGE | CONTENT SIZE (nén) |
|---|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | 1,67 GB ≈ 1.670 MB | 415 MB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 265 MB | 57,5 MB |
| Chênh lệch | giảm ≈ **84,1%** ((1.670 − 265) / 1.670) | giảm ≈ 86,1% |

Image production < 500 MB. Build bản production chỉ mất ~22 s vì base `python:3.11-slim` đã tải sẵn; lần build lại qua `docker compose` mọi lớp đều `CACHED`, chỉ 0,3 s.

### Exercise 2.4 · Docker Compose stack (`02-docker/production/docker-compose.yml`)

Chạy: `docker compose -p k5-day14-docker up -d --build` (tạo `.env.local` rỗng trước). 4 service được start:

```
                 Internet / máy host
                         │  cổng 80 (443)
                 ┌───────▼────────┐
                 │  nginx:alpine  │  reverse proxy / load balancer
                 └───────┬────────┘
                         │  proxy_pass http://agent_backend (cổng 8000, mạng nội bộ)
                 ┌───────▼────────┐
                 │     agent      │  FastAPI (image multi-stage, target runtime)
                 └───┬────────┬───┘
     redis://redis:6379 │        │ http://qdrant:6333
            ┌──────────▼──┐  ┌──▼──────────────┐
            │ redis:7     │  │ qdrant v1.9.0   │
            │ cache/rate  │  │ vector database │
            └─────────────┘  └─────────────────┘
         tất cả chung mạng bridge `internal`; chỉ nginx mở cổng ra ngoài
```

- Các service gọi nhau **bằng tên service** (`redis`, `qdrant`, `agent`) qua mạng `internal`; agent **không mở cổng ra ngoài**, mọi request phải đi qua Nginx.
- `depends_on` + `condition: service_healthy`: agent chỉ start khi Redis và Qdrant đã healthy.
- Redis và Qdrant lưu dữ liệu vào volume (`redis_data`, `qdrant_data`) nên không mất khi restart.

Kết quả:
```
$ docker compose -p k5-day14-docker ps
k5-day14-docker-agent-1    Up (healthy)   8000/tcp
k5-day14-docker-nginx-1    Up             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   Up (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    Up (healthy)   6379/tcp
$ curl http://localhost/health
{"status":"ok","uptime_seconds":18.9,"version":"2.0.0","timestamp":"2026-11-25T08:18:58.658579"}
$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```


