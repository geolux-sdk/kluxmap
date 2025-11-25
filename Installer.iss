; ============================
; KLuxMap Inno Setup Script
; ============================

#define MyAppName      "KLuxMap"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "KIGAM & GEOLUX"
#define MyAppExeName   "KLuxMap.exe"
#define MyAppDistDir   "KLuxMap.dist"

[Setup]
AppId={{9D9F8B3B-4A2C-4C1D-9A27-93C63D0D1234}  ; 임의의 GUID, 아무거나 고정으로 쓰면 됨
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={pf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename=KLuxMap_Setup
Compression=lzma
SolidCompression=yes

SetupIconFile=.\img\viewer.ico

; 64비트만 설치하도록 (nuitka --mingw64 로 빌드한 64bit exe 기준)
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

; 설치할 때 쓸 언어 (한국어 + 영어)
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 바탕화면 아이콘 만들기 옵션
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; KLuxMap.dist 폴더 전체를 {app} 으로 복사
; 이 .iss 가 KLuxMap.dist와 같은 폴더에 있다고 가정
Source: "{#MyAppDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
; 시작 메뉴 아이콘
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

; 바탕화면 아이콘 (위에서 Tasks에 연결)
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 설치가 끝난 후 바로 실행할지 여부 체크박스
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 언인스톨 시 APPDATA의 KLuxMap 폴더도 함께 삭제
Type: filesandordirs; Name: "{localappdata}\KLuxMap"