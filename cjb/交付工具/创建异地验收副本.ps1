$ErrorActionPreference = 'Stop'
$DeliveryRoot = Split-Path -Parent $PSScriptRoot
$TestParent = Join-Path ([IO.Path]::GetTempPath()) ('viewer-cjb-check-' + [guid]::NewGuid().ToString('N'))
$TestRoot = Join-Path $TestParent 'moved delivery'
New-Item -ItemType Directory -Path $TestRoot | Out-Null
& robocopy.exe $DeliveryRoot $TestRoot /E /XJ /COPY:DAT /DCOPY:DAT /R:0 /W:0 /NFL /NDL /NJH /NJS /NP /XD "$DeliveryRoot\runtime\pnpm-store" "$DeliveryRoot\.runtime" | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'Relocation test copy failed.' }
[pscustomobject]@{parent=$TestParent;root=$TestRoot} | ConvertTo-Json | Set-Content -LiteralPath "$DeliveryRoot\交付清单\异地验收位置.json" -Encoding utf8
Write-Output $TestRoot
