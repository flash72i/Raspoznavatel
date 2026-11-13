; installer.nsi — установщик «Распознаватель» 2.7.0
; Версия: Распознаватель 2.7.0
; NSIS 3 Unicode. Сборка: makensis installer.nsi
; Результат: dist\Raspoznavatel-2.7.0-Setup.exe
;
; Два режима:
;   * установка для текущего пользователя (ярлыки, удаление, реестр);
;   * портативная распаковка рядом с установщиком (без реестра и ярлыков).

Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"
!include "WinMessages.nsh"
!include "FileFunc.nsh"

!define APP_NAME "Распознаватель"
!define APP_VERSION "2.7.0"
!define APP_EXE "Raspoznavatel.exe"
!define APP_REG "Software\Raspoznavatel"
!define UNINST_REG "Software\Microsoft\Windows\CurrentVersion\Uninstall\Raspoznavatel"
!define PORTABLE_DIR "Raspoznavatel-Portable"

; --- оформление: все MUI_* до !include "MUI2.nsh" ---
!define MUI_ABORTWARNING
!define MUI_ICON   "ui\assets\icon.ico"
!define MUI_UNICON "ui\assets\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "installer_assets\welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "installer_assets\unwelcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "installer_assets\header.bmp"
!define MUI_HEADERIMAGE_RIGHT

Name "${APP_NAME}"
OutFile "dist\Raspoznavatel-2.7.0-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Raspoznavatel"
InstallDirRegKey HKCU "${APP_REG}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Распознаватель ${APP_VERSION} · офлайн"

Icon "ui\assets\icon.ico"
UninstallIcon "ui\assets\icon.ico"

VIProductVersion "2.7.0.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "FileDescription" "Установщик «${APP_NAME}» ${APP_VERSION}"
VIAddVersionKey "FileVersion"     "2.7.0"
VIAddVersionKey "ProductVersion"  "2.7.0"
VIAddVersionKey "LegalCopyright"  "Open source (flash72i)"
VIAddVersionKey "Comments"        "QR, штрих-коды, OCR, скриншоты, офлайн-перевод, история"

!define MUI_WELCOMEPAGE_TITLE "«Распознаватель» ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "QR-коды и штрих-коды, текст с картинок и с экрана, офлайн-перевод, история распознаваний — без интернета, телеметрии и прав администратора.$\r$\n$\r$\nНа следующем шаге выберите: установить программу или распаковать портативную версию рядом с установщиком."

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить «Распознаватель»"
!define MUI_FINISHPAGE_TEXT "Готово. Программа находится в:$\r$\n$INSTDIR$\r$\n$\r$\nПриятной работы!"

!insertmacro MUI_PAGE_WELCOME
Page custom ModePageShow ModePageLeave

!define MUI_PAGE_CUSTOMFUNCTION_PRE DirectoryPre
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY

!define MUI_PAGE_CUSTOMFUNCTION_PRE ComponentsPre
!insertmacro MUI_PAGE_COMPONENTS

!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"

; ============================ ПЕРЕМЕННЫЕ ============================
Var Mode              ; 0 — установка, 1 — портатив
Var Dialog
Var RadioInstall
Var RadioPortable
Var ModeInfo
Var ModeHint
Var InstallDirSaved
Var FontTitle
Var FontBody

; ============================ СТРАНИЦА РЕЖИМА ============================
Function ModePageShow
  nsDialogs::Create 1018
  Pop $Dialog
  ${If} $Dialog == error
    Abort
  ${EndIf}

  CreateFont $FontTitle "Segoe UI" 16 700
  CreateFont $FontBody "Segoe UI" 9 400

  ${NSD_CreateLabel} 0 0 100% 22u "Как использовать программу?"
  Pop $0
  SendMessage $0 ${WM_SETFONT} $FontTitle 1
  SetCtlColors $0 0x0B1224 0xFFFFFF

  ${NSD_CreateLabel} 0 22u 100% 14u "Выберите один из двух вариантов. Оба работают без прав администратора."
  Pop $0
  SendMessage $0 ${WM_SETFONT} $FontBody 1
  SetCtlColors $0 0x64708F 0xFFFFFF

  ${NSD_CreateRadioButton} 0 44u 100% 14u "Установить программу на этот компьютер"
  Pop $RadioInstall
  ${NSD_OnClick} $RadioInstall ModeChanged
  SendMessage $RadioInstall ${WM_SETFONT} $FontBody 1

  ${NSD_CreateLabel} 14u 58u 92% 22u "Ярлыки в меню «Пуск» и на рабочем столе, удаление через «Приложения», данные в профиле пользователя."
  Pop $0
  SendMessage $0 ${WM_SETFONT} $FontBody 1
  SetCtlColors $0 0x64708F 0xFFFFFF

  ${NSD_CreateRadioButton} 0 90u 100% 14u "Распаковать портативную версию рядом с установщиком"
  Pop $RadioPortable
  ${NSD_OnClick} $RadioPortable ModeChanged
  SendMessage $RadioPortable ${WM_SETFONT} $FontBody 1

  ${NSD_CreateLabel} 14u 104u 92% 22u "Папка «${PORTABLE_DIR}» появится рядом с Setup.exe. Реестр и ярлыки не изменяются."
  Pop $0
  SendMessage $0 ${WM_SETFONT} $FontBody 1
  SetCtlColors $0 0x64708F 0xFFFFFF

  ${NSD_CreateLabel} 0 132u 100% 42u ""
  Pop $ModeInfo
  SendMessage $ModeInfo ${WM_SETFONT} $FontBody 1
  SetCtlColors $ModeInfo 0x0B1224 0xEEF2FF

  ${NSD_CreateLabel} 0 178u 100% 10u "Версия ${APP_VERSION} · офлайн · без телеметрии"
  Pop $ModeHint
  SendMessage $ModeHint ${WM_SETFONT} $FontBody 1
  SetCtlColors $ModeHint 0x8A94B3 0xFFFFFF

  ${If} $Mode == 1
    ${NSD_Check} $RadioPortable
  ${Else}
    ${NSD_Check} $RadioInstall
  ${EndIf}
  Call ModeChanged

  nsDialogs::Show
FunctionEnd

Function ModeChanged
  ${NSD_GetState} $RadioPortable $0
  ${If} $0 == ${BST_CHECKED}
    ${NSD_SetText} $ModeInfo "Портативный режим.$\r$\nПапка рядом с Setup.exe:$\r$\n${PORTABLE_DIR}"
  ${Else}
    ${NSD_SetText} $ModeInfo "Установка для текущего пользователя.$\r$\nПапка: %LOCALAPPDATA%\Programs\Raspoznavatel$\r$\nПрава администратора не нужны."
  ${EndIf}
FunctionEnd

Function ModePageLeave
  ${NSD_GetState} $RadioPortable $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $Mode 1
    StrCpy $INSTDIR "$EXEDIR\${PORTABLE_DIR}"
  ${Else}
    StrCpy $Mode 0
    ${If} $InstallDirSaved != ""
      StrCpy $INSTDIR $InstallDirSaved
    ${Else}
      StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Raspoznavatel"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function DirectoryPre
  ${If} $Mode == 1
    Abort
  ${EndIf}
FunctionEnd

Function DirectoryLeave
  StrCpy $InstallDirSaved $INSTDIR
FunctionEnd

Function ComponentsPre
  ${If} $Mode == 1
    Abort
  ${EndIf}
FunctionEnd

; ============================ УСТАНОВКА ============================
Section "Программа (обязательно)" SecMain
  SectionIn RO

  RMDir /r "$INSTDIR\App"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\Uninstall.exe"

  SetOutPath "$INSTDIR"
  File /r "dist\Raspoznavatel\*.*"

  ${If} $Mode == 0
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    CreateDirectory "$SMPROGRAMS\Распознаватель"
    CreateShortcut "$SMPROGRAMS\Распознаватель\Распознаватель.lnk" "$INSTDIR\${APP_EXE}"
    CreateShortcut "$SMPROGRAMS\Распознаватель\Удаление.lnk" "$INSTDIR\Uninstall.exe"

    WriteRegStr HKCU "${UNINST_REG}" "DisplayName"     "${APP_NAME} ${APP_VERSION}"
    WriteRegStr HKCU "${UNINST_REG}" "DisplayVersion"  "${APP_VERSION}"
    WriteRegStr HKCU "${UNINST_REG}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
    WriteRegStr HKCU "${UNINST_REG}" "Publisher"       "flash72i"
    WriteRegStr HKCU "${UNINST_REG}" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegDWORD HKCU "${UNINST_REG}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINST_REG}" "NoRepair" 1
    WriteRegStr HKCU "${APP_REG}" "InstallDir" "$INSTDIR"
  ${EndIf}
SectionEnd

Section "Ярлык на рабочем столе" SecDesktop
  ${If} $Mode == 0
    CreateShortcut "$DESKTOP\Распознаватель.lnk" "$INSTDIR\${APP_EXE}"
  ${EndIf}
SectionEnd

Section /o "Запускать при включении Windows (свёрнутой в трей)" SecAuto
  ${If} $Mode == 0
    CreateShortcut "$SMSTARTUP\Raspoznavatel.lnk" "$INSTDIR\${APP_EXE}" "--minimized"
  ${EndIf}
SectionEnd

LangString DESC_MAIN ${LANG_RUSSIAN} "Все файлы программы: интерфейс, Tesseract, языковые модели OCR, офлайн-перевод EN<->RU, менеджер языковых пакетов."
LangString DESC_DESK ${LANG_RUSSIAN} "Создать ярлык «Распознаватель» на рабочем столе."
LangString DESC_AUTO ${LANG_RUSSIAN} "Запускать программу вместе с Windows свёрнутой в трей."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain}    $(DESC_MAIN)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_DESK)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAuto}    $(DESC_AUTO)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ============================ УДАЛЕНИЕ ============================
Section Uninstall
  Delete "$DESKTOP\Распознаватель.lnk"
  Delete "$SMSTARTUP\Raspoznavatel.lnk"
  RMDir /r "$SMPROGRAMS\Распознаватель"

  MessageBox MB_YESNO|MB_ICONQUESTION "Удалить также пользовательские данные?$\r$\n(скриншоты, журнал, настройки в папке Raspoznavatel_data и Screenshots)" IDNO +2
  RMDir /r "$INSTDIR\Raspoznavatel_data"
  RMDir /r "$INSTDIR\Screenshots"

  RMDir /r "$INSTDIR\App"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_REG}"
  DeleteRegKey HKCU "${APP_REG}"
SectionEnd

Function .onInit
  SetShellVarContext current
  StrCpy $Mode 0
  StrCpy $InstallDirSaved ""

  ; /PORTABLE — принудительно портативный режим (в том числе для /S).
  ${GetParameters} $R0
  ${GetOptions} $R0 "/PORTABLE" $R1
  ${IfNot} ${Errors}
    StrCpy $Mode 1
    StrCpy $INSTDIR "$EXEDIR\${PORTABLE_DIR}"
  ${EndIf}

  ${If} ${Silent}
    !insertmacro UnselectSection ${SecDesktop}
    !insertmacro UnselectSection ${SecAuto}
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext current
FunctionEnd
