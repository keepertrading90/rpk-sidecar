$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\RPK Sidecar.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\iniciar_app.bat"
$Shortcut.WorkingDirectory = "$PSScriptRoot"
$Shortcut.IconLocation = "$PSScriptRoot\assets\icon_v1.png"
$Shortcut.Save()
Write-Host "✅ Acceso directo creado en el Escritorio con el nuevo logo RPK."
