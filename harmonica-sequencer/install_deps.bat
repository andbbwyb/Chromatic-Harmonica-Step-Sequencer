@echo off
cd /d "%~dp0"
echo ==============================================
echo  安装依赖
echo ==============================================
echo.
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    pip install -e .
)
if errorlevel 1 (
    echo 安装失败，请确认已安装 Python 3.8+
    pause
    exit /b 1
)
echo.
echo 依赖安装完成，双击 run.bat 启动
pause