# Installation de la passerelle Assista-Crise sur un PC Windows.
#
# Lance par le petit fichier .bat telecharge depuis la page Satellites du site, qui lui passe
# l'adresse du site et le code d'installation. Tout est installe dans le profil de
# l'utilisateur : AUCUN droit d'administrateur n'est demande, rien n'est ajoute au demarrage de
# Windows, et la passerelle ne tourne que lorsque sa fenetre est ouverte.
#
# Ce fichier reste en ASCII : PowerShell 5 lit un script sans BOM dans l'encodage regional, et
# les accents y seraient abimes.
param(
    [string]$Central = "",
    [string]$Jeton = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"     # sinon les telechargements sont dix fois plus lents
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$VersionPython = "3.12.10"
$Racine  = Join-Path $env:LOCALAPPDATA "AssistaCrisePasserelle"
$Donnees = Join-Path $env:APPDATA "AssistaCrisePasserelle"
$App     = Join-Path $Racine "app"
$Venv    = Join-Path $Racine "venv"
$PythonLocal = Join-Path $Racine "python\python.exe"

function Etape([string]$texte) {
    Write-Host ""
    Write-Host "== $texte" -ForegroundColor Cyan
}

function Verifier([string]$quoi) {
    if ($LASTEXITCODE -ne 0) { throw "$quoi a echoue (code $LASTEXITCODE)." }
}

function Trouver-Python {
    # 1. Celui que nous avons installe. 2. Un Python 3.12 deja present sur le poste.
    if (Test-Path $PythonLocal) { return $PythonLocal }
    foreach ($ruche in "HKCU:\Software\Python\PythonCore\3.12\InstallPath",
                       "HKLM:\Software\Python\PythonCore\3.12\InstallPath") {
        try {
            $chemin = (Get-ItemProperty -Path $ruche -ErrorAction Stop).ExecutablePath
            if ($chemin -and (Test-Path $chemin)) { return $chemin }
        } catch { }
    }
    return $null
}

try {
    if (-not $Central) { throw "Adresse du site manquante : relancez le fichier telecharge depuis la page Satellites." }
    $Central = $Central.TrimEnd("/")
    New-Item -ItemType Directory -Force -Path $Racine, $Donnees | Out-Null

    # Une passerelle ouverte tient ses fichiers : on ne peut pas la mettre a jour par-dessus.
    $ouverte = $false
    try {
        $essai = New-Object Net.Sockets.TcpClient
        $essai.Connect("127.0.0.1", 47631)
        $ouverte = $essai.Connected
        $essai.Close()
    } catch { }
    if ($ouverte) { throw "La passerelle est ouverte : fermez sa fenetre, puis relancez l'installation." }

    Etape "1/5  Python"
    $python = Trouver-Python
    if (-not $python) {
        Write-Host "Telechargement de Python $VersionPython (environ 25 Mo)..."
        $installeur = Join-Path $Racine "python-installeur.exe"
        Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/$VersionPython/python-$VersionPython-amd64.exe" -OutFile $installeur
        Write-Host "Installation de Python (dans votre profil, sans droits d'administrateur)..."
        $arguments = @("/quiet", "InstallAllUsers=0", "TargetDir=`"$(Join-Path $Racine 'python')`"",
                       "Include_launcher=0", "Shortcuts=0", "AssociateFiles=0", "PrependPath=0",
                       "Include_test=0", "Include_doc=0", "Include_dev=0")
        $p = Start-Process -FilePath $installeur -ArgumentList $arguments -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "L'installation de Python a echoue (code $($p.ExitCode))." }
        Set-Content -Path (Join-Path $Racine "python-installe-par-nous.txt") -Value $VersionPython
        $python = Trouver-Python
        if (-not $python) { throw "Python est introuvable apres son installation." }
    }
    & $python -c "import tkinter, venv"
    Verifier "La verification de Python"
    Write-Host "Python : $python"

    Etape "2/5  Application"
    $archive = Join-Path $Racine "passerelle.zip"
    Invoke-WebRequest -UseBasicParsing "$Central/passerelle/passerelle.zip" -OutFile $archive
    if (Test-Path $App) { Remove-Item -Recurse -Force $App }
    Expand-Archive -Path $archive -DestinationPath $App -Force
    Remove-Item -Force $archive
    if (-not (Test-Path (Join-Path $App "passerelle\__main__.py"))) { throw "Archive de l'application incomplete." }

    Etape "3/5  Composants radio (quelques minutes la premiere fois)"
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
        & $python -m venv $Venv
        Verifier "La creation de l'environnement"
    }
    $pyVenv = Join-Path $Venv "Scripts\python.exe"
    & $pyVenv -m pip install --disable-pip-version-check --quiet --upgrade pip
    & $pyVenv -m pip install --disable-pip-version-check --quiet -r (Join-Path $App "requirements.txt")
    Verifier "L'installation des composants radio"

    Etape "4/5  Enregistrement"
    $dejaEnregistree = Test-Path (Join-Path $Donnees "config.json")
    if ($Jeton -and -not $dejaEnregistree) {
        # Lu une seule fois par l'application au premier lancement, puis supprime.
        $json = "{`"central`": `"$Central`", `"jeton`": `"$Jeton`"}"
        [IO.File]::WriteAllText((Join-Path $Donnees "premier-lancement.json"), $json, (New-Object Text.UTF8Encoding $false))
        Write-Host "Code d'installation pris en compte."
    } elseif ($dejaEnregistree) {
        Write-Host "Passerelle deja enregistree : mise a jour seulement."
    }

    Etape "5/5  Raccourci sur le bureau"
    Copy-Item -Force (Join-Path $App "desinstaller.bat") (Join-Path $Racine "desinstaller.bat")
    $bureau = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $raccourci = $shell.CreateShortcut((Join-Path $bureau "Assista-Crise Passerelle.lnk"))
    $raccourci.TargetPath = Join-Path $Venv "Scripts\pythonw.exe"
    $raccourci.Arguments = "-m passerelle"
    $raccourci.WorkingDirectory = $App
    $raccourci.IconLocation = Join-Path $App "passerelle.ico"
    $raccourci.Description = "Relaie les radios MeshCore et Meshtastic vers Assista-Crise"
    $raccourci.Save()

    Write-Host ""
    Write-Host "Installation terminee. La passerelle s'ouvre." -ForegroundColor Green
    Write-Host "Ensuite : raccourci 'Assista-Crise Passerelle' sur le bureau."
    Start-Process -FilePath (Join-Path $Venv "Scripts\pythonw.exe") -ArgumentList "-m", "passerelle" -WorkingDirectory $App
    Start-Sleep -Seconds 4
    exit 0
}
catch {
    Write-Host ""
    Write-Host "L'installation n'a pas abouti :" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Verifiez la connexion internet du poste, puis relancez le fichier d'installation."
    Read-Host "Appuyez sur Entree pour fermer"
    exit 1
}
