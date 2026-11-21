# Removes the "L6460 Duplex" and "L6460 One-sided" printers and their background program.
# Asks for admin approval once. The existing EPSON L6460 Series printer is not touched.
$ErrorActionPreference = 'Continue'
$taskName = 'L6460 Duplex'
$captures = [ordered]@{
    'L6460 Duplex'    = '\\.\pipe\L6460Duplex'
    'L6460 One-sided' = '\\.\pipe\L6460OneSided'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -Wait `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

foreach ($queueName in $captures.Keys) {
    Remove-Printer -Name $queueName -ErrorAction SilentlyContinue
    Remove-PrinterPort -Name $captures[$queueName] -ErrorAction SilentlyContinue
}
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'duplex-guard settings.lnk') -ErrorAction SilentlyContinue
