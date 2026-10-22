# Runs inside a guest (stored and executed through its agent by scripts/verify-isolation.sh).
#
# Reads one probe per line from -SpecFile, in the form
#     name TAB target TAB port TAB payload TAB marker TAB source
# where port is a TCP port or `icmp`, payload is base64 of the bytes to send once connected (may be
# empty), marker is a regular expression the reply must match (empty: a completed connection is
# enough) and source is a local address of this guest to send from (empty: the default one). It prints
# `REACH <name> yes|no` for every probe, then `DONE`, so a probe that never ran is not mistaken for a
# blocked one.
#
# A marker is how a real service is told from INetSim: on the inetsim route the rooter redirects every
# TCP port to INetSim, which accepts a connection to any address, so a connection alone proves nothing.
param(
    [Parameter(Mandatory = $true)][string]$SpecFile
)

$ConnectDeadlineMs = 5000
$ReplyDeadlineMs = 3000

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
        }
    }
}

function Test-Ping($Probe) {
    $from = if ($Probe.Source) { @('-S', $Probe.Source) } else { @() }
    $echo = & ping.exe -n 1 -w 3000 @from $Probe.Target
    $Probe.Reached = [bool]($echo -match 'TTL=')
}

function Start-Connect($Probe) {
    try {
        $Probe.Client = if ($Probe.Source) {
            New-Object System.Net.Sockets.TcpClient((New-Object System.Net.IPEndPoint([Net.IPAddress]::Parse($Probe.Source), 0)))
        } else {
            New-Object System.Net.Sockets.TcpClient
        }
        $Probe.Connecting = $Probe.Client.BeginConnect($Probe.Target, [int]$Probe.Port, $null, $null)
    } catch { }
}

function Test-Connected($Probe) {
    $Probe.Client -and $Probe.Connecting -and $Probe.Connecting.IsCompleted -and $Probe.Client.Connected
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
foreach ($probe in $probes) {
    if ($probe.Port -eq 'icmp') { Test-Ping $probe } else { Start-Connect $probe }
}
$tcp = @($probes | Where-Object { $_.Port -ne 'icmp' })
Wait-Until { -not ($tcp | Where-Object { $_.Connecting -and -not $_.Connecting.IsCompleted }) } $ConnectDeadlineMs

$connected = @($tcp | Where-Object { Test-Connected $_ })
$judged = @($connected | Where-Object { $_.Marker })
foreach ($probe in $connected) {
    if (-not $probe.Marker) { $probe.Reached = $true; continue }
    try { Start-Exchange $probe } catch { }
}
Wait-Until { $judged | ForEach-Object { Receive-Reply $_ }; -not ($judged | Where-Object { $_.Reading }) } $ReplyDeadlineMs

foreach ($probe in $probes) {
    if ($probe.Client) { $probe.Client.Close() }
    "REACH $($probe.Name) $(if ($probe.Reached) { 'yes' } else { 'no' })"
}
'DONE'
