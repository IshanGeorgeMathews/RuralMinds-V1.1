# Sample CPU, RAM, GPU and battery power every few seconds into a CSV, for eval/bench.py.
#
#   ./scripts/sample_resources.ps1 -Out logs/resources.csv          # Ctrl+C to stop
#   uv run python -m eval.bench --resources logs/resources.csv      # in another window
#
# Battery watts are only meaningful on battery (charger unplugged): Windows reports the discharge
# rate then, and 0 while charging. No new tools: Get-Counter and WMI ship with Windows.
param(
    [string]$Out = 'logs/resources.csv',
    [int]$IntervalSeconds = 2
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force (Split-Path -Parent $Out) | Out-Null
'time,cpu_percent,mem_used_mb,llama_ws_mb,python_ws_mb,gpu_3d_percent,gpu_compute_percent,on_battery,discharge_w' |
    Set-Content -Path $Out -Encoding utf8

$totalMb = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB

function Get-GpuPercent([string]$engineType) {
    # Busiest engine of one type, summed over processes. llama.cpp's Vulkan backend runs on the
    # Compute engines, not 3D, so both are sampled. Missing counter (no driver support) -> empty.
    try {
        $samples = (Get-Counter "\GPU Engine(*engtype_$engineType*)\Utilization Percentage" -ErrorAction Stop).CounterSamples
        $perEngine = $samples | Group-Object { ($_.InstanceName -split '_engtype_')[0] -replace '^pid_\d+_', '' } |
            ForEach-Object { ($_.Group | Measure-Object CookedValue -Sum).Sum }
        return [math]::Round(($perEngine | Measure-Object -Maximum).Maximum, 1)
    } catch { return '' }
}

function Get-Battery {
    try {
        $status = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus -ErrorAction Stop | Select-Object -First 1
        $watts = if ($status.Discharging) { [math]::Round($status.DischargeRate / 1000, 2) } else { 0 }
        return @([int](-not $status.PowerOnline), $watts)
    } catch { return @('', '') }
}

function Get-WorkingSetMb([string]$name) {
    $processes = Get-Process -Name $name -ErrorAction SilentlyContinue
    if (-not $processes) { return 0 }
    return [math]::Round(($processes | Measure-Object WorkingSet64 -Sum).Sum / 1MB, 0)
}

Write-Host "sampling every $IntervalSeconds s into $Out (Ctrl+C to stop)"
while ($true) {
    $cpu = [math]::Round((Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples[0].CookedValue, 1)
    $freeMb = (Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue
    $battery = Get-Battery
    $row = @(
        (Get-Date).ToString('s'),
        $cpu,
        [math]::Round($totalMb - $freeMb, 0),
        (Get-WorkingSetMb 'llama-server'),
        (Get-WorkingSetMb 'python'),
        (Get-GpuPercent '3D'),
        (Get-GpuPercent 'Compute'),
        $battery[0],
        $battery[1]
    ) -join ','
    Add-Content -Path $Out -Value $row -Encoding utf8
    Start-Sleep -Seconds $IntervalSeconds
}
