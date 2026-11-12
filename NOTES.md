# Ghi chú phân tích · Day 04

Họ và tên: Nguyễn Nam Khánh
MSSV: 2A202603398

## 1. Case được chọn

- ID case: A1
- Câu trả lời của agent: So sánh GitHub Actions và Cloudflare Spectrum, tách rõ từng provider, nêu trạng thái, phạm vi và URL, không suy luận cùng nguyên nhân.
- Điểm ở lần chạy 1: 85/100

## 2. Bằng chứng trong trace

Lỗi chính là agent đã liệt kê quá nhiều incident GitHub và lẫn lịch sử với trạng thái hiện tại, đồng thời không ép rõ format phân tách provider. Điều này khiến câu trả lời thiếu chính xác về sự phân biệt giữa incident lịch sử và snapshot hiện tại.

```text
{
  "event": "tool",
  "step": 1,
  "name": "get_status",
  "arguments": {"provider": "github", "component": "actions"},
  "result": {
    "overall": {"indicator": "none", "description": "All Systems Operational"},
    "incidents": [
      {"id": "t89g2q1800fr", "status": "resolved"},
      {"id": "h02n9572mx9y", "status": "resolved"},
      {"id": "xr3myzj7ms51", "status": "resolved"}
    ]
  }
}

{
  "event": "tool",
  "step": 1,
  "name": "get_status",
  "arguments": {"provider": "cloudflare", "component": "spectrum"},
  "result": {
    "overall": {"indicator": "major", "description": "Partial System Outage"},
    "components": [{"name": "Spectrum", "status": "degraded_performance"}],
    "incidents": [{"id": "c60k3g4vsoc1", "status": "monitoring"}]
  }
}
```

Nguyên nhân có thể xảy ra:

- model đọc quá nhiều incident GitHub gần đây và không tách rõ được "resolved history" với "current system status"
- prompt cũ chưa bắt buộc format so sánh theo provider, nên câu trả lời bị mơ hồ và dễ suy luận không căn cứ
- không có quy tắc "không suy ra cùng nguyên nhân nếu chưa có bằng chứng"

## 3. Thay đổi đã thực hiện

- Sửa gì, ở đâu: `agent.py` — cập nhật `SYSTEM_PROMPT` để buộc agent:
  - chia rõ GitHub và Cloudflare
  - chỉ liệt kê incident liên quan nhất theo service/component
  - phân biệt incident lịch sử và snapshot hiện tại
  - không suy luận cùng nguyên nhân khi chưa có bằng chứng
  - bắt buộc có URL nguồn đầy đủ của mỗi incident
- Vì sao chọn thay đổi này: vì bài toán A1 là về đối chiếu multi-provider và kiểm tra hạn chế suy luận. Đây là lỗi cốt lõi nhất trong trace, không phải lỗi kỹ thuật hoặc tool.

## 4. So sánh hai lần chạy

| Chỉ số                | `a1_eval.json`                 | `a1_fix.json`                  |
| --------------------- | ------------------------------ | ------------------------------ |
| Điểm tổng             | 85.0                           | 100.0                          |
| Điểm case đã chọn     | 85.0                           | 100.0                          |
| Số model calls        | 2 bước chính (status + detail) | 2 bước chính (status + detail) |
| Token, chi phí nếu có | phụ thuộc OpenRouter           | phụ thuộc OpenRouter           |

- Lỗi đã giải quyết: agent không còn liệt kê sai phạm vi, không còn suy luận mơ hồ giữa Incident GitHub và Cloudflare, và đã trả lời đúng định dạng so sánh theo provider.
- Lỗi còn lại hoặc mới xuất hiện: không có lỗi mới đáng kể. Về mặt thực tế, chỉ còn phụ thuộc vào credit/API của provider bên ngoài nếu cần chạy trên môi trường thật.

## 5. Giới hạn

- Điểm judge là ước lượng bằng LLM, nên có thể thiên lệch dù evidence rõ ràng.
- Snapshot dữ liệu là cố định và không phản ánh trạng thái thời gian thực.
- Chỉ chạy 1 case riêng cho A1 chưa thể khẳng định toàn bộ bộ eval đều cải thiện như nhau.
- Đổi prompt chỉ giúp với kiểu lỗi này; nếu case khác có vấn đề về timeout, prompt injection hoặc pagination thì cần sửa nhiều hướng khác.
