# Stop the llama-servers started by start_all.ps1, using the PIDs it saved in logs/.
# Only those exact processes are stopped, never every llama-server on the machine.
$root = Split-Path -Parent $PSScriptRoot
foreach ($name in 'llm', 'embed') {
    $pidFile = Join-Path $root "logs/$name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $processId = [int](Get-Content $pidFile)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'llama-server') {
        Stop-Process -Id $processId -Confirm:$false
        Write-Host "stopped $name (pid $processId)"
    }
    Remove-Item $pidFile -Confirm:$false
}
