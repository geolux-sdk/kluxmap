@echo off
setlocal

REM 1) 빌드할 파이썬 파일
set SRC=main.py

REM 2) Nuitka 출력이 모일 상위 폴더 (원하면 이름 바꿔도 됨: dist, build 등)
set OUT_DIR=%~dp0build

REM 출력 폴더가 없으면 생성
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

REM 3) Nuitka 빌드 (standalone 모드에서는 -o/--output-filename 사용 불가)
python -m nuitka "%SRC%" ^
  --standalone ^
  --mingw64 --jobs=8 ^
  --plugin-enable=pyside6 ^
  --file-reference-choice=runtime ^
  --deployment ^
  --include-data-files=./img/*.png=./img/ ^
  --include-data-files=./IGRF14.shc=./IGRF14.shc ^
  --include-data-files=./minilzo.dll=./minilzo.dll ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=./img/viewer.ico ^
  --output-dir="%OUT_DIR%"

REM 4) exe 이름만 KLuxMap.exe로 변경 (main.dist 안에서)
set DIST_DIR=%OUT_DIR%\main.dist

if exist "%DIST_DIR%\main.exe" (
    pushd "%DIST_DIR%"
    ren main.exe KLuxMap.exe
    popd
)

echo Build completed. Output is in "%DIST_DIR%".
endlocal
