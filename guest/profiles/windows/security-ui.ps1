#requires -version 5
<#
  Finds the Windows Security window and its Tamper Protection switch, for tamper-off.ps1 and
  defender-on.ps1 (dot-sourced by both, uploaded next to them). One copy, because the window is
  found by title among the top-level app frames: a class-name search, which looks right, finds
  nothing, and a fix made in one script must reach the other.

  Only Polish was observed on a real guest. All five switches on the page share one AutomationId,
  so the switch is found by its known names first and as the fifth one second.
#>
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$SecurityAppTitles = @('Zabezpieczenia Windows', 'Windows Security')
$TamperToggleNames = @('Ochrona przed naruszeniami', 'Ochrona przed manipulacją', 'Tamper Protection')
$TamperToggleFallbackIndex = 4

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

function Find-TamperToggle($Window) {
  $toggleCondition = New-Object Windows.Automation.PropertyCondition(
    [Windows.Automation.AutomationElement]::AutomationIdProperty, 'settingToggle'
  )
  $toggles = @($Window.FindAll([Windows.Automation.TreeScope]::Descendants, $toggleCondition))
  $byName = $toggles | Where-Object { $TamperToggleNames -contains $_.Current.Name } | Select-Object -First 1
  if ($byName) { return $byName }
  if ($toggles.Count -gt $TamperToggleFallbackIndex) { return $toggles[$TamperToggleFallbackIndex] }
  return $null
}

function Set-ToggleState($Toggle, [bool] $On) {
  $pattern = $Toggle.GetCurrentPattern([Windows.Automation.TogglePattern]::Pattern)
  $isOn = $pattern.Current.ToggleState -eq [Windows.Automation.ToggleState]::On
  if ($isOn -ne $On) { $pattern.Toggle() }
}

function Close-SecurityWindow($Window) {
  try { $Window.GetCurrentPattern([Windows.Automation.WindowPattern]::Pattern).Close() } catch {}
}
