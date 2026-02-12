import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if uid]

# Service URLs
SERVICES = {
    'proxmox': os.getenv('PROXMOX_URL'),
    'portainer': os.getenv('PORTAINER_URL'),
    'traefik': os.getenv('TRAEFIK_URL'),
}

# API Tokens
PROXMOX_TOKEN = os.getenv('PROXMOX_TOKEN')
PORTAINER_TOKEN = os.getenv('PORTAINER_TOKEN')

# Docker
DOCKER_HOST = os.getenv('DOCKER_HOST', 'unix:///var/run/docker.sock')