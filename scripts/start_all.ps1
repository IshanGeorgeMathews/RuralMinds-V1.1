# Start RuralMinds: embedding server, chat server, then the API.
#
#   ./scripts/start_all.ps1              # models + API (API runs in this window; Ctrl+C stops only the API)
#   ./scripts/start_all.ps1 -ModelsOnly  # just the two llama-servers (for dev / eval)
#
# Safe to re-run after a crash or power cut: a server that already answers /health is left alone.
# Settings come from .env (RURALMINDS_*). Logs and PID files go to logs/. Stop with ./scripts/stop_all.ps1.
param([switch]$ModelsOnly)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force logs | Out-Null

function Read-DotEnv([string]$path) {
    $values = @{}
    if (-not (Test-Path $path)) { throw "Missing $path. Copy .env.example to .env and set the model paths." }
    foreach ($line in Get-Content $path -Encoding UTF8) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
    }
    return $values
}

function Get-Setting([hashtable]$envValues, [string]$key, [string]$default) {
    # A process environment variable wins over .env, as in config.py (handy for the bake-off).
    $value = [Environment]::GetEnvironmentVariable("RURALMINDS_$key")
    if ([string]::IsNullOrWhiteSpace($value)) { $value = $envValues["RURALMINDS_$key"] }
    if ([string]::IsNullOrWhiteSpace($value)) { return $default }
    return $value
}

function Test-Health([int]$port) {
    try {
        $reply = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$port/health"
        return $reply.StatusCode -eq 200
    } catch {
        return $false  # not up yet (or still loading the model: llama-server answers 503 then)
    }
}

function Start-LlamaServer([string]$name, [int]$port, [string]$exe, [string[]]$arguments) {
    if (Test-Health $port) { Write-Host "$name already running on :$port"; return }
    $process = Start-Process -FilePath $exe -ArgumentList ($arguments + @('--host', '127.0.0.1', '--port', $port)) `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "logs/$name.out.log" -RedirectStandardError "logs/$name.log"
    Set-Content -Path "logs/$name.pid" -Value $process.Id -Encoding ascii
    Write-Host "$name starting on :$port (pid $($process.Id))..."
    for ($second = 0; $second -lt 180; $second++) {
        if (Test-Health $port) { Write-Host "$name ready"; return }
        if ($process.HasExited) { throw "$name exited early; see logs/$name.log" }
        Start-Sleep -Seconds 1
    }
    throw "$name not healthy after 180 s; see logs/$name.log"
}

$config = Read-DotEnv (Join-Path $root '.env')
$threads = Get-Setting $config 'THREADS' '8'

foreach ($key in 'EMBED_MODEL_PATH', 'CHAT_MODEL_PATH') {
    $path = Get-Setting $config $key ''
    if (-not (Test-Path $path)) { throw "RURALMINDS_$key does not point at a file: '$path'" }
}

# bge-m3 needs CLS pooling; -ub must cover a whole chunk because embeddings are not split across batches.
# The chat server may be a GPU (Vulkan) build; the embedder stays on a CPU build because it
# only embeds short questions at run time, and the iGPU's shared memory is kept for the chat model.
$chatExe = Get-Setting $config 'LLAMA_SERVER_PATH' 'llama-server'
$embedExe = Get-Setting $config 'EMBED_SERVER_PATH' $chatExe

Start-LlamaServer 'embed' ([uri](Get-Setting $config 'EMBED_URL' 'http://127.0.0.1:8081')).Port $embedExe @(
    '-m', (Get-Setting $config 'EMBED_MODEL_PATH' ''), '--embedding', '--pooling', 'cls',
    '-c', (Get-Setting $config 'EMBED_CTX' '4096'), '-b', '2048', '-ub', '2048', '-t', $threads
)

# Pinned chat flags: thinking off, image projector off, prompt-prefix reuse.
# KV cache type and flash attention are per backend: on the CPU, q8 KV + flash attention is fine;
# on the Radeon iGPU (Vulkan) flash attention cut prefill from 87 to 35-46 tok/s (llama-bench,
# 12 Oct), and a q8 V cache requires flash attention, so the GPU setting is f16 + flash-attn off.
$kvType = Get-Setting $config 'LLM_KV_TYPE' 'q8_0'
Start-LlamaServer 'llm' ([uri](Get-Setting $config 'LLM_URL' 'http://127.0.0.1:8080')).Port $chatExe @(
    '-m', (Get-Setting $config 'CHAT_MODEL_PATH' ''), '-ngl', (Get-Setting $config 'LLM_GPU_LAYERS' '0'),
    '-c', (Get-Setting $config 'LLM_CTX' '8192'), '-np', (Get-Setting $config 'LLM_PARALLEL' '2'),
    '-t', $threads, '-ctk', $kvType, '-ctv', $kvType, '-fa', (Get-Setting $config 'LLM_FLASH_ATTN' 'auto'),
    '--cache-reuse', '256', '--reasoning', 'off', '--no-mmproj'
)

if ($ModelsOnly) { return }

$apiHost = Get-Setting $config 'API_HOST' '0.0.0.0'
$apiPort = Get-Setting $config 'API_PORT' '8000'
Write-Host "API on http://${apiHost}:$apiPort (Ctrl+C to stop the API; model servers keep running)"
uv run uvicorn ruralminds.main:app --host $apiHost --port $apiPort
