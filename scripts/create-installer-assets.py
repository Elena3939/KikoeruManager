"""从系统现有图标生成 Windows 安装器素材。"""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
output = root / 'packaging/windows/assets'
output.mkdir(exist_ok=True)
source = Image.open(root / 'frontend/src/assets/icon/webIcon.png').convert('RGBA')
source.save(output / 'app.ico', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
