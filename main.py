import threading
import time

import webview
from waitress import serve

from app import app
from models import init_db


def run_server():
    init_db()
    serve(app, host="127.0.0.1", port=5000)


if __name__ == "__main__":
    # Jalankan server Flask di background
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Tunggu sebentar agar server siap
    time.sleep(1)

    # Buka aplikasi desktop
    window=webview.create_window(
        title="Aplikasi Penjualan & Pembeliaan Stok",
        url="http://127.0.0.1:5000",
        width=1300,
        height=800,
        resizable=True,
        min_size=(1024, 700),
        # fullscreen=True
    )

    def maximize():
        window.maximize()

    window.events.loaded += maximize

    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.start()