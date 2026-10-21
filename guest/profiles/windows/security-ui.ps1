#requires -version 5
<#
  Finds the Windows Security window and its Tamper Protection switch, for tamper-off.ps1 and
  defender-on.ps1 (dot-sourced by both, uploaded next to them). One copy, because the window is
  found by title among the top-level app frames: a class-name search, which looks right, finds
  nothing, and a fix made in one script must reach the other.

  Observed on real guests: Polish on Windows 11 (five switches, all with one AutomationId) and
  English on Windows 10 (four switches, no AutomationId at all). The switches are therefore found by
  what they are, anything that supports the TogglePattern, and the Tamper Protection one by its known
  names first and as the last switch second: it is the last on both versions.

  When the window or switch cannot be found, Resolve-TamperAction decides from IsTamperProtected
  whether a switch made by hand already did the job (CONTINUE re-runs the step from the top).
#>
# The pure Select-TamperToggle is tested on hosts that have no UI Automation.
if ($PSVersionTable.PSEdition -eq 'Desktop' -or $IsWindows) {
  Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
}

$SecurityAppTitles = @('Zabezpieczenia Windows', 'Windows Security')
$TamperToggleNames = @('Ochrona przed naruszeniami', 'Ochrona przed manipulacją', 'Tamper Protection')

function Open-SecurityWindow {
  Start-Process 'windowsdefender://threatsettings'
  Start-Sleep -Seconds 2
  $root = [Windows.Automation.AutomationElement]::RootElement
  $frameCondition = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::ClassNameProperty, 'ApplicationFrameWindow'
  )
  for ($attempt = 0; $attempt -lt 10; $attempt++) {
    Start-Sleep -Seconds 1
    foreach ($frame in $root.FindAll([Windows.Automation.TreeScope]::Children, $frameCondition)) {
      if ($SecurityAppTitles -contains $frame.Current.Name) { return $frame }
    }
  }
  return $null
}

function Select-TamperToggle([object[]] $Switches) {
  $present = @($Switches | Where-Object { $_ })
  $byName = $present | Where-Object { $TamperToggleNames -contains $_.Name } | Select-Object -First 1
  if ($byName) { return $byName }
  if ($present.Count -gt 0) { return $present[-1] }
  return $null
}

function Find-TamperToggle($Window) {
  $toggleCondition = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::IsTogglePatternAvailableProperty, $true
  )
  $switches = foreach ($element in $Window.FindAll([Windows.Automation.TreeScope]::Descendants, $toggleCondition)) {
    [pscustomobject]@{ Name = $element.Current.Name; Element = $element }
  }
  $tamperSwitch = Select-TamperToggle $switches
  if ($tamperSwitch) { return $tamperSwitch.Element }
  return $null
}

function Set-ToggleState($Toggle, [bool] $On) {
  $pattern = $Toggle.GetCurrentPattern([Windows.Automation.TogglePattern]::Pattern)
  $isOn = $pattern.Current.ToggleState -eq [Windows.Automation.ToggleState]::On
  if ($isOn -ne $On) { $pattern.Toggle() }
}

function Get-TamperProtected { [bool] (Get-MpComputerStatus).IsTamperProtected }

# The state is language-independent, so it decides what the window and switch lookup cannot:
# 'switch' when the switch was found, 'already-there' when the analyst (or an earlier run) has
# already put Tamper Protection where it is wanted, 'pause' for the manual fallback otherwise.
function Resolve-TamperAction([bool] $ToggleFound, [bool] $TamperProtected, [bool] $Wanted) {
  if ($ToggleFound) { return 'switch' }
  if ($TamperProtected -eq $Wanted) { return 'already-there' }
  return 'pause'
}

function Close-SecurityWindow($Window) {
  if (-not $Window) { return }
  try { $Window.GetCurrentPattern([Windows.Automation.WindowPattern]::Pattern).Close() } catch {}
}
