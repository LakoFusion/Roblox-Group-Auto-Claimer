# ⚡ Ultra Fusion — Roblox Group Auto Claimer

> High-speed parallel automated Roblox group claimer with Discord Gateway & live telemetry.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Engine: curl_cffi](https://img.shields.io/badge/Engine-curl_cffi-orange.svg)](https://github.com/yifeikong/curl_cffi)
[![Discord Gateway](https://img.shields.io/badge/Gateway-Discord%20v10-5865F2.svg)](https://discord.com)

---

## 📸 Demo Preview

![Demo](https://via.placeholder.com/1200x600.png?text=Ultra+Fusion+Demo+Screenshot)

---

## 🚀 Tính Năng Nổi Bật (Features)

- **⚡ Chiến thuật Parallel Staggered:** Bắn lệnh `JOIN` và các luồng `CLAIM` song song với độ trễ vi mô (`45ms`, `70ms`, `75ms`), kết hợp thuật toán **Rapid Post-Join Retry** (`0.35s`, `0.8s`, `1.6s`, `2.5s`) vét group ngay khi membership vừa mở.
- **🛡️ Bypass Cloudflare & TLS Fingerprint:** Sử dụng engine `curl_cffi` giả lập trình duyệt Chrome (`impersonate="chrome"`), vượt qua các rào cản bot detection của Roblox.
- **🔄 Auto XCSRF Token Refresher:** Background worker tự động refresh `X-CSRF-TOKEN` mỗi 90s, tự động phục hồi token ngay lập tức khi phát hiện mã `403`.
- **🍪 Per-GID Cookie Lease Isolation:** Cơ chế cấp phát cookie riêng cho từng Group ID đang xử lý, triệt tiêu hoàn toàn xung đột cookie và deadlock giữa các luồng đồng thời.
- **🛰️ Discord Gateway V10 Real-time Listener:** Tự động lắng nghe sự kiện tin nhắn qua WebSocket, nhận diện thông minh link group Roblox (`groups`, `communities`, `rblx.gg`, `roblox.com/share`).
- **💎 Tự Động Định Giá Group (Valuation):** Quét 6 API Roblox để thống kê số dư Robux, Pending Robux, Games, lượt Visits, quần áo và tự gắn nhãn `💎 High-Value` cho group giá trị.
- **📊 Giao Diện Terminal Clean Minimalist:** Thiết kế hiển thị gọn nhẹ, không dùng ký tự vẽ box (chống vỡ layout trên Windows), hỗ trợ cơ chế Anti-flicker mượt mà.
- **🔔 Discord Webhook Micro-Card V2:** Hệ thống thông báo 3 kênh riêng biệt (`logs`, `detections`, `errors`) hiển thị sạch sẽ, tách dòng trực quan, không bị pill đen.

---

## ⚠️ Disclaimer & Security Warning

> **Tuyên bố từ chối trách nhiệm:** Công cụ này được phát triển cho mục đích học tập và nghiên cứu kỹ thuật. Việc tự động hóa thao tác trên Roblox vi phạm Điều khoản dịch vụ (ToS) của Roblox và có thể dẫn đến việc tài khoản bị khóa hoặc cấm vĩnh viễn. Tác giả không chịu bất kỳ trách nhiệm pháp lý nào đối với thiệt hại phát sinh từ việc sử dụng tool này.

- **BẢO MẬT TUYỆT ĐỐI:** Tuyệt đối **KHÔNG** chia sẻ hoặc commit file `config.json`, token Discord, cookie `.ROBLOSECURITY` trong `input/cookies.txt` lên bất kỳ kho lưu trữ công khai nào (như GitHub).
- Nên thêm `config.json` và thư mục `input/` vào `.gitignore` trước khi đẩy mã nguồn lên repository.

---

## 🛠️ Cài Đặt & Hướng Dẫn Sử Dụng

### 1. Yêu cầu hệ thống

- **Python:** Phiên bản `3.10` trở lên.
- Hệ điều hành: Windows, macOS hoặc Linux.

### 2. Cài đặt thư viện

```bash
git clone https://github.com/your-username/claim-group.git
cd claim-group
pip install -r requirements.txt
```

### 3. Cấu hình Data & Hệ thống

1. **Nạp Cookie:** Mở file `input/cookies.txt` và dán cookie tài khoản Roblox của bạn (mỗi cookie một dòng).
2. **Nạp Proxy (nếu dùng):** Mở file `input/proxies.txt` và thêm proxy dạng `host:port` hoặc `host:port:user:pass`.
3. **Thiết lập `config.json`:**

```json
{
  "token": "DISCORD_BOT_TOKEN_HOAC_USER_TOKEN",
  "prefix": "--",
  "owner_ids": ["DISCORD_USER_ID_CUA_BAN"],
  "webhooks": {
    "logs": "URL_WEBHOOK_LOGS",
    "detections": "URL_WEBHOOK_DETECTIONS",
    "errors": "URL_WEBHOOK_ERRORS"
  },
  "claim_mode": "parallel",
  "parallel_delays": [0.045, 0.07, 0.075],
  "post_join_retry_delays": [0.35, 0.8, 1.6, 2.5],
  "claim_retry_attempts": 3,
  "claim_timeout_seconds": 12,
  "use_proxies": false,
  "proxy_file": "input/proxies.txt",
  "cookie_file": "input/cookies.txt",
  "verbose_logs": false,
  "dashboard": true,
  "dashboard_always_log": false
}
```

### 4. Khởi chạy

```bash
python main.py
```

---

## 📂 Cấu Trúc Thư Mục & Luồng Hoạt Động (Workflow)

```text
claim-group/
├── input/        # Nơi chứa data đầu vào (cookies.txt, proxies.txt)
├── src/          # Source code chính của tool (bot, handlers, config...)
├── config.json   # Cấu hình hệ thống & Webhook
├── main.py       # File khởi chạy tool
└── requirements.txt
```

### Luồng xử lý chính:

1. **Khởi tạo:** `main.py` đọc cấu hình `config.json`, nạp cookie từ `input/cookies.txt`, xác thực tài khoản và kết nối tới Discord Gateway WebSocket.
2. **Lắng nghe & trích xuất:** Khi có tin nhắn chứa link group gửi vào channel giám sát, bot trích xuất Group ID (GID), đưa vào hàng đợi `claim_semaphore` và cấp phát cookie riêng.
3. **Cướp & báo cáo:** Bot bắn lệnh `JOIN` kết hợp `CLAIM` song song với các độ trễ vi mô. Nếu thành công, hệ thống định giá group và bắn thông báo Embed tới Discord Webhook.

---

## ❓ Xử Lý Lỗi Thường Gặp (Troubleshooting / FAQ)

- **Lỗi `🚨 Cookies Exhausted` / `Cookie unauthorized (401)`:**
  - *Nguyên nhân:* Cookie bị hết hạn, đổi mật khẩu hoặc tài khoản bị hạn chế.
  - *Khắc phục:* Lấy lại cookie `.ROBLOSECURITY` mới và nạp vào `input/cookies.txt`.
- **Lỗi `Rate limited (429)` liên tục:**
  - *Nguyên nhân:* IP gửi quá nhiều request cùng lúc hoặc tài khoản bị gắn cờ tạm thời.
  - *Khắc phục:* Bật proxy trong `config.json` (`"use_proxies": true`) và nạp proxy sạch vào `input/proxies.txt`.
- **Lỗi thiếu module / thư viện:**
  - *Khắc phục:* Chạy lệnh `pip install -r requirements.txt` để cài đặt đầy đủ các dependency.

---

## 🌐 Connect & Support

- 👾 **Discord Server:** [Join here](https://discord.gg/rxw8Hwk3qA)
- 🎵 **TikTok:** [@lakofusion](https://www.tiktok.com/@lakofusion)
- 📺 **YouTube:** [@lakofusion2010](https://www.youtube.com/@lakofusion2010)

---

## 📄 License

Dự án này được phân phối dưới giấy phép **MIT License**. Xem chi tiết tại file `LICENSE`.

