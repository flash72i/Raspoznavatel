# Кастомный установщик

`SetupShell.cs` — оболочка установщика на WebView2.  
`build_installer_ui.py` собирает `installer_mockup/installer_ui.html` из `preview.html`, встраивая Tailwind и шрифты.  
`inno_setup.iss` — Inno Setup 7 backend.  
`make_final_setup.py` объединяет `SetupShell.exe` и `Raspoznavatel-2.7.0-Setup-Inno.exe` в один установщик.

## Порядок сборки

1. Соберите `SetupShell.cs` в Visual Studio с WebView2 SDK и сохраните результат как `SetupShell.exe` в этой папке. Файл исключён из git.
2. При необходимости пересоберите HTML:

```powershell
.\.venv\Scripts\python.exe .\installer_custom\build_installer_ui.py
```

3. Соберите `inno_setup.iss` в Inno Setup 7 — получится `dist\Raspoznavatel-2.7.0-Setup-Inno.exe`.
4. Запустите:

```powershell
.\.venv\Scripts\python.exe .\installer_custom\make_final_setup.py
```

Результат: `dist\Raspoznavatel-2.7.0-Setup-WebUI.exe`. Переименуйте его в `Raspoznavatel-2.7.0-Setup.exe`.
