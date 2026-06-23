# KLuxMap

KLuxMap은 KIGAM/GEOLUX 자기장 데이터 처리 및 시각화 도구입니다.
프로젝트 생성, Mag Hawk 데이터 변환, 비행 경로 확인, scan line 처리,
Kriging 결과 생성, PNG/KMZ 저장, Google Earth 확인 흐름을 지원합니다.

## Download

GitHub를 기준 배포 위치로 사용합니다.

- Latest release: https://github.com/geolux-sdk/kluxmap/releases/latest
- All releases: https://github.com/geolux-sdk/kluxmap/releases
- Tags: https://github.com/geolux-sdk/kluxmap/tags
- Current version: `V2.0.5`
- Installer asset: `KLuxMap_Setup_Windows_V2.0.5.exe`

릴리스 페이지에 설치 파일이 등록되어 있으면 해당 버전의
`KLuxMap_Setup_Windows_V*.exe` 파일을 내려받아 설치합니다.
릴리스 asset이 없는 태그는 GitHub tag의 source code archive만 제공될 수 있습니다.

## Version History

### V2.0.5

- 새 프로젝트 생성 전 설정 초기화 처리
- Sensor scaling 계산을 `CONVERSION_GAIN` 기준으로 정리
- Sensor 평균 이후 Mag 계산 오류 수정
- 앱 제목, 설치 스크립트, 사용자 가이드의 버전 표기를 `2.0.5`로 갱신

### V2.0.4

- KLuxMap 사용자 가이드 추가
- Kriging KMZ export 및 colorbar overlay 추가
- Kriging 입력값, gridding column, shade alpha 설정 검증 강화
- Kriging 결과를 프로젝트 `results` 폴더에 저장
- 설치 파일명에 Windows 플랫폼과 버전 표기 반영
- 설치 언어 표시 순서를 English 우선으로 정리

### V2.0.3

- Mag Hawk V2025 변환 지원 추가
- Mag Hawk V2025 DAT 포맷 문서 추가
- `minilzo.dll`을 Nuitka 빌드에 포함
- 기존 프로젝트 열기 동작을 `project_settings.json` 기준으로 정리
- 라이선스 만료 확인 추가
- Boundary polygon 우클릭 종료 및 이벤트 충돌 방지 처리

### V2.0.2

- 라인 번호 정렬 방식 변경
- Splash 화면 크기 조정
- Kriging 사선 영역 제외 처리
- 함수명 및 코드 정리

### v2.0.1

- 이전 2.0.x 릴리스 기준 태그

## Documentation

- User guide: [docs/KLuxMap_User_Guide.md](docs/KLuxMap_User_Guide.md)
- Mag Hawk V2025 DAT format: [docs/MagHawk_V2025_DAT_Format.md](docs/MagHawk_V2025_DAT_Format.md)

## Build And Packaging

- Application entry point: `main.py`
- Nuitka build script: `nuitka_gen_ex.bat`
- Windows installer script: `Installer.iss`
- Runtime resources: `img/`, `IGRF14.shc`, `minilzo.dll`

`nuitka_gen_ex.bat` builds the standalone application and renames the generated
executable to `KLuxMap.exe`. `Installer.iss` packages the built executable as a
Windows installer named `KLuxMap_Setup_Windows_V<version>.exe`.
