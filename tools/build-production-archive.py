"""按 UTF-8 清单构建发布包，避免 Windows tar 清单依赖系统代码页。"""

import sys
import tarfile
from pathlib import Path


def main():
    root, manifest, overrides, output = map(Path, sys.argv[1:])
    with tarfile.open(output, "w:gz") as archive:
        for name in manifest.read_text(encoding="utf-8").splitlines():
            relative = Path(name)
            if not name or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"非法发布文件路径: {name!r}")
            archive.add(root / relative, arcname=relative.as_posix(), recursive=False)
        for name in ("Dockerfile", ".dockerignore"):
            archive.add(overrides / name, arcname=name, recursive=False)


if __name__ == "__main__":
    main()
