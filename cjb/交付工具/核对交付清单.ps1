$ErrorActionPreference = 'Stop'
$DeliveryRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Split-Path -Parent $DeliveryRoot
$entries = Get-Content -LiteralPath "$DeliveryRoot\交付清单\源码复制清单.json" -Raw | ConvertFrom-Json
$AllowedChanges = @('back\.env','front\vite.config.ts','start-all.bat','start-back.bat','start-front.bat','.gitignore')
$SourceChanges = @()
$UnexpectedChanges = @()
$Verified = 0
foreach ($entry in $entries) {
    $original = Join-Path $SourceRoot $entry.path
    $copy = Join-Path $DeliveryRoot $entry.path
    if (-not (Test-Path -LiteralPath $original) -or (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash -ne $entry.sha256) {
        $SourceChanges += $entry.path
    }
    if (-not (Test-Path -LiteralPath $copy)) { $UnexpectedChanges += $entry.path; continue }
    $copiedHash = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
    if ($copiedHash -eq $entry.sha256) { $Verified++ }
    elseif ($AllowedChanges -notcontains $entry.path) { $UnexpectedChanges += $entry.path }
}
$links = @(Get-ChildItem -LiteralPath $DeliveryRoot -Force -Recurse -Attributes ReparsePoint | Select-Object -ExpandProperty FullName)
$dataRootFiles = @(Get-ChildItem -LiteralPath "$DeliveryRoot\shuju" -Recurse -File -Force)
$allFiles = Get-ChildItem -LiteralPath $DeliveryRoot -Recurse -File -Force
$size = ($allFiles | Measure-Object -Property Length -Sum).Sum
$report = [ordered]@{
    source_snapshot_files=$entries.Count
    original_files_changed_since_snapshot=$SourceChanges
    copied_files_identical=$Verified
    allowed_delivery_adaptations=$AllowedChanges
    unexpected_copy_changes=$UnexpectedChanges
    package_directory_links=$links
    delivery_data_files=$dataRootFiles.Count
    delivery_database_cluster_exists=(Test-Path -LiteralPath "$DeliveryRoot\.runtime\postgres")
    package_file_count=$allFiles.Count
    package_bytes=$size
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$DeliveryRoot\交付清单\完整性核对结果.json" -Encoding utf8
$report | ConvertTo-Json -Depth 5
if ($SourceChanges.Count -or $UnexpectedChanges.Count -or $links.Count -or $dataRootFiles.Count -or $report.delivery_database_cluster_exists) {
    throw 'Delivery integrity check failed.'
}
