"""
Vercel serverless entry point.

The market feeds have to be called server-side: neither TradingView's scanner
nor thaidw.com sends CORS headers, so a browser fetching them directly is
blocked. This function does the calls, renders the page, and returns HTML.
"""

import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.page import render          # noqa: E402
from web.report import collect       # noqa: E402

# Serve a cached copy for a short window: the underlying feeds update every few
# seconds, and a page reloaded ten times in a minute should not mean ten rounds
# of scanning the whole Thai market.
CACHE = 'public, s-maxage=45, stale-while-revalidate=180'

_ERROR_PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ดึงข้อมูลไม่ได้</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px">
<h1 style="font-size:20px">ดึงข้อมูลตลาดไม่ได้</h1>
<p style="color:#666">แหล่งข้อมูลอาจปิดชั่วคราวหรือปฏิเสธคำขอจากเซิร์ฟเวอร์นี้ ลองรีเฟรชอีกครั้ง</p>
<pre style="background:#f4f4f5;padding:14px;border-radius:8px;overflow:auto;
font-size:12px;color:#444">{detail}</pre></body>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = render(collect())
            status = 200
            cache = CACHE
        except Exception:
            body = _ERROR_PAGE.format(detail=traceback.format_exc(limit=4))
            status = 503
            cache = 'no-store'

        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass                          # Vercel captures stdout already
