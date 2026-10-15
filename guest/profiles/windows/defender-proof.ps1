#requires -version 5
<#
  Shows what real-time protection does with the standard test string: writes it to the public
  folder, waits, and reports whether the file is still there. The host step compares that with the
  option the guest was built with. Prints "RESULT write=ok|blocked" and "RESULT eicar_present=True|False".
#>
[CmdletBinding()]
param(
  [int] $WaitSeconds = 15
)

$ErrorActionPreference = 'Stop'

function Result([string] $key, $value) {
  Write-Output ("RESULT {0}={1}" -f $key, $value)
}

# Two halves, joined only here, so no scanner on a dev machine sees the whole string in this file.
$eicarFirstHalf = 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTI'
$eicarSecondHalf = 'VIRUS-TEST-FILE!$H+H*'
$testFile = Join-Path 'C:\Users\Public' 'sample-check.bin'

try {
  try {
    Set-Content -Path $testFile -Value ($eicarFirstHalf + $eicarSecondHalf) -NoNewline
    Result 'write' 'ok'
  }
  catch {
    # Real-time protection may refuse the write itself; the file is then as good as removed.
    Result 'write' 'blocked'
  }
  Start-Sleep -Seconds $WaitSeconds
  Result 'eicar_present' (Test-Path $testFile)
}
finally {
  Remove-Item -Path $testFile -Force -ErrorAction SilentlyContinue
}
exit 0
