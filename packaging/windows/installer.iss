#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\output\windows\app"
#endif
#ifndef OutputDirPath
  #define OutputDirPath "..\..\output\windows"
#endif
[Setup]
AppId={{DB485F61-7A47-453F-A1C4-734E6E57D816}
AppName=KikoeruManager
AppVersion={#AppVersion}
AppVerName=KikoeruManager v{#AppVersion}
SetupIconFile=assets\app.ico
AppPublisher=KikoeruManager
DefaultDirName={localappdata}\Programs\KikoeruManager
DefaultGroupName=KikoeruManager
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDirPath}
OutputBaseFilename=KikoeruManager-Setup-v{#AppVersion}-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
UninstallDisplayIcon={app}\KikoeruManager.exe
CloseApplications=yes
SetupMutex=KikoeruManagerInstaller
AppMutex=KikoeruManagerDesktop

[Languages]
Name: "zhcn"; MessagesFile: "ChineseSimplified.isl"

[Messages]
SetupWindowTitle=安装 - KikoeruManager v{#AppVersion}
WelcomeLabel1=欢迎安装 KikoeruManager v{#AppVersion}
WelcomeLabel2=安装包已包含运行依赖，无需额外下载。%n%n已有 PostgreSQL 或 Redis 服务时，可取消相应组件，首次启动时填写连接信息。%n%n安装过程中可单独选择数据目录，升级和卸载默认保留数据。

[Types]
Name: "full"; Description: "完整安装（使用内置数据库与 Redis）"
Name: "custom"; Description: "自定义安装（可使用已有服务）"; Flags: iscustom

[Components]
Name: "app"; Description: "KikoeruManager 主程序和下载解压工具"; Types: full custom; Flags: fixed
Name: "postgresql"; Description: "内置 PostgreSQL 18（已有可用数据库服务可取消）"; Types: full
Name: "redis"; Description: "内置 Redis（已有可用 Redis 服务可取消）"; Types: full

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\runtime\postgresql,\runtime\redis"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
Source: "{#SourceDir}\runtime\postgresql\*"; DestDir: "{app}\runtime\postgresql"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: postgresql
Source: "{#SourceDir}\runtime\redis\*"; DestDir: "{app}\runtime\redis"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: redis

[InstallDelete]
Type: filesandordirs; Name: "{app}\runtime\postgresql"; Check: RemovePostgres
Type: filesandordirs; Name: "{app}\runtime\redis"; Check: RemoveRedis

[Icons]
Name: "{group}\KikoeruManager"; Filename: "{app}\KikoeruManager.exe"
Name: "{autodesktop}\KikoeruManager"; Filename: "{app}\KikoeruManager.exe"; Tasks: desktopicon
Name: "{group}\打开数据目录"; Filename: "{code:GetDataDirectory}"

[Run]
Filename: "{app}\KikoeruManager.exe"; Description: "启动 KikoeruManager"; Flags: nowait postinstall skipifsilent

[Code]
var
  DataPage: TInputDirWizardPage;
  PostgresPage: TInputOptionWizardPage;
  RedisPage: TInputOptionWizardPage;
  ServiceChoicesLoaded: Boolean;

function RemovePostgres: Boolean;
begin
  Result := not WizardIsComponentSelected('postgresql');
end;

function RemoveRedis: Boolean;
begin
  Result := not WizardIsComponentSelected('redis');
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir, '选择数据存放目录',
    '配置、数据库、缓存和日志保存在哪里？',
    '请选择可写入且空间充足的本地目录。升级时请选择原数据目录；选择新目录将创建全新数据。',
    False, '');
  DataPage.Add('数据目录：');
  DataPage.Values[0] := ExpandConstant('{localappdata}\KikoeruManager');
  PostgresPage := CreateInputOptionPage(DataPage.ID, '选择 PostgreSQL 使用方式',
    '使用安装包内置服务，还是连接本机已有服务？',
    '内置服务由应用自动初始化和管理。已有服务需处于运行状态，并准备专用数据库和连接账号；首次启动时填写连接信息。', True, False);
  PostgresPage.Add('使用安装包内置 PostgreSQL（自动配置）');
  PostgresPage.Add('连接本机已有 PostgreSQL（不安装内置组件，自行填写连接）');
  PostgresPage.SelectedValueIndex := 0;
  RedisPage := CreateInputOptionPage(PostgresPage.ID, '选择 Redis 使用方式',
    '使用安装包内置服务，还是连接本机已有服务？',
    '内置服务由应用自动启动和停止。已有服务由你自行管理，首次启动时填写连接地址和密码。', True, False);
  RedisPage.Add('使用安装包内置 Redis（自动配置）');
  RedisPage.Add('连接本机已有 Redis（不安装内置组件，自行填写连接）');
  RedisPage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := PageID = wpSelectComponents;
end;

function GetDataDirectory(Param: String): String;
begin
  Result := DataPage.Values[0];
end;

procedure CurPageChanged(CurPageID: Integer);
var
  ExistingLocation: AnsiString;
begin
  if CurPageID = DataPage.ID then
  begin
    if LoadStringFromFile(ExpandConstant('{app}\data-location.txt'), ExistingLocation) then
      DataPage.Values[0] := Trim(UTF8Decode(ExistingLocation));
    if not ServiceChoicesLoaded then
    begin
      if not WizardIsComponentSelected('postgresql') then
        PostgresPage.SelectedValueIndex := 1;
      if not WizardIsComponentSelected('redis') then
        RedisPage.SelectedValueIndex := 1;
      ServiceChoicesLoaded := True;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  SelectedComponents: String;
begin
  Result := True;
  if CurPageID = RedisPage.ID then
  begin
    SelectedComponents := 'app';
    if PostgresPage.SelectedValueIndex = 0 then
      SelectedComponents := SelectedComponents + ',postgresql';
    if RedisPage.SelectedValueIndex = 0 then
      SelectedComponents := SelectedComponents + ',redis';
    WizardSelectComponents(SelectedComponents);
  end;
  if CurPageID = wpSelectDir then
    for I := 1 to Length(WizardDirValue) do
      if Ord(WizardDirValue[I]) > 127 then
      begin
        MsgBox('当前试用版的程序安装路径必须使用英文字母、数字等 ASCII 字符，例如 D:\KikoeruManager。数据目录可单独选择中文路径。', mbError, MB_OK);
        Result := False;
        Exit;
      end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Options: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not SaveStringToFile(ExpandConstant('{app}\data-location.txt'), UTF8Encode(DataPage.Values[0]), False) then
      RaiseException('无法保存数据目录设置。');
    Options := '[runtime]' + #13#10;
    if WizardIsComponentSelected('postgresql') then
      Options := Options + 'postgresql=embedded' + #13#10
    else
      Options := Options + 'postgresql=external' + #13#10;
    if WizardIsComponentSelected('redis') then
      Options := Options + 'redis=embedded' + #13#10
    else
      Options := Options + 'redis=external' + #13#10;
    if not SaveStringToFile(ExpandConstant('{app}\runtime-options.ini'), Options, False) then
      RaiseException('无法保存服务组件设置。');
  end;
end;
