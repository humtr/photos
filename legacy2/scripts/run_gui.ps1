param(
    [string]$Db = ".photos-data/photos.sqlite"
)

$ErrorActionPreference = "Stop"

python -m photos.app --db $Db

