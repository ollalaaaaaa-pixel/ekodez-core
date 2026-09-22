param([string]$Root, [string]$Script, [string]$Scenario)
# All OS mutation and HTTP commands are replaced. Only the temporary test root is written.
$ErrorActionPreference = 'Stop'
$global:fixtureStopped = $false
$global:fixtureActions = Join-Path $Root 'actions.txt'
function Record([string]$value) { Add-Content -LiteralPath $global:fixtureActions -Value $value }
function Get-CimInstance {
    param($ClassName, $Filter)
    $command = '-m scripts.run_backend --instance-root "' + (Join-Path $Root 'ekodez-core\backend') + '"'
    $created = if ($Filter -and $Scenario -eq 'reused') { 2 } else { 1 }
    [pscustomobject]@{ExecutablePath='C:\synthetic\python.exe'; CommandLine=$command; CreationDate=$created; ProcessId=99999}
}
function Get-NetTCPConnection {
    param($LocalPort, $ErrorAction)
    if (-not $global:fixtureStopped) {
        $owner = if ($Scenario -eq 'foreign') { 88888 } else { 99999 }
        [pscustomobject]@{OwningProcess=$owner;State='Listen'}
    }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName)
    $sid = if ($Scenario -eq 'otherowner') { 'other' } else { [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
    [pscustomobject]@{ReturnValue=0;Sid=$sid}
}
function Stop-ScheduledTask { param($TaskName) Record "stop:$TaskName" }
function Stop-Process { param($Id, [switch]$Force) Record "kill:$Id"; $global:fixtureStopped=$true }
function Start-ScheduledTask {
    param($TaskName)
    Record "start:$TaskName"
    Add-Content -LiteralPath (Join-Path $Root 'logs\autostart-backend.log') -Value 'new WRAPPER START backend'
}
function Start-Sleep { param($Seconds, $Milliseconds) }
function Invoke-WebRequest {
    param($Uri, $TimeoutSec, [switch]$UseBasicParsing)
    Record "probe:$Uri"
    [pscustomobject]@{StatusCode=200;Content='{"status":"ok"}'}
}
& $Script -Root $Root -PythonExecutable 'C:\synthetic\python.exe'
exit $LASTEXITCODE
