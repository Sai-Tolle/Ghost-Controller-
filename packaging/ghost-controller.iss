; Inno Setup script for the Windows installer.
;   iscc /DAppVersion=0.3.0 packaging\ghost-controller.iss
; Input: dist\ghost-handler\ (PyInstaller onedir) and build\ghost-controller.ico,
; both produced by packaging\build-windows.ps1.
;
; Installs per user (no admin prompt) so testers can install and update on
; managed laptops; "Install for all users" is offered on the first page.
; Re-running a newer installer upgrades in place: same AppId, settings kept.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B1C4E-3B7A-4F1D-9C2E-8A5D7F3B2C10}
AppName=Ghost Controller
AppVersion={#AppVersion}
AppVerName=Ghost Controller {#AppVersion}
AppPublisher=Ghost Controller
AppPublisherURL=https://github.com/Sai-Tolle/Ghost-Controller-
AppUpdatesURL=https://github.com/Sai-Tolle/Ghost-Controller-/releases/latest
DefaultDirName={autopf}\Ghost Controller
DefaultGroupName=Ghost Controller
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Ghost_Controller-Setup-x86_64
SetupIconFile=..\build\ghost-controller.ico
UninstallDisplayIcon={app}\ghost-handler.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ghost-handler\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update must not leave files of the previous version's bundle behind.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Ghost Controller"; Filename: "{app}\ghost-handler.exe"
Name: "{autodesktop}\Ghost Controller"; Filename: "{app}\ghost-handler.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ghost-handler.exe"; Description: "{cm:LaunchProgram,Ghost Controller}"; Flags: nowait postinstall skipifsilent
