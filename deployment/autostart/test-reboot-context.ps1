$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'reboot-context.ps1')
$now = [datetime]'2026-09-17T10:00:00'
$result = Get-RecentRebootContext -Now $now -ReadEvents {
    param($Since, $Until)
    foreach ($pair in @(@(1074, -3), @(6005, -2), @(6006, -11), @(41, 1))) {
        [pscustomobject]@{ Id = $pair[0]; TimeCreated = $Until.AddMinutes($pair[1]) }
    }
}
if ($result -notmatch 'id=1074' -or $result -notmatch 'id=6005' -or
    $result -match 'id=6006' -or $result -match 'id=41') { throw 'Event window test failed' }
if ((Get-RecentRebootContext -Now $now -ReadEvents { throw 'synthetic' }) -ne
    'reboot_context=unavailable') { throw 'Error isolation test failed' }
if ((Get-RecentRebootContext -Now $now -ReadEvents {}) -ne
    'reboot_context=none_within_10m') { throw 'Empty window test failed' }
$tokens = $null; $errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'run-autostart-hidden.ps1'), [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'Wrapper syntax check failed' }
Write-Output 'PASS: reboot window, error isolation, empty window, wrapper syntax (no service launch)'
