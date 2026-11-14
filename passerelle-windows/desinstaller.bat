@echo off
rem Desinstalle la passerelle Assista-Crise de ce compte Windows.
title Desinstallation de la passerelle Assista-Crise
set "RACINE=%LOCALAPPDATA%\AssistaCrisePasserelle"
set "DONNEES=%APPDATA%\AssistaCrisePasserelle"
echo Cette operation retire la passerelle Assista-Crise de ce poste.
echo Fermez d'abord sa fenetre si elle est ouverte.
pause
if exist "%RACINE%\python-installe-par-nous.txt" if exist "%RACINE%\python-installeur.exe" "%RACINE%\python-installeur.exe" /uninstall /quiet
del "%USERPROFILE%\Desktop\Assista-Crise Passerelle.lnk" 2>nul
powershell -NoProfile -Command "$b=[Environment]::GetFolderPath('Desktop'); Remove-Item -Force (Join-Path $b 'Assista-Crise Passerelle.lnk') -ErrorAction SilentlyContinue"
rmdir /s /q "%DONNEES%" 2>nul
cd /d "%TEMP%"
start "" /b cmd /c "timeout /t 2 >nul & rmdir /s /q "%RACINE%""
echo Passerelle desinstallee.
