# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (κ=0.757 ≥ 0.6, P=0.857 ≥ 0.8, R=0.800 ≥ 0.7) | Dùng làm gate |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt (Recall=0.300 < 0.7, κ=0.375 < 0.6) | Loại, không dùng |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008: "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người đúng | Ngôn từ suồng sã ("Em - anh", "nha"). Sửa rubric: cấm xưng hô thân mật cá nhân, bắt buộc đại xưng LogiX - Quý khách. |
| 2 | H-017: "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." | PASS | FAIL | Người đúng | Dùng từ "bạn ơi", "nha" là văn phong mạng xã hội thân mật. Sửa rubric: liệt kê từ cấm biểu thị suồng sã. |
| 3 | H-029: "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người đúng | Giọng cộc lốc, gạt phắt khách ("không cần nhắn thêm"). Sửa rubric: cấm câu từ gây cảm giác tiêu cực/ngắt lời. |
| 4 | H-042: "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người đúng | Phản hồi lịch sự, đầy đủ thông tin thời gian. Judge bắt nhầm (FP). Cần bổ sung ví dụ Few-shot tích cực cho câu ngắn đủ ý. |
| 5 | HL-015: "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | Người đúng | Khách hỏi lý do trễ đơn và khi nào hoàn tiền nhưng reply chỉ báo hoàn tiền. Judge helpful quá dễ dãi (FN=21). |

## Kết luận
- **Tiêu chí bị loại:** `judge_helpful` bị loại hoàn toàn khỏi release gate do Recall quá thấp (R=0.300 < 0.7, κ=0.375 < 0.6), ma trận nhầm lẫn có tới 21 FN (bỏ lọt 70% lỗi của con người). Tỉ lệ lỗi quan sát 9% trong khi tỉ lệ thực tế hiệu chỉnh Rogan-Gladen là 30%.
- **Rủi ro còn lại:** `judge_tone` đạt ngưỡng kiểm định nhưng mới chỉ kiểm tra trên dữ liệu replay đã công khai (100 dòng). Cần xây dựng tập dữ liệu held-out riêng được dán nhãn độc lập bởi người đánh giá mới để tránh overfitting.
