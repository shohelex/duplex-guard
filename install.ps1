# Installs the "L6460 Duplex" printer and its background program.
# Asks for Windows admin approval once. The existing EPSON L6460 Series printer is not changed.
param([string]$Pythonw)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$taskName = 'L6460 Duplex'
$queueName = 'L6460 Duplex'
$portName = '\\.\pipe\L6460Duplex'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    $python = (Get-Command python).Source
    $Pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Pythonw `"$Pythonw`""
    $process = Start-Process powershell -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}

$dataDir = Join-Path $env:LOCALAPPDATA 'L6460Duplex'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Start-Transcript -Path (Join-Path $dataDir 'install.log') -Force | Out-Null

try {
    if (-not $Pythonw -or -not (Test-Path $Pythonw)) { throw "pythonw.exe not found: '$Pythonw'" }

    # Start the background program first: Windows tests a new port by opening it.
    $action = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m l6460 serve' -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName

    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path $portName)) {
        if ((Get-Date) -gt $deadline) { throw 'The background program did not start.' }
        Start-Sleep -Milliseconds 300
    }

    if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) {
        Add-PrinterPort -Name $portName
    }
    if (-not (Get-Printer -Name $queueName -ErrorAction SilentlyContinue)) {
        Add-Printer -Name $queueName -DriverName 'Microsoft Print To PDF' -PortName $portName
    }
    Set-PrintConfiguration -PrinterName $queueName -PaperSize A4

    Write-Output "Installed '$queueName'."
    exit 0
}
catch {
    Write-Output "FAILED: $_"
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
