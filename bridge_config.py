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

# Channel Mapping (Discord Channel ID -> Telegram Chat ID)
# Load all environment variables that look like numeric keys (Discord channel IDs)
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
    # If the key is purely numeric (Discord channel ID), map it to Telegram chat ID
    if key.isdigit():
        try:
            CHANNEL_MAPPING[int(key)] = int(value)
            logger.info(f"Mapped Discord channel {key} -> Telegram chat {value}")
        except ValueError:
            logger.warning(f"Invalid channel mapping: {key}={value}")

if not CHANNEL_MAPPING:
    logger.warning("No channel mappings configured! Set environment variables like: DISCORD_CHANNEL_ID=TELEGRAM_CHAT_ID")

logger.info(f"Loaded {len(CHANNEL_MAPPING)} channel mapping(s)")
