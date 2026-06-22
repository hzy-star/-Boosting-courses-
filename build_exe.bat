@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   打包刷课工具（单文件 EXE，内含 ffmpeg/ffprobe/Python/Playwright）
echo ============================================
echo.

echo [1/2] 安装依赖...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [2/2] 打包中（onefile：把 ffmpeg/ffprobe/injected.js/config.ini/playwright 全部塞进 exe）...
pyinstaller --noconfirm --onefile --noconsole --noupx --name 刷课工具 ^
  --add-data "injected.js;." ^
  --add-data "config.ini;." ^
  --add-binary "ffmpeg.exe;." ^
  --add-binary "ffprobe.exe;." ^
  --collect-all playwright ^
  gui.py

echo.
echo ============================================
echo   完成！单文件在 dist\刷课工具.exe
echo   - 直接把这一个 exe 发给别人即可，对方电脑只要装了 Edge 或 Chrome 就能跑
echo   - 首次/每次启动会先解压到临时目录，体积大、稍慢属正常现象
echo   - 想改默认配置：把 config.ini 放到 exe 同目录即可覆盖内置默认值
echo ============================================
pause
