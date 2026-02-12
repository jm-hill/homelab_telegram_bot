import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Logging
LOG_LEVEL = os.getenv('BRIDGE_LOG_LEVEL', os.getenv('LOG_LEVEL', 'INFO'))
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('notifiarr_bridge')

# Telegram Configuration
# Falls back to BOT_TOKEN used by the main bot if BRIDGE_BOT_TOKEN is not set
TELEGRAM_BOT_TOKEN = os.getenv('BRIDGE_BOT_TOKEN', os.getenv('BOT_TOKEN'))
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("BRIDGE_BOT_TOKEN (or BOT_TOKEN) must be set in environment")

# Notifiarr Configuration (optional, for validation)
NOTIFIARR_API_KEY = os.getenv('NOTIFIARR_API_KEY', '')

# Server Configuration
FLASK_PORT = int(os.getenv('BRIDGE_PORT', 5000))

# Channel Mapping (Discord Channel ID -> Telegram Chat ID[:Topic ID])
# Supports two formats:
#   DISCORD_CHANNEL_ID=TELEGRAM_CHAT_ID              (regular group)
#   DISCORD_CHANNEL_ID=TELEGRAM_CHAT_ID:TOPIC_ID     (forum topic)
CHANNEL_MAPPING = {}
KNOWN_VARS = {
    'BOT_TOKEN', 'BRIDGE_BOT_TOKEN', 'NOTIFIARR_API_KEY', 'BRIDGE_PORT',
    'BRIDGE_LOG_LEVEL', 'LOG_LEVEL', 'AUTHORIZED_USER_IDS',
    'PROXMOX_URL', 'PROXMOX_TOKEN', 'PORTAINER_URL', 'PORTAINER_TOKEN',
    'TRAEFIK_URL', 'DOCKER_HOST', 'PATH', 'HOME', 'HOSTNAME', 'PWD',
    'LANG', 'TERM', 'SHLVL', 'VIRTUAL_ENV', 'PYTHONPATH',
}

for key, value in os.environ.items():
    if key in KNOWN_VARS:
        continue
    # If the key is purely numeric (Discord channel ID), map it
    if key.isdigit():
        try:
            if ':' in value:
                chat_id_str, topic_id_str = value.split(':', 1)
                CHANNEL_MAPPING[int(key)] = {
                    'chat_id': int(chat_id_str),
                    'topic_id': int(topic_id_str),
                }
                logger.info(f"Mapped Discord channel {key} -> Telegram chat {chat_id_str} topic {topic_id_str}")
            else:
                CHANNEL_MAPPING[int(key)] = {
                    'chat_id': int(value),
                    'topic_id': None,
                }
                logger.info(f"Mapped Discord channel {key} -> Telegram chat {value}")
        except ValueError:
            logger.warning(f"Invalid channel mapping: {key}={value}")

if not CHANNEL_MAPPING:
    logger.warning("No channel mappings configured! Set environment variables like: DISCORD_CHANNEL_ID=TELEGRAM_CHAT_ID")

logger.info(f"Loaded {len(CHANNEL_MAPPING)} channel mapping(s)")
