param([Parameter(Mandatory=$true)][string]$Root,
      [Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
$flag = Join-Path $Root 'deploy-in-progress'
if (Test-Path -LiteralPath $flag) { exit 20 }
$backend = [IO.Path]::GetFullPath((Join-Path $Root 'ekodez-core\backend'))
$log = Join-Path $Root 'logs\autostart-backend.log'
function Get-BackendConnections {
    try { Get-NetTCPConnection -LocalPort 8000 -ErrorAction Stop }
    catch {
        if ($_.FullyQualifiedErrorId -notlike 'CmdletizationQuery_NotFound_LocalPort*') { throw }
    }
}
$marker = '--instance-root "' + $backend + '"'
$processes = @(Get-CimInstance Win32_Process)
$candidates = @($processes | Where-Object {
    $_.ExecutablePath -eq $PythonExecutable -and
    $_.CommandLine -like '*-m scripts.run_backend*' -and
    $_.CommandLine.Contains($marker)
})
if ($candidates.Count -gt 1) { throw 'Ambiguous backend identity' }
$legacy = @($processes | Where-Object {
    $_.ExecutablePath -eq $PythonExecutable -and
    ($_.CommandLine -like '*-m uvicorn app.main:app*' -or
     $_.CommandLine -like '*-m scripts.run_backend*') -and
    $_.ProcessId -notin $candidates.ProcessId
})
if ($legacy.Count) { throw 'Unmarked backend: controlled deployment required' }
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($candidate in $candidates) {
    $identity = Invoke-CimMethod -InputObject $candidate -MethodName GetOwnerSid
    if ($identity.ReturnValue -ne 0 -or $identity.Sid -ne $ownerSid) {
        throw 'Backend process belongs to another owner'
    }
}
$ports = @(Get-BackendConnections)
foreach ($connection in $ports) {
    if ($connection.OwningProcess -ne 0 -and $connection.OwningProcess -notin $candidates.ProcessId) {
        throw 'Unverified port owner'
    }
}
if (Test-Path -LiteralPath $flag) { exit 20 }
$previous = @(Select-String -LiteralPath $log -Pattern 'WRAPPER START backend' -ErrorAction SilentlyContinue)
$lastStart = if ($previous.Count) { $previous[-1].Line } else { '' }
Stop-ScheduledTask -TaskName EkodezBackend
foreach ($candidate in $candidates) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.ProcessId)"
    if ($current) {
        if ($current.CreationDate -ne $candidate.CreationDate -or
            $current.CommandLine -ne $candidate.CommandLine -or
            $current.ExecutablePath -ne $candidate.ExecutablePath) {
            throw 'Backend identity changed'
        }
        Stop-Process -Id $current.ProcessId -Force
    }
}
$deadline = (Get-Date).AddSeconds(10)
do {
    $remaining = @(Get-BackendConnections |
        Where-Object { $_.State -eq 'Listen' -or $_.OwningProcess -ne 0 })
    if (-not $remaining.Count) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if ($remaining.Count) { throw 'Port not free' }
if (Test-Path -LiteralPath $flag) { exit 20 }
Start-ScheduledTask -TaskName EkodezBackend
$deadline = (Get-Date).AddSeconds(40)
do {
    Start-Sleep -Seconds 2
    $starts = @(Select-String -LiteralPath $log -Pattern 'WRAPPER START backend' -ErrorAction SilentlyContinue)
    if ($starts.Count -and $starts[-1].Line -ne $lastStart) {
        try {
            $healthy = $true
            foreach ($path in @('/health', '/health/db')) {
                $response = Invoke-WebRequest ('http://127.0.0.1:8000' + $path) -TimeoutSec 3 -UseBasicParsing
                if ($response.StatusCode -ne 200 -or ($response.Content | ConvertFrom-Json).status -ne 'ok') { $healthy = $false }
            }
            if ($healthy) { exit 0 }
        } catch { }
    }
} while ((Get-Date) -lt $deadline)
exit 1
