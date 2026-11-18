#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Preview', 'Install', 'Remove')]
    [string] $Action = 'Preview',
    [uri] $TerminalUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$profileId = '{1C1FF7E3-D6B4-49A7-BFD2-9FD3CDAF9A17}'
$statePath = 'HKLM:\SOFTWARE\Regsys\AssignedAccess'
$edgePath = 'HKLM:\SOFTWARE\Policies\Microsoft\Edge'
$schema = 'http://schemas.microsoft.com/AssignedAccess/2017/config'

function Get-TerminalOrigin([uri] $Url) {
    if (-not $Url -or -not $Url.IsAbsoluteUri -or $Url.Scheme -ne 'https' -or
        $Url.UserInfo -or $Url.Query -or $Url.Fragment -or $Url.AbsolutePath -ne '/' -or
        $Url.HostNameType -ne [UriHostNameType]::Dns) {
        throw 'Укажите DNS-адрес HTTPS терминала с путём / и без реквизитов или параметров'
    }
    return $Url.GetLeftPart([UriPartial]::Authority)
}

function New-AssignedAccessXml([string] $Origin) {
    $arguments = [Security.SecurityElement]::Escape(
        "--kiosk $Origin/ --edge-kiosk-type=fullscreen --no-first-run"
    )
    return @"
<AssignedAccessConfiguration xmlns="$schema"
    xmlns:rs5="http://schemas.microsoft.com/AssignedAccess/201810/config"
    xmlns:v4="http://schemas.microsoft.com/AssignedAccess/2021/config">
    <Profiles>
        <Profile Id="$profileId">
            <KioskModeApp v4:ClassicAppPath="%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
                v4:ClassicAppArguments="$arguments" />
        </Profile>
    </Profiles>
    <Configs>
        <Config>
            <AutoLogonAccount rs5:DisplayName="Regsys Terminal" />
            <DefaultProfile Id="$profileId" />
        </Config>
    </Configs>
</AssignedAccessConfiguration>
"@
}

function Get-EdgePolicies([uri] $Url) {
    $allow = "https://.$($Url.IdnHost):$($Url.Port)"
    $blocks = @('*') + @('/admin', '/login', '/p', '/api/auth', '/api/admin',
        '/api/participants', '/api/events') | ForEach-Object {
        if ($_ -eq '*') { $_ } else { "$allow$_" }
    }
    $policies = @(
        @{ Key = $edgePath; Name = 'DeveloperToolsAvailability'; Value = 2; Type = 'DWord' },
        @{ Key = $edgePath; Name = 'PrintingEnabled'; Value = 0; Type = 'DWord' },
        @{ Key = $edgePath; Name = 'DownloadRestrictions'; Value = 3; Type = 'DWord' },
        @{ Key = "$edgePath\URLAllowlist"; Name = '1'; Value = $allow; Type = 'String' }
    )
    for ($i = 0; $i -lt $blocks.Count; $i++) {
        $policies += @{ Key = "$edgePath\URLBlocklist"; Name = [string] ($i + 1)
            Value = $blocks[$i]; Type = 'String' }
    }
    return $policies
}

function Assert-EdgePolicies([object[]] $Policies, [bool] $Owned) {
    foreach ($entry in $Policies) {
        if (-not (Test-Path -LiteralPath $entry.Key)) { continue }
        $key = Get-Item -LiteralPath $entry.Key
        if ($key.GetValueNames() -notcontains $entry.Name) { continue }
        if (-not $Owned -or $key.GetValueKind($entry.Name).ToString() -ne $entry.Type -or
            $key.GetValue($entry.Name) -cne $entry.Value) {
            throw "Обнаружена сторонняя политика Edge: $($entry.Key) / $($entry.Name)"
        }
    }
    foreach ($list in @("$edgePath\URLAllowlist", "$edgePath\URLBlocklist")) {
        if (Test-Path -LiteralPath $list) {
            $ownedNames = @($Policies | Where-Object Key -eq $list | ForEach-Object Name)
            $names = (Get-Item -LiteralPath $list).GetValueNames()
            if (@($names | Where-Object { $_ -notin $ownedNames }).Count) {
                throw "Обнаружен сторонний список Edge: $list"
            }
        }
    }
}

function Assert-OwnedProfile([string] $Current, [bool] $Owned) {
    if ([string]::IsNullOrWhiteSpace($Current)) { return }
    if (-not $Owned) { throw 'Assigned Access уже настроен другим способом' }
    if (-not $Current.TrimStart().StartsWith('<')) { $Current = [Net.WebUtility]::HtmlDecode($Current) }
    [xml] $configuration = $Current
    $ns = [Xml.XmlNamespaceManager]::new($configuration.NameTable)
    $ns.AddNamespace('a', $schema)
    $profiles = $configuration.SelectNodes('/a:AssignedAccessConfiguration/a:Profiles/a:Profile', $ns)
    $configs = $configuration.SelectNodes('/a:AssignedAccessConfiguration/a:Configs/a:Config', $ns)
    if ($profiles.Count -ne 1 -or $profiles[0].GetAttribute('Id') -ne $profileId -or
        $configs.Count -ne 1 -or $null -eq $configs[0].SelectSingleNode('a:AutoLogonAccount', $ns) -or
        $null -eq $configs[0].SelectSingleNode("a:DefaultProfile[@Id='$profileId']", $ns)) {
        throw 'Assigned Access уже настроен другим способом'
    }
}

if ($Action -ne 'Remove') {
    $origin = Get-TerminalOrigin $TerminalUrl
    $xml = New-AssignedAccessXml $origin
}
if ($Action -eq 'Preview') { $xml; return }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not [Environment]::Is64BitProcess -or $identity.User.Value -ne 'S-1-5-18') {
    throw 'Используйте 64-разрядный Windows PowerShell под учётной записью SYSTEM'
}
if ([Environment]::OSVersion.Version.Build -lt 22000) {
    throw 'Этот XML Assigned Access рассчитан на Windows 11'
}
$assigned = Get-CimInstance -Namespace 'root\cimv2\mdm\dmmap' -ClassName 'MDM_AssignedAccess'
if (@($assigned).Count -ne 1) { throw 'Провайдер MDM_AssignedAccess недоступен' }

$owned = $false
if (Test-Path -LiteralPath $statePath) {
    $marker = Get-Item -LiteralPath $statePath
    $values = $marker.GetValueNames()
    if ($marker.SubKeyCount -or @($values | Where-Object { $_ -ne 'RegsysProfile' }).Count) {
        throw 'Обнаружен чужой установочный профиль'
    }
    if ($values -contains 'RegsysProfile') {
        $data = $marker.GetValue('RegsysProfile') -split ' ', 2
        if ($data.Count -ne 2 -or $data[0] -ne $profileId) {
            throw 'Обнаружен чужой установочный профиль'
        }
        $owned = $true
        if ($Action -eq 'Install' -and $data[1] -cne $origin) {
            throw 'Для смены адреса сначала удалите предыдущий профиль'
        }
        $origin = Get-TerminalOrigin ([uri] $data[1])
    }
}
if (-not $owned -and $Action -eq 'Remove') { return }

Assert-OwnedProfile $assigned.Configuration $owned
$policies = @(Get-EdgePolicies ([uri] $origin))
Assert-EdgePolicies $policies $owned

if ($Action -eq 'Remove') {
    if ($assigned.Configuration) {
        $assigned.Configuration = $null
        Set-CimInstance -CimInstance $assigned | Out-Null
    }
    foreach ($entry in $policies) {
        if ((Test-Path -LiteralPath $entry.Key) -and
            ((Get-Item -LiteralPath $entry.Key).GetValueNames() -contains $entry.Name)) {
            Remove-ItemProperty -LiteralPath $entry.Key -Name $entry.Name
        }
    }
    Remove-ItemProperty -LiteralPath $statePath -Name RegsysProfile
    return
}

if (-not $owned) {
    if (-not (Test-Path -LiteralPath $statePath)) {
        New-Item -Path $statePath -Force | Out-Null
    }
    New-ItemProperty -LiteralPath $statePath -Name RegsysProfile -Value "$profileId $origin" | Out-Null
}
foreach ($entry in $policies) {
    if (-not (Test-Path -LiteralPath $entry.Key)) {
        New-Item -Path $entry.Key | Out-Null
    }
    New-ItemProperty -LiteralPath $entry.Key -Name $entry.Name -Value $entry.Value `
        -PropertyType $entry.Type -Force | Out-Null
}
$encoded = [Net.WebUtility]::HtmlEncode($xml)
if ($assigned.Configuration -cne $encoded -and $assigned.Configuration -cne $xml) {
    $assigned.Configuration = $encoded
    Set-CimInstance -CimInstance $assigned | Out-Null
}
