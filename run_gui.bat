@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   在线壹佰分 刷课工具（GUI，直接运行）
echo ============================================
echo.

REM 首次运行会自动装依赖
python -c "import playwright" 2>nul
if errorlevel 1 (
    echo [安装依赖] 正在安装 playwright ...
    pip install -r requirements.txt
)

python gui.py
