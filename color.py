import asyncio
import logging
import sqlite3
import json
import random
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import Counter, deque
import statistics
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ChatMemberHandler
)
from telegram.constants import ParseMode

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8735707765:AAEliXQ5P89rT-Q0EFSxTZmrc77yPWcx7nY"  # @BotFather se token yahan paste karo

# Admin IDs (Jo bot ko control karenge)
ADMIN_IDS = [8179218740]  # Apna Telegram ID daalo

# API URL
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

# Database
DB_NAME = "jalwa_bot.db"

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.init_db()
    
    def get_conn(self):
        return sqlite3.connect(DB_NAME)
    
    def init_db(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TEXT,
                is_verified INTEGER DEFAULT 0,
                total_predictions INTEGER DEFAULT 0,
                correct_predictions INTEGER DEFAULT 0,
                last_prediction_period TEXT
            )
        ''')
        
        # Required channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                channel_username TEXT,
                channel_name TEXT,
                added_by INTEGER,
                added_date TEXT
            )
        ''')
        
        # Current prediction (SAME FOR ALL USERS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS current_prediction (
                id INTEGER PRIMARY KEY,
                period TEXT,
                prediction TEXT,
                confidence REAL,
                timestamp TEXT
            )
        ''')
        
        # Prediction history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT,
                prediction TEXT,
                confidence REAL,
                actual_result TEXT,
                is_correct INTEGER,
                timestamp TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # User methods
    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = None):
        conn = self.get_conn()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, joined_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def verify_user(self, user_id: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_verified = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def is_verified(self, user_id: int) -> bool:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT is_verified FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] == 1 if row else False
    
    def update_prediction_stats(self, user_id: int, period: str, is_correct: bool):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET total_predictions = total_predictions + 1,
                correct_predictions = correct_predictions + ?,
                last_prediction_period = ?
            WHERE user_id = ?
        ''', (1 if is_correct else 0, period, user_id))
        conn.commit()
        conn.close()
    
    def get_user_stats(self, user_id: int) -> Dict:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT total_predictions, correct_predictions FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            total, correct = row
            accuracy = (correct / total * 100) if total > 0 else 0
            return {'total': total, 'correct': correct, 'accuracy': accuracy}
        return {'total': 0, 'correct': 0, 'accuracy': 0}
    
    # Channel methods
    def add_channel(self, channel_id: str, username: str, name: str, admin_id: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_name, added_by, added_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (channel_id, username, name, admin_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def remove_channel(self, channel_id: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
        conn.commit()
        conn.close()
    
    def get_channels(self) -> List[Dict]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT channel_id, channel_username, channel_name FROM channels')
        rows = cursor.fetchall()
        conn.close()
        return [{'id': r[0], 'username': r[1], 'name': r[2]} for r in rows]
    
    # Prediction methods (GLOBAL - same for all users)
    def set_current_prediction(self, period: str, prediction: str, confidence: float):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM current_prediction')
        cursor.execute('''
            INSERT INTO current_prediction (id, period, prediction, confidence, timestamp)
            VALUES (1, ?, ?, ?, ?)
        ''', (period, prediction, confidence, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def get_current_prediction(self) -> Optional[Dict]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT period, prediction, confidence FROM current_prediction WHERE id = 1')
        row = cursor.fetchone()
        conn.close()
        if row:
            return {'period': row[0], 'prediction': row[1], 'confidence': row[2]}
        return None
    
    def add_prediction_history(self, period: str, prediction: str, confidence: float, actual: str = None, correct: int = None):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO prediction_history (period, prediction, confidence, actual_result, is_correct, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (period, prediction, confidence, actual, correct, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def update_prediction_result(self, period: str, actual: str, is_correct: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE prediction_history 
            SET actual_result = ?, is_correct = ?
            WHERE period = ?
        ''', (actual, is_correct, period))
        conn.commit()
        conn.close()

# ==================== PREDICTION ENGINE ====================
class PredictionEngine:
    def __init__(self, db: Database):
        self.db = db
        self.last_issue = None
    
    async def fetch_data(self) -> Optional[List[Dict]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and data.get("data") and data["data"].get("list"):
                            return data["data"]["list"]
        except Exception as e:
            logger.error(f"API error: {e}")
        return None
    
    def analyze_patterns(self, numbers: List[int]) -> Tuple[str, float]:
        if len(numbers) < 10:
            return "BIG" if random.random() > 0.5 else "SMALL", 50.0
        
        binary = [1 if n > 4 else 0 for n in numbers]
        
        # Run-length analysis
        runs = []
        curr_run = 1
        curr_val = binary[0]
        for i in range(1, len(binary)):
            if binary[i] == curr_val:
                curr_run += 1
            else:
                runs.append((curr_val, curr_run))
                curr_val = binary[i]
                curr_run = 1
        runs.append((curr_val, curr_run))
        
        last_val, last_len = runs[-1]
        
        # Mean reversion
        big_ratio = sum(binary[:20]) / min(20, len(binary))
        
        predictions = []
        confidences = []
        
        # Strategy 1: Run-length
        if last_len >= 3:
            predictions.append(1 - last_val)
            confidences.append(min(85, 55 + last_len * 5))
        else:
            predictions.append(last_val)
            confidences.append(55)
        
        # Strategy 2: Mean reversion
        if big_ratio > 0.65:
            predictions.append(0)
            confidences.append(70)
        elif big_ratio < 0.35:
            predictions.append(1)
            confidences.append(70)
        
        # Strategy 3: 2-step follow
        if len(binary) >= 3:
            if binary[0] == binary[1]:
                predictions.append(1 - binary[0])
                confidences.append(65)
            else:
                predictions.append(binary[0])
                confidences.append(60)
        
        # Ensemble voting
        vote_big = sum(c for p, c in zip(predictions, confidences) if p == 1)
        vote_small = sum(c for p, c in zip(predictions, confidences) if p == 0)
        
        total = vote_big + vote_small
        if total == 0:
            return "BIG" if random.random() > 0.5 else "SMALL", 50.0
        
        if vote_big > vote_small:
            confidence = min(85, (vote_big / total) * 100)
            return "BIG", confidence
        else:
            confidence = min(85, (vote_small / total) * 100)
            return "SMALL", confidence
    
    async def update_prediction(self):
        """Update global prediction for current period"""
        data = await self.fetch_data()
        if not data:
            return
        
        numbers = []
        for item in data:
            try:
                num = int(item.get('number', 0))
                if 0 <= num <= 9:
                    numbers.append(num)
            except:
                pass
        
        if len(numbers) < 5:
            return
        
        prediction, confidence = self.analyze_patterns(numbers)
        
        latest_issue = data[0].get('issueNumber', '')
        if latest_issue:
            next_issue = str(int(latest_issue) + 1)
            
            # Check if new period
            if next_issue != self.last_issue:
                self.last_issue = next_issue
                
                # Save to database
                self.db.set_current_prediction(next_issue, prediction, confidence)
                self.db.add_prediction_history(next_issue, prediction, confidence)
                
                logger.info(f"New prediction for period {next_issue}: {prediction} ({confidence:.1f}%)")
                
                return next_issue, prediction, confidence
        
        return None, None, None
    
    async def check_and_update_result(self):
        """Check last period result and update accuracy"""
        data = await self.fetch_data()
        if not data:
            return
        
        latest = data[0]
        latest_issue = latest.get('issueNumber', '')
        latest_num = int(latest.get('number', 0))
        actual = "BIG" if latest_num > 4 else "SMALL"
        
        # Check if we have prediction for this period
        conn = self.db.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT prediction, is_correct FROM prediction_history WHERE period = ?', (latest_issue,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[1] is None:
            is_correct = 1 if row[0] == actual else 0
            self.db.update_prediction_result(latest_issue, actual, is_correct)
            logger.info(f"Period {latest_issue} result: {actual} | Prediction: {row[0]} | {'✅' if is_correct else '❌'}")
            return row[0], actual, is_correct
        
        return None, None, None

# ==================== BOT HANDLERS ====================
class JalwaBot:
    def __init__(self, token: str):
        self.token = token
        self.db = Database()
        self.engine = PredictionEngine(self.db)
        self.app = None
        self.prediction_update_task = None
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS
    
    async def start(self):
        self.app = Application.builder().token(self.token).build()
        
        # Set commands
        await self.app.bot.set_my_commands([
            BotCommand("start", "🚀 Start the bot"),
            BotCommand("predict", "🎯 Get current prediction"),
            BotCommand("stats", "📊 Your statistics"),
            BotCommand("channel", "📢 Required channels"),
            BotCommand("help", "❓ Help"),
        ])
        
        # Admin commands
        if self.is_admin:
            await self.app.bot.set_my_commands([
                BotCommand("addchannel", "➕ Add required channel"),
                BotCommand("removechannel", "➖ Remove channel"),
                BotCommand("channels", "📋 List channels"),
                BotCommand("broadcast", "📢 Broadcast message"),
                BotCommand("status", "📊 Bot status"),
            ])
        
        # Handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("predict", self.predict_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("channel", self.channel_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        
        # Admin handlers
        self.app.add_handler(CommandHandler("addchannel", self.add_channel_command))
        self.app.add_handler(CommandHandler("removechannel", self.remove_channel_command))
        self.app.add_handler(CommandHandler("channels", self.list_channels_command))
        self.app.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        
        # Callback handler
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        # Start background tasks
        asyncio.create_task(self.prediction_updater())
        asyncio.create_task(self.result_checker())
        
        logger.info("Bot started!")
    
    async def check_membership(self, user_id: int) -> Tuple[bool, List[Dict]]:
        channels = self.db.get_channels()
        if not channels:
            return True, []
        
        not_joined = []
        for channel in channels:
            try:
                member = await self.app.bot.get_chat_member(channel['id'], user_id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(channel)
            except:
                not_joined.append(channel)
        
        return len(not_joined) == 0, not_joined
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        
        # Check if already verified
        if self.db.is_verified(user.id):
            await self.show_main_menu(update)
            return
        
        # Show verification required
        channels = self.db.get_channels()
        
        if not channels:
            # No channels required, auto verify
            self.db.verify_user(user.id)
            await self.show_main_menu(update)
            return
        
        keyboard = []
        for ch in channels:
            username = ch['username'].replace('@', '')
            keyboard.append([InlineKeyboardButton(f"📢 Join {ch['name']}", url=f"https://t.me/{username}")])
        
        keyboard.append([InlineKeyboardButton("✅ I've Joined - Verify Me", callback_data="verify")])
        
        await update.message.reply_text(
            f"🔐 *VERIFICATION REQUIRED*\n\n"
            f"Welcome {user.first_name}! 👋\n\n"
            f"Please join the following channel(s) to use this bot:\n\n"
            f"After joining, click the verify button.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_menu(self, update: Update):
        """Show main menu after verification"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Get Prediction", callback_data="get_prediction")],
            [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
            [InlineKeyboardButton("📢 Required Channels", callback_data="show_channels")],
            [InlineKeyboardButton("❓ Help", callback_data="help")],
        ])
        
        msg = """
🎯 *JALWA AI PREDICTION BOT* 🎯

✅ *Verification Complete!*

🔥 *Features:*
• Real-time AI predictions
• Same prediction for all users
• Track your accuracy
• 24/7 automated system

📌 *Tap Get Prediction to start!*
        """
        
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            else:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        # Check verification
        if not self.db.is_verified(user.id):
            await self.start_command(update, context)
            return
        
        # Get current global prediction
        prediction_data = self.db.get_current_prediction()
        
        if not prediction_data:
            await update.message.reply_text(
                "🔄 *Loading prediction...*\n\nPlease wait a moment and try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        period = prediction_data['period']
        prediction = prediction_data['prediction']
        confidence = prediction_data['confidence']
        
        emoji = "🔴" if prediction == "SMALL" else "🔵"
        conf_emoji = "🔥🔥🔥" if confidence >= 80 else "🔥🔥" if confidence >= 65 else "🔥"
        
        message = f"""
🎯 *JALWA AI PREDICTION* 🎯

📌 *Period:* `{period}`
{emoji} *Prediction:* `{prediction}`
📈 *Confidence:* `{confidence:.1f}%` {conf_emoji}

⚠️ *Note:* Same prediction for all users this period

🕐 Next update in 60 seconds...
        """
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not self.db.is_verified(user.id):
            await self.start_command(update, context)
            return
        
        stats = self.db.get_user_stats(user.id)
        
        message = f"""
📊 *YOUR STATISTICS* 📊

👤 *User:* {user.first_name}

🎯 *Total Predictions:* {stats['total']}
✅ *Correct Predictions:* {stats['correct']}
📈 *Accuracy:* {stats['accuracy']:.1f}%

🏆 *Status:* {'Premium' if stats['accuracy'] > 60 else 'Active'}

Keep using for better accuracy!
        """
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not self.db.is_verified(user.id):
            await self.start_command(update, context)
            return
        
        channels = self.db.get_channels()
        
        if not channels:
            await update.message.reply_text("📢 No required channels configured.")
            return
        
        message = "📢 *REQUIRED CHANNELS*\n\n"
        for ch in channels:
            message += f"• {ch['name']}\n  👉 @{ch['username'].replace('@', '')}\n\n"
        
        message += "⚠️ You must stay joined to use this bot!"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
❓ *JALWA AI HELP* ❓

*Commands:*
/predict - Get current prediction
/stats - View your statistics
/channel - List required channels
/start - Restart the bot

*How it works:*
1. Join required channels
2. Verify your account
3. Get predictions instantly

*Note:* All users get the SAME prediction for each period!

*Support:* @SIDIKI_MUSTAFA_92
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    # ==================== ADMIN COMMANDS ====================
    
    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only!")
            return
        
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /addchannel @username ChannelName\n"
                "Example: /addchannel @jalwa_channel JALWA Channel"
            )
            return
        
        username = args[0]
        name = ' '.join(args[1:])
        
        try:
            chat = await self.app.bot.get_chat(username)
            channel_id = str(chat.id)
            
            self.db.add_channel(channel_id, username, name, update.effective_user.id)
            
            await update.message.reply_text(
                f"✅ Channel added!\n\n"
                f"Name: {name}\n"
                f"Username: {username}\n"
                f"Users must now join this channel to use the bot."
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def remove_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only!")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /removechannel @username")
            return
        
        username = args[0]
        channels = self.db.get_channels()
        
        for ch in channels:
            if ch['username'] == username:
                self.db.remove_channel(ch['id'])
                await update.message.reply_text(f"✅ Channel {username} removed!")
                return
        
        await update.message.reply_text(f"❌ Channel {username} not found!")
    
    async def list_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only!")
            return
        
        channels = self.db.get_channels()
        
        if not channels:
            await update.message.reply_text("No channels configured.")
            return
        
        message = "📋 *CONFIGURED CHANNELS*\n\n"
        for i, ch in enumerate(channels, 1):
            message += f"{i}. {ch['name']}\n   @{ch['username'].replace('@', '')}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only!")
            return
        
        message = ' '.join(context.args)
        if not message:
            await update.message.reply_text("Usage: /broadcast Your message here")
            return
        
        conn = self.db.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        
        success = 0
        failed = 0
        
        status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
        
        for user in users:
            try:
                await self.app.bot.send_message(user[0], message, parse_mode=ParseMode.MARKDOWN)
                success += 1
            except:
                failed += 1
            await asyncio.sleep(0.05)
        
        await status_msg.edit_text(f"✅ Broadcast complete!\n\nSent: {success}\nFailed: {failed}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only!")
            return
        
        conn = self.db.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_verified = 1')
        verified_users = cursor.fetchone()[0]
        conn.close()
        
        prediction = self.db.get_current_prediction()
        
        status_text = f"""
📊 *BOT STATUS*

👥 *Total Users:* {total_users}
✅ *Verified Users:* {verified_users}

🎯 *Current Prediction:*
Period: {prediction['period'] if prediction else 'N/A'}
Prediction: {prediction['prediction'] if prediction else 'N/A'}
Confidence: {prediction['confidence']:.1f}% if prediction else 'N/A'

🤖 *Bot Status:* 🟢 Running
        """
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    
    # ==================== CALLBACK HANDLER ====================
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        if data == "verify":
            # Check membership
            is_member, not_joined = await self.check_membership(user.id)
            
            if is_member:
                self.db.verify_user(user.id)
                await query.message.edit_text(
                    "✅ *VERIFICATION SUCCESSFUL!*\n\n"
                    "You can now use the bot!",
                    parse_mode=ParseMode.MARKDOWN
                )
                await self.show_main_menu(update)
            else:
                # Show which channels still not joined
                keyboard = []
                for ch in not_joined:
                    username = ch['username'].replace('@', '')
                    keyboard.append([InlineKeyboardButton(f"📢 Join {ch['name']}", url=f"https://t.me/{username}")])
                
                keyboard.append([InlineKeyboardButton("✅ Try Again", callback_data="verify")])
                
                await query.message.edit_text(
                    "❌ *VERIFICATION FAILED*\n\n"
                    "You haven't joined all required channels yet!\n\n"
                    "Please join the following channels:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
        elif data == "get_prediction":
            prediction_data = self.db.get_current_prediction()
            
            if not prediction_data:
                await query.message.edit_text("🔄 Loading prediction... Please wait and try again.")
                return
            
            period = prediction_data['period']
            prediction = prediction_data['prediction']
            confidence = prediction_data['confidence']
            
            emoji = "🔴" if prediction == "SMALL" else "🔵"
            conf_emoji = "🔥🔥🔥" if confidence >= 80 else "🔥🔥" if confidence >= 65 else "🔥"
            
            message = f"""
🎯 *JALWA AI PREDICTION* 🎯

📌 *Period:* `{period}`
{emoji} *Prediction:* `{prediction}`
📈 *Confidence:* `{confidence:.1f}%` {conf_emoji}

⚠️ *Note:* Same prediction for all users this period

🕐 Next update in 60 seconds...
            """
            
            await query.message.edit_text(message, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(3)
            await self.show_main_menu(update)
        
        elif data == "my_stats":
            stats = self.db.get_user_stats(user.id)
            
            message = f"""
📊 *YOUR STATISTICS* 📊

👤 *User:* {user.first_name}

🎯 *Total Predictions:* {stats['total']}
✅ *Correct Predictions:* {stats['correct']}
📈 *Accuracy:* {stats['accuracy']:.1f}%

🏆 *Status:* {'Premium' if stats['accuracy'] > 60 else 'Active'}
            """
            
            await query.message.edit_text(message, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(3)
            await self.show_main_menu(update)
        
        elif data == "show_channels":
            channels = self.db.get_channels()
            
            if not channels:
                await query.message.edit_text("📢 No required channels configured.")
                await asyncio.sleep(2)
                await self.show_main_menu(update)
                return
            
            message = "📢 *REQUIRED CHANNELS*\n\n"
            for ch in channels:
                message += f"• {ch['name']}\n  👉 @{ch['username'].replace('@', '')}\n\n"
            
            message += "⚠️ You must stay joined to use this bot!"
            
            await query.message.edit_text(message, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(3)
            await self.show_main_menu(update)
        
        elif data == "help":
            help_text = """
❓ *JALWA AI HELP* ❓

*Commands:*
/predict - Get current prediction
/stats - View your statistics
/channel - List required channels

*How it works:*
1. Join required channels
2. Verify your account
3. Get predictions instantly

*Note:* All users get the SAME prediction!
            """
            
            await query.message.edit_text(help_text, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(3)
            await self.show_main_menu(update)
    
    # ==================== BACKGROUND TASKS ====================
    
    async def prediction_updater(self):
        """Update prediction every 3 seconds"""
        while True:
            try:
                period, prediction, confidence = await self.engine.update_prediction()
                
                # If new prediction available, send to all verified users
                if period and prediction:
                    emoji = "🔴" if prediction == "SMALL" else "🔵"
                    conf_emoji = "🔥🔥🔥" if confidence >= 80 else "🔥🔥" if confidence >= 65 else "🔥"
                    
                    message = f"""
🎯 *NEW PREDICTION AVAILABLE* 🎯

📌 *Period:* `{period}`
{emoji} *Prediction:* `{prediction}`
📈 *Confidence:* `{confidence:.1f}%` {conf_emoji}

Use /predict to get latest prediction!
                    """
                    
                    # Send to all verified users
                    conn = self.db.get_conn()
                    cursor = conn.cursor()
                    cursor.execute('SELECT user_id FROM users WHERE is_verified = 1')
                    users = cursor.fetchall()
                    conn.close()
                    
                    for user in users:
                        try:
                            await self.app.bot.send_message(user[0], message, parse_mode=ParseMode.MARKDOWN)
                            await asyncio.sleep(0.05)
                        except:
                            pass
                    
                    logger.info(f"New prediction broadcasted: {period} - {prediction}")
                
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Prediction updater error: {e}")
                await asyncio.sleep(10)
    
    async def result_checker(self):
        """Check results and update user stats"""
        while True:
            try:
                predicted, actual, is_correct = await self.engine.check_and_update_result()
                
                if predicted and is_correct is not None:
                    # Update all users who requested prediction for this period
                    # For now, we just log it
                    logger.info(f"Result updated: {actual} | Correct: {is_correct}")
                    
                    # Optional: Send result to users
                    result_emoji = "✅" if is_correct else "❌"
                    result_text = "WIN" if is_correct else "LOSS"
                    
                    message = f"""
📊 *PERIOD RESULT* 📊

Period ended!
Prediction: {predicted}
Actual: {actual}
Result: {result_emoji} {result_text}
                    """
                    
                    conn = self.db.get_conn()
                    cursor = conn.cursor()
                    cursor.execute('SELECT user_id FROM users WHERE is_verified = 1')
                    users = cursor.fetchall()
                    conn.close()
                    
                    for user in users:
                        try:
                            await self.app.bot.send_message(user[0], message, parse_mode=ParseMode.MARKDOWN)
                            await asyncio.sleep(0.05)
                        except:
                            pass
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Result checker error: {e}")
                await asyncio.sleep(10)

# ==================== MAIN ====================
async def main():
    bot = JalwaBot(BOT_TOKEN)
    await bot.start()
    
    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════╗
║     JALWA AI TELEGRAM BOT v5.0            ║
║     Premium Prediction Bot                ║
║     Global Predictions System             ║
║     Made by @SIDIKI_MUSTAFA_92            ║
╚════════════════════════════════════════════╝
    """)
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your BOT_TOKEN first!")
        print("Get token from @BotFather\n")
        print("Edit the file and change BOT_TOKEN variable")
    else:
        print("✅ Bot starting...")
        print("Press Ctrl+C to stop\n")
        asyncio.run(main())
