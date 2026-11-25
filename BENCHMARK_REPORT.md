# Benchmark & Observability Report — Day 14

**Họ tên:** Trần Thị Lý — 2A202603404
**Ngày chạy:** 2026-11-25
**Môi trường:** MacBook Apple M2, macOS, Python 3.13, Docker Desktop (8 CPU / 7.7 GB RAM). Bước develop chạy local không qua Docker: mỗi agent là 1 process `python app.py`.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Một lần gọi LLM bình thường mất khoảng 150–230 ms, nên 500 ms chừa đủ chỗ cho retrieval và jitter. Đặt theo p95 chứ không theo average vì average che mất tail latency (xem 2.2). |
| Error rate `/ask` | < 2 % | Upstream LLM có khoảng 1% lỗi 503 ngẫu nhiên (`MOCK_ERROR_RATE=0.01`), nên 2% là error budget vừa đủ cho lỗi nền mà vẫn bắt được sự cố thật. |
| Accuracy trên golden dataset | ≥ 80 % | Ngưỡng quality gate mặc định của `run_eval.py`. Kèm điều kiện không có câu nào regression so với baseline. Sau khi sửa KB, mình chạy gate với `--min-accuracy 1.0` để chứng minh đạt 23/23. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency $c --out reports/load_v2_c${c}.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.03 | 195.6 | 223.4 | 1699.7 | 0.33% (1/300) | ✅ p95 · ✅ error |
| 10 | 39.14 | 189.2 | 217.4 | 1689.8 | 2.00% (6/300) | ✅ p95 · ✅ error |
| 50 | 109.05 | 194.1 | 235.4 | 1670.8 | 2.67% (8/300) | ✅ p95 · ❌ error |
| 100 | 56.47 | 561.8 | 3559.8 | 3858.8 | 0.33% (1/300) | ❌ p95 · ✅ error |

**Nhận xét:** RPS chỉ tăng gần tuyến tính ở vùng tải thấp. Từ 1 lên 10, RPS tăng khoảng 9,7 lần (4.03 → 39.14) trong khi p50 gần như không đổi (khoảng 190 ms). Theo định luật Little, RPS ≈ concurrency / latency: latency giữ nguyên thì RPS tăng theo concurrency. Từ 10 lên 50, RPS chỉ tăng khoảng 2,8 lần (lên 109.05), thấp hơn nhiều so với mức tuyến tính (khoảng 5 lần), nghĩa là hệ thống bắt đầu chạm giới hạn. Ở 100, RPS **giảm** còn 56.47 và p50 tăng từ 194 lên 562 ms, p95 từ 235 lên 3560 ms. Agent đã **bão hoà**: một process uvicorn duy nhất không xử lý kịp, request phải xếp hàng (ở socket backlog và event loop), nên thời gian chờ cộng thẳng vào latency. Tăng thêm concurrency lúc này chỉ làm hàng đợi dài ra chứ không tăng throughput. Muốn tăng tiếp phải scale ngang (nhiều worker hoặc instance, xem mục 5).

Error rate dao động 0.33–2.67% nhưng chỉ ứng với 1–8 request trên 300, chủ yếu là lỗi 503 ngẫu nhiên của mock LLM (khoảng 1%), không tăng đều theo tải. Với mẫu 300 request, vài lỗi đã đủ làm thay đổi kết quả PASS/FAIL của SLO 2%. Mức c=50 FAIL error rate nên được xem là nhiễu thống kê hơn là dấu hiệu quá tải. Muốn kết luận chắc chắn cần chạy nhiều request hơn hoặc lặp lại nhiều lần.

### 2.2 Tail latency

Lệnh: restart agent v2 với `MOCK_SLOW_RATE=<x>`, rồi `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.8 | 218.3 | 225.8 |
| 0.03 (mặc định) | 214.7 | 218.7 | 1702.5 |
| 0.1 | 360.7 | 1690.2 | 1713.6 |

(Kèm theo: RPS lần lượt là 102.11 / 75.48 / 45.37; p50 lần lượt là 188.3 / 189.8 / 192.6 ms.)

**Nhận xét:** **p99 nhạy nhất.** Chỉ cần 3% request chậm, p99 đã nhảy từ 226 lên 1703 ms (khoảng 7,5 lần), trong khi p50 và p95 gần như không đổi: 3% request chậm nằm hoàn toàn trên ngưỡng 95%, nên chỉ p99 "nhìn thấy" chúng. Khi tỉ lệ chậm lên 10%, vượt quá 5%, p95 cũng rơi vào nhóm chậm (1690 ms) và vi phạm SLO. Trong khi đó, average chỉ tăng từ 189 lên 215 ms ở mức 3%, trông vẫn "ổn", dù cứ khoảng 33 người dùng thì có 1 người phải chờ gần 1,7 giây.

Vì vậy không nên đặt SLO theo average: average trộn số ít request rất chậm với số đông request nhanh, nên che mất trải nghiệm tệ của nhóm người dùng ở đuôi phân phối. Average cũng không cho biết *bao nhiêu* người bị ảnh hưởng. SLO theo p95 hoặc p99 nói thẳng rằng "95% hoặc 99% request phải nhanh hơn X", nên đo đúng thứ người dùng cảm nhận. Ngoài ra, request chậm còn giữ worker lâu hơn, làm RPS giảm từ 102 xuống 45: tail latency không chỉ ảnh hưởng vài người mà còn làm giảm năng lực của cả hệ thống.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.0 | 109.0 | 120.4 |
| Tổng cost (USD) | 0.000403 | 0.000760 | 0.000849 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003619 | 0.00003693 |
| Latency p50 / p95 (ms) | 167.9 / 190.0 | 183.6 / 203.7 | 197.9 / 221.9 |
| Quality gate | FAIL | PASS | PASS (`--min-accuracy 1.0`) |

Report JSON: `reports/eval_v1.json`, `reports/eval_v2.json` (baseline v1), `reports/eval_v2_fixed.json` (baseline v2).

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Câu hỏi không chứa keyword nào của `KNOWLEDGE_BASE`, nên retrieval trả rỗng và agent rơi về câu trả lời chung chung. Mình thêm vào `develop/utils/mock_llm.py` một tài liệu có keyword `["jwt", "json web token"]`, giải thích JWT là token có chữ ký số, có thời gian hết hạn (exp), so với API key cố định. |
| `scaling-03` "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Tương tự, không có tài liệu nào về Kubernetes. Mình thêm tài liệu có keyword `["kubernetes", "hpa", "horizontal pod autoscaler"]`, nói rõ HPA scale theo CPU, memory và custom metrics. |

Mình cố ý chọn keyword hẹp (không dùng `api key` hay `xác thực`) để tài liệu mới không "giành" retrieval của câu `security-01` vốn đang đúng. Kết quả: 2 câu được cải thiện, 0 câu regression. Golden dataset giữ nguyên, không sửa.

**Quality gate trong CI (exit code):** `run_eval.py` trả **exit code 0** khi đạt gate và **khác 0** khi trượt. Đã kiểm chứng: v2 sau khi sửa với `--min-accuracy 1.0` cho `exit code: 0`; v1 với `--min-accuracy 0.8` cho `exit code: 1`. Trong pipeline CI/CD (ví dụ một bước trước `build` trong `cloudbuild.yaml`), bước eval trả mã khác 0 sẽ làm pipeline dừng, nên phiên bản kém chất lượng hoặc có regression **không thể được deploy**, không cần ai kiểm tra thủ công.

Bước GitHub Actions chặn merge khi eval trượt (agent được khởi động trong job trước bước này):

```yaml
- name: Quality gate (eval golden dataset)
  working-directory: 06-lab-complete/benchmark-observability/develop
  run: |
    python eval/run_eval.py --url http://localhost:8002 \
      --baseline reports/eval_v2.json --min-accuracy 0.8 \
      --out reports/eval_ci.json
```

`run_eval.py` trả exit code khác 0 khi trượt, nên GitHub Actions đánh dấu step là failed. Khi bật branch protection với check này là bắt buộc, pull request không thể merge.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 dùng retrieval nên prompt dài hơn: số token trung bình tăng gần gấp đôi (57 → 109), tổng cost tăng khoảng 1,9 lần, và p95 chậm hơn khoảng 14 ms (thêm bước tìm tài liệu và prompt dài hơn). Đổi lại, accuracy tăng từ 4.3% lên 91.3%. Nếu tính **cost trên mỗi câu trả lời đúng**, v2 rẻ hơn v1 khoảng **11 lần** ($0.0000362 so với $0.000403), vì v1 tốn tiền mà hầu như trả lời sai. Sửa KB tiếp tục tăng accuracy lên 100% với chi phí nhỏ (+11 token/câu, p95 +18 ms, cost/câu đúng gần như không đổi). Kết luận: trade-off của v2 rõ ràng đáng giá. Latency tăng thêm vẫn nằm xa ngưỡng SLO 500 ms, còn chất lượng tăng vượt bậc.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability` trong `production/`: agent (1 hoặc 3 instance), Nginx, Prometheus, Grafana, Jaeger, Locust.

**Sự cố khi khởi động:** lần đầu chạy, container agent liên tục `Restarting (1)` với lỗi `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân: Dockerfile cài thư viện bằng `pip install --user` rồi copy vào `/home/agent/.local`, nhưng user `agent` được tạo với home là `/app` (`useradd -d /app`), nên Python tìm thư viện "user" ở `/app/.local`. Mình sửa bằng cách thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile`; sau khi build lại, agent `healthy` và `/ask` trả 200. Bài học: image build thành công chưa chắc đã chạy được, và nhờ có `HEALTHCHECK` cùng trạng thái của container mà lỗi được phát hiện ngay.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với alert đang **firing** (`AgentHighErrorRate` + `AgentHighLatencyP95` cùng firing): `screenshots/prometheus-alert-firing.png`

### 4.2 Thí nghiệm "phá hệ thống"

Trong suốt thí nghiệm, Locust chạy 30 user liên tục (`--no-deps`, 3 instance agent). Mỗi thay đổi được áp dụng bằng cách sửa `.env` rồi `docker compose up -d --scale agent=3`; giờ đổi lấy từ lệnh `date +%T`. Thời điểm PENDING và FIRING được suy ra từ cột **Active Since** trên trang Alerts tại lúc chụp màn hình, nên là số **xấp xỉ (≈)**.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical, `for: 1m`), giá trị ≈ 20.9% so với ngưỡng 5% | Đổi 17:32:37 → pending ≈ 17:33:07 → firing ≈ 17:34:07, tức **≈ 1 phút 30 giây** | Ô **Error rate** và panel **Requests/s theo status code** (đường 503 tăng) |
| B | `MOCK_SLOW_RATE=0.3` (A vẫn đang bật) | `AgentHighLatencyP95` (warning, `for: 2m`), p95 ≈ 1.89 s so với ngưỡng 1 s | Đổi 17:35:47 → pending ≈ 17:36:16 → firing ≈ 17:38:16, tức **≈ 2 phút 30 giây** | Panel **Latency /ask p50/p95/p99**: p95 và p99 vượt vạch 1 s, còn p50 và avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` (A, B đã trả về như cũ) | `LLMCostBurnRateHigh` (warning, `for: 2m`), ≈ $15.48/giờ so với ngưỡng $2/giờ. Không có alert latency nào firing | Đổi 17:39:33 → pending ≈ 17:40:16 → firing ≈ 17:42:16, tức **≈ 2 phút 43 giây** | Panel **Cost burn rate (USD/giờ)** (đỉnh khoảng $24/giờ) và **LLM latency p95 theo model** (model large khoảng 500 ms) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (critical, `for: 30s`), `instance="172.19.0.6:8000"`, `up == 0` | Pause 17:43:48 → pending ≈ 17:44:01 → firing ≈ 17:44:31, tức **≈ 43 giây** | Ô **Instances** (3 → 2) và **Requests/s theo instance** (đường 172.19.0.6 bị đứt). Ô Error rate **vẫn xanh (0.97%)** |
| E | `AGENT_VERSION=v1` | **Không có** | — | Bảng **Phiên bản đang chạy** (đổi sang `v1`) và **Tokens/s** (giảm vì không còn context trong prompt). Panel *Retrieval hit ratio* vẫn hiện khoảng 89% sau khoảng 2 phút quan sát, có thể do còn dữ liệu cũ trong cửa sổ tính toán. Stack đã tắt trước khi theo dõi thêm được |

**Nhận xét:**
- Thời gian đến lúc firing ≈ (thời gian để agent khởi động lại và Prometheus lấy số liệu, khoảng 13–43 giây) + thời gian `for` của rule. Rule cost chậm nhất vì dùng cửa sổ `rate(...[5m])`, phải tích luỹ đủ chi phí mới vượt ngưỡng. `AgentInstanceDown` nhanh nhất vì sự cố nghiêm trọng nên `for` chỉ 30 giây.
- Ở C, model lớn chậm hơn khoảng 2,5 lần nhưng p95 vẫn dưới ngưỡng alert 1 s, nên **chỉ alert về cost phát hiện được** sự cố này.
- Ở D, các request bị kẹt ở instance bị pause hết thời gian chờ ở Nginx (504). Agent không bao giờ xử lý xong những request đó nên metric của agent không đếm chúng: dashboard lỗi vẫn xanh. Cần giám sát ở tầng load balancer hoặc dùng synthetic check từ bên ngoài.
- Một quan sát chưa giải thích được: `LLMCostBurnRateHigh` từng firing ngắn trong lúc làm A (khoảng 17:34, khi đang dùng model small) rồi trở lại inactive vào khoảng 17:38. Mình chưa xác định được nguyên nhân.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là lỗi **chất lượng**: hệ thống vẫn nhanh, không lỗi, đủ instance, chỉ có câu trả lời là tệ đi. Metric hạ tầng không thấy được loại lỗi này. Các cách phát hiện:
1. **Chặn trước khi deploy:** chạy eval trên golden dataset trong CI, dùng quality gate theo exit code (mục 3). Bản v1 có accuracy 4.3%, sẽ bị chặn ngay.
2. **Eval online định kỳ:** một job gửi golden dataset (hoặc mẫu câu hỏi thật) vào production theo lịch, đẩy accuracy thành metric Prometheus và đặt alert khi accuracy giảm.
3. **Alert trên metric chất lượng gián tiếp:** retrieval hit ratio giảm đột ngột, số token trung bình mỗi request giảm, `agent_info{version}` thay đổi ngoài lịch release.
4. **Tín hiệu từ người dùng** (đánh giá thích/không thích, tỉ lệ hỏi lại) và **canary deploy:** so sánh chất lượng giữa bản cũ và bản mới trên cùng một lượng traffic trước khi chuyển hết sang bản mới.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (Jaeger, Min Duration `1s`):

- `trace_id`: `2c860b820536900f0cb286391426ac2f`
- Tổng thời gian: **1696.1 ms** (Jaeger hiển thị 1.7 s)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1672.2 ms, ≈ 98.6%**; 37 token vào, 17 token ra). Bước `agent.retrieve_context` chỉ mất 20.2 ms (≈ 1.2%). Request chậm hoàn toàn do LLM upstream (tail latency của `MOCK_SLOW_RATE`), không do code của agent.
- Dòng log tương ứng (`docker compose logs agent --no-log-prefix | grep <trace_id>`):

```json
{"ts": "2026-11-25T10:23:45.858295+00:00", "level": "INFO", "service": "observable-agent", "instance": "b0b4fbe25460", "event": "llm_call", "trace_id": "2c860b820536900f0cb286391426ac2f", "span_id": "469b6ffc5db8057d", "request_id": "9fea24bc8fa8", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 37, "output_tokens": 17, "cost_usd": 1.6e-05, "llm_ms": 1672.2}
{"ts": "2026-11-25T10:23:45.859053+00:00", "level": "INFO", "service": "observable-agent", "instance": "b0b4fbe25460", "event": "http_request", "trace_id": "2c860b820536900f0cb286391426ac2f", "span_id": "469b6ffc5db8057d", "request_id": "9fea24bc8fa8", "method": "POST", "route": "/ask", "status": 200, "ms": 1696.1}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`): span `chat mock-llm-small` có `error.type = upstream_unavailable` và event `exception` với `exception.message = Upstream LLM error: 503 Service Unavailable (mock)`. Stacktrace chỉ ra lỗi phát sinh ở `utils/mock_llm.py` dòng 199, được gọi từ `app/main.py` dòng 153 (`run_agent`).

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_N`. Số liệu lấy từ dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.40 | 190 | 230 | 1700 | 83 / 7216 (1.15%) |
| 3 | 59.36 | 190 | 230 | 1700 | 66 / 7087 (0.93%) |

**Lưu ý về cách đo:** lần chạy `scale_1` đầu tiên bị sai. Lệnh `docker compose run locust` (không có `--no-deps`) tự khởi động các service mà locust phụ thuộc và đưa `agent` về số bản mặc định trong compose. Log ghi `agent-2 Created`, và ô Instances trên Grafana hiện 2. Mình đã chạy lại với `--no-deps`, kiểm tra `ps` thấy đúng 1 agent trước và sau khi đo. Bảng trên là số liệu của lần chạy lại.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

**Không.** RPS, p50, p95, p99 gần như giống hệt nhau giữa 1 và 3 instance. Có hai lý do:

1. **Nút thắt nằm ở chính bộ tạo tải, không phải agent.** Locust là một hệ "vòng kín": mỗi user gửi request, chờ phản hồi (khoảng 0,23 s), rồi nghỉ `wait_time = between(0.5, 2)` (trung bình 1,25 s). Mỗi user chỉ tạo được khoảng 1 / 1,48 s ≈ 0,68 req/s, nên 100 user tạo tối đa khoảng **67,6 req/s**, khớp với Aggregated đo được (khoảng 66 req/s). Ở mức tải này, 1 agent vẫn còn dư sức (mock LLM dùng `asyncio.sleep`, nên agent chỉ chờ chứ không tốn CPU), vì vậy thêm instance không có gì để cải thiện. Muốn thấy tác dụng của scale, phải tăng tải đến mức 1 instance bão hoà, ví dụ tăng số user hoặc giảm `wait_time`. Ở mục 2.1, 1 process đã bão hoà ở khoảng 100 req/s.
2. **Phần lớn latency nằm ở LLM upstream.** p50/p95 khoảng 190–230 ms là thời gian gọi LLM. p99 = 1700 ms là tail latency do `MOCK_SLOW_RATE`. Đây là độ trễ của nhà cung cấp LLM nên **thêm instance agent không làm nhanh hơn được**: muốn giảm phải đổi model, cache câu trả lời, đặt timeout và retry, hoặc gửi song song nhiều request (hedged request).

Failures khoảng 1% ở cả hai lần đều là lỗi 503 do `MOCK_ERROR_RATE=0.01`, không liên quan đến số instance.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Latency phải đọc theo percentile.** 3% request chậm làm p99 tăng khoảng 7,5 lần trong khi average và p95 gần như không đổi. Throughput có điểm bão hoà (khoảng 50 concurrency cho 1 process); vượt quá điểm đó, RPS giảm và latency tăng vọt, nên load test phải quét nhiều mức tải.
  2. **Benchmark chỉ đáng tin khi kiểm soát được điều kiện đo.** `docker compose run` âm thầm đổi số instance và làm sai lần đo đầu. Còn so sánh 1 và 3 instance chỉ có ý nghĩa nếu bộ tạo tải đủ mạnh để làm hệ thống bão hoà. Phải kiểm tra cấu hình hạ tầng ngay trước mỗi lần đo và hiểu mô hình tải (vòng kín hay vòng mở).
  3. **Metrics, traces và logs bổ sung cho nhau, và mỗi loại chỉ thấy được một phần.** Dashboard báo p99 cao, Jaeger chỉ ra 98,6% thời gian nằm ở span LLM, log tìm theo `trace_id` cho đủ chi tiết token và cost. Nhưng metric hạ tầng không thấy lỗi ở tầng load balancer (thí nghiệm D) hay lỗi chất lượng (thí nghiệm E), nên cần thêm eval và giám sát từ bên ngoài.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Metric của Nginx/load balancer** (tỉ lệ 5xx/504, upstream response time) và **synthetic check** gọi `/ask` từ bên ngoài theo chu kỳ, để bắt lỗi kiểu D.
  - **Metric chất lượng:** accuracy từ eval online định kỳ, retrieval hit ratio, tỉ lệ người dùng đánh giá không thích, kèm alert khi giảm so với baseline, để bắt lỗi kiểu E.
  - **Alert về độ bão hoà:** `agent_in_flight_requests` cao kéo dài, hoặc thời gian chờ trong hàng đợi tăng. Đây là tín hiệu cần scale trước khi p95 vỡ SLO.
  - **Alert theo error budget burn rate** (đa cửa sổ, ví dụ 1 giờ và 6 giờ) thay vì ngưỡng cố định, để vừa bắt sự cố nhanh vừa ít báo nhầm.
  - **Ngân sách chi phí theo ngày hoặc theo người dùng**, cộng alert khi số token trung bình mỗi request thay đổi đột ngột (prompt dài bất thường hoặc model bị đổi).
