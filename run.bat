@echo off
chcp 65001>nul
if not exist .venv\ (
  python -m venv .venv
)
:test_driver
if exist msedgedriver.exe (
  goto :driver_exists
)
echo 엣지 웹드라이버를 다운로드 한 후 엔터를 눌러주세요...
echo 🔔 대부분의 경우에는 '안정 채널'의 x64가 적합합니다.
echo 🔔 폴더 상위에 'msedgedriver.exe' 파일이 위치하도록 해주세요.
start https://developer.microsoft.com/ko-kr/microsoft-edge/tools/webdriver
pause
goto :test_driver
:driver_exists
call ./.venv/Scripts/activate.bat
pip install -r requirements.txt
python arcaliveArchive.py