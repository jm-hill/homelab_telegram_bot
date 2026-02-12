# Homelab Alerts & Management Bot

A Telegram bot for monitoring services and managing Docker containers remotely.

## Features

- **Service Monitoring**: Check HTTP status of configured services
- **Docker Management**: List, start, stop, and restart containers
- **Network Tools**: Ping hosts and check connectivity
- **System Info**: View system uptime and resource usage
- **Security**: User authorization with Telegram user ID whitelist
- **Notifiarr Bridge**: Receive Notifiarr passthrough webhooks and forward to Telegram

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
- [bridge.py](bridge.py) - Notifiarr webhook-to-Telegram bridge (Flask)
- [bridge_config.py](bridge_config.py) - Bridge configuration and channel mappings
- [requirements.txt](requirements.txt) - Python dependencies
- [Dockerfile](Dockerfile) - Docker image for the bot
- [Dockerfile.bridge](Dockerfile.bridge) - Docker image for the bridge
- [docker-compose.yml](docker-compose.yml) - Docker Compose configuration

---

## Notifiarr-Telegram Bridge

Translates [Notifiarr](https://notifiarr.com) passthrough webhooks (Discord-formatted) into Telegram Bot API messages. Created to fill the gap until Notifiarr implements native Telegram support ([Notifiarr/website#22](https://github.com/Notifiarr/website/issues/22)).

### Bridge Features

- Accepts Notifiarr passthrough webhook payload format
- Converts Discord embed fields, colors, and formatting to Telegram HTML
- Maps Discord channel IDs to Telegram chat IDs (with optional forum topic routing)
- **Message updates**: `notification.update=true` edits an existing message in-place
- **Message deletion**: `DELETE /webhook` removes a previously sent notification
- **API key validation**: Optional `x-api-key` header check for webhook security
- **Forum topic support**: Routes messages to specific topics within Telegram supergroups
- Health check and test notification endpoints

### Bridge Quick Start

#### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Save the bot token

#### 2. Get Telegram Chat IDs

For each group you want to send alerts to:

1. Add your bot to the group (make it admin for best results)
2. Send a message in the group
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Find `"chat":{"id": -100XXXXXXXXX}` in the response
5. For forum topics, also note the `message_thread_id` value

#### 3. Configure Environment

Add to your `.env`:
```bash
# Bridge bot token (defaults to BOT_TOKEN if not set)
BRIDGE_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Optional: validate incoming webhooks
NOTIFIARR_API_KEY=your_notifiarr_api_key

# Channel Mappings: Discord Channel ID = Telegram Chat ID
735481457153277994=-1001234567890

# With forum topic support: CHAT_ID:TOPIC_ID
631827062348512345=-1009876543210:42
```

#### 4. Deploy

```bash
docker-compose up -d
```

#### 5. Configure Notifiarr

In Notifiarr's passthrough integration, set the webhook URL to:
```
http://your-server:5000/webhook
```

Use the same Discord channel IDs in Notifiarr that you've mapped to Telegram chats.

### Bridge Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook` | Receive Notifiarr passthrough webhooks |
| `DELETE` | `/webhook` | Delete a previously sent notification by name/event |
| `GET` | `/health` | Health check (mapped channels, tracked messages) |
| `GET` | `/mappings` | List configured Discord-to-Telegram channel mappings |
| `POST` | `/test` | Send a test notification to a specific chat |

#### Test notification
```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id": -1001234567890, "message": "Test from bridge"}'
```

#### Test with forum topic
```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id": -1001234567890, "topic_id": 42, "message": "Topic test"}'
```

#### Delete a notification
```bash
curl -X DELETE http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"notification": {"name": "App Name", "event": "12345"}}'
```

### Channel Mapping

Channel mappings are environment variables where:
- **Key** = Discord Channel ID (from Notifiarr passthrough config)
- **Value** = Telegram Chat ID, optionally with `:TOPIC_ID` for forum topics

```bash
# Regular group
735481457153277994=-1001234567890

# Forum topic (supergroup with topics enabled)
631827062348512345=-1009876543210:42
```

### Message Update Flow

When Notifiarr sends `notification.update: true`, the bridge edits the original Telegram message instead of posting a new one. This is useful for apps like Radarr/Sonarr that update download progress.

The bridge tracks message IDs in memory (keyed by `notification.name` + `notification.event`), bounded to 10,000 entries. If the original message can't be found or the edit fails, a new message is sent instead.

### Discord-to-Telegram Concept Mapping

Reference for how Discord concepts translate to the Telegram Bot API (addresses questions from [Notifiarr/website#22](https://github.com/Notifiarr/website/issues/22)):

| Discord Concept | Telegram Equivalent | Bot API Method | Notes |
|---|---|---|---|
| Server (Guild) | Group / Supergroup | - | Bots don't "list servers"; track via `my_chat_member` updates when added/removed |
| Channel | Forum Topic (in supergroup) | `createForumTopic` | Only in supergroups with topics enabled; regular groups have no sub-channels |
| List channels | List forum topics | No direct API | Must track topic creation events; no bulk "list all topics" endpoint |
| List members | Get chat member info | `getChatAdministrators`, `getChatMemberCount` | Cannot enumerate all non-admin members; only admins + individual lookups via `getChatMember` |
| Send message to channel | Send message to chat/topic | `sendMessage` with `message_thread_id` | `chat_id` targets the group; `message_thread_id` targets a specific forum topic |
| Edit message | Edit message | `editMessageText` | Requires stored `message_id`; bots can only edit their own messages |
| Delete message | Delete message | `deleteMessage` | Bots can delete their own messages and (if admin) others' messages |
| User ping (@mention) | User mention | HTML: `<a href="tg://user?id=USER_ID">name</a>` | Requires Telegram user ID; no Discord-to-Telegram user ID mapping exists natively |
| Role ping | No equivalent | - | Telegram has no role/group-mention system |
| Embed colors | No equivalent | - | Approximated with emoji indicators in this bridge |
| Reactions | No equivalent | - | Telegram Bot API does not support reactions |
| Auth model | Bot Token from @BotFather | - | Single token per bot; no app-level API keys like Discord |

### Limitations

- **In-memory message tracking**: Message ID mappings for updates are stored in memory and lost on restart. For persistent tracking, an external store (Redis, SQLite) would be needed.
- **User pings**: Discord user IDs cannot be mapped to Telegram user IDs without a separate user mapping.
- **No role pings**: Telegram has no concept of mentionable roles.
- **Reactions**: Not supported by the Telegram Bot API.
- **Bot group discovery**: Bots cannot list all groups they belong to; they must track `my_chat_member` join/leave events.
- **Topic enumeration**: No bulk API to list all forum topics in a supergroup.

### Troubleshooting

**"No Telegram mapping for Discord channel X"**
- Add the mapping to your `.env`: `X=-100YOUR_CHAT_ID`

**Bot not sending messages**
- Verify the bot is a member (ideally admin) of the target group
- Check the bot token is correct
- Check logs: `docker logs notifiarr-telegram-bridge`

**Getting chat IDs**
```bash
curl https://api.telegram.org/botYOUR_TOKEN/getUpdates
```

**Getting forum topic IDs**
- Send a message in the forum topic, then check `getUpdates` for `message_thread_id`

---

## License

MIT
