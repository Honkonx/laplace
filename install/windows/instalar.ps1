<#
Instalador de Laplace para Windows: detecta, descarga, instala y configura todo lo necesario SIN tocar el Python, el Node ni el PATH del sistema.

  instalar.bat                       instalación normal (Python propio + dependencias + .env + base de datos; compila la web si hace falta) y al final
                                     ofrece configurar tus conexiones (APIs) y crear tu administrador de la web
  instalar.bat -SinAsistente         no pregunta nada (solo crea el .env con los secretos propios); luego: configurar.bat
  instalar.bat -Reconfigurar         al final abre directamente configurar (cambiar claves); no toca los secretos propios
  instalar.bat -ConNode              instala también Node + pnpm propios y recompila la web (desarrollo)
  instalar.bat -ConML                instala numpy/scipy/scikit-learn (reajuste semanal del modelo y evaluaciones)
  instalar.bat -Rehacer              borra y recrea el entorno de Python (runtime\venv)

Todo vive dentro de esta carpeta (runtime\). Cada descarga se verifica contra una huella SHA-256 fijada en install\runtime-pins.json
(uv: GitHub de Astral; Node: nodejs.org) y se aborta si no coincide. Es repetible: correrlo otra vez solo completa lo que falte.
#>
param(
    [switch]$SinAsistente,
    [switch]$Reconfigurar,
    [switch]$ConNode,
    [switch]$ConML,
    [switch]$Rehacer
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest es muchísimo más rápido sin la barra de progreso
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Runtime = Join-Path $Raiz 'runtime'
$Cache = Join-Path $Runtime 'cache'
$Venv = Join-Path $Runtime 'venv'
$PythonVenv = Join-Path $Venv 'Scripts\python.exe'
Set-Location $Raiz

function Paso($texto)  { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Ok($texto)    { Write-Host "    [OK] $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    [AVISO] $texto" -ForegroundColor Yellow }
function Fallo($texto) { Write-Host "    [FALLO] $texto" -ForegroundColor Red; exit 1 }

function Obtener-Plataforma {
    $arq = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    switch ($arq) {
        'AMD64' { return 'windows-x64' }
        'ARM64' { return 'windows-arm64' }
        default { Fallo "Arquitectura no soportada: $arq (se necesita Windows de 64 bits)" }
    }
}

function Descargar-Verificado([string]$Url, [string]$Destino, [string]$Sha256) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Destino) | Out-Null
    if (Test-Path $Destino) {
        if ((Get-FileHash -Algorithm SHA256 -Path $Destino).Hash -ieq $Sha256) { Ok "ya descargado y verificado: $(Split-Path $Destino -Leaf)"; return }
        Remove-Item -Force $Destino
    }
    Write-Host "    descargando $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destino
    $real = (Get-FileHash -Algorithm SHA256 -Path $Destino).Hash
    if ($real -ine $Sha256) {
        Remove-Item -Force $Destino
        Fallo "La huella SHA-256 NO coincide para $(Split-Path $Destino -Leaf).`n    esperada: $Sha256`n    recibida: $real`n    Se canceló la instalación por seguridad (no se extrajo nada)."
    }
    Ok "huella SHA-256 verificada: $(Split-Path $Destino -Leaf)"
}

function Expandir-Zip([string]$Zip, [string]$Destino) {
    if (Test-Path $Destino) { Remove-Item -Recurse -Force $Destino }
    Expand-Archive -Path $Zip -DestinationPath $Destino -Force
}

# ---------------------------------------------------------------------------------------------------------------------------------
Paso 'Revisando el equipo'
$plataforma = Obtener-Plataforma
Ok "sistema: $plataforma"
$unidad = (Get-Item $Raiz).PSDrive
if ($unidad.Free -lt 2GB) { Fallo "Poco espacio libre en $($unidad.Name): ($([math]::Round($unidad.Free / 1GB, 1)) GB). Se necesitan al menos 2 GB." }
Ok "espacio libre: $([math]::Round($unidad.Free / 1GB, 1)) GB"
foreach ($puerto in 9001, 9100) {
    if (Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue) { Aviso "el puerto $puerto ya está en uso (si es otra instancia de Laplace, es normal)" }
}
$pines = Get-Content -Raw -Encoding UTF8 (Join-Path $Raiz 'install\runtime-pins.json') | ConvertFrom-Json

# ---------------------------------------------------------------------------------------------------------------------------------
Paso "uv $($pines.uv.version) (instala Python sin tocar el del sistema)"
$uvDir = Join-Path $Runtime 'uv'
$uv = Join-Path $uvDir 'uv.exe'
$archivoUv = $pines.uv.archivos.$plataforma
if (-not $archivoUv) { Fallo "No hay uv fijado para $plataforma en runtime-pins.json" }
$versionActual = if (Test-Path $uv) { (& $uv --version 2>$null) } else { '' }
if ($versionActual -match [regex]::Escape($pines.uv.version)) {
    Ok "uv $($pines.uv.version) ya instalado"
} else {
    $zip = Join-Path $Cache $archivoUv.archivo
    Descargar-Verificado ($pines.uv.url.Replace('{version}', $pines.uv.version).Replace('{archivo}', $archivoUv.archivo)) $zip $archivoUv.sha256
    Expandir-Zip $zip (Join-Path $Runtime 'uv-tmp')
    $encontrado = Get-ChildItem -Recurse -Path (Join-Path $Runtime 'uv-tmp') -Filter 'uv.exe' | Select-Object -First 1
    if (-not $encontrado) { Fallo 'El archivo de uv no contiene uv.exe' }
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    Copy-Item -Force (Join-Path $encontrado.DirectoryName '*') $uvDir
    Remove-Item -Recurse -Force (Join-Path $Runtime 'uv-tmp')
    Ok "uv $((& $uv --version))"
}
# Aislamiento: Python gestionado dentro de runtime\, nunca el del sistema; caché dentro de runtime\.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Runtime 'python'
$env:UV_CACHE_DIR = Join-Path $Cache 'uv'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_NO_CONFIG = '1'

# ---------------------------------------------------------------------------------------------------------------------------------
Paso "Python $($pines.python) propio"
if ($Rehacer -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv; Ok 'entorno anterior eliminado' }
& $uv python install $pines.python
if ($LASTEXITCODE -ne 0) { Fallo 'No se pudo instalar Python (¿hay conexión a internet?)' }
if (-not (Test-Path $PythonVenv)) {
    & $uv venv $Venv --python $pines.python
    if ($LASTEXITCODE -ne 0) { Fallo 'No se pudo crear el entorno de Python' }
}
Ok "entorno: $Venv ($(& $PythonVenv --version))"

Paso 'Dependencias de Python'
$requisitos = @('-r', 'backend\requirements.txt')
if ($ConML) { $requisitos += @('-r', 'backend\requirements-ml.txt') }
& $uv pip install --python $PythonVenv @requisitos
if ($LASTEXITCODE -ne 0) { Fallo 'Falló la instalación de dependencias' }
Ok 'dependencias instaladas'

# ---------------------------------------------------------------------------------------------------------------------------------
$hayWeb = Test-Path (Join-Path $Raiz 'frontend\dist\index.html')
if ($ConNode -or -not $hayWeb) {
    Paso "Node $($pines.node.version) y pnpm $($pines.pnpm) propios (para compilar la web)"
    $nodeDir = Join-Path $Runtime 'node'
    $archivoNode = $pines.node.archivos.$plataforma
    if (-not (Test-Path (Join-Path $nodeDir 'node.exe'))) {
        $zipNode = Join-Path $Cache $archivoNode.archivo
        Descargar-Verificado ($pines.node.url.Replace('{version}', $pines.node.version).Replace('{archivo}', $archivoNode.archivo)) $zipNode $archivoNode.sha256
        Expandir-Zip $zipNode (Join-Path $Runtime 'node-tmp')
        $interior = Get-ChildItem -Path (Join-Path $Runtime 'node-tmp') -Directory | Select-Object -First 1
        if (Test-Path $nodeDir) { Remove-Item -Recurse -Force $nodeDir }
        Move-Item -Path $interior.FullName -Destination $nodeDir
        Remove-Item -Recurse -Force (Join-Path $Runtime 'node-tmp')
    }
    Ok "Node $((& (Join-Path $nodeDir 'node.exe') --version))"
    $env:PATH = "$nodeDir;$env:PATH"
    $env:COREPACK_HOME = Join-Path $Runtime 'corepack'
    $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
    $env:npm_config_store_dir = Join-Path $Runtime 'pnpm-store'
    if (-not (Test-Path (Join-Path $Raiz 'frontend\package.json'))) {
        Aviso 'Este paquete no incluye los fuentes de la web (frontend\package.json): no se puede compilar. Usa el paquete que trae frontend\dist ya compilada.'
    } elseif ($ConNode -or -not $hayWeb) {
        Push-Location (Join-Path $Raiz 'frontend')
        try {
            & (Join-Path $nodeDir 'corepack.cmd') pnpm install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { Fallo 'pnpm install falló en frontend\' }
            & (Join-Path $nodeDir 'corepack.cmd') pnpm build
            if ($LASTEXITCODE -ne 0) { Fallo 'pnpm build falló en frontend\' }
        } finally { Pop-Location }
        Ok 'web compilada en frontend\dist'
    }
} else {
    Paso 'Web'
    Ok 'frontend\dist ya está compilada (no hace falta Node)'
}

# ---------------------------------------------------------------------------------------------------------------------------------
Paso 'Configuración (.env)'
& $PythonVenv install\comun\configurar_env.py
if ($LASTEXITCODE -ne 0) { Fallo 'No se pudo preparar el .env' }

Paso 'Base de datos'
& $PythonVenv -m alembic -c backend\api\alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { Fallo 'Falló la creación de la base de datos' }
Ok 'base de datos al día'

if ($ConML) {
    $linea = "LAPLACE_PYTHON_ML=$PythonVenv"
    $contenido = Get-Content -Raw -Encoding UTF8 (Join-Path $Raiz '.env')
    if ($contenido -notmatch '(?m)^LAPLACE_PYTHON_ML=') {
        Add-Content -Encoding UTF8 -Path (Join-Path $Raiz '.env') -Value $linea
        Ok 'el reajuste semanal del modelo usará este Python (LAPLACE_PYTHON_ML)'
    }
}

Paso 'Diagnóstico'
& $PythonVenv backend\scripts\doctor.py

$interactivo = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
if ($interactivo -and (-not $SinAsistente -or $Reconfigurar)) {
    Paso 'Conexiones (APIs de datos, IA y Telegram)'
    $respuesta = if ($Reconfigurar) { 'S' } else { Read-Host '¿Configurar ahora tus conexiones? Detecta y prueba cada API [S/n]' }
    if ($respuesta -notmatch '^(n|N)') { & $PythonVenv install\comun\configurar.py }
    if (-not $SinAsistente) {
        Paso 'Administrador de la web'
        $respuesta = Read-Host '¿Crear tu administrador de la web (entra al panel de administración)? [S/n]'
        if ($respuesta -notmatch '^(n|N)') {
            $usuario = Read-Host 'Nombre de usuario del administrador [admin]'
            if (-not $usuario) { $usuario = 'admin' }
            & $PythonVenv backend\scripts\create_admin.py --username $usuario --si-no-hay
        }
    }
}

Write-Host "`nListo. Para encender Laplace:  iniciar.bat" -ForegroundColor Green
Write-Host '   cambiar claves o proveedores: configurar.bat   |   control completo: laplace.bat (estado, detener, logs, doctor)' -ForegroundColor Green
