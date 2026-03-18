#!/usr/bin/env python3
"""
Prekikoeru 桌面应用入口 (带系统托盘)
用于 Windows 打包
"""
import sys
import os
import threading
import webbrowser
import time
import pystray
import socket
from PIL import Image
import uvicorn
import logging
import signal

# 将项目根目录添加到 python 路径，确保可以找到 backend 包
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DesktopApp:
    def __init__(self):
        self.stop_event = threading.Event()
        self.backend_thread = None
        self.icon = None
        self.port = 8000
        self.lock_port = 29173  # 专门用于单实例锁定的端口
        self.host = "127.0.0.1"
        self.url = f"http://{self.host}:{self.port}"
        self.lock_socket = None
        self.backend_error = None
        self.server = None
        
        # 查找图标路径
        self.icon_path = self._find_icon()

    def check_single_instance(self):
        """检查应用是否已经在运行"""
        try:
            self.lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 尝试绑定端口，如果失败说明应用已在运行
            self.lock_socket.bind((self.host, self.lock_port))
            # 锁定成功，我们是第一个实例
            return True
        except socket.error:
            # 绑定失败，说明已有实例
            return False

    def _find_icon(self):
        """查找图标文件路径"""
        user_icon = r"D:\Tool\0edba671-6c04-463c-9b4f-7f1cec565830.ico"
        logger.info(f"检查主图标路径: {user_icon}")
        if os.path.exists(user_icon):
            logger.info(f"找到主图标: {user_icon}")
            return user_icon

        # 打包后的资源路径
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            icon_filename = os.path.basename(user_icon)
            path = os.path.join(base_path, icon_filename)
            logger.info(f"检查打包内图标路径: {path}")
            if os.path.exists(path):
                logger.info(f"找到打包内图标: {path}")
                return path
        
        # 尝试项目根目录下的 fallback 图标
        project_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "app.ico")
        logger.info(f"检查备用图标路径: {project_icon}")
        if os.path.exists(project_icon):
            logger.info(f"找到备用图标: {project_icon}")
            return project_icon
            
        logger.warning("未找到任何图标，将使用默认占位图")
        return None

    def run_backend(self):
        """运行后端服务"""
        try:
            from backend.app.api.routes import app
            logger.info(f"正在启动后端服务于 {self.url}")
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                log_config=None
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception as e:
            self.backend_error = str(e)
            logger.error(f"后端启动失败: {e}", exc_info=True)

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
        """在浏览器中打开应用"""
        webbrowser.open(self.url)

    def show_status(self, icon, item):
        """显示当前运行状态"""
        icon.notify("应用正在后台运行", "Prekikoeru")

    def on_quit(self, icon, item):
        """优雅退出应用"""
        logger.info("正在退出应用...")
        if self.icon:
            self.icon.stop()
        
        # 释放锁定端口
        if self.lock_socket:
            self.lock_socket.close()
            
        # 强制退出，确保所有线程结束
        os._exit(0)

    def setup_tray(self):
        """设置系统托盘"""
        try:
            logger.info(f"正在加载图标，路径: {self.icon_path}")
            if self.icon_path and os.path.exists(self.icon_path):
                # 显式转换图像格式以确保兼容性
                with Image.open(self.icon_path) as img:
                    image = img.convert('RGBA')
                    # Windows 托盘建议使用 16x16 或 32x32，pystray 虽能处理但预缩放更稳定
                    image = image.resize((32, 32), Image.Resampling.LANCZOS)
            else:
                # 创建一个简单的占位图标
                image = Image.new('RGBA', (64, 64), color=(73, 109, 137, 255))
            
            menu = pystray.Menu(
                pystray.MenuItem("打开浏览器界面", self.open_browser, default=True),
                pystray.MenuItem("查看运行状态", self.show_status),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("访问地址: " + self.url, lambda: None, enabled=False),
                pystray.MenuItem("托盘运行中 (点击退出)", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出应用", self.on_quit)
            )
            
            self.icon = pystray.Icon("kikoeruTool", image, "Prekikoeru (运行中)", menu)
            
            # 启动通知
            def notify_start():
                try:
                    self.icon.notify("Prekikoeru 已在后台启动", "您可以通过托盘图标进行管理")
                except Exception as e:
                    logger.warning(f"发送启动通知失败: {e}")

            threading.Timer(2.0, notify_start).start()
            
            logger.info("系统托盘已启动并阻塞主线程")
            self.icon.run()
        except Exception as e:
            logger.error(f"托盘图标设置失败 (致命错误): {e}", exc_info=True)
            # 保持后端运行
            while True:
                time.sleep(1)

    def run(self):
        # 1. 检查单实例
        if not self.check_single_instance():
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("提示", "应用已在运行中，请在系统托盘查看。")
            sys.exit(0)

        # 2. 设置环境变量与基础路径
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = base_dir

        data_dir = os.path.join(base_dir, 'data')
        config_dir = os.path.join(data_dir, 'config')
        os.makedirs(config_dir, exist_ok=True)

        os.environ['DATA_PATH'] = data_dir
        config_path = os.path.join(config_dir, 'config.yaml')
        os.environ['CONFIG_PATH'] = config_path
        log_path = os.path.join(data_dir, 'app.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers = []
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        if sys.stdout:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 如果外部配置文件不存在，则从包内复制
        if not os.path.exists(config_path):
            import shutil
            bundled_config = os.path.join(bundle_dir, 'backend', 'config', 'config.yaml')
            if os.path.exists(bundled_config):
                shutil.copy2(bundled_config, config_path)
                logger.info(f"已从包内复制默认配置到: {config_path}")
            else:
                # 尝试另一个可能的路径
                bundled_config = os.path.join(bundle_dir, 'config', 'config.yaml')
                if os.path.exists(bundled_config):
                    shutil.copy2(bundled_config, config_path)
                    logger.info(f"已从包内复制默认配置到: {config_path}")

        # 3. 启动后端线程
        self.backend_thread = threading.Thread(target=self.run_backend, daemon=True)
        self.backend_thread.start()

        # 4. 等待后端启动后打开浏览器 (如果是初次运行)
        if self.wait_for_backend():
            self.open_browser()
        else:
            logger.error("后端未在预期时间内启动")
            if self.backend_error:
                logger.error(f"后端错误信息: {self.backend_error}")

        # 5. 启动托盘图标 (阻塞主线程)
        self.setup_tray()

if __name__ == "__main__":
    app_instance = DesktopApp()
    app_instance.run()
