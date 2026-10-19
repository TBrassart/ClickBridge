#ifndef AppVersion
#define AppVersion "1.0.0"
#endif

[Setup]
AppId={{2C7B01A4-1435-47F5-9D75-6A22E8A401D8}
AppName=ClickBridge
AppVersion={#AppVersion}
AppPublisher=TBrassart
DefaultDirName={autopf}\ClickBridge
DefaultGroupName=ClickBridge
OutputDir=dist
OutputBaseFilename=ClickBridge-Setup
SetupIconFile=logo.ico
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\ClickBridge.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\ClickBridge.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ClickBridge"; Filename: "{app}\ClickBridge.exe"

[Run]
Filename: "{app}\ClickBridge.exe"; Description: "Lancer ClickBridge"; Flags: postinstall nowait runasoriginaluser skipifsilent; Check: not RestartAfterUpdate

[Code]
function RestartAfterUpdate: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/RESTARTAPP') = 0 then
      Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  LaunchCommand: String;
begin
  if (CurStep = ssPostInstall) and RestartAfterUpdate() then
  begin
    { The updater may have launched this installer from a PyInstaller one-file
      process. Clear its stale extraction path before starting the new app. }
    LaunchCommand := '/D /C set "_MEIPASS2=" && set "PYINSTALLER_RESET_ENVIRONMENT=1" && start "" /B "' +
                     ExpandConstant('{app}\ClickBridge.exe') + '"';
    ExecAsOriginalUser(ExpandConstant('{sys}\cmd.exe'), LaunchCommand,
                       ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode);
  end;
end;
