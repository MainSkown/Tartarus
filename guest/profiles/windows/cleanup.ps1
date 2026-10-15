#requires -version 5
<#
  Removes the installers and provisioning payload from WorkDir once the build has fetched the
  provisioning log (so the log is gone only after it is safely off the guest), keeping the agent
  so the scheduled task keeps working. Run by the host step through the agent, after provision.ps1.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string] $WorkDir,
  [Parameter(Mandatory = $true)] [string] $LogName,
  [Parameter(Mandatory = $true)] [string] $DoneMarker,
  [string] $KeepAgent = 'agent.py'
)

$ErrorActionPreference = 'Continue'
$keep = @($KeepAgent, $LogName, $DoneMarker)

Get-ChildItem -Path $WorkDir -File -ErrorAction SilentlyContinue | Where-Object {
  $keep -notcontains $_.Name
} | ForEach-Object {
  try {
    Remove-Item -Path $_.FullName -Force -ErrorAction Stop
    Write-Output "RESULT removed=$($_.Name)"
  }
  catch {
    Write-Output "RESULT kept=$($_.Name) reason=$($_.Exception.Message)"
  }
}
