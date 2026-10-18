"""用独立测试服务验证内置/外部混合模式，不连接开发数据库。"""
import argparse
import json
from pathlib import Path
import sys
import subprocess

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_runtime import DesktopRuntime

parser = argparse.ArgumentParser()
parser.add_argument('--install-dir', required=True)
parser.add_argument('--data-dir', required=True)
parser.add_argument('--external-executable')
args = parser.parse_args()
install = Path(args.install_dir).resolve()
base = Path(args.data_dir).resolve()
if base.exists():
    raise SystemExit('测试目录必须不存在')
base.mkdir(parents=True)
owner = DesktopRuntime(install, base / 'owner')
try:
    owner.start()
    for pg, redis in ((False, False), (False, True), (True, False)):
        data = base / f'mode-{pg}-{redis}'
        (data / 'config').mkdir(parents=True)
        external = {
            'database': {'host': '127.0.0.1', 'port': owner.state['pg_port'],
                         'database': 'kikoerumanager', 'username': 'kikoerumanager',
                         'password': owner.state['pg_password'], 'sslmode': 'disable'},
            'redis': {'enabled': True, 'required': True,
                      'url': f"redis://:{owner.state['redis_password']}@127.0.0.1:{owner.state['redis_port']}/0"},
        }
        (data / 'config/config.yaml').write_text(yaml.safe_dump(external), encoding='utf-8')
        runtime = DesktopRuntime(install, data)
        runtime.embedded_pg, runtime.embedded_redis = pg, redis
        try:
            runtime.start()
            assert runtime.pg_started == pg
            assert (runtime.redis_process is not None) == redis
        finally:
            runtime.stop()
        assert (data / 'postgresql/PG_VERSION').exists() == pg
        assert (data / 'redis/redis.conf').exists() == redis
        saved = yaml.safe_load((data / 'config/config.yaml').read_text(encoding='utf-8'))
        if not pg:
            assert saved['database'] == external['database']
        if not redis:
            assert saved['redis']['url'] == external['redis']['url']
        # 外部模式退出不能关闭所连接的服务。
        runtime.check_external_postgres() if not pg else None
        runtime.check_external_redis() if not redis else None
        print(json.dumps({'postgresql': 'embedded' if pg else 'external',
                          'redis': 'embedded' if redis else 'external', 'result': 'ok'}))
    if args.external_executable:
        data = base / 'packaged-external'
        config_path = base / 'packaged-external-config.yaml'
        config_path.write_text(yaml.safe_dump(external), encoding='utf-8')
        result = subprocess.run([str(Path(args.external_executable).resolve()), '--smoke-test-data-dir', str(data),
                                 '--smoke-test-config', str(config_path)],
                                timeout=120)
        assert result.returncode == 0, '打包程序退出失败'
        smoke = json.loads((data / 'smoke-result.json').read_text(encoding='utf-8'))
        assert smoke['shutdown'] == 'ok'
        assert not (data / 'postgresql').exists()
        assert not (data / 'redis').exists()
        probe = DesktopRuntime(install, data)
        probe.check_external_postgres()
        probe.check_external_redis()
        print('打包程序外部服务模式：首页、健康、退出及外部服务存活验证通过')
finally:
    owner.stop()
