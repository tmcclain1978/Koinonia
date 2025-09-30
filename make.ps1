param(
    [string]$Task = "help"
)

switch ($Task) {
    "up" {
        Write-Host "🚀 Starting containers (with build)..."
        docker compose up -d --build
    }
    "down" {
        Write-Host "🛑 Stopping containers and removing volumes..."
        docker compose down -v
    }
    "logs" {
        Write-Host "📜 Showing API logs..."
        docker compose logs -f --tail=200 api
    }
    "sh" {
        Write-Host "🔧 Opening shell in API container..."
        docker compose exec api powershell
    }
    "migrate" {
        Write-Host "📂 Running migrations..."
        docker compose exec api bash scripts/migrate.sh
    }
    "rebuild" {
        Write-Host "🔄 Rebuilding API container without cache..."
        docker compose build --no-cache api
    }
    "help" {
        Write-Host "Available commands:"
        Write-Host "  .\make.ps1 up       -> start containers"
        Write-Host "  .\make.ps1 down     -> stop and remove containers/volumes"
        Write-Host "  .\make.ps1 logs     -> view logs"
        Write-Host "  .\make.ps1 sh       -> open shell in API container"
        Write-Host "  .\make.ps1 migrate  -> run DB migrations"
        Write-Host "  .\make.ps1 rebuild  -> rebuild API container"
    }
    Default {
        Write-Host "❌ Unknown task '$Task'. Run '.\make.ps1 help' to see available commands."
    }
}
