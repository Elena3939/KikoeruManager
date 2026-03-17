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
from PIL import Image
import uvicorn

# 将项目根目录添加到 python 路径，确保可以找到 backend 包
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.app.api.routes import app
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DesktopApp:
    def __init__(self):
        self.stop_event = threading.Event()
        self.backend_thread = None
        self.icon = None
        self.port = 8000
        self.host = "127.0.0.1"
        self.url = f"http://{self.host}:{self.port}"
        
        # 查找图标路径
        self.icon_path = self._find_icon()

    def _find_icon(self):
        """查找图标文件路径"""
        # 打包后的路径
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            icon_name = "app_icon.ico"
            path = os.path.join(base_path, icon_name)
            if os.path.exists(path):
                return path
        
        # 用户指定的绝对路径
        user_icon = r"D:\Tool\0edba671-6c04-463c-9b4f-7f1cec565830.ico"
        if os.path.exists(user_icon):
            return user_icon
            
        # 默认回退到项目目录下的图标（如果有）
        return None

    def run_backend(self):
        """运行后端服务"""
        try:
            logger.info(f"正在启动后端服务于 {self.url}")
            config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
            server = uvicorn.Server(config)
            server.run()
        except Exception as e:
            logger.error(f"后端启动失败: {e}")

    def open_browser(self):
        """在浏览器中打开应用"""
        webbrowser.open(self.url)

    def on_quit(self, icon, item):
        """退出应用"""
        logger.info("正在退出应用...")
        icon.stop()
        # 后端服务通常会随主进程退出，但为了优雅退出可以进一步处理
        os._exit(0)

    def setup_tray(self):
        """设置系统托盘"""
        try:
            if self.icon_path and os.path.exists(self.icon_path):
                image = Image.open(self.icon_path)
            else:
                # 创建一个简单的占位图标（如果没有找到图标）
                image = Image.new('RGB', (64, 64), color=(73, 109, 137))
            
            menu = pystray.Menu(
                pystray.MenuItem("打开 Prekikoeru", self.open_browser),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self.on_quit)
            )
            
            self.icon = pystray.Icon("kikoeruTool", image, "Kikoeru Tool", menu)
            
            # 点击图标时默认打开浏览器
            self.icon.run()
        except Exception as e:
            logger.error(f"托盘图标设置失败: {e}")
            # 如果托盘失败，至少让后端继续运行
            while True:
                time.sleep(1)

    def run(self):
        # 设置环境变量
        # 获取基础路径
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        os.environ['CONFIG_PATH'] = os.path.join(base_dir, 'config', 'config.yaml')
        os.environ['DATA_PATH'] = os.path.join(base_dir, 'data')
        
        # 确保目录存在
        os.makedirs(os.environ['DATA_PATH'], exist_ok=True)

        # 启动后端线程
        self.backend_thread = threading.Thread(target=self.run_backend, daemon=True)
        self.backend_thread.start()

        # 等待后端启动后打开浏览器
        time.sleep(2)
        self.open_browser()

        # 启动托盘图标 (阻塞主线程)
        self.setup_tray()

if __name__ == "__main__":
    app_instance = DesktopApp()
    app_instance.run()
