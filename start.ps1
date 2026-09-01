$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

if (-not (Test-Path -LiteralPath ".\config.json")) {
    Copy-Item -LiteralPath ".\config.example.json" -Destination ".\config.json"
    Write-Host "已生成 config.json。请先填写群名和 AI 接口配置，然后重新运行。" -ForegroundColor Yellow
    exit 1
}

if (-not $env:AI_API_KEY) {
    Write-Host "当前终端没有 AI_API_KEY。请先运行：" -ForegroundColor Yellow
    Write-Host '$env:AI_API_KEY = "你的密钥"'
    exit 1
}

$PythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}

& $PythonExe .\screen_bot.py
