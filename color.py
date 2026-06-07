#!/usr/bin/env python3
"""
⚡ JALWA AI - Telegram Bot ⚡
Same period me same prediction deta hai sabko!
"""

import asyncio
import logging
import math
import time
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "8735707765:AAEliXQ5P89rT-Q0EFSxTZmrc77yPWcx7nY"  # @BotFather se token lo
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== CACHE ==========
# Same period me same prediction mile isliye cache
prediction_cache = {
    "period": None,
    "prediction": None,
    "confidence": None,
    "signal": None,
    "timestamp": 0,
    "next_period": None,
    "raw_numbers": []
}

# ========== PYTHON LOGIC (Same as HTML version) ==========

class StatisticalArbiter:
    def predict_with_statistics(self, numbers):
        if len(numbers) < 15:
            return {"prediction": 0, "confidence": 0.5, "signal": "insufficient_data"}

        recent = numbers[:30]
        binary_seq = [1 if x > 4 else 0 for x in recent]

        predictions, weights, signals = [], [], []

        # Mean reversion
        big_ratio = sum(binary_seq) / len(binary_seq)
        threshold = 0.2

        if abs(big_ratio - 0.5) > threshold:
            if big_ratio > 0.5 + threshold:
                predictions.append(0)
                signals.append("mean_reversion_high")
            else:
                predictions.append(1)
                signals.append("mean_reversion_low")
            weights.append(0.35 * abs(big_ratio - 0.5) * 2)

        # Momentum
        if len(binary_seq) >= 10:
            m_short = (sum(binary_seq[0:3]) / 3) - (sum(binary_seq[3:6]) / 3)
            m_long = (sum(binary_seq[0:6]) / 6) - (sum(binary_seq[6:10]) / 4)

            if m_short * m_long > 0:
                predictions.append(1 if m_short > 0 else 0)
                signals.append("confirmed_momentum")
                w = (abs(m_short) + abs(m_long)) / 2
                weights.append(0.25 * w)

        # Volatility
        changes = []
        for i in range(len(recent) - 1):
            denom = max(recent[i], recent[i+1])
            if denom != 0:
                changes.append(abs(recent[i] - recent[i+1]) / denom)

        volatility = (sum(changes) / len(changes) * 100) if len(changes) >= 2 else 0
        vol_factor = min(volatility / 3, 1.5)

        if volatility > 2.5:
            predictions.append(binary_seq[0])
            signals.append("high_vol_continuation")
            weights.append(0.15 * vol_factor)
        else:
            predictions.append(1 - binary_seq[0])
            signals.append("low_vol_reversion")
            weights.append(0.25 * (1 / (vol_factor or 0.2)))

        if not predictions:
            return {"prediction": 0, "confidence": 0.5, "signal": "no_signal"}

        vote_big, vote_small = 0, 0
        for i, p in enumerate(predictions):
            if p == 1:
                vote_big += weights[i]
            else:
                vote_small += weights[i]

        total = vote_big + vote_small
        if total == 0:
            return {"prediction": 0, "confidence": 0.5, "signal": "no_confidence"}

        if abs(vote_big - vote_small) / total < 0.1:
            return {"prediction": 0, "confidence": 0.5, "signal": "neutral"}

        pred = 1 if vote_big > vote_small else 0
        conf = max(vote_big, vote_small) / total
        conf = min(0.85, max(0.55, conf))

        return {
            "prediction": pred,
            "confidence": conf,
            "signal": signals[0] if signals else "statistical"
        }


class AdvancedPatternAnalyzer:
    def analyze(self, sequence):
        if len(sequence) < 10:
            return {}

        binary = [1 if x > 4 else 0 for x in sequence]

        return {
            "ngram": self._ngram(binary),
            "markov": self._markov(binary),
            "run_length": self._run_length(binary)
        }

    def _ngram(self, seq, n=4):
        if len(seq) < n * 2:
            return {}

        last_ngram = seq[-n:]
        predictions = []

        for i in range(len(seq) - n):
            if seq[i:i+n] == last_ngram and i + n < len(seq):
                predictions.append(seq[i + n])

        if not predictions:
            return {}

        from collections import Counter
        counter = Counter(predictions)
        most_common = counter.most_common(2)

        if len(most_common) >= 2 and most_common[0][1] > most_common[1][1] * 1.5:
            return {
                "prediction": most_common[0][0],
                "confidence": most_common[0][1] / len(predictions),
                "occurrences": len(predictions)
            }
        elif len(most_common) == 1:
            return {
                "prediction": most_common[0][0],
                "confidence": most_common[0][1] / len(predictions),
                "occurrences": len(predictions)
            }
        return {}

    def _markov(self, seq):
        if len(seq) < 15:
            return {}

        transitions = {}
        for i in range(len(seq) - 2):
            state = (seq[i], seq[i+1])
            nxt = seq[i+2]
            if state not in transitions:
                transitions[state] = {}
            transitions[state][nxt] = transitions[state].get(nxt, 0) + 1

        last_state = (seq[-2], seq[-1])
        if last_state not in transitions:
            return {}

        next_states = transitions[last_state]
        total = sum(next_states.values())
        if total < 3:
            return {}

        most_likely = max(next_states.items(), key=lambda x: x[1])
        if most_likely[1] / total > 0.6:
            return {
                "prediction": most_likely[0],
                "confidence": most_likely[1] / total,
                "total": total
            }
        return {}

    def _run_length(self, seq):
        if not seq:
            return {}

        runs = []
        curr_val, curr_len = seq[0], 1
        for i in range(1, len(seq)):
            if seq[i] == curr_val:
                curr_len += 1
            else:
                runs.append((curr_val, curr_len))
                curr_val, curr_len = seq[i], 1
        runs.append((curr_val, curr_len))

        big_runs = [r[1] for r in runs if r[0] == 1]
        small_runs = [r[1] for r in runs if r[0] == 0]

        if not big_runs or not small_runs:
            return {}

        avg_big = sum(big_runs) / len(big_runs)
        avg_small = sum(small_runs) / len(small_runs)
        last_val, last_len = runs[-1]

        if last_len >= 3:
            pred = 0 if last_val == 1 else 1
            conf = min(0.85, 0.5 + (last_len - (avg_big if last_val == 1 else avg_small)) * 0.1)
            return {"prediction": pred, "confidence": conf, "signal": "reversal"}
        else:
            pred = last_val
            conf = min(0.7, 0.5 + ((avg_big if last_val == 1 else avg_small) - last_len) * 0.05)
            return {"prediction": pred, "confidence": conf, "signal": "continuation"}


class PredictionEngine:
    def __init__(self):
        self.pattern_analyzer = AdvancedPatternAnalyzer()
        self.statistical_arbiter = StatisticalArbiter()
        self.weights = {
            "pattern": 0.40,
            "statistical": 0.35,
            "trend": 0.15,
        }

    def predict(self, numbers):
        if len(numbers) < 10:
            return {"prediction": "BIG", "confidence": 50, "signal": "insufficient_data"}

        pattern_analysis = self.pattern_analyzer.analyze(numbers)
        stat_pred = self.statistical_arbiter.predict_with_statistics(numbers)

        predictions, confidences, sources = [], [], []

        # Pattern predictions
        for source_name in ["ngram", "markov", "run_length"]:
            p = pattern_analysis.get(source_name, {})
            if p and p.get("prediction") is not None and p.get("confidence", 0) > 0.55:
                predictions.append(p["prediction"])
                confidences.append(p["confidence"] * 100)
                sources.append("pattern")

        # Statistical
        if stat_pred["confidence"] > 0.5:
            predictions.append(stat_pred["prediction"])
            confidences.append(stat_pred["confidence"] * 100)
            sources.append("statistical")

        # Trend
        trend = self._trend(numbers)
        if trend["confidence"] > 50:
            predictions.append(trend["prediction"])
            confidences.append(trend["confidence"])
            sources.append("trend")

        if len(predictions) < 2:
            import random
            p = random.randint(0, 1)
            return {
                "prediction": "BIG" if p == 1 else "SMALL",
                "confidence": 50,
                "signal": "random_fallback"
            }

        result = self._ensemble_vote(predictions, confidences, sources)
        final_conf = max(50, min(85, result["confidence"]))
        pred_str = "BIG" if result["prediction"] == 1 else "SMALL"

        return {
            "prediction": pred_str,
            "confidence": round(final_conf, 1),
            "signal": stat_pred.get("signal", "ensemble_vote")
        }

    def _trend(self, numbers):
        if len(numbers) < 8:
            return {"prediction": 0, "confidence": 45}

        binary = [1 if x > 4 else 0 for x in numbers[:15]]
        sma_short = sum(binary[0:3]) / 3
        sma_long = sum(binary[0:6]) / 6
        roc_short = sma_short - (sum(binary[3:6]) / 3)
        roc_long = sma_long - (sum(binary[6:9]) / 3)
        strength = abs(roc_short) + abs(roc_long)

        if sma_short > sma_long and roc_short > 0:
            return {"prediction": 1, "confidence": min(75, 50 + strength * 20)}
        elif sma_short < sma_long and roc_short < 0:
            return {"prediction": 0, "confidence": min(75, 50 + strength * 20)}
        else:
            return {"prediction": 1 if sma_short > 0.5 else 0, "confidence": 55}

    def _ensemble_vote(self, predictions, confidences, sources):
        vote_big, vote_small = 0, 0
        for i, p in enumerate(predictions):
            sw = self.weights.get(sources[i], 0.25)
            cw = confidences[i] / 100
            tw = sw * cw
            if p == 1:
                vote_big += tw
            else:
                vote_small += tw

        total = vote_big + vote_small
        if total == 0:
            return {"prediction": 0, "confidence": 50}

        final_pred = 1 if vote_big > vote_small else 0
        final_conf = (max(vote_big, vote_small) / total) * 100
        consensus = abs(vote_big - vote_small) / total
        if consensus > 0.3:
            final_conf *= (1 + consensus * 0.2)

        return {"prediction": final_pred, "confidence": min(85, final_conf)}


# Global engine
engine = PredictionEngine()


# ========== API FETCH ==========

async def fetch_and_predict():
    """Fetch data and generate prediction — cached per period."""
    global prediction_cache

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                json_data = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"API fetch error: {e}")
            return None

    results = json_data.get("data", {}).get("list", [])
    if not results:
        return None

    latest = results[0]
    latest_issue = latest["issueNumber"]
    next_period = str(int(latest_issue) + 1)

    # Same period me cache hit
    if prediction_cache["period"] == next_period:
        return prediction_cache

    numbers = [int(r["number"]) for r in results if 0 <= int(r["number"]) <= 9]
    pred_result = engine.predict(numbers)

    # Update cache
    prediction_cache.update({
        "period": next_period,
        "prediction": pred_result["prediction"],
        "confidence": pred_result["confidence"],
        "signal": pred_result["signal"],
        "timestamp": time.time(),
        "next_period": next_period,
        "raw_numbers": numbers[:5],
        "last_num": int(results[0]["number"]),
        "last_result": "BIG" if int(results[0]["number"]) >= 5 else "SMALL"
    })

    return prediction_cache


# ========== BOT HANDLERS ==========

def get_prediction_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 GET PREDICTION", callback_data="predict")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="predict")]
    ])


def format_prediction_message(data):
    pred = data["prediction"]
    conf = data["confidence"]
    period = data["period"]
    signal = data.get("signal", "ensemble_vote")
    last_num = data.get("last_num", "?")
    last_result = data.get("last_result", "?")

    emoji = "🟢" if pred == "BIG" else "🔴"
    bar_filled = int(conf / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    # Timer
    sec = datetime.now().second
    remaining = 60 - sec

    msg = f"""
⚡ *JALWA AI PREDICTION* ⚡

🎯 *Target Period:* `{period}`
⏱️ *Next Result In:* `{remaining}s`

━━━━━━━━━━━━━━━━━━━━
{emoji} *PREDICTION: {pred}*
━━━━━━━━━━━━━━━━━━━━

📊 *Confidence:* `{conf}%`
`{bar}` 

📈 *Signal:* `{signal}`
🔢 *Last Number:* `{last_num}` → `{last_result}`

━━━━━━━━━━━━━━━━━━━━
🕐 `{datetime.now().strftime('%H:%M:%S')}`
🤖 *JALWA AI | Python Logic*
"""
    return msg


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
⚡ *JALWA AI BOT* ⚡

🧠 Same period me sabko same prediction milegi!

Commands:
/predict - Get prediction
/start - Home screen

Button se bhi prediction lo 👇
"""
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_prediction_keyboard()
    )


async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Analyzing...")
    data = await fetch_and_predict()
    if not data:
        await msg.edit_text("❌ API se data nahi mila. Retry karo.")
        return
    await msg.edit_text(
        format_prediction_message(data),
        parse_mode="Markdown",
        reply_markup=get_prediction_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data in ("predict", "refresh"):
        data = await fetch_and_predict()
        if not data:
            await query.edit_message_text("❌ API se data nahi mila. Retry karo.")
            return
        await query.edit_message_text(
            format_prediction_message(data),
            parse_mode="Markdown",
            reply_markup=get_prediction_keyboard()
        )

    elif query.data == "stats":
        if not prediction_cache["period"]:
            await query.answer("Pehle prediction lo!", show_alert=True)
            return

        msg = f"""
📊 *JALWA AI STATS*

🎯 *Current Period:* `{prediction_cache['period']}`
🔮 *Prediction:* `{prediction_cache['prediction']}`
📈 *Confidence:* `{prediction_cache['confidence']}%`
📡 *Signal:* `{prediction_cache['signal']}`
🕐 *Cached At:* `{datetime.fromtimestamp(prediction_cache['timestamp']).strftime('%H:%M:%S')}`

_Same period me refresh karne par same prediction milegi_
"""
        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=get_prediction_keyboard()
        )


# ========== MAIN ==========

def main():
    print("🚀 JALWA AI Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
