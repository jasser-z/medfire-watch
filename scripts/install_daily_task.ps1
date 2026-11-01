$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$updater = Join-Path $PSScriptRoot '19_refresh_world.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $updater)) {
    throw 'Project Python or satellite/weather updater is missing.'
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $updater) -WorkingDirectory $projectRoot
$daily = New-ScheduledTaskTrigger -Daily -At '08:00'
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName 'MedFire Watch Daily Refresh' -Action $action -Trigger @($daily, $logon) -Settings $settings -Description 'Refresh recent satellite observations and current weather forecasts without Telegram messages.' -Force | Out-Null
Write-Output 'Registered MedFire Watch Daily Refresh for 08:00 and at logon.'
