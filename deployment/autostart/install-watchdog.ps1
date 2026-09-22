param([Parameter(Mandatory=$true)][string]$Root, [switch]$Apply)
$ErrorActionPreference = 'Stop'
if (-not $Apply) { throw 'Deploy approval required: pass -Apply only after owner approval' }
$backend = Join-Path $Root 'ekodez-core\backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$action = New-ScheduledTaskAction -Execute $python -Argument '-B -m scripts.backend_watchdog' -WorkingDirectory $backend
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName EkodezBackendWatchdog -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
