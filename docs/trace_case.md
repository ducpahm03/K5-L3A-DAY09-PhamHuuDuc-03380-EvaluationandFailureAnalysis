# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Bảng phân tích case C-002@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, Run ID: `E-seeded_regression-20261117-d9c8` |
| Triệu chứng | `lab8_pass` FAIL (`status resolved != denied`), `db_fact_kept` FAIL, `refund_amount_correct` FAIL (ledger=20000 != label=0). Reply: "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." |
| Bước sai đầu tiên | Event 3: `model_override` payload: `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) và Event 2 (`investigator`) truy vấn đúng dữ liệu đơn hàng `O-202` từ DB. Tại bước 3, agent để lời khai trong ticket đè dữ liệu thật của DB. |
| Failure mode | `FM-03` (`ticket_trust` — tin ticket hơn DB) |
| Đối chứng | Trên shape `fixed` (cùng claim@seed): không có event `model_override`. Event 3 trực tiếp là `quote` với `amount_vnd: 0, reason: "no_entitlement"`, dẫn đến kết quả `denied`, ledger=0đ (PASS). |
| Regression test | `test_lab9_graders.py::test_override_event_breaks_db_fact` và grader `DbFactKept` / `RefundAmountCorrect`. Bắt được fail trên `seeded_regression` và pass trên `fixed`. |
| Chưa chắc chắn | Trace chỉ ghi nhận event xuất ra (`model_override`), không phản ánh toàn bộ prompt context nội bộ của LLM thật trước khi ra quyết định. |

## Quy tắc
- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: đã tích hợp vào grader `DbFactKept` và kiểm thử trong `test_lab9_graders.py`.
