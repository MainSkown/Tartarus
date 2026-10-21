# Runs inside a guest (stored and executed through its agent by scripts/verify-isolation.sh).
# Prints one `REACH <tcp/port|icmp> yes|no` line per probe of -Target, then `DONE`, so a probe that
# never ran is not mistaken for a blocked one.
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Ports,
    [switch]$Ping
)

foreach ($port in $Ports.Split(',')) {
    $client = New-Object System.Net.Sockets.TcpClient
    $open = $false
    try {
        $pending = $client.BeginConnect($Target, [int]$port, $null, $null)
        $open = $pending.AsyncWaitHandle.WaitOne(4000) -and $client.Connected
    } catch {
        $open = $false
    } finally {
        $client.Close()
    }
    $answer = if ($open) { 'yes' } else { 'no' }
    "REACH tcp/$port $answer"
}

if ($Ping) {
    $echo = & ping.exe -n 1 -w 3000 $Target
    $answer = if ($echo -match 'TTL=') { 'yes' } else { 'no' }
    "REACH icmp $answer"
}

'DONE'
