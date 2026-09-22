function Get-RecentRebootContext {
    param(
        [datetime]$Now = (Get-Date),
        [scriptblock]$ReadEvents = {
            param($Since, $Until)
            Get-WinEvent -FilterHashtable @{
                LogName = 'System'; Id = @(1074, 6005, 6006, 41)
                StartTime = $Since; EndTime = $Until
            } -ErrorAction Stop
        }
    )
    try {
        $events = @(& $ReadEvents $Now.AddMinutes(-10) $Now) | Where-Object {
            $_.Id -in @(1074, 6005, 6006, 41) -and
            $_.TimeCreated -gt $Now.AddMinutes(-10) -and $_.TimeCreated -le $Now
        } | Sort-Object TimeCreated
        $items = @($events | ForEach-Object {
            $reason = switch ($_.Id) {
                1074 { 'planned_shutdown_request' }
                6005 { 'eventlog_started' }
                6006 { 'eventlog_stopped' }
                41 { 'unclean_shutdown' }
            }
            $reasonCode = ''
            if ($_.Id -eq 1074 -and $_.PSObject.Methods['ToXml']) {
                $xml = [xml]$_.ToXml()
                $code = @($xml.Event.EventData.Data | Where-Object {
                    $_.Name -eq 'param4'
                } | ForEach-Object { $_.'#text' }) | Select-Object -First 1
                if ($code -match '^0x[0-9a-fA-F]+$') { $reasonCode = ";code=$code" }
            }
            "id=$($_.Id);at=$($_.TimeCreated.ToString('o'));reason=$reason$reasonCode"
        })
        if ($items.Count -eq 0) { return 'reboot_context=none_within_10m' }
        return 'reboot_context=[' + ($items -join '|') + ']'
    } catch {
        return 'reboot_context=unavailable'
    }
}
