import json
import logging
import subprocess
import requests
import urllib3
import docker

from aiohttp import web
from functools import wraps
from telegram import MessageEntity, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.helpers import escape_markdown
from config import BOT_TOKEN, AUTHORIZED_USER_IDS, SERVICES, DOCKER_HOST, WEBHOOK_PORT, WEBHOOK_CHAT_ID, PORTAINER_TOKEN
from portainer import get_stacks, start_stack, stop_stack

# Disable insecure request warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Security decorator
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in AUTHORIZED_USER_IDS:
            logger.warning(f"Unauthorized access attempt by {user_id}")
            await update.effective_message.reply_text("⛔ Unauthorized")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# Command Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initialize bot and show welcome message"""
    welcome_msg = """
🤖 *Keystone Bot Online*

Use /help to see available commands.
    """
    await update.effective_message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands"""
    help_text = f"""
*Available Commands:*

🔍 *Monitoring*
/status - Check all services
/ping <host> - Ping a specific host
/docker - Swarm service status (or container list)
/docker <node> - List containers on a specific node
/container <name> - Get container details

🔧 *Control*
/restart <container> - Restart a container
/stop <container> - Stop a container
/start <container> - Start a container

📦 *Portainer*
/portainer - List all stacks
/portainer start <name> - Start a stack
/portainer stop <name> - Stop a stack

ℹ️ *Info*
/whoami - Get your Telegram user ID
/uptime - Show system uptime
/help - Show this message

🔔 *Webhooks*
POST to port {WEBHOOK_PORT}/webhook with JSON to receive alerts here.
    """
    await update.effective_message.reply_text(help_text, parse_mode='Markdown')

@restricted
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's Telegram ID"""
    user = update.effective_user
    msg = f"👤 *User Info*\n\n"
    name = escape_markdown(f"{user.first_name} {user.last_name or ''}")
    username = escape_markdown(user.username or 'N/A')
    msg += f"Name: {name}\n"
    msg += f"Username: @{username}\n"
    msg += f"ID: `{user.id}`"
    await update.effective_message.reply_text(msg, parse_mode='Markdown')

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check status of all configured services"""
    await update.effective_message.reply_text("🔍 Checking services...")
    
    status_msg = "*Service Status:*\n\n"
    
    for name, url in SERVICES.items():
        if not url:
            continue
            
        safe_name = escape_markdown(name.title())
        try:
            response = requests.get(url, timeout=5, verify=False)
            if response.status_code < 400:
                status_msg += f"✅ {safe_name}: UP ({response.status_code})\n"
            elif response.status_code < 500:
                status_msg += f"⚠️ {safe_name}: DEGRADED ({response.status_code})\n"
            else:
                status_msg += f"❌ {safe_name}: ERROR ({response.status_code})\n"
        except requests.exceptions.Timeout:
            status_msg += f"⏱️ {safe_name}: TIMEOUT\n"
        except requests.exceptions.ConnectionError:
            status_msg += f"❌ {safe_name}: DOWN\n"
        except Exception as e:
            status_msg += f"❓ {safe_name}: ERROR\n"
            logger.error(f"Error checking {name}: {str(e)}")
    
    await update.effective_message.reply_text(status_msg, parse_mode='Markdown')

@restricted
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping a specific host"""
    if not context.args:
        await update.effective_message.reply_text("🏓 Pong!")
        return
    
    host = context.args[0]
    await update.effective_message.reply_text(f"🏓 Pinging {host}...")
    
    try:
        result = subprocess.run(
            ['ping', '-c', '4', host],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Parse ping output for summary
            lines = result.stdout.split('\n')
            summary = [line for line in lines if 'packet loss' in line or 'min/avg/max' in line]
            
            msg = f"✅ *Ping Results for {escape_markdown(host)}*\n\n"
            msg += f"```\n{chr(10).join(summary)}```"
        else:
            msg = f"❌ Unable to reach {host}"
            
        await update.effective_message.reply_text(msg, parse_mode='Markdown')
        
    except subprocess.TimeoutExpired:
        await update.effective_message.reply_text(f"⏱️ Ping timeout for {host}")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Ping error: {str(e)}")

async def _docker_local_containers(update, client):
    """List all running containers on the local Docker host."""
    containers = client.containers.list(all=False)

    if not containers:
        await update.effective_message.reply_text("No running containers found")
        return

    msg = f"*Running Containers ({len(containers)}):*\n\n"

    for container in containers:
        status_emoji = "🟢" if container.status == "running" else "🟡"
        msg += f"{status_emoji} `{container.name}`\n"
        msg += f"   Status: {container.status}\n"
        image_tag = container.image.tags[0] if container.image.tags else container.attrs.get('Config', {}).get('Image', 'N/A')
        msg += f"   Image: {escape_markdown(image_tag)}\n\n"

    await update.effective_message.reply_text(msg, parse_mode='Markdown')


async def _docker_swarm_status(update, client):
    """Show swarm service status grouped by stack."""
    services = client.services.list()

    if not services:
        await update.effective_message.reply_text("No swarm services found")
        return

    # Group services by stack namespace
    stacks = {}
    for service in services:
        labels = service.attrs['Spec'].get('Labels', {})
        stack_name = labels.get('com.docker.stack.namespace', '(no stack)')
        stacks.setdefault(stack_name, []).append(service)

    # Build message per stack
    stack_blocks = []
    for stack_name in sorted(stacks.keys()):
        services_in_stack = stacks[stack_name]
        total_services = len(services_in_stack)
        running_services = 0
        failed_list = []

        for service in services_in_stack:
            spec_mode = service.attrs['Spec'].get('Mode', {})
            if 'Replicated' in spec_mode:
                desired = spec_mode['Replicated'].get('Replicas', 1)
            else:
                desired = None  # determined from tasks below

            tasks = service.tasks(filters={'desired-state': 'running'})
            running = sum(1 for t in tasks if t['Status']['State'] == 'running')

            # For global services (or unknown modes), use the number of
            # tasks with desired-state=running as the expected count.
            # This correctly handles placement constraints that limit
            # which nodes a global service runs on.
            if desired is None:
                desired = len(tasks)

            if running >= desired and desired > 0:
                running_services += 1
            else:
                svc_name = service.attrs['Spec']['Name']
                short_name = svc_name.replace(f"{stack_name}_", "", 1) if stack_name != '(no stack)' else svc_name
                failed_list.append(short_name)

        safe_stack = escape_markdown(stack_name)

        block = ""
        if failed_list:
            failed_names = ", ".join(escape_markdown(n) for n in failed_list)
            emoji = "❌" if running_services == 0 else "⚠️"
            block += f"{emoji} *{safe_stack}*: {running_services}/{total_services} services running\n"
            block += f"   Failed: {failed_names}\n\n"
        else:
            block += f"✅ *{safe_stack}*: {running_services}/{total_services} services running\n\n"

        stack_blocks.append(block)

    # Send messages, splitting at stack boundaries if too long
    header = "*🐳 Swarm Service Status:*\n\n"
    msg = header
    for block in stack_blocks:
        if len(msg) + len(block) > 4000:
            await update.effective_message.reply_text(msg, parse_mode='Markdown')
            msg = ""
        msg += block

    if msg:
        await update.effective_message.reply_text(msg, parse_mode='Markdown')


async def _docker_node_containers(update, client, node_name):
    """List running tasks on a specific swarm node."""
    nodes = client.nodes.list()
    target_node = None
    for node in nodes:
        hostname = node.attrs['Description']['Hostname']
        if hostname.lower() == node_name.lower():
            target_node = node
            break

    if not target_node:
        await update.effective_message.reply_text(
            f"❌ Node '{escape_markdown(node_name)}' not found in swarm",
            parse_mode='Markdown'
        )
        return

    tasks = client.api.tasks(filters={
        'node': target_node.id,
        'desired-state': 'running'
    })

    if not tasks:
        await update.effective_message.reply_text(
            f"No running tasks on node {escape_markdown(node_name)}",
            parse_mode='Markdown'
        )
        return

    msg = f"*Running Tasks on {escape_markdown(node_name)} ({len(tasks)}):*\n\n"
    for task in tasks:
        state = task['Status']['State']
        status_emoji = "🟢" if state == "running" else "🟡"
        service_id = task.get('ServiceID', 'unknown')
        try:
            svc = client.services.get(service_id)
            svc_name = svc.name
        except Exception:
            svc_name = service_id[:12]

        slot = task.get('Slot', '')
        task_name = f"{svc_name}.{slot}" if slot else svc_name
        image = task['Spec']['ContainerSpec']['Image'].split('@')[0]

        msg += f"{status_emoji} `{escape_markdown(task_name)}`\n"
        msg += f"   Status: {state}\n"
        msg += f"   Image: {escape_markdown(image)}\n\n"

    await update.effective_message.reply_text(msg, parse_mode='Markdown')


@restricted
async def docker_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List Docker swarm services or containers by node"""
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)

        # Detect swarm mode
        try:
            swarm_attrs = client.swarm.attrs
            is_swarm = bool(swarm_attrs and swarm_attrs.get('ID'))
        except docker.errors.APIError:
            is_swarm = False

        if context.args:
            if is_swarm:
                await _docker_node_containers(update, client, context.args[0])
            else:
                await update.effective_message.reply_text("❌ Not in swarm mode, cannot filter by node")
        elif is_swarm:
            await _docker_swarm_status(update, client)
        else:
            await _docker_local_containers(update, client)

    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error accessing Docker: {str(e)}")
        logger.error(f"Docker error: {str(e)}")

@restricted
async def container_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get detailed info about a specific container"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /container <name>")
        return
    
    container_name = context.args[0]
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        
        msg = f"*Container: {escape_markdown(container.name)}*\n\n"
        msg += f"Status: {container.status}\n"
        image_tag = container.image.tags[0] if container.image.tags else container.attrs.get('Config', {}).get('Image', 'N/A')
        msg += f"Image: {escape_markdown(image_tag)}\n"
        msg += f"ID: `{container.short_id}`\n"
        
        # Get stats
        stats = container.stats(stream=False)
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
        cpu_percent = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0
        
        mem_usage = stats['memory_stats']['usage'] / (1024 * 1024)  # MB
        mem_limit = stats['memory_stats']['limit'] / (1024 * 1024)  # MB
        
        msg += f"\n*Resources:*\n"
        msg += f"CPU: {cpu_percent:.2f}%\n"
        msg += f"Memory: {mem_usage:.1f}MB / {mem_limit:.1f}MB\n"
        
        await update.effective_message.reply_text(msg, parse_mode='Markdown')
        
    except docker.errors.NotFound:
        await update.effective_message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Container details error: {str(e)}")

@restricted
async def restart_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart a Docker container"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /restart <container_name>")
        return
    
    container_name = context.args[0]
    await update.effective_message.reply_text(f"🔄 Restarting {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.restart()
        
        await update.effective_message.reply_text(f"✅ Container {container_name} restarted successfully")
        
    except docker.errors.NotFound:
        await update.effective_message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Restart error: {str(e)}")

@restricted
async def stop_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop a Docker container"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /stop <container_name>")
        return
    
    container_name = context.args[0]
    await update.effective_message.reply_text(f"🛑 Stopping {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.stop()
        
        await update.effective_message.reply_text(f"✅ Container {container_name} stopped")
        
    except docker.errors.NotFound:
        await update.effective_message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Stop error: {str(e)}")

@restricted
async def start_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a Docker container"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /start <container_name>")
        return
    
    container_name = context.args[0]
    await update.effective_message.reply_text(f"▶️ Starting {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.start()
        
        await update.effective_message.reply_text(f"✅ Container {container_name} started")
        
    except docker.errors.NotFound:
        await update.effective_message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Start error: {str(e)}")

@restricted
async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show system uptime"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        msg = f"⏱️ *System Uptime*\n\n"
        msg += f"{days} days, {hours} hours, {minutes} minutes"
        
        await update.effective_message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Uptime error: {str(e)}")

@restricted
async def portainer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage Portainer stacks"""
    base_url = SERVICES.get('portainer')
    if not base_url or not PORTAINER_TOKEN:
        await update.effective_message.reply_text("❌ Portainer is not configured (missing URL or API key)")
        return

    subcommand = context.args[0].lower() if context.args else "stacks"

    if subcommand == "stacks":
        await update.effective_message.reply_text("🔍 Fetching stacks...")
        try:
            stacks = get_stacks(base_url, PORTAINER_TOKEN)
            if not stacks:
                await update.effective_message.reply_text("No stacks found in Portainer")
                return

            msg = "*Portainer Stacks:*\n\n"
            for s in sorted(stacks, key=lambda x: x['name']):
                emoji = "🟢" if s['status'] == 1 else "🔴"
                status_text = "active" if s['status'] == 1 else "inactive"
                safe_name = escape_markdown(s['name'])
                msg += f"{emoji} *{safe_name}* — {status_text}\n"

            await update.effective_message.reply_text(msg, parse_mode='Markdown')
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error fetching stacks: {str(e)}")
            logger.error(f"Portainer stacks error: {str(e)}")

    elif subcommand in ("start", "stop"):
        if len(context.args) < 2:
            await update.effective_message.reply_text(f"Usage: /portainer {subcommand} <stack\\_name>", parse_mode='Markdown')
            return

        stack_name = context.args[1]
        action_emoji = "▶️" if subcommand == "start" else "🛑"
        await update.effective_message.reply_text(f"{action_emoji} {subcommand.title()}ing stack {escape_markdown(stack_name)}...", parse_mode='Markdown')

        try:
            stacks = get_stacks(base_url, PORTAINER_TOKEN)
            target = next((s for s in stacks if s['name'].lower() == stack_name.lower()), None)
            if not target:
                await update.effective_message.reply_text(f"❌ Stack '{escape_markdown(stack_name)}' not found", parse_mode='Markdown')
                return

            if subcommand == "start":
                start_stack(base_url, PORTAINER_TOKEN, target['id'], target['endpoint_id'])
            else:
                stop_stack(base_url, PORTAINER_TOKEN, target['id'], target['endpoint_id'])

            await update.effective_message.reply_text(f"✅ Stack {escape_markdown(stack_name)} {subcommand}ed successfully", parse_mode='Markdown')
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error: {str(e)}")
            logger.error(f"Portainer {subcommand} error: {str(e)}")

    else:
        await update.effective_message.reply_text(
            "Usage:\n/portainer — List stacks\n/portainer start <name>\n/portainer stop <name>"
        )

# Webhook server
_webhook_runner = None


_SERVICE_NAME_KEYS = ('service', 'source', 'app', 'component', 'product', 'title')
_MESSAGE_KEYS = ('message', 'text', 'description', 'summary')
_SEVERITY_EMOJIS = {
    'critical': '\U0001F6A8',
    'error': '\u274C',
    'warning': '\u26A0\uFE0F',
    'info': '\U0001F514',
}


def _normalize_service_name(name: str) -> str:
    """Normalize a service name to clean uppercase."""
    return name.replace('_', ' ').replace('-', ' ').upper().strip()


def format_webhook_payload(data: dict) -> str:
    """Format a webhook JSON payload into a Telegram-friendly message."""
    # Resolve service name
    service_name = None
    service_key = None
    for key in _SERVICE_NAME_KEYS:
        if key in data and data[key]:
            service_name = _normalize_service_name(str(data[key]))
            service_key = key
            break
    if not service_name:
        service_name = 'WEBHOOK'

    # Pick emoji based on severity if present
    severity = str(data.get('severity', '')).lower()
    emoji = _SEVERITY_EMOJIS.get(severity, '\U0001F514')

    # Resolve main message body
    message = None
    message_key = None
    for key in _MESSAGE_KEYS:
        if key in data and data[key]:
            message = str(data[key])
            message_key = key
            break

    # Build output
    used_keys = {service_key, message_key} - {None}
    parts = [f"{emoji} *{escape_markdown(service_name)}*"]

    if message:
        parts.append(escape_markdown(message))

    # Compact details block for remaining fields
    extra_keys = [k for k in data if k not in used_keys]
    if extra_keys:
        details = []
        for key in extra_keys:
            value = data[key]
            safe_key = escape_markdown(str(key))
            if isinstance(value, (dict, list)):
                safe_val = f"`{json.dumps(value, indent=2)[:500]}`"
            else:
                safe_val = escape_markdown(str(value))
            details.append(f"_{safe_key}_: {safe_val}")
        parts.append("\n".join(details))

    return "\n".join(parts)


async def handle_webhook_request(request: web.Request) -> web.Response:
    """Handle incoming webhook POST requests and forward to Telegram."""
    try:
        data = await request.json()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Webhook received invalid JSON: {e}")
        return web.Response(status=400, text="Invalid JSON payload")

    logger.info(f"Webhook received: {json.dumps(data)[:200]}")

    text = format_webhook_payload(data)
    if len(text) > 4000:
        text = text[:3990] + "\n\n_...truncated_"

    if WEBHOOK_CHAT_ID:
        try:
            chat_ids = [int(WEBHOOK_CHAT_ID)]
        except ValueError:
            logger.error(f"Invalid WEBHOOK_CHAT_ID: {WEBHOOK_CHAT_ID}")
            return web.Response(status=500, text="Server misconfigured")
    else:
        chat_ids = AUTHORIZED_USER_IDS

    if not chat_ids:
        logger.error("No chat IDs configured for webhook delivery")
        return web.Response(status=500, text="No recipients configured")

    bot = request.app['telegram_bot']
    errors = []
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send webhook alert to {chat_id}: {e}")
            errors.append(str(chat_id))

    if errors:
        return web.Response(status=207, text=f"Delivered with errors. Failed: {', '.join(errors)}")
    return web.Response(status=200, text="OK")


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint that verifies bot internals."""
    checks = {}

    # Check Telegram bot connectivity
    try:
        bot = request.app['telegram_bot']
        await bot.get_me()
        checks['telegram'] = 'ok'
    except Exception as e:
        checks['telegram'] = f'error: {e}'

    # Check Docker socket access
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        client.ping()
        client.close()
        checks['docker'] = 'ok'
    except Exception as e:
        checks['docker'] = f'error: {e}'

    all_ok = all(v == 'ok' for v in checks.values())
    status = 'healthy' if all_ok else 'unhealthy'
    http_status = 200 if all_ok else 503

    body = json.dumps({'status': status, 'checks': checks})
    return web.Response(status=http_status, text=body, content_type='application/json')


async def start_webhook_server(application) -> None:
    """Start the aiohttp webhook server (post_init hook)."""
    global _webhook_runner

    webhook_app = web.Application()
    webhook_app.router.add_post('/webhook', handle_webhook_request)
    webhook_app.router.add_get('/health', handle_health)
    webhook_app['telegram_bot'] = application.bot

    _webhook_runner = web.AppRunner(webhook_app)
    await _webhook_runner.setup()

    site = web.TCPSite(_webhook_runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    logger.info(f"Webhook server started on port {WEBHOOK_PORT}")


async def stop_webhook_server(application) -> None:
    """Stop the aiohttp webhook server (post_stop hook)."""
    global _webhook_runner

    if _webhook_runner:
        await _webhook_runner.cleanup()
        _webhook_runner = None
        logger.info("Webhook server stopped")


async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle @botname command format in groups/channels"""
    message = update.message
    if not message or not message.text or not message.entities:
        return

    bot_username = context.bot.username.lower()
    text = message.text

    # Map of recognized commands to their handler functions
    command_map = {
        'help': help_command,
        'whoami': whoami,
        'status': status,
        'ping': ping,
        'docker': docker_list,
        'container': container_details,
        'restart': restart_container,
        'stop': stop_container,
        'start': start_container,
        'uptime': uptime,
        'portainer': portainer_command,
        'pt': portainer_command,
    }

    for entity in message.entities:
        if entity.type == MessageEntity.MENTION:
            mention = text[entity.offset:entity.offset + entity.length]
            if mention.lower() == f"@{bot_username}":
                # Extract text after the mention
                after_mention = text[entity.offset + entity.length:].strip()
                if not after_mention:
                    await help_command(update, context)
                    return

                # Parse command and arguments
                parts = after_mention.split()
                command = parts[0].lower().lstrip('/')
                context.args = parts[1:] if len(parts) > 1 else []

                handler = command_map.get(command)
                if handler:
                    await handler(update, context)
                else:
                    await update.effective_message.reply_text(
                        f"Unknown command: {command}\nUse /help to see available commands."
                    )
                return


def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment")
        return
    
    if not AUTHORIZED_USER_IDS:
        logger.warning("No authorized users configured - bot will reject all commands")
    
    # Build application
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(start_webhook_server)
        .post_stop(stop_webhook_server)
        .build()
    )
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("docker", docker_list))
    app.add_handler(CommandHandler("container", container_details))
    app.add_handler(CommandHandler("restart", restart_container))
    app.add_handler(CommandHandler("stop", stop_container))
    app.add_handler(CommandHandler("start", start_container))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("portainer", portainer_command))
    app.add_handler(CommandHandler("pt", portainer_command))

    # Start polling
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()