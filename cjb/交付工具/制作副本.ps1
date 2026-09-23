$ErrorActionPreference = 'Stop'
$SourceRoot = 'E:\viewer'
$DeliveryRoot = 'E:\viewer\cjb'
if ([IO.Path]::GetFullPath($PSScriptRoot) -ne "$DeliveryRoot\交付工具") { throw 'This builder is only for the original delivery directory.' }
if (Test-Path -LiteralPath "$DeliveryRoot\交付清单\源码复制清单.json") { throw 'Snapshot already exists; do not overwrite a completed delivery.' }
$ExcludedDirs = @('.git','.agents','.codex','.vscode','.tmp','.venv','node_modules','__pycache__','.pytest_cache','.pytest-tmp','.ruff_cache','.mypy_cache','.vite','.vite-temp','dist','logs','shuju','cjb','.viewer-zp','.viewer-uploads','.viewer-derived','.pnpm-store')
$ExcludedPaths = @('mzml-demo\data','dia-ms2-pipei\Hela_DIA_v2_for_frontend\data','Hela_DIA_v2_PFMB_delivery_20260629\data')
$ExcludedFiles = @('deploy_ssh_helper.py','_p2_1s_run.sh','vite-out.txt','vite-err.txt')
$DataExtensions = @('.raw','.mzml','.mzxml','.pfmb','.zp','.pkl','.pickle','.parquet','.fasta','.fa','.tdf','.tdf_bin','.sqlite','.sqlite3','.db','.zip','.pyc','.log','.tsbuildinfo')
$Entries = [Collections.Generic.List[object]]::new()
$Excluded = [Collections.Generic.List[object]]::new()
function Copy-SourceTree([string]$Directory) {
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
        $relative = $item.FullName.Substring($SourceRoot.Length + 1)
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected source link: $relative" }
        if ($item.PSIsContainer) {
            if (($ExcludedDirs -contains $item.Name) -or ($ExcludedPaths -contains $relative)) {
                $Excluded.Add([pscustomobject]@{path=$relative;reason='data/cache/local-environment directory'})
                continue
            }
            New-Item -ItemType Directory -Path (Join-Path $DeliveryRoot $relative) -Force | Out-Null
            Copy-SourceTree $item.FullName
        } else {
            if (($DataExtensions -contains $item.Extension.ToLowerInvariant()) -or ($ExcludedFiles -contains $relative)) {
                $Excluded.Add([pscustomobject]@{path=$relative;reason='data/cache/local-operations file'})
                continue
            }
            $destination = Join-Path $DeliveryRoot $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            $before = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
            Copy-Item -LiteralPath $item.FullName -Destination $destination
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $before) { throw "Source changed during copy: $relative" }
            $Entries.Add([pscustomobject]@{path=$relative;bytes=$item.Length;sha256=$before})
        }
    }
}
function Copy-Runtime([string]$From, [string]$To, [string[]]$Extra = @()) {
    Write-Output "Copy runtime: $From"
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    & robocopy.exe $From $To /E /XJ /COPY:DAT /DCOPY:DAT /R:0 /W:0 /NFL /NDL /NJH /NJS /NP @Extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Runtime copy failed: $From ($LASTEXITCODE)" }
}
Write-Output 'Copying current source snapshot (including uncommitted files).'
Copy-SourceTree $SourceRoot
New-Item -ItemType Directory -Path "$DeliveryRoot\交付清单","$DeliveryRoot\数据库","$DeliveryRoot\shuju","$DeliveryRoot\runtime\tools","$DeliveryRoot\runtime\installers" -Force | Out-Null
$Entries | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$DeliveryRoot\交付清单\源码复制清单.json" -Encoding utf8
$Excluded | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$DeliveryRoot\交付清单\排除清单.json" -Encoding utf8
Copy-Runtime 'E:\python' "$DeliveryRoot\runtime\python" @('/XD','E:\python\Lib\site-packages','E:\python\Scripts','E:\python\Doc','E:\python\share','E:\python\etc','__pycache__','/XF','python-3.12.7-amd64.exe','*.pyc')
Copy-Runtime "$SourceRoot\back\.venv\Lib\site-packages" "$DeliveryRoot\runtime\python\Lib\site-packages" @('/XD','__pycache__','/XF','*.pyc')
Copy-Runtime 'E:\node.js' "$DeliveryRoot\runtime\node"
Copy-Runtime 'E:\.pnpm-store\v10' "$DeliveryRoot\runtime\pnpm-store\v10"
foreach ($part in @('bin','lib','share')) { Copy-Runtime "E:\postgreSQL\$part" "$DeliveryRoot\runtime\postgresql\$part" }
Copy-Item -LiteralPath 'E:\postgreSQL\server_license.txt','E:\postgreSQL\commandlinetools_3rd_party_licenses.txt' -Destination "$DeliveryRoot\runtime\postgresql"
Copy-Item -LiteralPath 'E:\postgreSQL\installer\vcredist_x64.exe','E:\python\python-3.12.7-amd64.exe' -Destination "$DeliveryRoot\runtime\installers"
Copy-Item -LiteralPath 'C:\Users\65573\AppData\Local\pnpm\.tools\pnpm-exe\10.33.1\pnpm.exe','C:\Users\65573\.local\bin\uv.exe' -Destination "$DeliveryRoot\runtime\tools"
Write-Output "Source snapshot: $($Entries.Count) files. Database server data directory was NOT copied."
