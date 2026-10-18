"""在显式指定的全新目录验证安装依赖，绝不读取开发配置。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_runtime import DesktopRuntime

parser = argparse.ArgumentParser()
parser.add_argument('--install-dir', required=True)
parser.add_argument('--data-dir', required=True)
args = parser.parse_args()
runtime = DesktopRuntime(Path(args.install_dir).resolve(), Path(args.data_dir).resolve())
if runtime.data.exists():
    raise SystemExit('测试数据目录必须不存在，防止影响已有用户数据')
try:
    runtime.start()
    print('首次初始化、pg_trgm 和 Redis PING 验证通过')
finally:
    runtime.stop()
password = runtime.state['pg_password']
try:
    runtime.start()
    assert runtime.state['pg_password'] == password
    print('二次启动保留数据库凭据验证通过')
finally:
    runtime.stop()
print(json.dumps({'result': 'ok', 'data_dir': str(runtime.data)}, ensure_ascii=False))
