$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigFile = Join-Path $ProjectDir "config.json"
$ConfigExample = Join-Path $ProjectDir "config.example.json"
$SecretFile = Join-Path $ProjectDir "api-key.secure"
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements.txt"
$BotScript = Join-Path $ProjectDir "screen_bot.py"
Set-Location -LiteralPath $ProjectDir

function Show-Title {
    Clear-Host
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "       微信群 DeepSeek AI 机器人" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Wait-ForKey {
    Write-Host ""
    Read-Host "按回车键返回菜单"
}

function Get-Python {
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike "*WindowsApps*") {
        return $python.Source
    }
    throw "找不到可用的 Python。请安装 Python 3.9 或更高版本。"
}

function Install-Dependencies {
    $python = Get-Python
    & $python -c "import uiautomation, win32gui, pyperclip" 2>$null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    Write-Host "正在安装微信界面读取依赖，请稍候……" -ForegroundColor Yellow
    & $python -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "依赖安装失败，请检查网络连接。"
    }
}

function Save-ApiKey {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $plainKey = [Microsoft.VisualBasic.Interaction]::InputBox(
        "请粘贴完整的 DeepSeek API Key（内容会直接显示）：",
        "配置 DeepSeek API Key",
        ""
    ).Trim()
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "没有输入 API Key，或已取消输入。"
    }
    if ($plainKey.Length -lt 20 -or $plainKey.Contains(" ")) {
        throw ("DeepSeek API Key 格式无效：当前读取到 " + $plainKey.Length + " 个字符。请粘贴完整且不含空格的 Key。")
    }
    $secureKey = ConvertTo-SecureString $plainKey -AsPlainText -Force
    $secureKey | ConvertFrom-SecureString | Set-Content -LiteralPath $SecretFile -Encoding UTF8
}

function Import-ApiKey {
    if (-not (Test-Path -LiteralPath $SecretFile)) {
        throw '尚未保存 DeepSeek API Key，请先选择“首次配置”。'
    }
    $encrypted = Get-Content -Raw -LiteralPath $SecretFile -Encoding UTF8
    $secureKey = $encrypted.Trim() | ConvertTo-SecureString
    $credential = [System.Net.NetworkCredential]::new("", $secureKey)
    $env:AI_API_KEY = $credential.Password
    if ([string]::IsNullOrWhiteSpace($env:AI_API_KEY)) {
        throw "保存的 API Key 无法读取，请重新进行首次配置。"
    }
}

function Configure-Bot {
    Show-Title
    Write-Host "首次配置" -ForegroundColor Green
    Write-Host "多个群名请用英文逗号分隔；名称必须与微信聊天列表完全一致。"
    $groupText = Read-Host "请输入微信群名"
    $groups = @($groupText.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($groups.Count -eq 0) {
        throw "至少需要填写一个微信群名。"
    }
    $botNickname = (Read-Host "请输入你在群里显示的昵称（用于识别 @你）").Trim()
    if ([string]::IsNullOrWhiteSpace($botNickname)) {
        throw "群昵称不能为空。"
    }
    $wakeWordText = Read-Host "请输入唤醒关键词，多个用英文逗号分隔（可留空）"
    $wakeWords = @($wakeWordText.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })

    $config = Get-Content -Raw -LiteralPath $ConfigExample -Encoding UTF8 | ConvertFrom-Json
    $config.groups = $groups
    $config.bot_nickname = $botNickname
    $config.wake_words = $wakeWords
    $config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ConfigFile -Encoding UTF8
    Save-ApiKey
    Install-Dependencies
    Write-Host ""
    Write-Host "配置完成。API Key 已使用 Windows 当前用户加密保存。" -ForegroundColor Green
}

function Check-Bot {
    Install-Dependencies
    Import-ApiKey
    if (-not (Test-Path -LiteralPath $ConfigFile)) {
        throw '尚未生成 config.json，请先选择“首次配置”。'
    }
    $python = Get-Python
    & $python $BotScript --check
    if ($LASTEXITCODE -ne 0) {
        throw "配置检查未通过，请查看上面的错误信息。"
    }
}

function Start-Bot {
    Check-Bot
    Write-Host ""
    Write-Host "机器人正在启动。请保持群聊独立窗口打开且未最小化。" -ForegroundColor Green
    Write-Host "按 Ctrl+C 停止机器人。" -ForegroundColor Yellow
    $python = Get-Python
    & $python $BotScript
}

:mainLoop while ($true) {
    Show-Title
    Write-Host "1. 首次配置 / 重新配置"
    Write-Host "2. 启动机器人"
    Write-Host "3. 检查配置"
    Write-Host "4. 编辑高级配置"
    Write-Host "5. 退出"
    Write-Host ""
    $choice = Read-Host "请选择（1-5）"

    try {
        switch ($choice) {
            "1" { Configure-Bot; Wait-ForKey }
            "2" { Start-Bot; Wait-ForKey }
            "3" { Check-Bot; Wait-ForKey }
            "4" {
                if (-not (Test-Path -LiteralPath $ConfigFile)) {
                    Copy-Item -LiteralPath $ConfigExample -Destination $ConfigFile
                }
                Start-Process notepad.exe -ArgumentList $ConfigFile -Wait
            }
            "5" { break mainLoop }
            default { Write-Host "请输入 1 到 5。" -ForegroundColor Yellow; Start-Sleep -Seconds 1 }
        }
    }
    catch {
        Write-Host ""
        Write-Host ("操作失败：" + $_.Exception.Message) -ForegroundColor Red
        Wait-ForKey
    }
}
