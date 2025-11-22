# Startup script for entire system.

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "AUTOMATED NEGOTIATION SYSTEM" -ForegroundColor Yellow  
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""

# Check environment
if (!(Test-Path "system_manager.py")) {
    Write-Host "ERROR: Run this script from the Project directory" -ForegroundColor Red
    Read-Host "Press Enter to exit" ; exit 1
}

# Determine which Python to use. Prefer activated venv, then ../venv, then system python.
$usingSystemPython = $false
if ($env:VIRTUAL_ENV) {
    $candidate = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
    if (Test-Path $candidate) {
        $venvPython = $candidate
    }
}

if (-not $venvPython) {
    $candidate = "..\venv\Scripts\python.exe"
    if (Test-Path $candidate) {
        $venvPython = $candidate
    }
}

if (-not $venvPython) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $venvPython = $cmd.Definition
        $usingSystemPython = $true
    }
}

if (-not $venvPython -or -not (Test-Path $venvPython)) {
    Write-Host "ERROR: Python interpreter not found (tried activated venv, ../venv, and system python)" -ForegroundColor Red
    Write-Host "Expected ..\venv\Scripts\python.exe or an active virtual environment." -ForegroundColor Red
    Read-Host "Press Enter to exit" ; exit 1
}

# User interface to choose negotiation mode. There are three choices: full system manager, human vs AI, quick bilateral.
Write-Host "CHOOSE YOUR INTERFACE:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  [1] Full System Manager" -ForegroundColor Green
Write-Host "      Complete CLI with all options" -ForegroundColor Gray
Write-Host ""
Write-Host "  [2] Human vs AI Negotiation" -ForegroundColor Green  
Write-Host "      Practice negotiating with agents" -ForegroundColor Gray
Write-Host ""
Write-Host "  [3] Quick Bilateral Setup" -ForegroundColor Green
Write-Host "      Fast agent vs agent setup" -ForegroundColor Gray
Write-Host ""
Write-Host "  [Q] Quit" -ForegroundColor Red
Write-Host ""

$choice = Read-Host "Select option [1/2/3/Q]"

try { # Option handling for mode selected by user.
    # Attempt to activate the virtual environment if not already active and the activation script exists.
    if (-not $env:VIRTUAL_ENV) {
        $activateScript = "..\venv\Scripts\Activate.ps1"
        if (Test-Path $activateScript) {
            Write-Host "Attempting to activate virtual environment..." -ForegroundColor Green
            try {
                & $activateScript
                Write-Host "Activation attempted. (If PowerShell execution policy prevented activation, we'll still run using the interpreter directly.)" -ForegroundColor Yellow
            } catch {
                Write-Host "Warning: Activation failed or was blocked by execution policy. Proceeding using $venvPython directly." -ForegroundColor Yellow
            }
        } else {
            if ($usingSystemPython) {
                Write-Host "No virtual environment activation script found; using system Python: $venvPython" -ForegroundColor Yellow
            } else {
                Write-Host "No activation script found at $activateScript; proceeding to use: $venvPython" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "Using active virtual environment: $env:VIRTUAL_ENV" -ForegroundColor Green
    }

    switch ($choice.ToUpper()) {
        "1" { 
            Write-Host "Launching Full System Manager..." -ForegroundColor Green
            & $venvPython system_manager.py 
        }
        "2" { 
            Write-Host "Launching Human-Agent Negotiation..." -ForegroundColor Green
            & $venvPython human_negotiator.py 
        }
        "3" { 
            Write-Host "Quick Bilateral Setup:" -ForegroundColor Green
            Write-Host "A=Aggressive, C=Cooperative, G=Gradual"
            $agents = Read-Host "Enter two agents (e.g., AC, AG, CG, AA)"
            if ($agents.Length -eq 2) {
                & $venvPython -c "
from system_manager import SystemManager
sm = SystemManager()
agents = ['$($agents[0])', '$($agents[1])']
sm.launch_bilateral_negotiation(agents)
"
            } else {
                Write-Host "Invalid input. Use two letters (A/C/G)" -ForegroundColor Red
            }
        }
        "Q" { 
            Write-Host "Goodbye!" -ForegroundColor Yellow 
            exit 0 
        }
        default { 
            Write-Host "Invalid choice" -ForegroundColor Red 
        }
    }
    
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
} finally {
    Read-Host "`nPress Enter to close"
}
