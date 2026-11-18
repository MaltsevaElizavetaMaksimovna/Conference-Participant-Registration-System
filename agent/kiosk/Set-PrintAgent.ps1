#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Preview', 'Install', 'Remove')]
    [string] $Action = 'Preview',
    [string] $AgentExe,
    [uri] $ServerUrl,
    [string] $PrinterName,
    [string] $CaFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$taskName = 'Regsys Print Agent'
$taskDescription = 'Регистрация конференции · агент печати терминала'
$root = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'RegsysKioskAgent'
$runtime = Join-Path $root 'runtime'
$exe = Join-Path $root 'regsys-agent.exe'
$config = Join-Path $root 'agent.ini'
$certificate = Join-Path $root 'site-ca.pem'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()

function New-AgentDirectorySecurity([bool] $WritableByAgent) {
    $security = New-Object Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $administrators = [Security.Principal.SecurityIdentifier] 'S-1-5-32-544'
    $security.SetOwner($administrators)
    $rules = @(
        @($administrators, 'FullControl'),
        @([Security.Principal.SecurityIdentifier] 'S-1-5-18', 'FullControl'),
        @([Security.Principal.SecurityIdentifier] 'S-1-5-19', $(if ($WritableByAgent) { 'Modify' } else { 'ReadAndExecute' }))
    )
    foreach ($entry in $rules) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $entry[0], $entry[1], 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )
        $security.AddAccessRule($rule)
    }
    return $security
}

function Assert-AgentDirectory([string] $Path, [Security.AccessControl.DirectorySecurity] $Security) {
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Ожидался обычный каталог: $Path"
    }
    $acl = Get-Acl -LiteralPath $Path
    $sidType = [Security.Principal.SecurityIdentifier]
    $expected = $Security.GetAccessRules($true, $true, $sidType)
    $actual = $acl.GetAccessRules($true, $true, $sidType)
    $fields = @('IdentityReference', 'FileSystemRights', 'AccessControlType',
        'InheritanceFlags', 'PropagationFlags', 'IsInherited')
    if (-not $acl.AreAccessRulesProtected -or $acl.GetOwner($sidType).Value -ne 'S-1-5-32-544' -or
        $actual.Count -ne $expected.Count -or (Compare-Object $expected $actual -Property $fields)) {
        throw "Обнаружены посторонние разрешения каталога: $Path"
    }
}

function Assert-LocalProvisionFile([string] $Path) {
    if (-not $Path) { throw 'Укажите абсолютный путь к подготовленному файлу' }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSProvider.Name -ne 'FileSystem' -or $item.PSIsContainer -or
        $item.FullName.StartsWith('\\') -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Для установки нужен обычный файл на локальном диске'
    }
    for ($parent = $item.Directory; $null -ne $parent; $parent = $parent.Parent) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Источник установки находится за точкой повторной обработки'
        }
    }
    return $item.FullName
}

function Stop-RegsysTask {
    if ($null -eq $task) { return }
    if ($task.State -in @('Running', 'Queued')) {
        Stop-ScheduledTask -TaskName $taskName -TaskPath '\'
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ((Get-ScheduledTask -TaskName $taskName -TaskPath '\').State -notin @('Running', 'Queued')) {
                return
            }
            Start-Sleep -Milliseconds 500
        }
        throw 'Агент не остановился. Дождитесь остановки задачи перед повтором.'
    }
}

if ($Action -ne 'Remove') {
    if (-not $ServerUrl -or -not $ServerUrl.IsAbsoluteUri -or $ServerUrl.Scheme -ne 'https' -or
        $ServerUrl.UserInfo -or $ServerUrl.Query -or $ServerUrl.Fragment -or $ServerUrl.AbsolutePath -ne '/') {
        throw 'Укажите HTTPS-адрес сервера без пути, реквизитов и параметров'
    }
    if ([string]::IsNullOrWhiteSpace($PrinterName) -or $PrinterName -match '[\r\n\x00]') {
        throw 'Укажите имя принтера Windows одной строкой'
    }
    $sourceExe = Assert-LocalProvisionFile $AgentExe
    if ([IO.Path]::GetExtension($sourceExe) -ine '.exe') { throw 'Ожидается собранный regsys-agent.exe' }
    if ($CaFile) { $sourceCA = Assert-LocalProvisionFile $CaFile }
}

if ($Action -eq 'Preview') {
    [pscustomobject] @{
        Task = $taskName
        Account = 'NT AUTHORITY\LOCAL SERVICE'
        Executable = $exe
        Config = $config
        Trigger = 'AtStartup'
        MultipleInstances = 'IgnoreNew'
        Server = $ServerUrl.GetLeftPart([UriPartial]::Authority)
        Printer = $PrinterName
        OwnCA = [bool] $CaFile
    }
    return
}

if ($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess) {
    throw 'Для установки и удаления используйте 64-разрядный Windows PowerShell 5.1'
}
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Требуется повышенная сессия администратора'
}

$rootSecurity = New-AgentDirectorySecurity $false
$dataSecurity = New-AgentDirectorySecurity $true
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($task -and ($task.Description -ne $taskDescription -or @($task.Actions).Count -ne 1 -or
    $task.Actions[0].Execute -ne $exe)) {
    throw "Обнаружена чужая задача $taskName"
}
if (Test-Path -LiteralPath $root) {
    Assert-AgentDirectory $root $rootSecurity
} elseif ($Action -eq 'Install') {
    [void] [IO.Directory]::CreateDirectory($root, $rootSecurity)
    Assert-AgentDirectory $root $rootSecurity
}

if ($Action -eq 'Remove') {
    Stop-RegsysTask
    if ($task) { Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false }
    foreach ($path in @($config, "$config.new")) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path }
    }
    return
}

if (Test-Path -LiteralPath $runtime) {
    Assert-AgentDirectory $runtime $dataSecurity
} else {
    [void] [IO.Directory]::CreateDirectory($runtime, $dataSecurity)
    Assert-AgentDirectory $runtime $dataSecurity
}

$token = Read-Host 'Токен агента печати из админки принтеров' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($token)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ($plain -cnotmatch '\Aagt_[A-Za-z0-9_-]{43}\z') {
        throw 'Неверный формат токена агента'
    }
    $settings = @(
        '[agent]',
        ('server_url = ' + $ServerUrl.GetLeftPart([UriPartial]::Authority)),
        ('printer_name = ' + $PrinterName.Trim()),
        ('token = ' + $plain),
        'log_path = runtime/agent.log',
        'journal_path = runtime/journal.jsonl'
    )
    if ($CaFile) { $settings += 'ca_file = site-ca.pem' }

    if ($task) {
        $sameConfig = [IO.File]::Exists($config) -and
            (([IO.File]::ReadAllLines($config) -join "`n") -ceq ($settings -join "`n"))
        $sameExe = [IO.File]::Exists($exe) -and
            ((Get-FileHash -LiteralPath $sourceExe).Hash -eq (Get-FileHash -LiteralPath $exe).Hash)
        $sameCA = -not $CaFile -or ([IO.File]::Exists($certificate) -and
            ((Get-FileHash -LiteralPath $sourceCA).Hash -eq (Get-FileHash -LiteralPath $certificate).Hash))
        if (-not ($sameConfig -and $sameExe -and $sameCA)) {
            throw 'Параметры действующего агента изменились. Для обновления используйте Remove и затем Install.'
        }
        if ($task.State -notin @('Running', 'Queued')) {
            Start-ScheduledTask -TaskName $taskName -TaskPath '\'
        }
        return
    }

    if ($sourceExe -ine $exe) { Copy-Item -LiteralPath $sourceExe -Destination $exe -Force }
    if ($CaFile -and $sourceCA -ine $certificate) {
        Copy-Item -LiteralPath $sourceCA -Destination $certificate -Force
    }
    [IO.File]::WriteAllLines("$config.new", [string[]] $settings, [Text.UTF8Encoding]::new($false))
    if ([IO.File]::Exists($config)) { [IO.File]::Replace("$config.new", $config, $null) }
    else { [IO.File]::Move("$config.new", $config) }
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $token.Dispose()
    $plain = $null
    $settings = $null
    if ([IO.File]::Exists("$config.new")) { [IO.File]::Delete("$config.new") }
}

$runAgent = New-ScheduledTaskAction -Execute $exe -Argument ('--config "{0}"' -f $config) -WorkingDirectory $root
$boot = New-ScheduledTaskTrigger -AtStartup
$localService = New-ScheduledTaskPrincipal -UserId 'LOCALSERVICE' -LogonType ServiceAccount
$taskOptions = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Description $taskDescription `
    -Action $runAgent -Trigger $boot -Principal $localService -Settings $taskOptions -Force | Out-Null
Start-ScheduledTask -TaskName $taskName -TaskPath '\'
