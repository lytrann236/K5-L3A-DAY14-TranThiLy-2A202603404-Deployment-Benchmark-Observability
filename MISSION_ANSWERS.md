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

## Part 3 — Cloud Deployment

**Public URL:** https://agent-production-3b4bac03.up.railway.app (Railway, Root Directory `06-lab-complete`, service `agent` + Redis)

Kết quả kiểm tra trên URL public: `/health` 200 · `/ready` 200 · `/ask` không key 401 · `/ask` có key 200. `check_production_ready.py --public-url` → PASS 12/12 (44/44 checks). Chi tiết trong DEPLOYMENT.md.

**So sánh railway.toml và render.yaml**
- `railway.toml` chỉ cấu hình build/deploy cho **một** service (builder DOCKERFILE, healthcheckPath, restart policy). Redis và biến môi trường phải tạo trên dashboard.
- `render.yaml` là Blueprint mô tả **cả hạ tầng**: web service (runtime docker, rootDir, healthCheckPath) và Key Value Redis. Nó còn nối biến với nhau (`REDIS_URL` lấy từ `fromService`), và secret dùng `generateValue: true` nên không ghi giá trị vào file.
- Điểm chung: đều build từ Dockerfile, đều health check `/health`, app đọc `PORT` do platform cấp.
- Ghi chú thực tế: Railway đã ngừng Config-as-code cho service mới, nên khi deploy mình phải đặt Builder, Healthcheck Path, Root Directory trên dashboard. `railway.toml` vẫn giữ trong repo.

**Cloud Run CI/CD (`03-cloud-deployment/production-cloud-run/`)**
- `cloudbuild.yaml` là pipeline 4 bước nối tiếp nhau bằng `waitFor`: **test** (cài requirements và chạy `pytest tests/`; test fail thì dừng, không build) → **build** Docker image, gắn 2 tag `:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tái sử dụng layer → **push** lên Container Registry → **deploy** lên Cloud Run bằng đúng image `:$COMMIT_SHA` (truy vết và rollback theo commit được).
- Lúc deploy: region `asia-southeast1`, `--min-instances=1` để tránh cold start, `--max-instances=10` để giới hạn scale và chi phí, 512Mi / 1 CPU, timeout 60s. Secret lấy từ **Secret Manager** (`--set-secrets`) chứ không ghi vào file.
- `service.yaml` là IaC khai báo cùng service đó (Knative): autoscale 1–10 instance, `containerConcurrency: 80`, resource requests/limits, env và secret qua `secretKeyRef`. **livenessProbe** gọi `/health`, còn **startupProbe** gọi `/ready`: Cloud Run chỉ chuyển traffic khi app đã sẵn sàng (Redis kết nối được).
- So với Railway: Cloud Run có test làm "cổng chặn" trước khi deploy và cấu hình hạ tầng nằm hết trong code; Railway thì build và deploy ngay khi push, không có bước test.


## Part 4 — API Security

### Exercise 4.1 · API key (`04-api-gateway/develop/app.py`)

- **Kiểm tra key ở đâu:** hàm `verify_api_key` đọc header `X-API-Key` (qua `APIKeyHeader`), được gắn vào `/ask` bằng `Depends(verify_api_key)`. `/` và `/health` để công khai.
- **Sai key thì sao:** thiếu key → **401** `Missing API key`; có key nhưng sai → **403** `Invalid API key`. Endpoint không chạy tiếp.
- **Rotate key:** key đọc từ biến môi trường `AGENT_API_KEY`, nên đổi giá trị biến trên server rồi khởi động lại, không cần sửa code. Muốn đổi không gián đoạn thì cho phép cùng lúc key cũ và key mới trong một thời gian ngắn.

Chạy với `AGENT_API_KEY=secret-key-123 python app.py`:

```
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -H "X-API-Key: secret-key-123" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -H "X-API-Key: sai-key" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}
```

Ghi chú: lần đầu tôi gửi câu hỏi qua query (`?question=Hello`) kèm key đúng thì nhận **500 Internal Server Error**, vì `/ask` đọc JSON body (`await request.json()`) mà body rỗng. App nên bắt lỗi này và trả 422 thay vì 500 — tôi áp dụng điều này ở Part 6.

### Exercise 4.2 · JWT (`04-api-gateway/production/`)

Luồng: `POST /auth/token` với `{"username":"student","password":"demo123"}` → server kiểm tra mật khẩu, trả `access_token` (JWT ký bằng secret, chứa `username`, `role`, hết hạn sau 60 phút). Client gửi lại token ở header `Authorization: Bearer <token>`; server chỉ cần kiểm tra chữ ký và hạn, không phải tra mật khẩu mỗi lần.

```
$ TOKEN=$(curl -s -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
$ echo "Token dài ${#TOKEN} ký tự"
Token dài 168 ký tự          # token không in ra để tránh lộ
```

### Exercise 4.3 · Rate limiting (`rate_limiter.py`)

- **Thuật toán:** sliding window — mỗi user giữ một hàng đợi các mốc thời gian request; mỗi lần gọi bỏ các mốc cũ hơn 60 giây rồi đếm số còn lại.
- **Giới hạn:** user thường 10 request / 60 giây; admin 100 request / 60 giây.
- **Bypass cho admin:** không bỏ hẳn giới hạn mà chọn limiter theo `role` trong JWT (`rate_limiter_admin if role == "admin" else rate_limiter_user`), admin có mức cao hơn 10 lần.

```
$ for i in $(seq 1 12); do curl -s -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ... | head -1; done
Lần 1–10:  HTTP/1.1 200 OK
Lần 11:    HTTP/1.1 429 Too Many Requests
Lần 12:    HTTP/1.1 429 Too Many Requests

$ curl -s -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Test 13"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 52
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":52}}
```

Hạn chế: bộ đếm nằm trong RAM của một process, chạy nhiều instance thì mỗi instance đếm riêng → phải chuyển sang Redis (làm ở Part 6).

### Exercise 4.4 · Cost guard (`cost_guard.py`)

- Mỗi request ghi số token vào và ra của user, đổi ra tiền theo giá GPT-4o-mini ($0,15/1M input, $0,60/1M output).
- **Trước** khi gọi LLM, `check_budget` kiểm tra: tổng chi trong ngày của user ≥ $1 → **402 Payment Required**; tổng toàn hệ thống ≥ $10/ngày → **503**. Dùng tới 80% thì ghi log cảnh báo.
- Bản ghi gắn với ngày (`%Y-%m-%d`), sang ngày mới thì tự tính lại từ 0.
- Cách làm với Redis (yêu cầu của bài, $10/tháng): key `budget:<user_id>:<YYYY-MM>`; đọc số đã chi, nếu `hiện tại + chi phí ước tính > 10` thì từ chối; nếu không thì `INCRBYFLOAT` cộng thêm và đặt hạn hết hạn khoảng 32 ngày — sang tháng mới tên key đổi nên tự reset, và mọi instance dùng chung một bộ đếm.
- **Vì sao cần cả hai:** rate limit chặn gọi **quá nhanh** (spam, DoS); cost guard chặn **tiêu quá tiền** — một user gọi chậm nhưng câu hỏi dài vẫn có thể đốt hết ngân sách mà không chạm rate limit.


## Part 5 — Scaling & Reliability

### Exercise 5.1 · Health checks (`05-scaling-reliability/develop/app.py`)

- **`/health` (liveness):** "process còn sống không?" — trả 200 kèm uptime, version, kiểm tra RAM (`psutil`). Nền tảng gọi định kỳ; lỗi hoặc timeout → restart container.
- **`/ready` (readiness):** "đã sẵn sàng nhận request chưa?" — 200 khi đã khởi động xong, 503 khi đang khởi động hoặc đang tắt. Load balancer dựa vào đây để quyết định có chuyển request vào không.
- **Khác nhau:** liveness sai → **restart**; readiness sai → **tạm ngừng gửi request** nhưng không restart (ví dụ đang chờ Redis).

```
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":23.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:29:44.522482+00:00","checks":{"memory":{"status":"ok","used_percent":62.5}}}
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

### Exercise 5.2 · Graceful shutdown

Code: middleware đếm `_in_flight_requests`; khi nhận SIGTERM, `lifespan` đặt `_is_ready = False` (ngừng nhận việc mới) rồi chờ các request đang chạy xong (tối đa 30 s) mới thoát.

Test: gửi một request rồi `kill -TERM` ngay sau 0,2 s:

```
$ PID=$(lsof -ti tcp:8000 -sTCP:LISTEN | head -1)
$ curl -s -X POST "http://localhost:8000/ask?question=Long%20task" & sleep 0.2; kill -TERM $PID; wait
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Log server:
```
INFO:     Shutting down
INFO:     127.0.0.1:56081 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO Received signal 15 — uvicorn will handle graceful shutdown
```

→ Request đang chạy vẫn nhận **200** dù đã có lệnh tắt; tắt xong mới thoát process.

### Exercise 5.3 · Stateless design

Lưu lịch sử hội thoại trong biến Python (`conversation_history = {}`) thì mỗi instance có RAM riêng: request 1 vào instance A, request 2 vào instance B → B không thấy lịch sử A đã lưu; instance restart là mất hết. Bản production lưu state trong **Redis** theo key session, mọi instance đọc/ghi cùng một chỗ, instance nào trả lời cũng được.

### Exercise 5.4 · Load balancing (3 agent + Nginx + Redis)

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
k5-day14-scaling-agent-1   Up (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up (healthy)   6379/tcp
```

Nginx (cổng 8080) phân phối request tới 3 agent; agent không mở cổng ra ngoài. Lần đầu tôi chạy test ngay khi container vừa start thì nhận **HTTP 502 Bad Gateway** vì cả 3 agent còn `health: starting` — đợi tới `healthy` mới chạy lại. Đây đúng là lý do cần readiness check: chỉ chuyển request tới instance đã sẵn sàng.

### Exercise 5.5 · Test stateless

```
$ python3 test_stateless.py
Session ID: 2a2b9921-92c0-41ff-8af0-6f22892b8232
Request 1: [instance-613b72]  Q: What is Docker?
Request 2: [instance-613b72]  Q: Why do we need containers?
Request 3: [instance-6862b9]  Q: What is Kubernetes?
Request 4: [instance-613b72]  Q: How does load balancing work?
Request 5: [instance-306a28]  Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-6862b9', 'instance-613b72', 'instance-306a28'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

Giải thích: 5 câu của **cùng một session** được 3 instance khác nhau trả lời, nhưng lịch sử vẫn đủ 10 tin nhắn (5 user + 5 assistant) theo đúng thứ tự → state nằm trong Redis, không trong RAM của instance nào. Script không tự tắt instance; nếu tắt một agent, Nginx chuyển sang 2 agent còn lại và lịch sử vẫn còn vì Redis không bị ảnh hưởng.


## Part 6 — Final Project (`06-lab-complete/`)

`python check_production_ready.py` (bản đầy đủ, có Docker):

```
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Một số số đo từ lần chấm: image 262 MB; build 10 s; 429 sau 5 request (`RATE_LIMIT_PER_MINUTE=5`), restart agent vẫn 429 (state trong Redis); 402 ở request đầu với budget 0,000001 USD; `docker stop` exit code 0 trong 0,5 s.

Tóm tắt thiết kế:
- `/health` không đụng Redis (liveness), `/ready` ping Redis → 503 khi mất kết nối (readiness).
- Rate limit: sliding window 60 s bằng Redis sorted set theo API key (băm SHA-256, không lưu key thật), có header `Retry-After`.
- Cost guard: cộng chi phí theo token vào `budget:<ngày UTC>` (`INCRBYFLOAT`), kiểm tra trước khi gọi LLM.
- Lỗi đầu vào trả 422 JSON, lỗi Redis trả 503, lỗi khác trả 500 JSON — không lộ stack trace.
- Graceful shutdown: dựa vào uvicorn + `lifespan`; CMD dùng `exec uvicorn` để uvicorn là PID 1.












## AI log

- Part 1: hỏi Claude cách chạy bản develop/production và cách trình bày bảng so sánh. Tôi tự chạy lệnh, đối chiếu từng anti-pattern với dòng code trong `develop/app.py` và `production/app.py`.
- Part 2: nhờ Claude giải thích Dockerfile develop và multi-stage, viết nháp câu trả lời 2.1 và 2.3. Tôi đọc lại từng dòng Dockerfile để đối chiếu; số đo image là số tôi tự chạy `docker images`.
- Part 3: Claude hướng dẫn các bước deploy trên Railway dashboard, viết lệnh test (chỉ in mã HTTP, không in key) và soạn DEPLOYMENT.md từ kết quả mình tự chạy.
- Part 4: Claude giải thích lỗi 500 (gửi query thay vì JSON body), cách lấy JWT mà không in token, và đọc `rate_limiter.py` / `cost_guard.py` để viết phần trả lời. Mọi output 401/200/403/429 là tôi tự chạy.
- Part 5: Claude hướng dẫn lệnh test SIGTERM và giải thích lỗi 502 (agent chưa healthy). Output là tôi tự chạy.
- Part 6: Claude viết code cho 12 TODO trong `06-lab-complete/` (app/*.py, Dockerfile, compose, .dockerignore, .env.example, railway.toml, render.yaml). Tôi đọc từng file, chạy `check_production_ready.py` trên máy mình để kiểm tra và đọc lại phần giải thích từng file để tự trình bày được.
- Part 7 (CP7): Claude hướng dẫn chạy load test/eval, chỉ ra nguyên nhân security-02 & scaling-03 sai (retrieval không có tài liệu khớp), viết 2 entry KB bổ sung trong develop/utils/mock_llm.py, và soạn mục 1–3 BENCHMARK_REPORT.md từ số liệu mình tự chạy.