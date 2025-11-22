# start.ps1   (place in scenarios\logistics)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$venv = Resolve-Path "..\..\venv\Scripts\Activate.ps1"

# helper to spawn a new window with venv active
function Start-Agent($script) {
  Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& { . `"$venv`"; Set-Location `"$here`"; python `"$script`" }"
  )
}

Start-Agent "packer.py"
Start-Agent "wrapper.py"
Start-Agent "labeler.py"
Start-Sleep 2
Start-Agent "merchant.py"

Write-Host "Started 4 agent windows. Close them when done."
