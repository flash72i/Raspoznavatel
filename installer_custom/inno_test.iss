; Inno Setup 7 — тест кастомного тёмного мастера и анимированной полосы.
[Setup]
AppId={{7E6C2D0A-9A57-4A7A-9D5F-RSP270TEST}
AppName=Распознаватель
AppVersion=2.7.0
AppVerName=Распознаватель 2.7.0
AppPublisher=flash72i
DefaultDirName={localappdata}\Programs\Raspoznavatel
DefaultGroupName=Распознаватель
OutputDir=..\dist
OutputBaseFilename=Inno-UI-Test
SetupIconFile=..\ui\assets\icon.ico
WizardStyle=modern dark
WizardSizePercent=150
WizardImageFile=..\installer_assets\inno-left-150.png
WizardImageStretch=no
WizardSmallImageFile=..\installer_assets\inno-small.png
WizardBackImageFile=..\installer_assets\inno-back.png
WizardBackColor=#070b16
WizardImageBackColor=#070b16
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
Uninstallable=no
Compression=none
SolidCompression=no
PrivilegesRequired=lowest
ShowLanguageDialog=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  PageTitle, PageSub: TNewStaticText;
  CardInstall, CardPortable: TPanel;
  RadioInstall, RadioPortable: TNewRadioButton;
  CardTitle1, CardTitle2, CardDesc1, CardDesc2: TNewStaticText;
  Accent1, Accent2: TPanel;
  Bars: array[0..23] of TPanel;
  BarsBaseTop: Integer;
  TimerID: UINT_PTR;
  AnimPhase: Integer;
  PortableMode: Boolean;

function SetTimer(hWnd: HWND; nIDEvent: UINT_PTR; uElapse: UINT; lpTimerFunc: NativeInt): UINT_PTR;
external 'SetTimer@user32.dll stdcall';

function KillTimer(hWnd: HWND; nIDEvent: UINT_PTR): BOOL;
external 'KillTimer@user32.dll stdcall';

procedure AnimTimer(Arg1: HWND; Arg2: UINT; Arg3: UINT_PTR; Arg4: DWORD);
var
  I, H: Integer;
begin
  Inc(AnimPhase);
  for I := 0 to 23 do
  begin
    H := ScaleY(5 + ((AnimPhase * 7 + I * 13) mod 30));
    Bars[I].Height := H;
    Bars[I].Top := BarsBaseTop + ScaleY(38) - H;
  end;
end;

procedure CreateBars;
var
  I, LeftPos: Integer;
begin
  BarsBaseTop := WizardForm.ClientHeight - ScaleY(54);
  LeftPos := ScaleX(24);
  for I := 0 to 23 do
  begin
    Bars[I] := TPanel.Create(WizardForm);
    with Bars[I] do
    begin
      Parent := WizardForm;
      BevelOuter := bvNone;
      BevelInner := bvNone;
      Width := ScaleX(4);
      Height := ScaleY(12);
      Left := LeftPos + I * ScaleX(8);
      Top := BarsBaseTop + ScaleY(38) - Height;
      if I mod 3 = 0 then Color := $00EED322
      else if I mod 3 = 1 then Color := $00F65C8B
      else Color := $00F979E8;
      BringToFront;
    end;
  end;
end;

procedure ModeChanged(Sender: TObject);
begin
  PortableMode := RadioPortable.Checked;
end;

procedure InitializeWizard;
var
  W, CardW, CardH, Gap, OffsetX: Integer;
begin
  AnimPhase := 0;
  PortableMode := False;

  WizardForm.WelcomeLabel1.Visible := False;
  WizardForm.WelcomeLabel2.Visible := False;
  if WizardForm.BeveledLabel <> nil then
    WizardForm.BeveledLabel.Visible := False;

  OffsetX := 360;
  W := WizardForm.WelcomePage.Width - OffsetX - ScaleX(24);
  Gap := ScaleX(18);
  CardW := W;
  CardH := ScaleY(112);

  PageTitle := TNewStaticText.Create(WizardForm.WelcomePage);
  with PageTitle do
  begin
    Parent := WizardForm.WelcomePage;
    Left := OffsetX;
    Top := ScaleY(22);
    Width := W;
    AutoSize := False;
    Caption := 'Как установить «Распознаватель»?';
    Font.Size := 15;
    Font.Style := [fsBold];
    Font.Color := $00FFECE8;
  end;

  PageSub := TNewStaticText.Create(WizardForm.WelcomePage);
  with PageSub do
  begin
    Parent := WizardForm.WelcomePage;
    Left := OffsetX;
    Top := ScaleY(58);
    Width := W;
    Height := ScaleY(30);
    AutoSize := False;
    Caption := 'Выберите режим. Оба варианта работают' + #13#10 + 'без прав администратора.';
    Font.Size := 9;
    Font.Color := $00C9A59A;
  end;

  CardInstall := TPanel.Create(WizardForm.WelcomePage);
  with CardInstall do
  begin
    Parent := WizardForm.WelcomePage;
    Left := OffsetX;
    Top := ScaleY(92);
    Width := CardW;
    Height := CardH;
    BevelOuter := bvRaised;
    Color := $00351A11;
  end;

  Accent1 := TPanel.Create(CardInstall);
  with Accent1 do
  begin
    Parent := CardInstall;
    Left := 0; Top := 0; Width := CardInstall.Width; Height := ScaleY(2);
    BevelOuter := bvNone;
    Color := $00EED322;
  end;

  RadioInstall := TNewRadioButton.Create(CardInstall);
  with RadioInstall do
  begin
    Parent := CardInstall;
    Left := ScaleX(14); Top := ScaleY(14);
    Width := CardInstall.Width - ScaleX(28);
    Caption := 'Установить в систему';
    Font.Size := 10;
    Font.Style := [fsBold];
    Font.Color := $00FFECE8;
    Checked := True;
    OnClick := @ModeChanged;
  end;

  CardTitle1 := TNewStaticText.Create(CardInstall);
  with CardTitle1 do
  begin
    Parent := CardInstall;
    Left := ScaleX(14); Top := ScaleY(46);
    Width := CardInstall.Width - ScaleX(28);
    Height := CardH - ScaleY(56);
    AutoSize := False;
    Caption := 'Ярлыки в «Пуск» и на рабочем столе.' + #13#10 + 'Удаление через «Приложения».' + #13#10 + 'Данные в профиле.';
    Font.Size := 8;
    Font.Color := $00C9A59A;
  end;

  CardPortable := TPanel.Create(WizardForm.WelcomePage);
  with CardPortable do
  begin
    Parent := WizardForm.WelcomePage;
    Left := OffsetX;
    Top := ScaleY(92) + CardH + ScaleY(12);
    Width := CardW;
    Height := CardH;
    BevelOuter := bvRaised;
    Color := $002B150E;
  end;

  Accent2 := TPanel.Create(CardPortable);
  with Accent2 do
  begin
    Parent := CardPortable;
    Left := 0; Top := 0; Width := CardPortable.Width; Height := ScaleY(2);
    BevelOuter := bvNone;
    Color := $00F65C8B;
  end;

  RadioPortable := TNewRadioButton.Create(CardPortable);
  with RadioPortable do
  begin
    Parent := CardPortable;
    Left := ScaleX(14); Top := ScaleY(14);
    Width := CardPortable.Width - ScaleX(28);
    Caption := 'Портативная версия';
    Font.Size := 10;
    Font.Style := [fsBold];
    Font.Color := $00FFECE8;
    OnClick := @ModeChanged;
  end;

  CardTitle2 := TNewStaticText.Create(CardPortable);
  with CardTitle2 do
  begin
    Parent := CardPortable;
    Left := ScaleX(14); Top := ScaleY(46);
    Width := CardPortable.Width - ScaleX(28);
    Height := CardH - ScaleY(56);
    AutoSize := False;
    Caption := 'Папка Raspoznavatel-Portable' + #13#10 + 'рядом с установщиком.' + #13#10 + 'Без реестра и ярлыков.';
    Font.Size := 8;
    Font.Color := $00C9A59A;
  end;

  CreateBars;
  TimerID := SetTimer(0, 0, 80, CreateCallback(@AnimTimer));
end;

procedure CurPageChanged(CurPageID: Integer);
var
  I: Integer;
begin
  for I := 0 to 23 do
    Bars[I].Visible := CurPageID = wpWelcome;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpWelcome then
  begin
    PortableMode := RadioPortable.Checked;
    if PortableMode then
      WizardForm.DirEdit.Text := AddBackslash(ExtractFilePath(ExpandConstant('{srcexe}'))) + 'Raspoznavatel-Portable'
    else
      WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Programs\Raspoznavatel');
  end;
end;

procedure DeinitializeSetup;
begin
  if TimerID <> 0 then
  begin
    KillTimer(0, TimerID);
    TimerID := 0;
  end;
end;
