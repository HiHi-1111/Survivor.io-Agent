$ErrorActionPreference = "Stop"

$repoZip = "https://github.com/HiHi-1111/Survivor.io/archive/refs/heads/main.zip"
$installRoot = Join-Path $HOME "Survivor.io-Agent"
$tempZip = Join-Path $env:TEMP "survivor-io-agent.zip"
$tempExtract = Join-Path $env:TEMP "survivor-io-agent-extract"

Write-Host "Installing uv..."
powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
$uv = Join-Path $HOME ".local\bin\uv.exe"
if (-not (Test-Path $uv)) { $uv = "uv" }

Write-Host "Downloading Survivor.io agent..."
Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
Invoke-WebRequest -Uri $repoZip -OutFile $tempZip
Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

if (Test-Path $installRoot) {
    Write-Host "Updating existing installation..."
    Remove-Item $installRoot -Recurse -Force
}
Move-Item (Join-Path $tempExtract "Survivor.io-main") $installRoot
Set-Location $installRoot

Write-Host "Installing Python and dependencies..."
& $uv python install 3.12
& $uv sync

function Read-SecretText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$openai = Read-SecretText "Paste your OPENAI_API_KEY"
$composio = Read-SecretText "Paste your COMPOSIO_API_KEY"

@"
OPENAI_API_KEY=$openai
COMPOSIO_API_KEY=$composio
SURVIVOR_USER_ID=survivor_admin_001
"@ | Set-Content -Path ".env" -Encoding UTF8

Write-Host ""
Write-Host "Installation complete. Starting the agent..."
& $uv run python agent.py
