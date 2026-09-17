$ocrRoot = $PSScriptRoot
$pidFile = Join-Path $ocrRoot 'server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $ocrPid = [int](Get-Content -LiteralPath $pidFile)
    $ocrProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ocrPid"
    $expectedScript = Join-Path $ocrRoot 'app.py'
    if ($ocrProcess -and $ocrProcess.CommandLine.Contains($expectedScript)) {
        Stop-Process -Id $ocrPid
        Write-Host 'Local OCR server stopped.'
    } else {
        Write-Host 'No matching OCR server is running.'
    }
}
