import asyncio
import html
import json
import os

from flask import Flask, request, jsonify
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from bridge_config import (
    logger, TELEGRAM_BOT_TOKEN, CHANNEL_MAPPING, NOTIFIARR_API_KEY, FLASK_PORT,
)

app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Color hex to emoji mapping (matches Notifiarr's scheme)
COLOR_MAP = {
    '00FF00': '🟢',  # Green / Success
    'FFFF00': '🟡',  # Yellow / Warning
    'FF0000': '🔴',  # Red / Error
    'FFA500': '🟠',  # Orange
    '0000FF': '🔵',  # Blue
    'FFFFFF': '⚪',  # White
    '000000': '⚫',  # Black
}


def run_async(coro):
    """Run an async coroutine from synchronous Flask context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def get_color_emoji(color_hex):
    """Convert hex color to emoji indicator."""
    if not color_hex:
        return ''

    color_hex = str(color_hex).upper().lstrip('#')

    # Exact match
    if color_hex in COLOR_MAP:
        return COLOR_MAP[color_hex]

    # Approximate match for common colors
    if color_hex.startswith('00FF') or color_hex.startswith('0F'):
        return '🟢'
    elif color_hex.startswith('FF0') or color_hex.startswith('F0'):
        return '🟡'
    elif color_hex.startswith('FF') and not color_hex.startswith('FF0'):
        return '🔴'
    elif color_hex.startswith('0'):
        return '🔵'

    return '🔘'


def build_telegram_message(payload):
    """
    Convert Notifiarr Discord payload to Telegram message.

    Returns: (message_text, parse_mode, thumbnail_url, image_url)
    """
    discord = payload.get('discord', {})
    notification = payload.get('notification', {})

    text_data = discord.get('text', {})
    images = discord.get('images', {})

    parts = []

    # Color indicator
    color = discord.get('color', '')
    if color:
        emoji = get_color_emoji(color)
        if emoji:
            parts.append(emoji)

    # Title (bold)
    title = text_data.get('title', '')
    if title:
        parts.append(f"<b>{html.escape(title)}</b>")

    # Content (appears above embed in Discord)
    content = text_data.get('content', '')
    if content:
        parts.append(html.escape(content))

    # Description
    description = text_data.get('description', '')
    if description:
        parts.append(html.escape(description))

    # Fields
    fields = text_data.get('fields', [])
    if fields:
        parts.append('')  # Blank line before fields
        for field in fields:
            field_title = field.get('title', '')
            field_text = field.get('text', '')
            inline = field.get('inline', False)

            if inline:
                parts.append(f"<b>{html.escape(field_title)}:</b> {html.escape(field_text)}")
            else:
                parts.append(f"<b>{html.escape(field_title)}</b>")
                parts.append(html.escape(field_text))

    # Footer
    footer = text_data.get('footer', '')
    if footer:
        parts.append('')
        parts.append(f"<i>{html.escape(footer)}</i>")

    # App name from notification
    app_name = notification.get('name', '')
    if app_name:
        parts.append(f"\n{'━' * 15}")
        parts.append(f"<code>{html.escape(app_name)}</code>")

    message_text = '\n'.join(parts)

    thumbnail_url = images.get('thumbnail', '')
    image_url = images.get('image', '')

    return message_text, ParseMode.HTML, thumbnail_url, image_url


def get_telegram_chat_id(discord_channel_id):
    """Map Discord channel ID to Telegram chat ID."""
    if not discord_channel_id:
        logger.warning("No Discord channel ID provided")
        return None

    chat_id = CHANNEL_MAPPING.get(discord_channel_id)

    if not chat_id:
        logger.warning(f"No Telegram mapping found for Discord channel {discord_channel_id}")
        logger.info(f"Available mappings: {list(CHANNEL_MAPPING.keys())}")

    return chat_id


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'mapped_channels': len(CHANNEL_MAPPING),
    }), 200


@app.route('/webhook', methods=['POST'])
def notifiarr_webhook():
    """
    Receive Notifiarr passthrough webhook and forward to Telegram.

    Expects Notifiarr passthrough payload format:
    {
        "notification": {
            "update": bool,
            "name": str,
            "event": str
        },
        "discord": {
            "color": str,
            "ping": {...},
            "images": {...},
            "text": {...},
            "ids": {
                "channel": int
            }
        }
    }
    """
    try:
        payload = request.json

        if not payload:
            logger.error("Empty payload received")
            return jsonify({'error': 'Empty payload'}), 400

        logger.debug(f"Received payload: {json.dumps(payload, indent=2)}")

        # Extract Discord channel ID
        discord_channel_id = payload.get('discord', {}).get('ids', {}).get('channel')

        if not discord_channel_id:
            logger.error("No Discord channel ID in payload")
            return jsonify({'error': 'Missing discord.ids.channel'}), 400

        # Map to Telegram chat ID
        telegram_chat_id = get_telegram_chat_id(discord_channel_id)

        if not telegram_chat_id:
            return jsonify({
                'error': f'No Telegram mapping for Discord channel {discord_channel_id}',
                'hint': f'Add mapping in environment: {discord_channel_id}=TELEGRAM_CHAT_ID',
            }), 404

        # Build Telegram message
        message_text, parse_mode, thumbnail_url, image_url = build_telegram_message(payload)

        if not message_text:
            logger.warning("Empty message text generated")
            message_text = "Notification received (no content)"

        logger.info(f"Sending message to Telegram chat {telegram_chat_id}")

        # Send main message (async call wrapped for sync Flask)
        sent_message = run_async(bot.send_message(
            chat_id=telegram_chat_id,
            text=message_text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        ))

        # Send thumbnail if present
        if thumbnail_url:
            try:
                run_async(bot.send_photo(
                    chat_id=telegram_chat_id,
                    photo=thumbnail_url,
                ))
            except TelegramError as e:
                logger.warning(f"Failed to send thumbnail: {e}")

        # Send image if present (and different from thumbnail)
        if image_url and image_url != thumbnail_url:
            try:
                run_async(bot.send_photo(
                    chat_id=telegram_chat_id,
                    photo=image_url,
                ))
            except TelegramError as e:
                logger.warning(f"Failed to send image: {e}")

        return jsonify({
            'status': 'success',
            'telegram_message_id': sent_message.message_id,
            'telegram_chat_id': telegram_chat_id,
            'discord_channel_id': discord_channel_id,
        }), 200

    except TelegramError as e:
        logger.error(f"Telegram API error: {e}")
        return jsonify({
            'error': 'Telegram API error',
            'details': str(e),
        }), 500

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'details': str(e),
        }), 500


@app.route('/mappings', methods=['GET'])
def list_mappings():
    """List configured channel mappings."""
    return jsonify({
        'mappings': {
            str(discord_id): telegram_id
            for discord_id, telegram_id in CHANNEL_MAPPING.items()
        }
    }), 200


@app.route('/test', methods=['POST'])
def test_notification():
    """
    Send a test notification to verify configuration.

    POST body:
    {
        "telegram_chat_id": -1001234567890,
        "message": "Test message"
    }
    """
    try:
        data = request.json
        chat_id = data.get('telegram_chat_id')
        message = data.get('message', 'Test notification from Notifiarr-Telegram Bridge')

        if not chat_id:
            return jsonify({'error': 'telegram_chat_id required'}), 400

        sent = run_async(bot.send_message(
            chat_id=chat_id,
            text=f"✅ {message}",
            parse_mode=ParseMode.HTML,
        ))

        return jsonify({
            'status': 'success',
            'message_id': sent.message_id,
            'chat_id': chat_id,
        }), 200

    except TelegramError as e:
        return jsonify({
            'error': 'Telegram error',
            'details': str(e),
        }), 500


if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Notifiarr -> Telegram Bridge Starting")
    logger.info("=" * 50)
    logger.info(f"Mapped channels: {len(CHANNEL_MAPPING)}")

    if not CHANNEL_MAPPING:
        logger.warning("No channel mappings configured!")
        logger.warning("Set environment variables: DISCORD_CHANNEL_ID=TELEGRAM_CHAT_ID")

    logger.info(f"Starting Flask on port {FLASK_PORT}")
    logger.info("=" * 50)

    app.run(
        host='0.0.0.0',
        port=FLASK_PORT,
        debug=False,
    )
