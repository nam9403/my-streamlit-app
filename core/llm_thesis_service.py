from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM_PROMPT = """Bạn là Giám đốc Phân tích Đầu tư Giá trị (Value Investing CIO) của một quỹ đầu tư dài hạn.

Nhiệm vụ:
- Đọc kỹ dữ liệu JSON cổ phiếu được cung cấp (ticker, giá, MOS, F-Score, CR, CFO, catalyst/news, phase, risk, macro...).
- Trích xuất tín hiệu quan trọng, phân biệt dữ liệu chắc chắn và dữ liệu thiếu.
- Ưu tiên triết lý đầu tư kết hợp:
  1) "Máy cân": nội lực doanh nghiệp, định giá an toàn, chất lượng dòng tiền.
  2) "Máy bỏ phiếu": câu chuyện/chất xúc tác giúp giá được tái định giá trong ngắn-trung hạn.

Bắt buộc trả về DUY NHẤT Markdown (không code fence, không JSON), đúng 4 phần sau:
1. 🎯 **NỘI LỰC DOANH NGHIỆP (Máy cân)**
   - Tóm tắt MOS, F-Score, CFO/NI và CR.
   - Nêu nhanh chất lượng định giá + sức khỏe tài chính cốt lõi.
2. 📢 **CÂU CHUYỆN THỊ TRƯỜNG & CHẤT XÚC TÁC (Máy bỏ phiếu)**
   - Chỉ ra động lực tăng giá ngắn/trung hạn: cổ tức, tăng trưởng BCTC, sự kiện doanh nghiệp, vĩ mô hỗ trợ.
   - Nhấn mạnh catalyst nào là mạnh nhất tại thời điểm hiện tại.
3. ⚠️ **CẢNH BÁO GÃY LUẬN ĐIỂM (Invalidation Radar)**
   - Đưa các mốc cảnh báo rõ ràng khiến luận điểm mua bị hủy, ví dụ:
     - F-Score < 5
     - CFO đảo chiều âm
     - MOS < 5%
   - Có thể bổ sung mốc khác nếu dữ liệu cho thấy rủi ro cao.
4. 🚀 **KẾ HOẠCH HÀNH ĐỘNG (Action Plan)**
   - Đề xuất vùng giá giải ngân an toàn (dựa trên giá hiện tại và MOS).
   - Đề xuất tỷ trọng tài khoản (ví dụ 15-20% nếu luận điểm đủ mạnh).
   - Định hướng "Mua tích lũy & Nhận cổ tức" hoặc "WATCH" nếu chưa đủ điều kiện.

Yêu cầu văn phong:
- Khách quan, chuyên nghiệp, súc tích, giàu insight.
- Dưới 250 từ.
- Tránh sáo rỗng, tránh hàn lâm quá mức, tránh khuyến nghị mơ hồ."""


@dataclass(slots=True)
class AIThesisGenerator:
    """
    Build AI Executive Thesis text from stock analysis payload.

    Configure by environment variables (or pass values directly):
    - AI_THESIS_API_URL
    - AI_THESIS_API_KEY
    - AI_THESIS_MODEL
    """

    api_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_sec: float = 20.0
    default_message: str = "Hệ thống AI hiện đang bận, vui lòng thử lại sau giây lát."

    def generate_executive_thesis(self, stock_data: dict[str, Any]) -> str:
        """
        Convert input data to JSON text and request thesis from LLM API.

        Defensive behavior:
        - Any timeout/rate-limit/network/API error returns a friendly fallback.
        """
        if not isinstance(stock_data, dict) or not stock_data:
            return self.default_message

        try:
            prompt = self._build_prompt(stock_data)
            return self._call_api(prompt)
        except (TimeoutError, HTTPError, URLError, ValueError, KeyError, RuntimeError, OSError):
            return self.default_message
        except Exception:
            return self.default_message

    def generate_thesis(self, stock_data: dict[str, Any]) -> str:
        """
        Backward-compatible alias for previous integrations.
        """
        return self.generate_executive_thesis(stock_data)

    def _build_prompt(self, stock_data: dict[str, Any]) -> str:
        data_json = json.dumps(stock_data, ensure_ascii=False, indent=2, default=str)
        return (
            "Dưới đây là dữ liệu JSON đầu vào cho AI Executive Thesis Card.\n"
            "Hãy tuân thủ đúng SYSTEM PROMPT để trả về markdown 4 phần.\n"
            "Dữ liệu:\n"
            f"{data_json}"
        )

    def _call_api(self, prompt: str) -> str:
        url = (self.api_url or os.environ.get("AI_THESIS_API_URL") or "").strip()
        if not url:
            raise ValueError("Missing AI_THESIS_API_URL")

        api_key = (self.api_key or os.environ.get("AI_THESIS_API_KEY") or "").strip()
        model = (self.model or os.environ.get("AI_THESIS_MODEL") or "gpt-4o-mini").strip()

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urlopen(request, timeout=self.timeout_sec) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)

        content = self._extract_text_from_response(data)
        if not content:
            raise ValueError("Empty LLM response content")
        return content.strip()

    @staticmethod
    def _extract_text_from_response(data: dict[str, Any]) -> str:
        # OpenAI-compatible shape.
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content

        # Gemini-like or custom fallback shape.
        if isinstance(data.get("text"), str):
            return str(data["text"])
        if isinstance(data.get("output_text"), str):
            return str(data["output_text"])
        return ""

