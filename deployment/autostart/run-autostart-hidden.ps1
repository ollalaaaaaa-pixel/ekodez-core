param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('backend', 'frontend')]
    [string]$Service
)
$ErrorActionPreference = 'Stop'
$rootPath = Split-Path -Parent $PSScriptRoot
$batchPath = Join-Path $rootPath "scripts\start-$Service.bat"
$logPath = Join-Path $rootPath "logs\autostart-$Service.log"
$statePath = Join-Path $rootPath "logs\autostart-$Service.previous.json"
$previousCode = 'unknown'
$previousLine = ''
if (Test-Path -LiteralPath $logPath) {
    $tail = @(Get-Content -LiteralPath $logPath -Tail 50)
    $lastLine = if ($tail.Count) { [string]$tail[-1] } else { '' }
    # A crash without WRAPPER EXIT must not inherit an older exit code.
    if ($lastLine -match 'WRAPPER EXIT .* code=(-?\d+)') { $previousCode = $Matches[1] }
    for ($i = $tail.Count - 1; $i -ge 0; $i--) {
        if ($tail[$i] -match 'WRAPPER START') { break }
        if ($tail[$i] -notmatch 'WRAPPER EXIT' -and $tail[$i].Trim()) {
            $previousLine = [string]$tail[$i]
            break
        }
    }
}
$previousLine = $previousLine -replace '\b\d{8,12}:[A-Za-z0-9_-]{25,}', '[TOKEN]'
$previousLine = $previousLine -replace '[A-Za-z]:\\[^"\r\n]+', '[PATH]'
$previousLine = $previousLine -replace '\b\d{10,}\b', '[NUMBER]'
if ($previousLine.Length -gt 300) { $previousLine = $previousLine.Substring(0, 300) }
$details = @{previous_exit_code=$previousCode;previous_last_line=$previousLine} | ConvertTo-Json -Compress
$rebootContext = 'reboot_context=unavailable'
$helper = Join-Path $PSScriptRoot 'reboot-context.ps1'
if (Test-Path -LiteralPath $helper) {
    . $helper
    $rebootContext = Get-RecentRebootContext
}
Add-Content -LiteralPath $logPath -Value "[$([DateTimeOffset]::Now.ToString('o'))] WRAPPER START $Service $details $rebootContext"
$process = Start-Process -FilePath $env:ComSpec `
    -ArgumentList @('/d', '/c', "call `"$batchPath`"") `
    -WindowStyle Hidden -Wait -PassThru
$code = $process.ExitCode
@{exit_code=$code} | ConvertTo-Json -Compress | Set-Content -LiteralPath $statePath
Add-Content -LiteralPath $logPath -Value "[$([DateTimeOffset]::Now.ToString('o'))] WRAPPER EXIT $Service code=$code"
exit $code
