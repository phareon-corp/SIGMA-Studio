; Inno Setup 6 — instalador do ia4294 para Windows 10/11 64 bits.
;
;   iscc packaging\ia4294.iss
;
; Espera dist\ia4294\ pronto (packaging\build_windows.ps1 faz os dois passos).
; Instala por usuário (sem UAC): a bancada costuma rodar com conta sem
; privilégio, e o app só precisa da porta COM, que não pede administrador.

#define AppName "ia4294"
#define AppVersion "0.1.0"
#define AppPublisher "Phareon"
#define AppExe "ia4294.exe"

[Setup]
AppId={{7A4294A0-16451-4B29-9A42-94A16451B000}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ia4294-{#AppVersion}-setup
SetupIconFile=ia4294.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=
MinVersion=10.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; a pasta inteira que o PyInstaller gerou
Source: "..\dist\ia4294\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (simulador)"; Filename: "{app}\{#AppExe}"; Parameters: "--sim"; Comment: "Abre conectado ao simulador do 4294A, sem instrumento"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
brazilianportuguese.FinishedLabel=O {#AppName} foi instalado.%n%nA interface AR488 aparece como uma porta COM. Se o Windows não reconhecer a placa, instale o driver USB-serial dela (Arduino Mega oficial: driver do Arduino IDE; clones: CH340 ou FTDI) e confira o número da porta no Gerenciador de Dispositivos.

[UninstallDelete]
; o que o app escreve em runtime fica fora de {app}; nada a limpar aqui.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
