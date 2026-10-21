#requires -version 5
<#
  Closes every app on the desktop of the logged-in user's session, so the clean snapshot is taken
  of a quiet desktop. Windows opens Edge on every boot for the captive-portal page INetSim answers
  with, and leaves a "Networks: allow your PC to be discoverable?" prompt behind, so the snapshot
  would otherwise start every analysis with both open. Runs through the guest agent as the last
  pre-snapshot step, after the agent answers.

  Every app window is asked to close first (as the user closing it would) and what is still there
  after the wait is stopped. What stays is the list in desktop-apps.ps1: the shell and what the
  guest needs, above all the agent itself.

  Prints RESULT closed=<names> and RESULT left=<names>. Idempotent: with nothing open it closes
  nothing and exits 0; it exits 1 only when it cannot run.
#>
[CmdletBinding()]
param(
  [int] $GraceSeconds = 5
)

$ErrorActionPreference = 'Stop'

function Result([string] $key, $value) {
  Write-Output ('RESULT {0}={1}' -f $key, $value)
}

function Get-Names([object[]] $Processes) {
  return Select-AppProcessName @($Processes | ForEach-Object { $_.ProcessName })
}

# Windows reads this key when a network is new, so it only helps from the next boot on: the prompt
# that is open now is dismissed by hand below.
function Disable-NewNetworkPrompt {
  $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Network\NewNetworkWindowOff'
  if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
}

function Dismiss-NetworksPrompt {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
  }
  catch {
    Write-Output ('could not send Escape to the foreground flyout: {0}' -f $_.Exception.Message)
  }
}

try {
  . (Join-Path $PSScriptRoot 'desktop-apps.ps1')

  $open = @(Get-AppWindowProcess)
  foreach ($app in $open) { [void] $app.CloseMainWindow() }
  if ($open.Count -gt 0) { Start-Sleep -Seconds $GraceSeconds }

  $stillRunning = @($open | Where-Object { -not $_.HasExited })
  $stillRunning | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1

  Disable-NewNetworkPrompt
  Dismiss-NetworksPrompt

  $left = Get-Names @(Get-AppWindowProcess)
  Result 'closed' ((Get-Names $open | Where-Object { $left -notcontains $_ }) -join ',')
  Result 'left' ($left -join ',')
}
catch {
  Write-Output ('quiet-desktop.ps1 could not run: {0}' -f $_.Exception.Message)
  exit 1
}
exit 0
