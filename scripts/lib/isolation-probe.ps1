# Runs inside a guest (stored and executed through its agent by scripts/verify-isolation.sh).
#
# Reads one probe per line from -SpecFile, in the form
#     name TAB target TAB port TAB payload TAB marker TAB source
# where port says what kind of probe it is:
#     a TCP port   the connection completes and, when marker is set, the reply matches it
#     any:PORT     the target answers at all, a completed connection or a refusal (a RST): a firewall that
#                  drops the SYN is told from one that lets it reach a host with nothing listening
#     icmp         an echo reply arrives (when marker is set, its `ping` output matches it: `TTL=128`)
#     arp          the guest holds a resolved neighbour entry for the target after the other probes ran
# payload is base64 of the bytes to send once connected (may be empty), marker is a regular expression the
# reply must match (empty: a completed connection is enough) and source is a local address of this guest to
# send from (empty: the default one). It prints `REACH <name> yes|no` for every probe, then `DONE`, so a
# probe that never ran is not mistaken for a blocked one.
#
# A marker is how a real service is told from INetSim: on the inetsim route the rooter redirects every
# TCP port to INetSim, which accepts a connection to any address, so a connection alone proves nothing.
param(
    [Parameter(Mandatory = $true)][string]$SpecFile
)

$ConnectDeadlineMs = 5000
$ReplyDeadlineMs = 3000
$PingDeadlineMs = 5000
$AnyPrefix = 'any:'
$ConnectionRefused = [Net.Sockets.SocketError]::ConnectionRefused
$LiveNeighborStates = @('Reachable', 'Stale', 'Delay', 'Probe', 'Permanent')

function Wait-Until([scriptblock]$Done, [int]$DeadlineMs) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (-not (& $Done) -and $clock.ElapsedMilliseconds -lt $DeadlineMs) { Start-Sleep -Milliseconds 100 }
}

function Read-Probes([string]$Path) {
    foreach ($line in Get-Content -LiteralPath $Path) {
        if (-not $line.Trim()) { continue }
        $name, $target, $port, $payload, $marker, $source = $line.Split("`t")
        [pscustomobject]@{
            Name = $name; Target = $target; Port = $port; Payload = $payload; Marker = $marker; Source = $source
            Client = $null; Connecting = $null; Reading = $null; Buffer = New-Object byte[] 4096; Reply = ''; Reached = $false
            Process = $null
        }
    }
}

function Test-Kind($Probe, [string]$Kind) {
    if ($Kind -eq 'tcp') { return $Probe.Port -notin @('icmp', 'arp') }
    return $Probe.Port -eq $Kind
}

function Get-TcpPort($Probe) { [int]($Probe.Port -replace "^$AnyPrefix", '') }

# Pings run side by side: a silent target costs three seconds, and one run has dozens of them.
function Start-Ping($Probe) {
    $arguments = @('-n', '1', '-w', '3000')
    if ($Probe.Source) { $arguments += @('-S', $Probe.Source) }
    $info = New-Object Diagnostics.ProcessStartInfo 'ping.exe', (($arguments + $Probe.Target) -join ' ')
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.CreateNoWindow = $true
    $Probe.Process = [Diagnostics.Process]::Start($info)
}

function Receive-Ping($Probe) {
    $echo = $Probe.Process.StandardOutput.ReadToEnd()
    $pattern = if ($Probe.Marker) { $Probe.Marker } else { 'TTL=' }
    $Probe.Reached = [bool]($echo -match $pattern)
}

function Clear-Neighbor($Probe) {
    Remove-NetNeighbor -AddressFamily IPv4 -IPAddress $Probe.Target -Confirm:$false -ErrorAction SilentlyContinue
}

function Test-Neighbor($Probe) {
    $entry = Get-NetNeighbor -AddressFamily IPv4 -IPAddress $Probe.Target -ErrorAction SilentlyContinue |
        Where-Object { $LiveNeighborStates -contains [string]$_.State -and $_.LinkLayerAddress -match '[1-9a-fA-F]' }
    $Probe.Reached = [bool]$entry
}

function Start-Connect($Probe) {
    try {
        $Probe.Client = if ($Probe.Source) {
            New-Object System.Net.Sockets.TcpClient((New-Object System.Net.IPEndPoint([Net.IPAddress]::Parse($Probe.Source), 0)))
        } else {
            New-Object System.Net.Sockets.TcpClient
        }
        $Probe.Connecting = $Probe.Client.BeginConnect($Probe.Target, (Get-TcpPort $Probe), $null, $null)
    } catch { }
}

function Test-Connected($Probe) {
    $Probe.Client -and $Probe.Connecting -and $Probe.Connecting.IsCompleted -and $Probe.Client.Connected
}

function Test-Refused($Probe) {
    if (-not $Probe.Connecting -or -not $Probe.Connecting.IsCompleted) { return $false }
    try { $Probe.Client.EndConnect($Probe.Connecting) } catch {
        # A .NET method call wraps what it throws, so the socket error is the inner exception.
        $inner = $_.Exception.InnerException
        return ($inner -is [Net.Sockets.SocketException]) -and $inner.SocketErrorCode -eq $ConnectionRefused
    }
    return $false
}

function Start-Exchange($Probe) {
    $stream = $Probe.Client.GetStream()
    if ($Probe.Payload) {
        $bytes = [Convert]::FromBase64String($Probe.Payload)
        $stream.Write($bytes, 0, $bytes.Length)
    }
    $Probe.Reading = $stream.BeginRead($Probe.Buffer, 0, $Probe.Buffer.Length, $null, $null)
}

function Receive-Reply($Probe) {
    if (-not $Probe.Reading -or -not $Probe.Reading.IsCompleted) { return }
    $stream = $Probe.Client.GetStream()
    $count = 0
    try { $count = $stream.EndRead($Probe.Reading) } catch { }
    $Probe.Reading = $null
    if ($count -eq 0) { return }
    $Probe.Reply += [Text.Encoding]::GetEncoding('iso-8859-1').GetString($Probe.Buffer, 0, $count)
    if ($Probe.Reply -match $Probe.Marker) { $Probe.Reached = $true; return }
    $Probe.Reading = $stream.BeginRead($Probe.Buffer, 0, $Probe.Buffer.Length, $null, $null)
}

$probes = @(Read-Probes $SpecFile)
$pings = @($probes | Where-Object { Test-Kind $_ 'icmp' })
$neighbours = @($probes | Where-Object { Test-Kind $_ 'arp' })
$tcp = @($probes | Where-Object { Test-Kind $_ 'tcp' })

foreach ($probe in $neighbours) { Clear-Neighbor $probe }
foreach ($probe in $pings) { Start-Ping $probe }
foreach ($probe in $tcp) { Start-Connect $probe }
Wait-Until { -not ($tcp | Where-Object { $_.Connecting -and -not $_.Connecting.IsCompleted }) } $ConnectDeadlineMs

$connected = @($tcp | Where-Object { Test-Connected $_ })
$judged = @($connected | Where-Object { $_.Marker })
foreach ($probe in $connected) {
    if (-not $probe.Marker) { $probe.Reached = $true; continue }
    try { Start-Exchange $probe } catch { }
}
foreach ($probe in @($tcp | Where-Object { $_.Port.StartsWith($AnyPrefix) -and -not (Test-Connected $_) })) {
    $probe.Reached = Test-Refused $probe
}
Wait-Until { $judged | ForEach-Object { Receive-Reply $_ }; -not ($judged | Where-Object { $_.Reading }) } $ReplyDeadlineMs

foreach ($probe in $pings) {
    if (-not $probe.Process.WaitForExit($PingDeadlineMs)) { $probe.Process.Kill(); continue }
    Receive-Ping $probe
}
foreach ($probe in $neighbours) { Test-Neighbor $probe }

foreach ($probe in $probes) {
    if ($probe.Client) { $probe.Client.Close() }
    "REACH $($probe.Name) $(if ($probe.Reached) { 'yes' } else { 'no' })"
}
'DONE'
