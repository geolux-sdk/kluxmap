# KLuxMap 사용 방법

이 문서는 KLuxMap에서 프로젝트를 만들고, 자기장 데이터를 변환하고, 비행 경로와 스캔 라인을 확인한 뒤 Kriging 결과를 저장하거나 Google Earth용 KMZ로 내보내는 기본 절차를 정리한 사용자 가이드입니다.

현재 문서는 KLuxMap V2.0.4 기준입니다.

## 1. 기본 흐름

일반적인 작업 순서는 다음과 같습니다.

1. `Project > Create Project Folder`로 프로젝트를 생성합니다.
2. `Convert > Convert to CSV`로 원시 데이터를 CSV로 변환합니다.
3. `DRONE DATA` 탭에서 측정 비행 데이터를 불러오고 비행 경로를 확인합니다.
4. 필요한 경우 `Trim Filters`, `Line Cut`, `Line Append`를 사용해 비행 데이터를 정리합니다.
5. `SCAN LINE DATA` 탭에서 scan line 데이터를 생성하고 필터를 적용합니다.
6. `Gridding`을 실행해 Kriging 이미지를 생성합니다.
7. `Save Plot` 또는 `KMZ Export`로 결과를 저장합니다.

## 2. 프로젝트 생성

메뉴에서 `Project > Create Project Folder`를 선택합니다.

프로젝트 생성 창에서 다음 항목을 설정합니다.

- `Name`: 프로젝트 이름입니다. 기본값은 날짜 기반 이름으로 생성됩니다.
- `Path`: 프로젝트를 저장할 상위 폴더입니다.
- `Full Path`: 실제 생성될 프로젝트 전체 경로입니다.
- `Flight Azimuth`: 주 비행 방향입니다. 다이얼 또는 숫자 입력으로 설정합니다.

`OK`를 누르면 프로젝트 폴더와 `project_settings.json`이 만들어지고, 프로그램의 각 탭 기능이 활성화됩니다.

## 3. 기존 프로젝트 열기

메뉴에서 `Project > Open Project Folder`를 선택합니다.

선택하는 폴더 안에는 `project_settings.json` 파일이 있어야 합니다. 이 파일이 없으면 기존 프로젝트로 인식하지 않습니다.

최근 사용한 프로젝트는 `Project > Recent Project`에서 다시 열 수 있습니다.

## 4. 프로젝트 초기화

메뉴에서 `Project > Reset Project Folder`를 선택하면 현재 프로젝트 폴더의 데이터가 삭제되고 프로젝트 설정이 다시 초기화됩니다.

주의: 이 기능은 프로젝트 안의 데이터를 삭제하는 작업입니다. 필요한 결과 파일은 먼저 따로 보관한 뒤 실행하십시오.

## 5. 데이터 변환

메뉴에서 `Convert > Convert to CSV`를 선택합니다.

`Data Load` 창에서 장치와 입력 방식을 선택합니다.

지원 장치:

- `Mag Hawk V2022`
- `Mag Hawk V2023`
- `Mag Hawk V2025`
- `Mag Arrow`

주요 옵션:

- `Northern Hemisphere` / `Southern Hemisphere`: V2022, V2023 데이터의 위도 부호 처리에 사용합니다.
- `Folder` / `File`: 폴더 단위 또는 파일 단위로 변환 대상을 선택합니다.
- `1000Hz`, `100Hz`, `10Hz`: Mag Arrow 데이터 변환 시 사용할 sampling rate입니다.
- `Save to`: 변환된 CSV를 저장할 프로젝트 하위 폴더입니다.

저장 위치:

- `Measure Flight Folder`: 일반 측정 비행 데이터
- `Calibration Flight Folder`: calibration 비행 데이터
- `Diurnal Data Folder`: 일변화 보정용 데이터

변환이 시작되면 진행 창이 표시됩니다. 변환된 CSV는 선택한 `Save to` 폴더에 저장되고, 중간 처리 데이터는 `.processed` 폴더에 저장됩니다.

## 6. IAGA-2002 파일 가져오기

메뉴에서 `Convert > Import IAGA-2002 FILE`을 선택합니다.

이 기능은 IAGA-2002 형식의 SEC 파일을 읽어 `Date`, `Time`, `Mag` 컬럼을 가진 CSV로 변환합니다. 결과는 프로젝트의 `Diurnal Data Folder`에 저장됩니다.

## 7. Boundary Info 설정

메뉴에서 `Convert > Boundary Info`를 선택합니다.

이 창에서는 작업 영역 경계 좌표를 설정합니다. 좌표는 easting/northing 형태의 숫자 쌍으로 입력합니다. 각 줄에는 하나의 점 좌표를 입력합니다.

입력 예:

```text
123456.0 4567890.0
123556.0 4567890.0
123556.0 4567990.0
123456.0 4567990.0
```

## 8. Google Maps API Key 설정

메뉴에서 `Help > Google Maps API Key`를 선택합니다.

Google 지도 배경을 사용하려면 API key를 입력하고 저장합니다. 저장된 key는 사용자 설정에 보관됩니다. 필요하면 `Clear`로 삭제할 수 있습니다.

## 9. Settings 확인

메뉴에서 `Help > Settings`를 선택하면 현재 프로젝트의 `project_settings.json` 내용을 확인할 수 있습니다.

프로젝트가 열려 있지 않거나 설정 파일이 없으면 Settings 창을 열 수 없습니다.

## 10. Calibration Flight 탭

`Calibration Flight` 탭에서는 calibration flight CSV 파일을 불러와 방향별 보정값을 확인합니다.

사용 절차:

1. 프로젝트를 엽니다.
2. `Open Calibration Flight Folder..` 버튼을 누릅니다.
3. 프로젝트의 `Calibration Flight Folder`에서 CSV 파일을 선택합니다.
4. 비행 경로, 방향별 데이터, 속도 그래프를 확인합니다.

계산된 방향별 보정값은 scan line 데이터 필터의 calibration correction에 사용할 수 있습니다.

## 11. DRONE DATA 탭

`DRONE DATA` 탭은 측정 비행 데이터를 확인하고 line 데이터를 만들기 전의 비행 경로를 정리하는 화면입니다.

상단 도구:

- `Open File Browser`: `Measure Flight Folder`에서 CSV 파일을 선택합니다.
- `Trim Filters`: 방향, 연속 데이터 수, 속도, area bound 조건을 설정합니다.
- `Line Cut`: 선택한 구간을 line 데이터에서 제외합니다.
- `Line Append`: 선택한 구간을 line 데이터에 추가합니다.
- `Export KML`: 현재 비행 경로를 Google Earth에서 볼 수 있는 KML 파일로 저장합니다.

내부 탭:

- `Flight`: 원본 또는 필터 적용된 비행 경로를 확인합니다.
- `Line`: line cut/append 작업 결과를 확인합니다.

`Export KML`은 위도/경도 컬럼이 있는 데이터에서 사용할 수 있습니다.

## 12. SCAN LINE DATA 탭

`SCAN LINE DATA` 탭은 scan line 파일을 생성하고, 보정 및 필터를 적용한 뒤, Kriging 처리를 실행하는 화면입니다.

상단 도구:

- `Filter`: scan line 데이터 보정 및 필터 설정
- `Gridding`: 선택한 컬럼으로 Kriging 실행
- `SAVE`: 처리된 scan line CSV 저장

프로젝트의 `results` 폴더에 scan line 파일이 없으면 프로그램이 scan line 생성을 수행할 수 있습니다. 기존 scan line 파일이 있을 경우 새로 생성할지 확인합니다.

`SAVE`를 누르면 각 scan line CSV가 저장되고, 병합 파일 `combined_processed_scanlines.csv`도 같은 결과 폴더에 저장됩니다.

## 13. Scan Line 필터

`SCAN LINE DATA > Filter`에서 다음 보정과 필터를 설정할 수 있습니다.

- `Diurnal Correction`: `Diurnal Data Folder`의 diurnal CSV를 사용해 일변화 보정을 적용합니다.
- `IGRF Correction`: 위도/경도와 시간 정보를 사용해 IGRF 보정을 적용합니다.
- `Median Filter`: 지정한 kernel size로 median filter를 적용합니다.
- `Low-pass Filter`: cutoff frequency 기준으로 low-pass filter를 적용합니다.
- `Calibration Correction`: calibration flight에서 계산한 방향별 offset을 적용합니다.
- `Micro Levelling`: short/long filter, search radius, minimum neighbor count를 사용해 line 간 leveling을 적용합니다.

필터 결과는 원본 컬럼을 바로 덮어쓰기보다 새 컬럼으로 추가되는 방식입니다. 예를 들어 `Mag_median`, `Mag_lowpass`, `Mag_igrf`, `Mag_calibrated`, `Mag_micro` 같은 컬럼이 생성될 수 있습니다.

## 14. Kriging 실행

`SCAN LINE DATA` 탭에서 Kriging에 사용할 숫자 컬럼을 테이블에서 선택한 뒤 `Gridding`을 누릅니다.

주의 사항:

- 컬럼을 선택하지 않으면 Kriging 창을 열지 않습니다.
- 선택한 컬럼은 숫자 데이터여야 합니다.
- `X`, `Y`, 선택 컬럼에 숫자가 아닌 값이나 빈 값이 있으면 해당 행은 제외됩니다.
- Kriging에는 최소 3개의 유효한 숫자 행이 필요합니다.

Kriging 창 주요 항목:

- `Shade`: hillshade 효과를 켜거나 끕니다.
- `Contour`: contour line을 켜거나 끕니다.
- `Flight Path`: 원본 비행 경로 점을 함께 표시합니다.
- `X Min`, `X Max`, `Y Min`, `Y Max`: gridding 범위입니다.
- `X Grid`, `Y Grid`: gridding 해상도입니다.
- `Run Kriging`: 현재 설정으로 Kriging을 다시 실행합니다.
- `Save Plot`: 현재 plot 이미지를 저장합니다.

grid 입력 제한:

- grid 개수는 2 이상이어야 합니다.
- 너무 큰 grid는 계산 시간과 메모리를 크게 사용하므로 제한됩니다.
- min 값은 max 값보다 작아야 합니다.

## 15. Kriging 설정

Kriging 창 상단 toolbar에서 세부 설정을 바꿀 수 있습니다.

`Shade` 설정:

- `Azimuth`: 빛 방향 각도
- `Altitude`: 빛 고도 각도
- `Vertical Exaggeration`: 음영 강조
- `Fraction`: hillshade fraction
- `Alpha Scale`: 음영 alpha scale
- `Alpha Max`: 최대 alpha 값, 0에서 1 사이 값만 허용

`Contour` 설정:

- `Scale`: contour level scale
- `Levels`: contour level 개수
- `Line Width`: contour line 두께
- `Alpha`: contour line 투명도
- `Label Font Size`: contour label 글자 크기

## 16. 결과 저장

### Save Plot

Kriging 창에서 `Save Plot`을 누르면 현재 plot을 이미지 파일로 저장합니다.

기본 저장 위치:

```text
<프로젝트 폴더>/results
```

기본 파일명:

```text
<선택 컬럼>_kriging.png
```

저장 대화상자에서 다른 위치나 파일명을 선택할 수 있습니다.

### KMZ Export

Kriging 창 toolbar에서 `KMZ Export`를 누르면 Google Earth에서 열 수 있는 KMZ 파일을 저장합니다.

기본 저장 위치:

```text
<프로젝트 폴더>/results
```

기본 파일명:

```text
<선택 컬럼>_kriging.kmz
```

KMZ 안에는 다음 항목이 포함됩니다.

- Kriging overlay image
- Colorbar overlay image
- Google Earth에서 overlay 위치를 잡기 위한 KML

KMZ export에는 위도/경도 또는 좌표 변환에 필요한 CRS 정보가 필요합니다.

## 17. Google Earth에서 KMZ 확인

1. Google Earth를 엽니다.
2. `KMZ Export`로 생성한 `.kmz` 파일을 엽니다.
3. 지도 위에 Kriging 이미지와 colorbar가 표시되는지 확인합니다.
4. 이미지 위치가 맞지 않으면 원본 CSV의 `Latitude`, `Longitude`, `X`, `Y`, CRS 정보를 확인합니다.

KML 파일만 따로 열면 이미지 파일 경로 문제로 overlay가 보이지 않을 수 있습니다. Google Earth 확인용으로는 KMZ 파일 사용을 권장합니다.

## 18. 프로젝트 폴더 구조

일반적인 프로젝트 폴더 구조는 다음과 같습니다.

```text
Project_Folder/
  project_settings.json
  .processed/
  Measure Flight Folder/
  Calibration Flight Folder/
  Diurnal Data Folder/
  results/
```

주요 폴더:

- `project_settings.json`: 프로젝트 설정 파일입니다.
- `.processed`: 변환 중간 결과와 내부 처리 파일이 저장됩니다.
- `Measure Flight Folder`: 측정 비행 CSV가 저장됩니다.
- `Calibration Flight Folder`: calibration 비행 CSV가 저장됩니다.
- `Diurnal Data Folder`: 일변화 보정용 CSV가 저장됩니다.
- `results`: scan line CSV, 병합 CSV, Kriging PNG, KMZ 결과가 저장됩니다.

## 19. 설치 파일

Windows 설치 파일은 Inno Setup 스크립트 `Installer.iss`로 생성합니다.

현재 출력 파일명 형식:

```text
KLuxMap_Setup_Windows_V2.0.4.exe
```

설치 언어 선택 화면에서는 영어가 먼저 표시되고, 한국어가 다음에 표시됩니다.

## 20. 자주 확인할 문제

### 프로젝트를 열 수 없음

선택한 폴더 안에 `project_settings.json`이 있는지 확인합니다. 새 프로젝트는 `Project > Create Project Folder`로 생성해야 합니다.

### Convert 결과가 보이지 않음

`Save to`에서 선택한 폴더를 확인합니다. 측정 데이터는 보통 `Measure Flight Folder`에 저장합니다.

### Flight Plot이 비어 있음

`DRONE DATA` 탭에서 `Open File Browser`로 CSV를 선택했는지 확인합니다. CSV에 위치 좌표가 있는지도 확인합니다.

### Scan Line 데이터가 없음

`SCAN LINE DATA` 탭에서 scan line 생성을 수행했는지 확인합니다. 기존 `results` 폴더에 scan line CSV가 있으면 재생성 여부를 묻습니다.

### Kriging 버튼을 눌러도 실행되지 않음

테이블에서 Kriging 대상 컬럼을 먼저 선택해야 합니다. `Date`, `Time` 같은 비수치 컬럼이 아니라 `Mag` 또는 필터 결과 컬럼처럼 숫자 컬럼을 선택하십시오.

### KMZ가 Google Earth에서 이상하게 보임

원본 데이터의 좌표 정보를 확인합니다. Google Earth overlay에는 위도/경도 또는 좌표 변환 가능한 CRS 정보가 필요합니다. 단독 KML보다 KMZ 파일을 사용하는 것이 안전합니다.

