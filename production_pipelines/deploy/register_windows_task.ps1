param(
    [string]$TaskName = "ArdentMillsProductionETL",
    [string]$RunTime = "02:00",
    [string]$PythonCommand = "py"
)

$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\samir\OneDrive\Desktop\New folder (2)\Ardent Mills project"
$Runner = Join-Path $ProjectDir "production_pipelines\deploy\run_all_production_pipelines.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -PythonCommand `"$PythonCommand`""

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs Ardent Mills OLTP, OLAP incremental, and audit/control pipelines." `
    -Force

Write-Host "Registered task '$TaskName' to run daily at $RunTime."
