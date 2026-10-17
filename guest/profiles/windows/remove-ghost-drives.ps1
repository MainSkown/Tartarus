#requires -version 5
<#
  Removes the optical drives the installation left behind. A running guest has no drive, but Windows
  keeps a non-present CD-ROM device for each one it saw, and a sample can still read those entries
  (decision 6 of the M7 foundations). Runs through the guest agent before the clean snapshot.

  Best-effort and idempotent: a device that cannot be removed is logged and the script still exits 0,
  and a guest with nothing to remove reports found=0 and removed=0.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

function Result([string] $key, $value) {
  Write-Output ('RESULT {0}={1}' -f $key, $value)
}

$ghosts = @(Get-PnpDevice -Class CDROM -ErrorAction SilentlyContinue | Where-Object { -not $_.Present })
$removed = 0
foreach ($ghost in $ghosts) {
  pnputil /remove-device $ghost.InstanceId | Out-Null
  if ($LASTEXITCODE -eq 0) { $removed++ } else { Write-Output ("could not remove {0}" -f $ghost.InstanceId) }
}
Result 'found' $ghosts.Count
Result 'removed' $removed
exit 0
