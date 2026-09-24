param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('backend', 'frontend')]
    [string]$Service
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'reboot-context.ps1')
$projectDirectory = [string]::Concat(
    [char]0x042D, [char]0x043A, [char]0x043E,
    [char]0x0434, [char]0x0435, [char]0x0437
)
$rootPath = Join-Path 'C:\D' $projectDirectory
$batchPath = Join-Path $rootPath "scripts\start-$Service.bat"
$logPath = Join-Path $rootPath "logs\autostart-$Service.log"
$rebootContext = Get-RecentRebootContext
Add-Content -LiteralPath $logPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] WRAPPER START $Service $rebootContext"
$process = Start-Process -FilePath $env:ComSpec `
    -ArgumentList @('/d', '/c', "call `"$batchPath`"") `
    -WindowStyle Hidden -Wait -PassThru
$exitCode = $process.ExitCode
Add-Content -LiteralPath $logPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] WRAPPER EXIT $Service code=$exitCode"
exit $exitCode
