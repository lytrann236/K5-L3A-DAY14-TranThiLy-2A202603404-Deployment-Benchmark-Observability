# Benchmark & Observability Report — Day 14

**Họ tên:** Trần Thị Lý — 2A202603404
**Ngày chạy:** 2026-11-25
**Môi trường:** MacBook Apple M2, macOS, Python 3.13, Docker Desktop (___ CPU / ___ GB RAM). Bước develop chạy local không qua Docker: mỗi agent là 1 process `python app.py`.

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

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 dùng retrieval nên prompt dài hơn: số token trung bình tăng gần gấp đôi (57 → 109), tổng cost tăng khoảng 1,9 lần, và p95 chậm hơn khoảng 14 ms (thêm bước tìm tài liệu và prompt dài hơn). Đổi lại, accuracy tăng từ 4.3% lên 91.3%. Nếu tính **cost trên mỗi câu trả lời đúng**, v2 rẻ hơn v1 khoảng **11 lần** ($0.0000362 so với $0.000403), vì v1 tốn tiền mà hầu như trả lời sai. Sửa KB tiếp tục tăng accuracy lên 100% với chi phí nhỏ (+11 token/câu, p95 +18 ms, cost/câu đúng gần như không đổi). Kết luận: trade-off của v2 rõ ràng đáng giá. Latency tăng thêm vẫn nằm xa ngưỡng SLO 500 ms, còn chất lượng tăng vượt bậc.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [ ] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: `screenshots/prometheus-alert-firing.png`

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. Latency phải đọc theo percentile: 3% request chậm làm p99 tăng 7,5 lần trong khi average và p95 gần như không đổi.
  2. Throughput có điểm bão hoà: vượt quá điểm đó (ở đây khoảng 50 concurrency cho 1 process), RPS giảm và latency tăng vọt, nên load test phải quét nhiều mức tải chứ không chỉ một mức.
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
