# Homelab Alerts & Management Bot

A Telegram bot for monitoring services and managing Docker containers remotely.

## Features

- **Service Monitoring**: Check HTTP status of configured services
- **Docker Management**: List, start, stop, and restart containers
- **Network Tools**: Ping hosts and check connectivity
- **System Info**: View system uptime and resource usage
- **Security**: User authorization with Telegram user ID whitelist

## Commands

### Monitoring
- `/status` - Check all configured services
- `/ping <host>` - Ping a specific host
- `/docker` - List running containers
- `/container <name>` - Get detailed container information

### Control
- `/restart <container>` - Restart a Docker container
- `/stop <container>` - Stop a Docker container
- `/start <container>` - Start a Docker container

### Info
- `/whoami` - Get your Telegram user ID
- `/uptime` - Show system uptime
- `/help` - Show available commands

## Setup

### Prerequisites
- Python 3.8+
- Docker (for container management features)
- A Telegram Bot Token from [@BotFather](https://t.me/botfather)

### Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd telegram_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your configuration:
```env
BOT_TOKEN=your_telegram_bot_token_here
AUTHORIZED_USER_IDS=123456789,987654321
DOCKER_HOST=unix://var/run/docker.sock

# Services to monitor (optional)
SERVICE_API=https://api.example.com
SERVICE_WEB=https://example.com
```

4. Run the bot:
```bash
python bot.py
```

### Docker Deployment

Run with Docker Compose:
```bash
docker-compose up -d
```

## Configuration

Configuration is managed through environment variables in the [.env](.env) file:

- `BOT_TOKEN`: Your Telegram bot token from BotFather
- `AUTHORIZED_USER_IDS`: Comma-separated list of Telegram user IDs allowed to use the bot
- `DOCKER_HOST`: Docker daemon socket (default: `unix://var/run/docker.sock`)
- `SERVICE_*`: URLs of services to monitor (e.g., `SERVICE_API`, `SERVICE_WEB`)

### Getting Your Telegram User ID

1. Start the bot and send `/whoami`
2. The bot will reply with your user ID
3. Add your ID to `AUTHORIZED_USER_IDS` in [.env](.env)

## Security

- All commands except `/start` and `/help` require user authorization
- Only Telegram user IDs listed in `AUTHORIZED_USER_IDS` can execute commands
- Unauthorized access attempts are logged

## Project Structure

- [bot.py](bot.py) - Main bot application with command handlers
- [config.py](config.py) - Configuration loader
- [requirements.txt](requirements.txt) - Python dependencies
- [Dockerfile](Dockerfile) - Docker image definition
- [docker-compose.yml](docker-compose.yml) - Docker Compose configuration

## License

MIT
