# Quick prerequisite check for ROMTG-Doom. Run: powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ws = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
foreach ($t in 'git','python','cmake','dotnet') {
  $c = Get-Command $t -ErrorAction SilentlyContinue
  if ($c -and $c.Source -notlike '*WindowsApps*') { "[ok]      $t  " + ((& $t --version 2>&1) | Select-Object -First 1) } else { "[MISSING] $t" }
}
$vsw = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = if (Test-Path $vsw) { & $vsw -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property displayName }
if ($vs) { "[ok]      C++ build tools: $vs" } else { "[MISSING] Visual Studio C++ build tools" }
if (Get-Service -Name 'Memurai*' -ErrorAction SilentlyContinue) { "[ok]      Memurai (Redis)" } else { "[MISSING] Memurai (Redis)" }
if (Get-ChildItem "$ws\reference\doom\*.wad" -ErrorAction SilentlyContinue) { "[ok]      IWAD in reference\doom" } else { "[MISSING] IWAD in $ws\reference\doom" }
if (Get-ChildItem "$ws\reference\rotmg\client" -ErrorAction SilentlyContinue) { "[ok]      RotMG client" } else { "[later]   RotMG client in $ws\reference\rotmg\client (run setup.py client)" }
