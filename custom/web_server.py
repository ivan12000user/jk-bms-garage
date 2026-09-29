#!/usr/bin/env python3

import os
from http.server import (
    ThreadingHTTPServer,
    SimpleHTTPRequestHandler,
)

WEB_DIR = "/opt/batmon-ha/web"
LISTEN = "0.0.0.0"
PORT = 8088


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if (
            self.path.startswith("/state.json")
            or self.path.startswith("/jk_log.csv")
        ):
            self.send_header(
                "Cache-Control",
                "no-store, no-cache, must-revalidate"
            )

        super().end_headers()

    def log_message(self, fmt, *args):
        # Не писать в journal запрос state.json каждые 5 секунд.
        pass


os.chdir(WEB_DIR)

server = ThreadingHTTPServer(
    (LISTEN, PORT),
    Handler,
)

print(
    f"JK web: http://{LISTEN}:{PORT}/ "
    f"directory={WEB_DIR}",
    flush=True,
)

server.serve_forever()
