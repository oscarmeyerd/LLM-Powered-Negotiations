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

Start-Agent "seller.py"
Start-Agent "shipper.py"
Start-Sleep 2
Start-Agent "buyer.py"

Write-Host "`n=== Purchase Scenario Started ===" -ForegroundColor Green
Write-Host "Three agent windows have been opened:" -ForegroundColor White
Write-Host "  1. Seller - Processes RFQs and manages inventory" -ForegroundColor Cyan
Write-Host "  2. Shipper - Handles logistics and deliveries" -ForegroundColor Cyan  
Write-Host "  3. Buyer - Initiates purchases and receives deliveries" -ForegroundColor Cyan
Write-Host "`nWatch the interaction between agents in each window." -ForegroundColor White
Write-Host "The buyer will send 5 purchase requests and make decisions based on pricing." -ForegroundColor White
Write-Host "`nClose the agent windows when you're finished observing the scenario." -ForegroundColor Yellow