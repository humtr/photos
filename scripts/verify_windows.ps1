param(
    [switch]$Gui,
    [switch]$CommercialSmoke,
    [Alias("WindowsProbePlaceholders")]
    [switch]$WindowsFilesystemProbes,
    [string]$SamplePath = "tests\fixtures\sample_media"
)

$ErrorActionPreference = "Stop"
$Python = ".\.venv\Scripts\python.exe"
$Results = [System.Collections.Generic.List[object]]::new()

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function Invoke-NativeJson {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    $Output = & $FilePath @Arguments 2>&1
    $ExitCode = $LASTEXITCODE
    $Text = ($Output | Out-String).Trim()
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code $ExitCode`: $FilePath $($Arguments -join ' ')`n$Text"
    }
    try {
        return $Text | ConvertFrom-Json
    } catch {
        throw "Command did not return JSON: $FilePath $($Arguments -join ' ')`n$Text"
    }
}

function Add-Result {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Message,
        [object]$Data = $null
    )

    $Results.Add([pscustomobject]@{
        name = $Name
        status = $Status
        message = $Message
        data = $Data
    }) | Out-Null
    Write-Host "[$Status] $Name - $Message"
}

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Body
    )

    try {
        $Data = & $Body
        Add-Result -Name $Name -Status "passed" -Message "completed" -Data $Data
    } catch {
        Add-Result -Name $Name -Status "failed" -Message $_.Exception.Message
    }
}

function New-TempWorkspace {
    $Root = Join-Path ([System.IO.Path]::GetTempPath()) ("photos-verify-windows-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    return (Resolve-Path $Root).Path
}

function Copy-Fixture {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing sample fixture: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
}

function Invoke-CommercialSmoke {
    $Workspace = New-TempWorkspace
    try {
        $Media = Join-Path $Workspace "media"
        $Archive = Join-Path $Workspace "archive"
        $Output = Join-Path $Workspace "analysis"
        $Db = Join-Path $Workspace "photos.sqlite"
        Copy-Fixture -Source $SamplePath -Destination $Media
        New-Item -ItemType Directory -Path $Archive -Force | Out-Null

        $Analyze = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "analyze", $Media,
            "--db", $Db,
            "--output", $Output
        )
        if ($Analyze.scanned -lt 1) {
            throw "commercial smoke analyzed no files"
        }

        $Plan = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-create",
            "--db", $Db,
            "--archive-root", $Archive
        )
        if (-not $Plan.ok) {
            throw "plan-create returned ok=false"
        }
        $PlanId = [int]$Plan.data.plan_id

        $Actions = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-actions", "$PlanId",
            "--db", $Db,
            "--limit", "20"
        )
        if (-not $Actions.ok -or $Actions.data.total -lt 1) {
            throw "plan-actions returned no actions"
        }

        $InitialDryRun = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-dry-run", "$PlanId",
            "--db", $Db
        )
        if (-not $InitialDryRun.ok -or $InitialDryRun.data.action_count -lt 1) {
            throw "initial plan-dry-run failed or returned no actions"
        }
        if ($InitialDryRun.data.destructive_action_performed) {
            throw "initial plan-dry-run reported destructive action"
        }
        if ($InitialDryRun.data.execute_allowed) {
            throw "initial plan-dry-run allowed execution before approval"
        }
        if ($InitialDryRun.warnings -notcontains "missing_execute_approval") {
            throw "initial plan-dry-run did not report missing_execute_approval"
        }

        $Approve = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-approve", "$PlanId",
            "--db", $Db,
            "--note", "verify_windows commercial smoke"
        )
        if (-not $Approve.ok) {
            throw "plan-approve returned ok=false"
        }

        $PreExecuteDryRun = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-dry-run", "$PlanId",
            "--db", $Db
        )
        if (-not $PreExecuteDryRun.ok -or -not $PreExecuteDryRun.data.execute_allowed) {
            throw "pre-execution plan-dry-run did not allow execution"
        }
        if ($PreExecuteDryRun.data.blocking_reasons.Count -ne 0) {
            throw "pre-execution plan-dry-run returned blocking reasons: $($PreExecuteDryRun.data.blocking_reasons -join ', ')"
        }

        $Execute = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-execute", "$PlanId",
            "--db", $Db,
            "--yes"
        )
        if (-not $Execute.ok -or -not $Execute.data.executed -or $Execute.data.failed_count -ne 0) {
            throw "plan-execute did not complete cleanly"
        }
        $BatchId = [int]$Execute.data.batch_id

        $Manifest = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "batch-manifest-validate", "$BatchId",
            "--db", $Db,
            "--verify-files"
        )
        if (-not $Manifest.ok) {
            throw "execution manifest validation returned ok=false"
        }
        if (-not $Manifest.data.valid) {
            throw "execution manifest validation did not return data.valid=true"
        }

        $Integrity = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "integrity-check",
            "--db", $Db
        )
        if (-not $Integrity.ok) {
            throw "integrity-check returned ok=false"
        }
        if ($Integrity.data.status -ne "ok") {
            throw "integrity-check status was $($Integrity.data.status)"
        }

        $Rollback = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "batch-rollback", "$BatchId",
            "--db", $Db,
            "--yes"
        )
        if (-not $Rollback.ok -or -not $Rollback.data.rolled_back -or $Rollback.data.failed_count -ne 0) {
            throw "batch-rollback did not complete cleanly"
        }
        $RollbackBatchId = [int]$Rollback.data.rollback_batch_id

        $RollbackManifest = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "batch-manifest-validate", "$RollbackBatchId",
            "--db", $Db,
            "--verify-files"
        )
        if (-not $RollbackManifest.ok) {
            throw "rollback manifest validation returned ok=false"
        }
        if (-not $RollbackManifest.data.valid) {
            throw "rollback manifest validation did not return data.valid=true"
        }

        return [pscustomobject]@{
            workspace = $Workspace
            scanned = $Analyze.scanned
            plan_id = $PlanId
            action_count = $Actions.data.total
            execution_batch_id = $BatchId
            rollback_batch_id = $RollbackBatchId
            execution_manifest = $Execute.data.manifest_path
            rollback_manifest = $Rollback.data.manifest_path
        }
    } finally {
        if (Test-Path -LiteralPath $Workspace) {
            Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-LongPathProbe {
    $Workspace = New-TempWorkspace
    try {
        $LongRoot = Join-Path $Workspace "long_path_probe"
        $LongDir = $LongRoot
        $LongFileName = "probe.txt"
        while ((Join-Path $LongDir $LongFileName).Length -le 260) {
            $Index = ($LongDir.Length % 1000)
            $Segment = "nested-" + ("x" * 32) + ("-{0:D3}" -f $Index)
            $LongDir = Join-Path $LongDir $Segment
        }
        New-Item -ItemType Directory -Path $LongDir -Force | Out-Null
        $LongFile = Join-Path $LongDir $LongFileName
        $LongContent = "long-path-probe"
        [System.IO.File]::WriteAllText($LongFile, $LongContent, [System.Text.UTF8Encoding]::new($false))
        $ResolvedLongFile = (Resolve-Path -LiteralPath $LongFile).Path
        if ($ResolvedLongFile.Length -le 260) {
            throw "long_path_probe resolved path length was $($ResolvedLongFile.Length), expected > 260"
        }
        $ReadLongContent = Get-Content -LiteralPath $ResolvedLongFile -Raw -Encoding UTF8
        if ($ReadLongContent -ne $LongContent) {
            throw "long_path_probe readback mismatch"
        }
        $LongPathProbe = [pscustomobject]@{
            workspace = $Workspace
            path_length = $ResolvedLongFile.Length
            file = $ResolvedLongFile
            exceeded_default_windows_limit = ($ResolvedLongFile.Length -gt 260)
            created_read_deleted = $false
        }
        [System.IO.File]::Delete($ResolvedLongFile)
        if (Test-Path -LiteralPath $ResolvedLongFile) {
            throw "long_path_probe file still exists after delete"
        }
        $LongPathProbe.created_read_deleted = $true

        return $LongPathProbe
    } finally {
        if (Test-Path -LiteralPath $Workspace) {
            Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-CaseCollisionProbe {
    $Workspace = New-TempWorkspace
    try {
        $Media = Join-Path $Workspace "media"
        $Archive = Join-Path $Workspace "archive"
        $Output = Join-Path $Workspace "analysis"
        $Db = Join-Path $Workspace "photos.sqlite"
        New-Item -ItemType Directory -Path (Join-Path $Media "a") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $Media "b") -Force | Out-Null
        New-Item -ItemType Directory -Path $Archive -Force | Out-Null
        [System.IO.File]::WriteAllBytes(
            (Join-Path $Media "a\SAME.JPG"),
            [System.Text.Encoding]::UTF8.GetBytes("case-a")
        )
        [System.IO.File]::WriteAllBytes(
            (Join-Path $Media "b\same.jpg"),
            [System.Text.Encoding]::UTF8.GetBytes("case-b")
        )
        $TimestampUtc = [datetime]"2024-01-02T03:04:05Z"
        [System.IO.File]::SetLastWriteTimeUtc((Join-Path $Media "a\SAME.JPG"), $TimestampUtc)
        [System.IO.File]::SetLastWriteTimeUtc((Join-Path $Media "b\same.jpg"), $TimestampUtc)

        $Analyze = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "analyze", $Media,
            "--db", $Db,
            "--output", $Output,
            "--skip-hash"
        )
        if ($Analyze.scanned -lt 2) {
            throw "case_collision_probe analyzed fewer than 2 files"
        }

        $Plan = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-create",
            "--db", $Db,
            "--archive-root", $Archive
        )
        if (-not $Plan.ok) {
            throw "case_collision_probe plan-create returned ok=false"
        }
        $PlanId = [int]$Plan.data.plan_id

        $Actions = Invoke-NativeJson -FilePath $Python -Arguments @(
            "-m", "photos", "plan-actions", "$PlanId",
            "--db", $Db,
            "--limit", "20"
        )
        if (-not $Actions.ok -or $Actions.data.total -lt 2) {
            throw "case_collision_probe plan-actions returned fewer than 2 actions"
        }
        $SourceNames = @($Actions.data.rows | ForEach-Object { Split-Path -Leaf ([string]$_.source_path) })
        $LowerSourceNames = @($SourceNames | ForEach-Object { ([string]$_).ToLowerInvariant() })
        if (($LowerSourceNames | Select-Object -Unique).Count -eq $LowerSourceNames.Count) {
            throw "case_collision_probe did not create a case-insensitive source-name collision fixture"
        }
        $Destinations = @($Actions.data.rows | ForEach-Object { [string]$_.destination_path })
        $LowerDestinations = @($Destinations | ForEach-Object { ([string]$_).ToLowerInvariant() })
        if (($LowerDestinations | Select-Object -Unique).Count -ne $LowerDestinations.Count) {
            throw "case_collision_probe destination paths are not unique when lowercased"
        }
        return [pscustomobject]@{
            workspace = $Workspace
            scanned = $Analyze.scanned
            plan_id = $PlanId
            action_total = [int]$Actions.data.total
            source_names = $SourceNames
            destinations = $Destinations
            case_insensitive_unique_destination_count = $LowerDestinations.Count
        }
    } finally {
        if (Test-Path -LiteralPath $Workspace) {
            Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run .\scripts\setup_windows.ps1 first."
}

Invoke-Check -Name "handoff" -Body {
    Invoke-Native -FilePath $Python -Arguments @(".\scripts\verify_handoff.py")
    return [pscustomobject]@{ command = ".\scripts\verify_handoff.py" }
}

if ($CommercialSmoke) {
    Invoke-Check -Name "commercial_copied_fixture_smoke" -Body {
        Invoke-CommercialSmoke
    }
}

if ($WindowsFilesystemProbes) {
    Invoke-Check -Name "long_path_probe" -Body {
        Invoke-LongPathProbe
    }
    Add-Result -Name "junction_reparse_probe" -Status "skipped" -Message "not implemented in this verifier slice; requires a Windows junction/reparse temp-root probe"
    Invoke-Check -Name "case_collision_probe" -Body {
        Invoke-CaseCollisionProbe
    }
    Add-Result -Name "permission_lock_probe" -Status "skipped" -Message "not implemented in this verifier slice; requires a Windows exclusive-lock or permission-denial probe"
}

if ($Gui) {
    # Optional interactive check of the same installed GUI route used by run_windows.ps1.
    Invoke-Check -Name "gui_launch" -Body {
        Invoke-Native -FilePath $Python -Arguments @("-m", "photos", "gui")
        return [pscustomobject]@{ command = "python -m photos gui" }
    }
}

$Failed = @($Results | Where-Object { $_.status -eq "failed" })
$Summary = [pscustomobject]@{
    status = if ($Failed.Count -eq 0) { "ok" } else { "failed" }
    windows_release_ready = $false
    results = $Results
    note = "This verifier is safe by default. Opt-in smoke and filesystem probes use only temp workspaces. Passing probes are bounded checks, not a Windows release-readiness claim."
}
$Summary | ConvertTo-Json -Depth 8

if ($Failed.Count -gt 0) {
    exit 1
}
