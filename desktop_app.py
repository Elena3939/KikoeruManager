#!/usr/bin/env python3
"""
Prekikoeru desktop entrypoint with system tray support.
Used for Windows packaging.
"""

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import messagebox

import pystray
import uvicorn
from PIL import Image, ImageDraw

APP_NAME = "Prekikoeru"
APP_TITLE = f"{APP_NAME}（运行中）"
DEFAULT_PORT = 8000
LOCK_PORT = 29173
HOST = "127.0.0.1"


project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DesktopApp:
    def __init__(self):
        self.stop_event = threading.Event()
        self.backend_thread = None
        self.icon = None
        self.port = DEFAULT_PORT
        self.lock_port = LOCK_PORT
        self.host = HOST
        self.url = f"http://{self.host}:{self.port}"
        self.lock_socket = None
        self.backend_error = None
        self.server = None
        self.icon_path = self._find_icon()

    def check_single_instance(self):
        """Return True when this is the first running instance."""
        try:
            self.lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.lock_socket.bind((self.host, self.lock_port))
            return True
        except socket.error:
            return False

    def _icon_candidates(self):
        bundle_dir = getattr(sys, "_MEIPASS", project_root) if getattr(sys, "frozen", False) else project_root
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else project_root
        return [
            os.path.join(exe_dir, "app.ico"),
            os.path.join(bundle_dir, "app.ico"),
            os.path.join(bundle_dir, "backend", "app.ico"),
            os.path.join(project_root, "backend", "app.ico"),
        ]

    def _find_icon(self):
        for path in self._icon_candidates():
            logger.info("Checking icon path: %s", path)
            if os.path.exists(path):
                logger.info("Using icon: %s", path)
                return path
        logger.warning("No application icon found; falling back to generated placeholder icon")
        return None

    def _create_generated_icon(self):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(30, 41, 59, 255))
        draw.rectangle((20, 14, 28, 50), fill=(255, 255, 255, 255))
        draw.polygon(((30, 30), (46, 14), (52, 20), (38, 34), (52, 50), (46, 56)), fill=(255, 255, 255, 255))
        return image

    def _load_tray_image(self):
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                with Image.open(self.icon_path) as img:
                    return img.convert("RGBA").resize((32, 32), Image.Resampling.LANCZOS)
            except Exception as exc:
                logger.warning("Failed to load tray icon from %s: %s", self.icon_path, exc)
        logger.warning("Falling back to generated tray icon")
        return self._create_generated_icon()

    def run_backend(self):
        """Run the backend service."""
        try:
            from backend.app.api.routes import app

            logger.info("Starting backend service at %s", self.url)
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                log_config=None,
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception as exc:
            self.backend_error = str(exc)
            logger.error("Backend startup failed: %s", exc, exc_info=True)

    def wait_for_backend(self, timeout_seconds=20):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.backend_thread and not self.backend_thread.is_alive():
                return False
            try:
                with socket.create_connection((self.host, self.port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.3)
        return False

    def open_browser(self, icon=None, item=None):
        webbrowser.open(self.url)

    def show_status(self, icon=None, item=None):
        tray_icon = icon or self.icon
        if tray_icon:
            try:
                tray_icon.notify(
                    f"监听地址: {self.host}:{self.port}",
                    f"{APP_NAME} 正在后台运行",
                )
            except Exception as exc:
                logger.warning("Failed to show tray notification: %s", exc)

    def _noop(self, icon=None, item=None):
        return None

    def _menu_status_label(self, item):
        return f"{APP_NAME} 运行中"

    def _menu_port_label(self, item):
        return f"监听端口: {self.port}"

    def _menu_address_label(self, item):
        return f"访问地址: {self.url}"

    def on_quit(self, icon=None, item=None):
        logger.info("Exiting application")
        if self.icon:
            self.icon.stop()
        if self.server:
            self.server.should_exit = True
        if self.lock_socket:
            self.lock_socket.close()
        os._exit(0)

    def _show_fallback_control_window(self, error_message):
        logger.error("Showing fallback control window because tray initialization failed")
        root = tk.Tk()
        root.title(APP_NAME)
        root.geometry("420x180")
        root.resizable(False, False)

        def open_browser():
            webbrowser.open(self.url)

        def quit_app():
            root.destroy()
            self.on_quit(None, None)

        message = (
            f"{APP_NAME} 正在运行，但系统托盘初始化失败。\n\n"
            f"地址: {self.url}\n\n"
            f"错误: {error_message}"
        )
        tk.Label(root, text=message, justify="left", wraplength=380).pack(padx=20, pady=(20, 16))

        button_frame = tk.Frame(root)
        button_frame.pack()
        tk.Button(button_frame, text="打开 Web 界面", width=14, command=open_browser).pack(side="left", padx=8)
        tk.Button(button_frame, text="退出程序", width=14, command=quit_app).pack(side="left", padx=8)

        root.protocol("WM_DELETE_WINDOW", quit_app)
        root.mainloop()

    def setup_tray(self):
        """Use pystray native menu with runtime metadata and no startup toast."""
        try:
            image = self._load_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem(self._menu_status_label, self._noop, enabled=False),
                pystray.MenuItem(self._menu_port_label, self._noop, enabled=False),
                pystray.MenuItem(self._menu_address_label, self._noop, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("打开 Web 界面", self.open_browser, default=True),
                pystray.MenuItem("显示运行状态", self.show_status),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self.on_quit),
            )

            self.icon = pystray.Icon(APP_NAME, image, APP_TITLE, menu)
            logger.info("System tray initialized using pystray native menu")
            self.icon.run()
        except Exception as exc:
            logger.error("Failed to initialize tray icon: %s", exc, exc_info=True)
            self._show_fallback_control_window(str(exc))

    def run(self):
        if not self.check_single_instance():
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("提示", "应用已在运行中，请在系统托盘查看。")
            sys.exit(0)

        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS
        else:
            base_dir = project_root
            bundle_dir = base_dir

        data_dir = os.path.join(base_dir, "data")
        config_dir = os.path.join(data_dir, "config")
        os.makedirs(config_dir, exist_ok=True)

        os.environ["DATA_PATH"] = data_dir
        config_path = os.path.join(config_dir, "config.yaml")
        os.environ["CONFIG_PATH"] = config_path

        log_path = os.path.join(data_dir, "app.log")
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers = []

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        if sys.stdout:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        if not os.path.exists(config_path):
            import shutil

            bundled_candidates = [
                os.path.join(bundle_dir, "backend", "config", "config.yaml"),
                os.path.join(bundle_dir, "config", "config.yaml"),
            ]
            for bundled_config in bundled_candidates:
                if os.path.exists(bundled_config):
                    shutil.copy2(bundled_config, config_path)
                    logger.info("Copied default config to %s", config_path)
                    break

        self.backend_thread = threading.Thread(target=self.run_backend, daemon=True)
        self.backend_thread.start()

        if self.wait_for_backend():
            self.open_browser()
        else:
            logger.error("Backend did not become ready in time")
            if self.backend_error:
                logger.error("Backend error: %s", self.backend_error)

        self.setup_tray()


if __name__ == "__main__":
    app_instance = DesktopApp()
    app_instance.run()
