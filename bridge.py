import asyncio
import collections
import html
import json
import threading
import time

from flask import Flask, request, jsonify
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from bridge_config import (
    logger, TELEGRAM_BOT_TOKEN, CHANNEL_MAPPING, NOTIFIARR_API_KEY, FLASK_PORT,
)

app = Flask(__name__)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# In-memory store for message ID tracking (enables notification.update support).
# Key: (notification_name, notification_event) -> telegram_message_id
# Bounded to prevent unbounded memory growth; oldest entries evicted first.
MAX_MESSAGE_STORE = 10000
_message_store = collections.OrderedDict()
_store_lock = threading.Lock()

# Color hex to emoji mapping (matches Notifiarr's scheme)
COLOR_MAP = {
    '00FF00': '\U0001f7e2',  # Green / Success
    'FFFF00': '\U0001f7e1',  # Yellow / Warning
    'FF0000': '\U0001f534',  # Red / Error
    'FFA500': '\U0001f7e0',  # Orange
    '0000FF': '\U0001f535',  # Blue
    'FFFFFF': '\u26aa',       # White
    '000000': '\u26ab',       # Black
}


def run_async(coro):
    """Run an async coroutine from synchronous Flask context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _store_message_id(name, event, chat_id, message_id):
    """Store a Telegram message_id for later update/delete by notification key."""
    if not name:
        return
    key = (name, event or '')
    with _store_lock:
        _message_store[key] = {'chat_id': chat_id, 'message_id': message_id, 'ts': time.time()}
        _message_store.move_to_end(key)
        while len(_message_store) > MAX_MESSAGE_STORE:
            _message_store.popitem(last=False)


def _get_stored_message(name, event):
    """Retrieve a previously stored Telegram message_id for update/delete."""
    key = (name, event or '')
    with _store_lock:
        return _message_store.get(key)


def _remove_stored_message(name, event):
    """Remove a stored message mapping."""
    key = (name, event or '')
    with _store_lock:
        _message_store.pop(key, None)


def get_color_emoji(color_hex):
    """Convert hex color to emoji indicator."""
    if not color_hex:
        return ''

    color_hex = str(color_hex).upper().lstrip('#')

    if color_hex in COLOR_MAP:
        return COLOR_MAP[color_hex]

    # Approximate match for common colors
    if color_hex.startswith('00FF') or color_hex.startswith('0F'):
        return '\U0001f7e2'
    elif color_hex.startswith('FF0') or color_hex.startswith('F0'):
        return '\U0001f7e1'
    elif color_hex.startswith('FF') and not color_hex.startswith('FF0'):
        return '\U0001f534'
    elif color_hex.startswith('0'):
        return '\U0001f535'

    return '\U0001f518'


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

    # Fields (max 25 per Notifiarr spec)
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


def get_telegram_target(discord_channel_id):
    """Map Discord channel ID to Telegram chat_id and optional topic_id."""
    if not discord_channel_id:
        logger.warning("No Discord channel ID provided")
        return None, None

    mapping = CHANNEL_MAPPING.get(discord_channel_id)

    if not mapping:
        logger.warning(f"No Telegram mapping found for Discord channel {discord_channel_id}")
        logger.info(f"Available mappings: {list(CHANNEL_MAPPING.keys())}")
        return None, None

    return mapping['chat_id'], mapping.get('topic_id')


def validate_api_key():
    """Validate the Notifiarr API key from the request header, if configured."""
    if not NOTIFIARR_API_KEY:
        return True
    incoming_key = request.headers.get('x-api-key', '')
    return incoming_key == NOTIFIARR_API_KEY


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'mapped_channels': len(CHANNEL_MAPPING),
        'tracked_messages': len(_message_store),
    }), 200


@app.route('/webhook', methods=['POST'])
def notifiarr_webhook():
    """
    Receive Notifiarr passthrough webhook and forward to Telegram.

    Supports:
    - notification.update=true: edits an existing Telegram message instead of sending new
    - Forum topics: routes to specific topic threads via channel mapping
    - API key validation via x-api-key header (when NOTIFIARR_API_KEY is set)
    """
    if not validate_api_key():
        logger.warning("Rejected webhook: invalid API key")
        return jsonify({'error': 'Unauthorized'}), 401

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

        # Map to Telegram chat ID (and optional topic ID)
        telegram_chat_id, topic_id = get_telegram_target(discord_channel_id)

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

        # Check if this is an update to an existing message
        notification = payload.get('notification', {})
        should_update = notification.get('update', False)
        notif_name = notification.get('name', '')
        notif_event = notification.get('event', '')

        # Common kwargs for send/edit
        send_kwargs = {
            'chat_id': telegram_chat_id,
            'parse_mode': parse_mode,
        }
        if topic_id:
            send_kwargs['message_thread_id'] = topic_id

        if should_update and notif_name:
            stored = _get_stored_message(notif_name, notif_event)
            if stored and stored['chat_id'] == telegram_chat_id:
                # Update existing message
                logger.info(f"Updating message {stored['message_id']} in chat {telegram_chat_id}")
                try:
                    run_async(bot.edit_message_text(
                        text=message_text,
                        message_id=stored['message_id'],
                        disable_web_page_preview=True,
                        **send_kwargs,
                    ))
                    # Keep the same stored entry (message_id unchanged)
                    return jsonify({
                        'status': 'updated',
                        'telegram_message_id': stored['message_id'],
                        'telegram_chat_id': telegram_chat_id,
                        'discord_channel_id': discord_channel_id,
                    }), 200
                except TelegramError as e:
                    logger.warning(f"Failed to update message, sending new: {e}")
                    # Fall through to send a new message

        # Send new message
        logger.info(f"Sending message to Telegram chat {telegram_chat_id}" +
                     (f" topic {topic_id}" if topic_id else ""))

        sent_message = run_async(bot.send_message(
            text=message_text,
            disable_web_page_preview=True,
            **send_kwargs,
        ))

        # Store message ID for future updates
        _store_message_id(notif_name, notif_event, telegram_chat_id, sent_message.message_id)

        # Send thumbnail if present
        if thumbnail_url:
            try:
                photo_kwargs = {'chat_id': telegram_chat_id, 'photo': thumbnail_url}
                if topic_id:
                    photo_kwargs['message_thread_id'] = topic_id
                run_async(bot.send_photo(**photo_kwargs))
            except TelegramError as e:
                logger.warning(f"Failed to send thumbnail: {e}")

        # Send image if present (and different from thumbnail)
        if image_url and image_url != thumbnail_url:
            try:
                photo_kwargs = {'chat_id': telegram_chat_id, 'photo': image_url}
                if topic_id:
                    photo_kwargs['message_thread_id'] = topic_id
                run_async(bot.send_photo(**photo_kwargs))
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


@app.route('/webhook', methods=['DELETE'])
def delete_notification():
    """
    Delete a previously sent notification by name/event.

    DELETE body:
    {
        "notification": {
            "name": "App Name",
            "event": "event_id"
        }
    }
    """
    if not validate_api_key():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.json or {}
        notification = data.get('notification', {})
        name = notification.get('name', '')
        event = notification.get('event', '')

        if not name:
            return jsonify({'error': 'notification.name required'}), 400

        stored = _get_stored_message(name, event)
        if not stored:
            return jsonify({'error': 'No stored message found for this notification'}), 404

        run_async(bot.delete_message(
            chat_id=stored['chat_id'],
            message_id=stored['message_id'],
        ))

        _remove_stored_message(name, event)

        return jsonify({
            'status': 'deleted',
            'telegram_message_id': stored['message_id'],
            'telegram_chat_id': stored['chat_id'],
        }), 200

    except TelegramError as e:
        logger.error(f"Telegram API error on delete: {e}")
        return jsonify({'error': 'Telegram API error', 'details': str(e)}), 500

    except Exception as e:
        logger.error(f"Delete error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@app.route('/mappings', methods=['GET'])
def list_mappings():
    """List configured channel mappings."""
    return jsonify({
        'mappings': {
            str(discord_id): mapping
            for discord_id, mapping in CHANNEL_MAPPING.items()
        }
    }), 200


@app.route('/test', methods=['POST'])
def test_notification():
    """
    Send a test notification to verify configuration.

    POST body:
    {
        "telegram_chat_id": -1001234567890,
        "message": "Test message",
        "topic_id": 123  (optional, for forum topics)
    }
    """
    try:
        data = request.json
        chat_id = data.get('telegram_chat_id')
        message = data.get('message', 'Test notification from Notifiarr-Telegram Bridge')
        topic_id = data.get('topic_id')

        if not chat_id:
            return jsonify({'error': 'telegram_chat_id required'}), 400

        kwargs = {
            'chat_id': chat_id,
            'text': f"\u2705 {message}",
            'parse_mode': ParseMode.HTML,
        }
        if topic_id:
            kwargs['message_thread_id'] = topic_id

        sent = run_async(bot.send_message(**kwargs))

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
    logger.info(f"API key validation: {'enabled' if NOTIFIARR_API_KEY else 'disabled'}")

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
