$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$runner = Join-Path $PSScriptRoot '19_refresh_world.py'
$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $runner) -WorkingDirectory $projectRoot
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 9999)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'MedFire Watch World Observations' -Action $action -Trigger @($hourly,$logon) -Settings $settings -Description 'Refresh NASA observations and imagery availability without Telegram text messages.' -Force | Out-Null
Write-Output 'Registered hourly and logon world-observation refresh.'
