@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   打包刷课工具（GUI）成 EXE（onedir）
echo ============================================
echo.

echo [1/3] 安装依赖...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [2/3] 打包中（GUI + injected.js + playwright 一并打入）...
pyinstaller --noconfirm --onedir --noconsole --noupx --name 刷课工具 ^
  --add-data "injected.js;." ^
  --collect-all playwright ^
  gui.py

echo.
echo [3/3] 复制运行所需文件到 dist\刷课工具 ...
set "APP=dist\刷课工具"
if exist injected.js copy /Y injected.js "%APP%\injected.js" >nul
if exist config.ini copy /Y config.ini "%APP%\config.ini" >nul
if exist accounts.txt copy /Y accounts.txt "%APP%\accounts.txt" >nul
if exist face.y4m copy /Y face.y4m "%APP%\face.y4m" >nul
if exist face_front.mp4 copy /Y face_front.mp4 "%APP%\face_front.mp4" >nul
if exist face_turnA.mp4 copy /Y face_turnA.mp4 "%APP%\face_turnA.mp4" >nul
if exist face_turnB.mp4 copy /Y face_turnB.mp4 "%APP%\face_turnB.mp4" >nul
if exist faces xcopy /E /I /Y faces "%APP%\faces" >nul
if exist ffmpeg.exe copy /Y ffmpeg.exe "%APP%\ffmpeg.exe" >nul
if exist ffprobe.exe copy /Y ffprobe.exe "%APP%\ffprobe.exe" >nul

echo.
echo ============================================
echo   完成！可执行文件在 dist\刷课工具\刷课工具.exe
echo   注意：dist\刷课工具 目录里必须有 ffmpeg.exe 和 ffprobe.exe
echo   电脑需已安装 Edge 或 Chrome 浏览器
echo ============================================
pause
