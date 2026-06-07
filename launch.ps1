# Launch script: starts the scheduler in a hidden window, then Streamlit.
# This is the recommended way to run the app. If you skip the scheduler
# (e.g. you just `streamlit run` directly), background jobs won't run.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Activate venv if it exists
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & ".venv\Scripts\Activate.ps1"
} elseif (Test-Path "venv\Scripts\Activate.ps1") {
    & "venv\Scripts\Activate.ps1"
}

# Read the streamlit port from config.yaml (default 8502)
$Port = 8502
if (Test-Path "config.yaml") {
    $cfg = Get-Content "config.yaml" -Raw
    if ($cfg -match "port:\s*(\d+)") {
        $Port = [int]$Matches[1]
    }
}

# Start the scheduler in a hidden window. This is REQUIRED for background
# jobs (inbox poll, outreach dispatch, compliance audit) to run.
$SchedulerScript = Join-Path $ProjectRoot "app\scheduler.py"
if (-not (Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.MainModule.FileName -like "*python*" -and $_.CommandLine -like "*scheduler.py*" })) {
    Write-Host "Starting scheduler in hidden window..."
    Start-Process -FilePath "python" -ArgumentList "-u", "`"$SchedulerScript`"" `
        -WindowStyle Hidden -RedirectStandardOutput "data\scheduler.out.log" `
        -RedirectStandardError "data\scheduler.err.log"
} else {
    Write-Host "Scheduler already running."
}

# Brief pause so the scheduler has time to start
Start-Sleep -Seconds 2

# Start Streamlit
Write-Host "Starting Streamlit on port $Port..."
& "streamlit" "run" "app\Home.py" "--server.port" $Port "--server.headless" "false"
