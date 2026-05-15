param(
    [string]$PythonCommand = "py",
    [string]$ExcelPath = "",
    [switch]$ValidateOnly,
    [switch]$SkipDbCounts
)

$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\samir\OneDrive\Desktop\New folder (2)\Ardent Mills project"
$PipelineDir = Join-Path $ProjectDir "production_pipelines"

$oltpArgs = @((Join-Path $PipelineDir "01_oltp_load_pipeline.py"))
$olapArgs = @((Join-Path $PipelineDir "02_oltp_to_olap_incremental_pipeline.py"), "--skip-oltp")
$auditArgs = @((Join-Path $PipelineDir "03_audit_control_pipeline.py"))

function Invoke-CheckedPython {
    param(
        [string]$PythonCommand,
        [string[]]$PythonArgs
    )
    & $PythonCommand @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE`: $PythonCommand $($PythonArgs -join ' ')"
    }
}

if ($ExcelPath -ne "") {
    $oltpArgs += @("--excel", $ExcelPath)
}

if ($ValidateOnly) {
    $oltpArgs += "--validate-only"
    $olapArgs += @("--validate-only", "--skip-connection-test", "--load-date", "1900-01-01 00:00:00")
}

if ($SkipDbCounts) {
    $auditArgs += "--skip-db-counts"
}

Write-Host "Running OLTP pipeline..."
Invoke-CheckedPython -PythonCommand $PythonCommand -PythonArgs $oltpArgs

Write-Host "Running OLTP-to-OLAP incremental pipeline..."
Invoke-CheckedPython -PythonCommand $PythonCommand -PythonArgs $olapArgs

Write-Host "Running audit/control pipeline..."
Invoke-CheckedPython -PythonCommand $PythonCommand -PythonArgs $auditArgs

Write-Host "All production pipeline steps completed."
