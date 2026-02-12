import logging
import subprocess
import requests
import urllib3
import docker

from functools import wraps
from telegram import MessageEntity, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.helpers import escape_markdown
from config import BOT_TOKEN, AUTHORIZED_USER_IDS, SERVICES, DOCKER_HOST

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
            await update.message.reply_text("⛔ Unauthorized")
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
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands"""
    help_text = """
*Available Commands:*

🔍 *Monitoring*
/status - Check all services
/ping <host> - Ping a specific host
/docker - List running containers
/container <name> - Get container details

🔧 *Control*
/restart <container> - Restart a container
/stop <container> - Stop a container
/start <container> - Start a container

ℹ️ *Info*
/whoami - Get your Telegram user ID
/uptime - Show system uptime
/help - Show this message
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
    await update.message.reply_text(msg, parse_mode='Markdown')

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check status of all configured services"""
    await update.message.reply_text("🔍 Checking services...")
    
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
    
    await update.message.reply_text(status_msg, parse_mode='Markdown')

@restricted
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping a specific host"""
    if not context.args:
        await update.message.reply_text("Usage: /ping <host>")
        return
    
    host = context.args[0]
    await update.message.reply_text(f"🏓 Pinging {host}...")
    
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
            
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text(f"⏱️ Ping timeout for {host}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Ping error: {str(e)}")

@restricted
async def docker_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all running Docker containers"""
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        containers = client.containers.list(all=False)
        
        if not containers:
            await update.message.reply_text("No running containers found")
            return
        
        msg = f"*Running Containers ({len(containers)}):*\n\n"
        
        for container in containers:
            status_emoji = "🟢" if container.status == "running" else "🟡"
            msg += f"{status_emoji} `{container.name}`\n"
            msg += f"   Status: {container.status}\n"
            image_tag = container.image.tags[0] if container.image.tags else container.attrs.get('Config', {}).get('Image', 'N/A')
            msg += f"   Image: {escape_markdown(image_tag)}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error accessing Docker: {str(e)}")
        logger.error(f"Docker error: {str(e)}")

@restricted
async def container_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get detailed info about a specific container"""
    if not context.args:
        await update.message.reply_text("Usage: /container <name>")
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
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except docker.errors.NotFound:
        await update.message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Container details error: {str(e)}")

@restricted
async def restart_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart a Docker container"""
    if not context.args:
        await update.message.reply_text("Usage: /restart <container_name>")
        return
    
    container_name = context.args[0]
    await update.message.reply_text(f"🔄 Restarting {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.restart()
        
        await update.message.reply_text(f"✅ Container {container_name} restarted successfully")
        
    except docker.errors.NotFound:
        await update.message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Restart error: {str(e)}")

@restricted
async def stop_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop a Docker container"""
    if not context.args:
        await update.message.reply_text("Usage: /stop <container_name>")
        return
    
    container_name = context.args[0]
    await update.message.reply_text(f"🛑 Stopping {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.stop()
        
        await update.message.reply_text(f"✅ Container {container_name} stopped")
        
    except docker.errors.NotFound:
        await update.message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Stop error: {str(e)}")

@restricted
async def start_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a Docker container"""
    if not context.args:
        await update.message.reply_text("Usage: /start <container_name>")
        return
    
    container_name = context.args[0]
    await update.message.reply_text(f"▶️ Starting {container_name}...")
    
    try:
        client = docker.DockerClient(base_url=DOCKER_HOST)
        container = client.containers.get(container_name)
        container.start()
        
        await update.message.reply_text(f"✅ Container {container_name} started")
        
    except docker.errors.NotFound:
        await update.message.reply_text(f"❌ Container '{container_name}' not found")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
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
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Uptime error: {str(e)}")

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
                    await update.message.reply_text(
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
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
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

    # Start polling
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()