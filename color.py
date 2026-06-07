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
BOT_TOKEN = "8735707765:AAEliXQ5P89rT-Q0EFSxTZmrc77yPWcx7nY"
ADMIN_IDS = [8179218740]  # Apna ID daalo

API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
DB_NAME = "jalwa_bot.db"

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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                channel_username TEXT,
                channel_name TEXT,
                added_by INTEGER,
                added_date TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS current_prediction (
                id INTEGER PRIMARY KEY,
                period TEXT,
                prediction TEXT,
                confidence REAL,
                timestamp TEXT
            )
        ''')
        
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
        logger.info("Database initialized")
    
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
            return ("BIG" if random.random() > 0.5 else "SMALL", 50.0)
        
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
            return ("BIG" if random.random() > 0.5 else "SMALL", 50.0)
        
        if vote_big > vote_small:
            confidence = min(85, (vote_big / total) * 100)
            return ("BIG", confidence)
        else:
            confidence = min(85, (vote_small / total) * 100)
            return ("SMALL", confidence)
    
    async def update_prediction(self):
        """Update global prediction for current period"""
        try:
            data = await self.fetch_data()
            if not data:
                return None, None, None
            
            numbers = []
            for item in data:
                try:
                    num = int(item.get('number', 0))
                    if 0 <= num <= 9:
                        numbers.append(num)
                except:
                    pass
            
            if len(numbers) < 5:
                return None, None, None
            
            prediction, confidence = self.analyze_patterns(numbers)
            
            latest_issue = data[0].get('issueNumber', '')
            if latest_issue:
                next_issue = str(int(latest_issue) + 1)
                
                if next_issue != self.last_issue:
                    self.last_issue = next_issue
                    self.db.set_current_prediction(next_issue, prediction, confidence)
                    logger.info(f"New prediction: {next_issue} - {prediction} ({confidence:.1f}%)")
                    return next_issue, prediction, confidence
            
            return None, None, None
        except Exception as e:
            logger.error(f"Update prediction error: {e}")
            return None, None, None

# ==================== BOT HANDLERS ====================
class JalwaBot:
    def __init__(self, token: str):
        self.token = token
        self.db = Database()
        self.engine = PredictionEngine(self.db)
        self.app = None
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS
    
    async def start(self):
        self.app = Application.builder().token(self.token).build()
        
        # Set commands
        await self.app.bot.set_my_commands([
            BotCommand("start", "🚀 Start the bot"),
            BotCommand("predict", "🎯 Get prediction"),
            BotCommand("stats", "📊 Your statistics"),
            BotCommand("channel", "📢 Required channels"),
            BotCommand("help", "❓ Help"),
        ])
        
        # Handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("predict", self.predict_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("channel", self.channel_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        # Start background task
        asyncio.create_task(self.prediction_updater())
        
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
        
        if self.db.is_verified(user.id):
            await self.show_main_menu(update)
            return
        
        channels = self.db.get_channels()
        
        if not channels:
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
            f"Please join the channel(s) below and click verify:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_menu(self, update: Update):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Get Prediction", callback_data="get_prediction")],
            [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
            [InlineKeyboardButton("📢 Required Channels", callback_data="show_channels")],
        ])
        
        msg = """
🎯 *JALWA AI PREDICTION BOT* 🎯

✅ *Verification Complete!*

🔥 *Same prediction for ALL users!*

📌 *Tap Get Prediction to start!*
        """
        
        if update.callback_query:
            await update.callback_query.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not self.db.is_verified(user.id):
            await self.start_command(update, context)
            return
        
        pred_data = self.db.get_current_prediction()
        
        if not pred_data:
            await update.message.reply_text("🔄 Loading prediction... Please wait!")
            return
        
        emoji = "🔴" if pred_data['prediction'] == "SMALL" else "🔵"
        
        await update.message.reply_text(
            f"🎯 *JALWA AI PREDICTION* 🎯\n\n"
            f"📌 *Period:* `{pred_data['period']}`\n"
            f"{emoji} *Prediction:* `{pred_data['prediction']}`\n"
            f"📈 *Confidence:* `{pred_data['confidence']:.1f}%`\n\n"
            f"⚠️ *Same prediction for all users!*",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"📊 *Your Stats*\n\n"
            f"👤 User: {user.first_name}\n"
            f"✅ Verified: Yes\n\n"
            f"Use /predict to get predictions!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        channels = self.db.get_channels()
        if not channels:
            await update.message.reply_text("No required channels.")
            return
        
        msg = "📢 *Required Channels*\n\n"
        for ch in channels:
            msg += f"• {ch['name']}\n  👉 @{ch['username'].replace('@', '')}\n\n"
        
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "❓ *JALWA AI HELP*\n\n"
            "/start - Start bot\n"
            "/predict - Get prediction\n"
            "/stats - Your stats\n"
            "/channel - Required channels\n\n"
            "Made by @SIDIKI_MUSTAFA_92",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = query.from_user
        
        if query.data == "verify":
            is_member, not_joined = await self.check_membership(user.id)
            
            if is_member:
                self.db.verify_user(user.id)
                await query.message.edit_text("✅ Verified! Redirecting...")
                await self.show_main_menu(update)
            else:
                keyboard = []
                for ch in not_joined:
                    username = ch['username'].replace('@', '')
                    keyboard.append([InlineKeyboardButton(f"📢 Join {ch['name']}", url=f"https://t.me/{username}")])
                keyboard.append([InlineKeyboardButton("✅ Try Again", callback_data="verify")])
                
                await query.message.edit_text(
                    "❌ Please join all channels first!",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
        elif query.data == "get_prediction":
            pred_data = self.db.get_current_prediction()
            if pred_data:
                emoji = "🔴" if pred_data['prediction'] == "SMALL" else "🔵"
                await query.message.edit_text(
                    f"🎯 *Prediction*\n\n"
                    f"Period: `{pred_data['period']}`\n"
                    f"{emoji} {pred_data['prediction']}\n"
                    f"Confidence: {pred_data['confidence']:.1f}%",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.message.edit_text("Loading...")
            await asyncio.sleep(2)
            await self.show_main_menu(update)
        
        elif query.data == "my_stats":
            await query.message.edit_text("📊 *Stats Coming Soon*", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(2)
            await self.show_main_menu(update)
        
        elif query.data == "show_channels":
            channels = self.db.get_channels()
            if channels:
                msg = "📢 *Required Channels*\n\n"
                for ch in channels:
                    msg += f"• {ch['name']}\n  👉 @{ch['username'].replace('@', '')}\n\n"
                await query.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.message.edit_text("No channels configured.")
            await asyncio.sleep(2)
            await self.show_main_menu(update)
    
    async def prediction_updater(self):
        """Update prediction every 3 seconds"""
        while True:
            try:
                period, prediction, confidence = await self.engine.update_prediction()
                
                if period and prediction:
                    # Send to all verified users
                    conn = self.db.get_conn()
                    cursor = conn.cursor()
                    cursor.execute('SELECT user_id FROM users WHERE is_verified = 1')
                    users = cursor.fetchall()
                    conn.close()
                    
                    emoji = "🔴" if prediction == "SMALL" else "🔵"
                    msg = f"🎯 *NEW PREDICTION*\n\nPeriod: `{period}`\n{emoji} {prediction}\nConfidence: {confidence:.1f}%"
                    
                    for user in users:
                        try:
                            await self.app.bot.send_message(user[0], msg, parse_mode=ParseMode.MARKDOWN)
                            await asyncio.sleep(0.05)
                        except:
                            pass
                    
                    logger.info(f"Broadcasted: {period} - {prediction}")
                
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Updater error: {e}")
                await asyncio.sleep(10)

# ==================== MAIN ====================
async def main():
    bot = JalwaBot(BOT_TOKEN)
    await bot.start()
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════╗
║     JALWA AI TELEGRAM BOT v5.0            ║
║     Fixed & Ready to Run!                 ║
╚════════════════════════════════════════════╝
    """)
    asyncio.run(main())
