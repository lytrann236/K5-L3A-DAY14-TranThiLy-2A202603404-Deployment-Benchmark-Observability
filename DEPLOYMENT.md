# DEPLOYMENT — Day 14 Production Agent

## 1. Thông tin deploy

| Mục | Giá trị |
|---|---|
| Public URL | https://agent-production-3b4bac03.up.railway.app |
| Platform | Railway (gói Trial, miễn phí) |
| Region | US East (Virginia) |
| Source | GitHub repo này, branch `main`, Root Directory `06-lab-complete` |
| Builder | Dockerfile (multi-stage, `python:3.11-slim`, user non-root) |
| Services | `agent` (FastAPI + uvicorn 2 workers) và `Redis` (Railway database) |
| Health check | `/health` (liveness), `/ready` (readiness, kiểm tra Redis) |

## 2. Các bước đã làm

1. Railway → New Project → **Empty Service**, đổi tên thành `agent`. Không tạo trực tiếp từ GitHub repo vì tên repo vượt giới hạn độ dài tên service.
2. Settings → Source → **Connect Repo** → chọn repo này, branch `main`.
3. Settings → **Root Directory** = `06-lab-complete`.
4. Settings → **Healthcheck Path** = `/health`, Restart Policy = On Failure.
5. **+ Add → Database → Redis**.
6. Tab **Variables** của `agent`: đặt 4 biến (xem mục 3).
7. Settings → Networking → **Generate Domain**.
8. Bấm **Deploy**. Service chuyển sang trạng thái **Online**.

> Ghi chú: Railway đã ngừng cho service mới bật *Config-as-code*, nên `railway.toml` vẫn nằm trong repo (builder DOCKERFILE + healthcheckPath `/health`) nhưng các thiết lập tương đương được đặt trực tiếp trên dashboard.

## 3. Biến môi trường

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | *(bí mật, không ghi ở đây)* | Tạo bằng `openssl rand -hex 32`, chỉ lưu trong Railway Variables |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Railway tự thay bằng URL của service Redis |
| `ENVIRONMENT` | `production` | |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `PORT` | do Railway cấp | App đọc `${PORT:-8000}` |

Không có file `.env` hay secret nào được commit vào repo.

## 4. Kiểm tra

```bash
export BASE="https://agent-production-3b4bac03.up.railway.app"
read -s "AGENT_API_KEY?API key: "; echo; export AGENT_API_KEY   # zsh, key không hiện ra màn hình

curl -s -o /dev/null -w '%{http_code}\n' $BASE/health
curl -s -o /dev/null -w '%{http_code}\n' $BASE/ready
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/ask \
  -H 'Content-Type: application/json' -d '{"question":"hi"}'
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' \
  -d '{"question":"What is Docker?"}'
```

Kết quả thực tế (2026-11-25):

| Kiểm tra | Mong đợi | Thực tế |
|---|---|---|
| `GET /health` | 200 | **200** |
| `GET /ready` | 200 | **200** |
| `POST /ask` không có key | 401 | **401** |
| `POST /ask` có key đúng | 200 | **200** |

Checker chính thức:

```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

Kết quả: **PASS 12/12 tiêu chí · 44/44 checks**, gồm cả dòng
`Public URL: GET https://agent-production-3b4bac03.up.railway.app/health → 200`.

## 5. Ảnh chụp màn hình

- `screenshots/dashboard.png`: Railway project gồm `agent` (Online) và `Redis`, tab Variables với giá trị bị che
- `screenshots/running.png`: tab Deployments, bản deploy mới nhất ở trạng thái Active/Success
- `screenshots/test.png`: Terminal với 4 mã HTTP và kết quả PASS 12/12

## 6. Vận hành

- **Redeploy:** push lên `main` thì Railway tự build và deploy lại.
- **Đổi API key:** sửa `AGENT_API_KEY` trong Variables rồi Deploy. Key cũ hết hiệu lực ngay.
- **Rollback:** tab Deployments → chọn bản cũ → Redeploy.
- **Chi phí:** gói Trial ($5 / 30 ngày). Sau khi chấm bài có thể xoá project để không bị tính phí.
