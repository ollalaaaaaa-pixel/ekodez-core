param([Parameter(Mandatory=$true)][string]$Root,
      [Parameter(Mandatory=$true)][string]$PythonExecutable,
      [int]$LockTimeoutMinutes = 10,
      [switch]$Deployment)
$ErrorActionPreference = 'Stop'
$flag = Join-Path $Root 'deploy-in-progress'
$flagAtEntry = Test-Path -LiteralPath $flag
if ($flagAtEntry -and -not $Deployment) { exit 20 }
if ($Deployment -and -not $flagAtEntry) { throw 'Deployment flag required' }
$backend = [IO.Path]::GetFullPath((Join-Path $Root 'ekodez-core\backend'))
$log = Join-Path $Root 'logs\autostart-backend.log'
$lockPath = Join-Path $Root 'logs\backend-restart.lock'
function Write-LogSafe([string]$Message) {
    try {
        Add-Content -LiteralPath $log -ErrorAction Stop -Value "[$([DateTimeOffset]::Now.ToString('o'))] WATCHDOG $Message"
    } catch {
        try { [Console]::Error.WriteLine("WATCHDOG warning=log_write_failed $Message") }
        catch { } # Even a closed stderr must not interrupt recovery.
    }
}
function Get-WrapperStartSafe {
    try {
        $lines = @(Select-String -LiteralPath $log -Pattern 'WRAPPER START backend' -ErrorAction Stop)
        $line = if ($lines.Count) { $lines[-1].Line } else { '' }
        return [pscustomobject]@{Available=$true;Line=$line}
    } catch {
        Write-LogSafe 'warning=wrapper_log_unavailable'
        return [pscustomobject]@{Available=$false;Line=''}
    }
}
if ($LockTimeoutMinutes -lt 1) { throw 'Invalid lock timeout' }
try {
    $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write, [IO.FileShare]::None)
} catch [IO.IOException] {
    if (-not (Test-Path -LiteralPath $lockPath)) { throw }
    $age = [DateTime]::UtcNow - (Get-Item -LiteralPath $lockPath).LastWriteTimeUtc
    if ($age.TotalMinutes -lt $LockTimeoutMinutes) { exit 21 }
    try { Remove-Item -LiteralPath $lockPath -ErrorAction Stop }
    catch { exit 21 }
    Write-LogSafe 'warning=stale_restart_lock'
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write, [IO.FileShare]::None)
    } catch [IO.IOException] { exit 21 }
}
$stopped = $false
$healthChecked = $false
try {
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
$previous = Get-WrapperStartSafe
Stop-ScheduledTask -TaskName EkodezBackend
$stopped = $true
$operationError = $null
try {
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
} catch {
    $operationError = $_
} finally {
    try {
        if (-not $flagAtEntry -and (Test-Path -LiteralPath $flag)) {
            Write-LogSafe 'warning=deploy_flag_during_restart'
        }
    } catch {
        Write-LogSafe 'warning=deploy_flag_check_failed'
    }
    Start-ScheduledTask -TaskName EkodezBackend
}
$deadline = (Get-Date).AddSeconds(40)
do {
    Start-Sleep -Seconds 2
    $currentStart = Get-WrapperStartSafe
    if (-not $currentStart.Available -or -not $previous.Available -or
        ($currentStart.Line -and $currentStart.Line -ne $previous.Line)) {
        $healthChecked = $true
        try {
            $healthy = $true
            foreach ($path in @('/health', '/health/db')) {
                $response = Invoke-WebRequest ('http://127.0.0.1:8000' + $path) -TimeoutSec 3 -UseBasicParsing
                if ($response.StatusCode -ne 200 -or ($response.Content | ConvertFrom-Json).status -ne 'ok') { $healthy = $false }
            }
            if ($healthy) {
                if ($operationError) { exit 22 }
                exit 0
            }
        } catch { }
    }
} while ((Get-Date) -lt $deadline)
exit 1
} finally {
    try { $lockStream.Dispose() }
    catch { Write-LogSafe 'warning=lock_close_failed' }
    if (-not $stopped -or $healthChecked) {
        try { Remove-Item -LiteralPath $lockPath -ErrorAction Stop }
        catch { Write-LogSafe 'warning=lock_cleanup_failed' }
    }
}
