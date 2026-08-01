#!/bin/bash

# KikoeruManager Windows 打包脚本

echo "开始打包 KikoeruManager..."

# 安装依赖
echo "安装依赖..."
pip install pyinstaller
pip install -r backend/requirements.txt

# 打包后端
echo "打包后端..."
cd backend

# 使用 PyInstaller 打包
pyinstaller \
    --onefile \
    --name "kikoerumanager-backend" \
    --add-data "app;app" \
    --hidden-import=uvicorn \
    --hidden-import=fastapi \
    --hidden-import=sqlalchemy \
    --hidden-import=yaml \
    --hidden-import=watchdog \
    --hidden-import=filetype \
    --hidden-import=requests \
    app/main.py

cd ..

# 创建发布目录
echo "创建发布目录..."
mkdir -p dist/kikoerumanager
cp backend/dist/kikoerumanager-backend.exe dist/kikoerumanager/
cp -r config dist/kikoerumanager/
mkdir -p dist/kikoerumanager/data

# 创建启动脚本
cat > dist/kikoerumanager/start.bat << 'EOF'
@echo off
echo Starting KikoeruManager...
start http://localhost:8000
kikoerumanager-backend.exe
pause
EOF

echo "打包完成！"
echo "发布文件位于: dist/kikoerumanager/"
echo "请确保已安装 7-Zip 并添加到系统 PATH"
