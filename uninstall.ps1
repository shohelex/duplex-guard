# Removes the "L6460 Duplex" printer and its background program. Asks for admin approval once.
# The existing EPSON L6460 Series printer is not touched.
$ErrorActionPreference = 'Continue'
$taskName = 'L6460 Duplex'
$queueName = 'L6460 Duplex'
$portName = '\\.\pipe\L6460Duplex'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -Wait `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Remove-Printer -Name $queueName -ErrorAction SilentlyContinue
Remove-PrinterPort -Name $portName -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
