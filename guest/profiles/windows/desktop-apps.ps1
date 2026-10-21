#requires -version 5
<#
  Which processes with a window on the desktop are an open app, for quiet-desktop.ps1 (closes them
  before the clean snapshot) and selftest/guest-facts.ps1 (reports the ones still open after the
  snapshot was reverted). Dot-sourced by both, uploaded next to them: one list, because a second
  copy would drift and the self-test would then fail the guest for an app the closer keeps.

  Loading this file changes nothing; the functions only read.
#>

# Why each name stays open when the desktop is made quiet:
#   explorer and the shell hosts draw the desktop, taskbar, start menu and the flyouts; stopping
#     one blanks the screen or leaves it until the next logon.
#   python and pythonw are the guest agent (a scheduled task started with pythonw.exe by
#     provision.ps1); closing it cuts the host off from the guest for good.
#   powershell, pwsh, cmd and conhost run the very script that is asking, started by the agent.
$KeptProcessNames = @(
  'explorer',
  'ShellExperienceHost',
  'StartMenuExperienceHost',
  'SearchHost',
  'SearchApp',
  'SearchUI',
  'TextInputHost',
  'ApplicationFrameHost',
  'RuntimeBroker',
  'sihost',
  'ctfmon',
  'dwm',
  'LockApp',
  'SecurityHealthSystray',
  'python',
  'pythonw',
  'powershell',
  'pwsh',
  'cmd',
  'conhost'
)

function Test-KeptProcess([string] $ProcessName) {
  return $KeptProcessNames -contains $ProcessName
}

function Get-AppWindowProcess {
  Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and -not (Test-KeptProcess $_.ProcessName) }
}

# Names in, names out: the ones that are an open app, each once, in alphabetical order.
function Select-AppProcessName([string[]] $ProcessNames) {
  return @($ProcessNames | Where-Object { $_ -and -not (Test-KeptProcess $_) } | Sort-Object -Unique)
}
