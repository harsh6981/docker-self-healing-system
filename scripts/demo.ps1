<#
  Helper commands for the demonstration (Windows PowerShell).

  Run from the project root:
      powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 status
      powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 fail A
      powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 crash B

  Commands: status | watch | fail | restore | crash | logs | report | open | help
  Service : A (port 5000, container sh-web)  or  B (port 5001, container sh-web2)
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "status", "watch", "fail", "restore", "crash", "logs", "report", "open")]
    [string]$Command = "help",

    [Parameter(Position = 1)]
    [ValidateSet("A", "B")]
    [string]$Service = "A"
)

$port = if ($Service -eq "B") { 5001 } else { 5000 }
$base = "http://localhost:$port"
$fmt = "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

switch ($Command) {
    "status"  { docker ps -a --filter "name=sh-" --format $fmt
                Write-Host ""
                Write-Host "Restarts performed by Docker's restart policy:"
                docker inspect -f "  {{.Name}}  RestartCount={{.RestartCount}}  Health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}" sh-web sh-web2 }
    "watch"   { while ($true) { Clear-Host; Get-Date -Format "HH:mm:ss"; docker ps -a --filter "name=sh-" --format $fmt; Start-Sleep -Seconds 2 } }
    "fail"    { (Invoke-RestMethod "$base/fail").message }
    "restore" { (Invoke-RestMethod "$base/restore").message }
    "crash"   { try { (Invoke-RestMethod -Method Post "$base/crash").message } catch { "Crash requested." } }
    "logs"    { Get-Content .\logs\recovery.log -Tail 20 -Wait }
    "report"  { Invoke-RestMethod http://localhost:8080/api/report | ConvertTo-Json -Depth 6 }
    "open"    { Start-Process "http://localhost:8080"; Start-Process "http://localhost:5000"; Start-Process "http://localhost:5001" }
    default   { Get-Help $MyInvocation.MyCommand.Path | Out-String | Write-Host }
}
