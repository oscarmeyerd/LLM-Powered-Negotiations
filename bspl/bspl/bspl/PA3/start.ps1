$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venv = Join-Path $here "..\venv\Scripts\Activate.ps1"

$envFile = Join-Path $here ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#=]+)\s*=\s*(.+)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# Get API key from current environment
$apiKey = $env:OPENROUTER_API_KEY
if (-not $apiKey ) {
    Write-Error " OPENROUTER_API_KEY environment variable not set. Please set it and
        try again."
    exit 1
}
# Helper function to spawn agents with API key
function Start-Agent ($script) {
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "& {
            `$env:OPENROUTER_API_KEY = `'$apiKey`';
            & `"$venv`";
            Set-Location `"$here`";
            python `"$script`"
        }"
    )
}

Start-Agent "buyer.py"
Start-Agent "seller.py"
Start-Agent "shipper.py"

Write-Host "All agents launched. Check individual windows for updates."