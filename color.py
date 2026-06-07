import asyncio
import aiohttp
import logging
import math
import random
from collections import deque
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, JobQueue
)

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8735707765:AAEliXQ5P89rT-Q0EFSxTZmrc77yPWcx7nY"  # REPLACE WITH YOUR NEW TOKEN AFTER REVOKING
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
UPDATE_INTERVAL_SECONDS = 3
PREDICTION_CACHE_DURATION_SECONDS = 55

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== RISK MANAGER ====================
class RiskManager:
    def __init__(self, initial_bankroll: float = 100.0):
        self.bankroll = initial_bankroll
        self.peak_bankroll = initial_bankroll
        self.max_drawdown = 0.0
        self.win_streak = 0
        self.loss_streak = 0
        self.max_loss_streak = 0
        self.total_bets = 0
        self.total_wins = 0
        self.consecutive_losses = 0
        self.last_bet_amount = 0.0
        
        self.base_bet_percentage = 0.02
        self.max_bet_percentage = 0.05
        self.min_bet_percentage = 0.005
        self.stop_loss_trigger = 3
        self.stop_loss_recovery = 6
        self.aggressive_mode_win_streak = 3
        self.win_multiplier = 1.3
        self.loss_multiplier = 0.7
        self.streak_breaker_multiplier = 0.5
    
    def calculate_bet_size(self, confidence: float, is_streak_breaker: bool = False) -> float:
        multiplier = 1.0
        
        if confidence >= 70:
            multiplier = 1.2
        elif confidence >= 60:
            multiplier = 1.0
        else:
            multiplier = 0.8
        
        if self.loss_streak >= self.stop_loss_trigger:
            streak_reduction = max(0.3, 1.0 - (self.loss_streak - self.stop_loss_trigger) * 0.2)
            multiplier *= streak_reduction
        
        if self.win_streak >= self.aggressive_mode_win_streak:
            streak_boost = min(1.5, 1.0 + (self.win_streak - self.aggressive_mode_win_streak) * 0.1)
            multiplier *= streak_boost
        
        if self.total_bets > 0:
            if self.loss_streak > 0:
                multiplier *= pow(self.loss_multiplier, min(self.loss_streak, 3))
            elif self.win_streak > 0:
                multiplier *= pow(self.win_multiplier, min(self.win_streak, 2))
        
        if is_streak_breaker:
            multiplier *= self.streak_breaker_multiplier
        
        bet_percentage = self.base_bet_percentage * multiplier
        bet_percentage = max(self.min_bet_percentage, min(bet_percentage, self.max_bet_percentage))
        
        bet_amount = self.bankroll * bet_percentage
        min_bet = 0.5
        max_bet = self.bankroll * 0.1
        bet_amount = max(min_bet, min(bet_amount, max_bet))
        
        self.last_bet_amount = round(bet_amount, 2)
        return self.last_bet_amount
    
    def update_result(self, won: bool, amount: float):
        self.total_bets += 1
        
        if won:
            self.bankroll += amount
            self.total_wins += 1
            self.win_streak += 1
            self.loss_streak = 0
            self.consecutive_losses = 0
        else:
            self.bankroll -= amount
            self.loss_streak += 1
            self.win_streak = 0
            self.consecutive_losses += 1
            self.max_loss_streak = max(self.max_loss_streak, self.loss_streak)
        
        if self.bankroll > self.peak_bankroll:
            self.peak_bankroll = self.bankroll
        
        current_drawdown = (self.peak_bankroll - self.bankroll) / self.peak_bankroll
        self.max_drawdown = max(self.max_drawdown, current_drawdown)
    
    def should_bet(self, confidence: float) -> bool:
        if confidence < 50:
            return False
        if self.bankroll < 5.0:
            return False
        if self.loss_streak >= self.stop_loss_trigger and confidence < 70:
            return False
        
        current_drawdown = (self.peak_bankroll - self.bankroll) / self.peak_bankroll
        if current_drawdown > 0.25 and confidence < 70:
            return False
        
        return True
    
    def is_streak_breaker_scenario(self) -> bool:
        return self.loss_streak >= 2 or self.consecutive_losses >= 2
    
    def get_status(self) -> dict:
        return {
            "bankroll": round(self.bankroll, 2),
            "profit": round(self.bankroll - 100, 2),
            "loss_streak": self.loss_streak,
            "win_streak": self.win_streak,
            "total_bets": self.total_bets,
            "total_wins": self.total_wins,
            "win_rate": round(self.total_wins / self.total_bets * 100, 1) if self.total_bets > 0 else 0
        }

# ==================== STATISTICAL ARBITER ====================
class StatisticalArbiter:
    def __init__(self):
        self.window_sizes = [5, 8, 13, 21]
    
    def calculate_entropy(self, sequence: List[int]) -> float:
        if not sequence:
            return 0
        p_big = sum(sequence) / len(sequence)
        p_small = 1 - p_big
        if p_big == 0 or p_small == 0:
            return 0
        return -(p_big * math.log2(p_big) + p_small * math.log2(p_small))
    
    def calculate_volatility(self, numbers: List[int]) -> float:
        if len(numbers) < 3:
            return 0
        changes = []
        for i in range(len(numbers) - 1):
            if numbers[i+1] != 0:
                change = abs(numbers[i] - numbers[i+1]) / max(numbers[i], numbers[i+1])
                changes.append(change)
        if len(changes) < 2:
            return 0
        return sum(changes) / len(changes) * 100
    
    def predict_with_statistics(self, numbers: List[int]) -> dict:
        if len(numbers) < 15:
            return {"prediction": 0, "confidence": 0.5, "signal": "insufficient_data"}
        
        recent_numbers = numbers[:30]
        binary_seq = [1 if x > 4 else 0 for x in recent_numbers]
        
        predictions = []
        weights = []
        signals = []
        
        # Mean reversion
        big_ratio = sum(binary_seq) / len(binary_seq)
        mean_reversion_threshold = 0.2
        
        if abs(big_ratio - 0.5) > mean_reversion_threshold:
            if big_ratio > 0.5 + mean_reversion_threshold:
                predictions.append(0)
                signals.append("mean_reversion_high")
            else:
                predictions.append(1)
                signals.append("mean_reversion_low")
            weights.append(0.35 * abs(big_ratio - 0.5) * 2)
        
        # Momentum
        if len(binary_seq) >= 10:
            momentum_short = sum(binary_seq[:3])/3 - sum(binary_seq[3:6])/3
            momentum_long = sum(binary_seq[:6])/6 - sum(binary_seq[6:10])/4
            
            if momentum_short * momentum_long > 0:
                predictions.append(1 if momentum_short > 0 else 0)
                signals.append("confirmed_momentum")
                weight = (abs(momentum_short) + abs(momentum_long)) / 2
                weights.append(0.25 * weight)
        
        # Volatility adjusted
        volatility = self.calculate_volatility(recent_numbers)
        volatility_factor = min(volatility / 3, 1.5)
        
        if volatility > 2.5:
            predictions.append(binary_seq[0])
            signals.append("high_vol_continuation")
            weights.append(0.15 * volatility_factor)
        else:
            predictions.append(1 - binary_seq[0])
            signals.append("low_vol_reversion")
            weights.append(0.25 * (1 / max(volatility_factor, 0.2)))
        
        if not predictions:
            return {"prediction": 0, "confidence": 0.5, "signal": "no_clear_signal"}
        
        vote_big = sum(weights[i] for i, p in enumerate(predictions) if p == 1)
        vote_small = sum(weights[i] for i, p in enumerate(predictions) if p == 0)
        
        total_votes = vote_big + vote_small
        if total_votes == 0:
            return {"prediction": 0, "confidence": 0.5, "signal": "no_confidence"}
        
        min_vote_diff = 0.1
        if abs(vote_big - vote_small) / total_votes < min_vote_diff:
            return {"prediction": 0, "confidence": 0.5, "signal": "neutral_no_clear_signal"}
        
        prediction = 1 if vote_big > vote_small else 0
        confidence = max(vote_big, vote_small) / total_votes
        confidence = min(0.85, max(0.55, confidence))
        
        return {
            "prediction": prediction,
            "confidence": confidence,
            "big_ratio": big_ratio,
            "volatility": volatility,
            "signal": signals[0] if signals else "statistical"
        }

# ==================== ADVANCED PATTERN ANALYZER ====================
class AdvancedPatternAnalyzer:
    def __init__(self):
        self.n_gram_size = 4
    
    def analyze_advanced_patterns(self, sequence: List[int]) -> dict:
        if len(sequence) < 10:
            return {}
        
        binary_seq = [1 if x > 4 else 0 for x in sequence]
        
        return {
            "ngram": self.ngram_analysis(binary_seq),
            "markov": self.markov_chain_analysis(binary_seq),
            "run_length": self.run_length_analysis(binary_seq),
            "trend": self.exponential_smoothing_analysis(binary_seq)
        }
    
    def ngram_analysis(self, sequence: List[int]) -> dict:
        n = 4
        if len(sequence) < n * 2:
            return {}
        
        ngrams = []
        for i in range(len(sequence) - n):
            ngrams.append(tuple(sequence[i:i + n]))
        
        last_ngram = tuple(sequence[-n:])
        predictions = []
        
        for i in range(len(ngrams) - 1):
            if ngrams[i] == last_ngram:
                if i + n < len(sequence):
                    predictions.append(sequence[i + n])
        
        if not predictions:
            return {}
        
        counter = {}
        for p in predictions:
            counter[p] = counter.get(p, 0) + 1
        
        sorted_items = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        most_common = sorted_items[0]
        
        if len(sorted_items) >= 2 and most_common[1] > sorted_items[1][1] * 1.5:
            return {
                "prediction": most_common[0],
                "confidence": most_common[1] / len(predictions),
                "occurrences": len(predictions)
            }
        
        return {}
    
    def markov_chain_analysis(self, sequence: List[int]) -> dict:
        if len(sequence) < 15:
            return {}
        
        transitions = {}
        
        for i in range(len(sequence) - 2):
            current_state = f"{sequence[i]},{sequence[i+1]}"
            next_state = sequence[i+2]
            if current_state not in transitions:
                transitions[current_state] = {}
            transitions[current_state][next_state] = transitions[current_state].get(next_state, 0) + 1
        
        last_state = f"{sequence[-2]},{sequence[-1]}"
        
        if last_state in transitions:
            next_states = transitions[last_state]
            total = sum(next_states.values())
            
            if total < 3:
                return {}
            
            most_likely = max(next_states.items(), key=lambda x: x[1])
            
            if most_likely[1] / total > 0.6:
                return {
                    "prediction": most_likely[0],
                    "confidence": most_likely[1] / total,
                    "total_transitions": total
                }
        
        return {}
    
    def run_length_analysis(self, sequence: List[int]) -> dict:
        if not sequence:
            return {}
        
        runs = []
        current_run = 1
        current_value = sequence[0]
        
        for i in range(1, len(sequence)):
            if sequence[i] == current_value:
                current_run += 1
            else:
                runs.append({"value": current_value, "length": current_run})
                current_value = sequence[i]
                current_run = 1
        runs.append({"value": current_value, "length": current_run})
        
        big_runs = [r["length"] for r in runs if r["value"] == 1]
        small_runs = [r["length"] for r in runs if r["value"] == 0]
        
        if not big_runs or not small_runs:
            return {}
        
        avg_big_run = sum(big_runs) / len(big_runs)
        avg_small_run = sum(small_runs) / len(small_runs)
        last_run = runs[-1]
        
        if last_run["length"] >= 3:
            next_prediction = 0 if last_run["value"] == 1 else 1
            confidence = min(0.85, 0.5 + (last_run["length"] - (avg_big_run if last_run["value"] == 1 else avg_small_run)) * 0.1)
            return {
                "prediction": next_prediction,
                "confidence": confidence,
                "signal": "reversal"
            }
        else:
            next_prediction = last_run["value"]
            confidence = min(0.7, 0.5 + ((avg_big_run if last_run["value"] == 1 else avg_small_run) - last_run["length"]) * 0.05)
            return {
                "prediction": next_prediction,
                "confidence": confidence,
                "signal": "continuation"
            }
    
    def exponential_smoothing_analysis(self, sequence: List[int], alpha: float = 0.3) -> dict:
        if len(sequence) < 8:
            return {}
        
        ema_fast = sequence[0]
        ema_slow = sequence[0]
        
        for i in range(1, len(sequence)):
            ema_fast = 0.4 * sequence[i] + 0.6 * ema_fast
            ema_slow = 0.15 * sequence[i] + 0.85 * ema_slow
        
        macd = ema_fast - ema_slow
        trend_strength = abs(macd)
        
        return {
            "macd": macd,
            "trend_strength": trend_strength,
            "signal": "strong_trend" if trend_strength > 0.5 else "weak_trend"
        }

# ==================== PREDICTION ENGINE ====================
class PredictionEngine:
    def __init__(self):
        self.pattern_analyzer = AdvancedPatternAnalyzer()
        self.statistical_arbiter = StatisticalArbiter()
        self.risk_manager = RiskManager()
        
        self.weights = {
            "pattern": 0.40,
            "statistical": 0.35,
            "trend": 0.15,
            "counter_trend": 0.10
        }
        
        self.predictions_history = []
        self.accuracy_history = deque(maxlen=20)
        self.loss_streak_tracker = deque(maxlen=10)
        self.current_loss_streak = 0
        self.current_win_streak = 0
    
    def predict(self, numbers: List[int]) -> dict:
        if len(numbers) < 10:
            return {
                "prediction": "BIG" if random.random() > 0.5 else "SMALL",
                "confidence": 45,
                "bet_amount": 1.0,
                "is_streak_breaker": False
            }
        
        pattern_analysis = self.pattern_analyzer.analyze_advanced_patterns(numbers)
        statistical_pred = self.statistical_arbiter.predict_with_statistics(numbers)
        
        predictions = []
        confidences = []
        sources = []
        
        # Pattern prediction
        pattern_pred = self._extract_pattern_prediction(pattern_analysis)
        if pattern_pred and pattern_pred["confidence"] > 50:
            predictions.append(pattern_pred["prediction"])
            confidences.append(pattern_pred["confidence"])
            sources.append("pattern")
        
        # Statistical prediction
        if statistical_pred["confidence"] > 0.5:
            predictions.append(1 if statistical_pred["prediction"] == 1 else 0)
            confidences.append(statistical_pred["confidence"] * 100)
            sources.append("statistical")
        
        # Trend prediction
        trend_pred = self._calculate_trend_prediction(numbers)
        if trend_pred["confidence"] > 50:
            predictions.append(trend_pred["prediction"])
            confidences.append(trend_pred["confidence"])
            sources.append("trend")
        
        if len(predictions) < 2:
            random_pred = 1 if random.random() > 0.5 else 0
            pred_str = "BIG" if random_pred == 1 else "SMALL"
            is_streak_breaker = self.risk_manager.is_streak_breaker_scenario()
            bet_amount = self.risk_manager.calculate_bet_size(50, is_streak_breaker)
            return {
                "prediction": pred_str,
                "confidence": 50,
                "bet_amount": bet_amount,
                "is_streak_breaker": is_streak_breaker
            }
        
        final_prediction = self._ensemble_vote(predictions, confidences, sources)
        final_confidence = final_prediction["confidence"]
        
        is_streak_breaker = self.risk_manager.is_streak_breaker_scenario()
        
        if is_streak_breaker:
            final_confidence = self._apply_streak_breaker_boost(final_confidence, pattern_analysis)
        
        final_confidence = max(50, min(85, final_confidence))
        
        prediction_str = "BIG" if final_prediction["prediction"] == 1 else "SMALL"
        bet_amount = self.risk_manager.calculate_bet_size(final_confidence, is_streak_breaker)
        
        return {
            "prediction": prediction_str,
            "confidence": round(final_confidence, 1),
            "bet_amount": bet_amount,
            "is_streak_breaker": is_streak_breaker,
            "signal": final_prediction.get("signal") or statistical_pred.get("signal", "ensemble_vote")
        }
    
    def _extract_pattern_prediction(self, pattern_analysis: dict) -> Optional[dict]:
        predictions = []
        sources_to_check = ["ngram", "markov", "run_length"]
        
        for source in sources_to_check:
            if source in pattern_analysis and pattern_analysis[source].get("prediction") is not None:
                pred_data = pattern_analysis[source]
                if pred_data.get("confidence", 0) > 0.55:
                    predictions.append({
                        "prediction": pred_data["prediction"],
                        "confidence": pred_data["confidence"] * 100,
                        "source": source,
                        "signal": pred_data.get("signal", "unknown")
                    })
        
        if not predictions:
            return None
        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        return predictions[0]
    
    def _calculate_trend_prediction(self, numbers: List[int]) -> dict:
        if len(numbers) < 8:
            return {"prediction": 0, "confidence": 45, "signal": "insufficient_data"}
        
        binary_seq = [1 if x > 4 else 0 for x in numbers[:15]]
        
        sma_short = sum(binary_seq[:3]) / 3
        sma_long = sum(binary_seq[:6]) / 6
        
        roc_short = sma_short - (sum(binary_seq[3:6]) / 3)
        roc_long = sma_long - (sum(binary_seq[6:9]) / 4)
        
        trend_strength = abs(roc_short) + abs(roc_long)
        
        if sma_short > sma_long and roc_short > 0:
            confidence = min(75, 50 + trend_strength * 20)
            return {"prediction": 1, "confidence": confidence, "signal": "strong_uptrend"}
        elif sma_short < sma_long and roc_short < 0:
            confidence = min(75, 50 + trend_strength * 20)
            return {"prediction": 0, "confidence": confidence, "signal": "strong_downtrend"}
        elif abs(sma_short - sma_long) < 0.1 and abs(roc_short) < 0.1:
            return {"prediction": 1 if random.random() > 0.5 else 0, "confidence": 50, "signal": "range_bound"}
        else:
            prediction = 1 if sma_short > 0.5 else 0
            return {"prediction": prediction, "confidence": 55, "signal": "weak_trend"}
    
    def _ensemble_vote(self, predictions: List[int], confidences: List[float], sources: List[str]) -> dict:
        weighted_votes_big = 0
        weighted_votes_small = 0
        
        for i, pred in enumerate(predictions):
            source_weight = self.weights.get(sources[i], 0.25)
            conf_weight = confidences[i] / 100
            total_weight = source_weight * conf_weight
            
            if pred == 1:
                weighted_votes_big += total_weight
            else:
                weighted_votes_small += total_weight
        
        total_votes = weighted_votes_big + weighted_votes_small
        if total_votes == 0:
            return {"prediction": 1 if random.random() > 0.5 else 0, "confidence": 50, "signal": "random"}
        
        consensus_level = abs(weighted_votes_big - weighted_votes_small) / total_votes
        final_prediction = 1 if weighted_votes_big > weighted_votes_small else 0
        final_confidence = (max(weighted_votes_big, weighted_votes_small) / total_votes) * 100
        
        if consensus_level > 0.3:
            final_confidence *= (1 + consensus_level * 0.2)
        
        return {
            "prediction": final_prediction,
            "confidence": min(85, final_confidence),
            "consensus_level": consensus_level
        }
    
    def _apply_streak_breaker_boost(self, confidence: float, pattern_analysis: dict) -> float:
        boosted_confidence = confidence
        reversal_signals = 0
        
        if pattern_analysis.get("run_length") and pattern_analysis["run_length"].get("signal") == "reversal":
            if pattern_analysis["run_length"].get("confidence", 0) > 0.6:
                reversal_signals += 1
                boosted_confidence *= 1.10
        
        if reversal_signals >= 1:
            boosted_confidence *= 1.12
        
        return min(90, boosted_confidence)
    
    def update_performance(self, predicted: str, actual: str, confidence: float, won: bool):
        correct = predicted == actual
        self.predictions_history.append({
            "predicted": predicted,
            "actual": actual,
            "correct": correct,
            "confidence": confidence,
            "won": won
        })
        self.accuracy_history.append(1 if correct else 0)
        
        if correct:
            self.current_win_streak += 1
            self.current_loss_streak = 0
            self.loss_streak_tracker.append(0)
        else:
            self.current_loss_streak += 1
            self.current_win_streak = 0
            self.loss_streak_tracker.append(1)
        
        if len(self.predictions_history) > 100:
            self.predictions_history.pop(0)
    
    def get_performance(self) -> dict:
        if not self.predictions_history:
            return {"accuracy": 0, "recent_accuracy": 0, "win_rate": 0, "current_loss_streak": 0}
        
        total = len(self.predictions_history)
        correct = sum(1 for p in self.predictions_history if p["correct"])
        accuracy = correct / total if total > 0 else 0
        
        recent_accuracy = sum(self.accuracy_history) / len(self.accuracy_history) if self.accuracy_history else 0
        
        actual_bets = [p for p in self.predictions_history if p.get("won") is not None]
        wins = sum(1 for p in actual_bets if p["won"])
        win_rate = wins / len(actual_bets) if actual_bets else 0
        
        return {
            "accuracy": round(accuracy * 100, 1),
            "recent_accuracy": round(recent_accuracy * 100, 1),
            "win_rate": round(win_rate * 100, 1),
            "current_loss_streak": self.current_loss_streak
        }

# ==================== BOT APPLICATION ====================
class JALWABot:
    def __init__(self, token: str):
        self.token = token
        self.prediction_engine = PredictionEngine()
        self.current_period: Optional[str] = None
        self.current_prediction: Optional[dict] = None
        self.last_result: Optional[dict] = None
        self.history_data: List[dict] = []
        self.last_issue_processed: Optional[str] = None
        
    async def fetch_data(self) -> Optional[List[dict]]:
        """Fetch latest data from API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, ssl=False) as response:
                    data = await response.json()
                    if data.get("data") and data["data"].get("list"):
                        return data["data"]["list"]
        except Exception as e:
            logger.error(f"Fetch error: {e}")
        return None
    
    def process_data(self, results: List[dict]):
        """Process fetched data and update predictions"""
        if not results:
            return
        
        latest = results[0]
        latest_issue = latest.get("issueNumber")
        latest_num = int(latest.get("number", 0))
        latest_result = "BIG" if latest_num >= 5 else "SMALL"
        
        # Update current period (next period)
        next_period = str(int(latest_issue) + 1) if latest_issue else "---"
        self.current_period = next_period
        
        # Extract numbers for analysis
        numbers = [int(r.get("number", 0)) for r in results if r.get("number") is not None]
        
        # Generate prediction
        self.current_prediction = self.prediction_engine.predict(numbers)
        
        # Track accuracy if we have a previous prediction
        if self.last_result and self.last_issue_processed and self.last_issue_processed != latest_issue:
            was_win = (self.last_result["prediction"] == latest_result)
            bet_amount = self.last_result.get("bet_amount", 1.0)
            self.prediction_engine.update_performance(
                self.last_result["prediction"],
                latest_result,
                self.last_result["confidence"],
                was_win
            )
            self.prediction_engine.risk_manager.update_result(was_win, bet_amount)
        
        # Store current result for next round
        self.last_result = {
            "prediction": self.current_prediction["prediction"],
            "confidence": self.current_prediction["confidence"],
            "bet_amount": self.current_prediction["bet_amount"]
        }
        self.last_issue_processed = latest_issue
        
        # Store history
        self.history_data = results[:20]
    
    def get_prediction_message(self) -> str:
        """Generate prediction message for current period"""
        if not self.current_period or not self.current_prediction:
            return "🔮 Fetching data... Please wait."
        
        pred = self.current_prediction
        risk_status = self.prediction_engine.risk_manager.get_status()
        perf = self.prediction_engine.get_performance()
        
        # Determine emoji based on prediction
        pred_emoji = "🐂" if pred["prediction"] == "BIG" else "🐁"
        pred_color = "🟢" if pred["prediction"] == "BIG" else "🔴"
        
        message = f"""
╔══════════════════════════════════╗
║     🔮 JALWA AI PREDICTION 🔮     ║
╠══════════════════════════════════╣
║  📍 PERIOD: #{self.current_period}
║  {pred_color} PREDICTION: {pred_emoji} {pred["prediction"]}
║  🎯 CONFIDENCE: {pred['confidence']}%
║  💰 SUGGESTED BET: ${pred['bet_amount']}
║  📊 SIGNAL: {pred.get('signal', 'ensemble_vote')}
╠══════════════════════════════════╣
║  📈 STATISTICS:
║  ├ Win Rate: {risk_status['win_rate']}%
║  ├ W/L: {risk_status['total_wins']}/{risk_status['total_bets'] - risk_status['total_wins']}
║  ├ Streak: {'+' + str(risk_status['win_streak']) if risk_status['win_streak'] > 0 else str(-risk_status['loss_streak'])}
║  ├ Bankroll: ${risk_status['bankroll']}
║  └ Profit: ${risk_status['profit']}
╠══════════════════════════════════╣
║  🧠 AI Accuracy: {perf['recent_accuracy']}% (Recent)
║  ⚡ Status: {'STREAK BREAKER ACTIVE' if pred.get('is_streak_breaker') else 'Normal Mode'}
╚══════════════════════════════════╝
"""
        return message
    
    def get_history_message(self) -> str:
        """Generate history message"""
        if not self.history_data:
            return "📜 No history available yet."
        
        message = "📜 **RECENT RESULTS**\n\n"
        message += "```\n"
        message += f"{'PERIOD':<12} {'NUM':<6} {'RESULT':<8}\n"
        message += "-" * 30 + "\n"
        
        for item in self.history_data[:10]:
            period = item.get("issueNumber", "---")[-8:]
            num = item.get("number", "?")
            result = "BIG" if int(num) >= 5 else "SMALL"
            emoji = "🟢" if result == "BIG" else "🔴"
            message += f"{period:<12} {num:<6} {emoji} {result:<8}\n"
        
        message += "```"
        return message
    
    def get_status_message(self) -> str:
        """Generate status message"""
        risk_status = self.prediction_engine.risk_manager.get_status()
        perf = self.prediction_engine.get_performance()
        
        message = f"""
╔══════════════════════════════════╗
║        📊 JALWA AI STATUS        ║
╠══════════════════════════════════╣
║  💰 BANKROLL: ${risk_status['bankroll']}
║  📈 PROFIT: ${risk_status['profit']}
║  🎯 WIN RATE: {risk_status['win_rate']}%
║  📊 W/L: {risk_status['total_wins']}/{risk_status['total_bets'] - risk_status['total_wins']}
║  🔥 STREAK: {'+' + str(risk_status['win_streak']) if risk_status['win_streak'] > 0 else str(-risk_status['loss_streak'])}
║  🧠 ACCURACY: {perf['accuracy']}% (Overall)
║  ⚡ RECENT: {perf['recent_accuracy']}% (Last 20)
║  📈 TOTAL BETS: {risk_status['total_bets']}
╚══════════════════════════════════╝
"""
        return message

# ==================== TELEGRAM HANDLERS ====================
bot_instance: Optional[JALWABot] = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when /start is issued."""
    welcome_msg = """
╔══════════════════════════════════════╗
║     🤖 JALWA AI TRADING BOT 🤖        ║
║     Python Logic | Advanced AI       ║
╠══════════════════════════════════════╣
║  Commands:                           ║
║  /prediction - Get current prediction║
║  /history    - Show recent results   ║
║  /status     - Show bot statistics   ║
║  /help       - Show this message     ║
╠══════════════════════════════════════╣
║  ⚡ Real-time AI predictions for     ║
║     WinGo 1M game using advanced     ║
║     statistical and pattern analysis ║
╚══════════════════════════════════════╝
"""
    await update.message.reply_text(welcome_msg)

async def get_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the current prediction."""
    if bot_instance and bot_instance.current_prediction:
        message = bot_instance.get_prediction_message()
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text("🔮 Loading prediction... Please wait a moment.")

async def get_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send recent history."""
    if bot_instance:
        message = bot_instance.get_history_message()
        await update.message.reply_text(message, parse_mode="Markdown")

async def get_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send bot status."""
    if bot_instance:
        message = bot_instance.get_status_message()
        await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message."""
    help_msg = """
🤖 **JALWA AI BOT COMMANDS**

/prediction - Get current period prediction with confidence and bet amount
/history    - View last 10 game results
/status     - View bot performance and statistics
/help       - Show this help message

**How it works:**
- Bot fetches live data every 3 seconds
- Uses Python-based AI with pattern recognition
- Same prediction for all users per period
- Confidence-based betting suggestions
"""
    await update.message.reply_text(help_msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "refresh":
        if bot_instance and bot_instance.current_prediction:
            message = bot_instance.get_prediction_message()
            await query.edit_message_text(message)
        else:
            await query.edit_message_text("🔮 Loading... Please wait.")

async def auto_update(context: ContextTypes.DEFAULT_TYPE):
    """Auto-update prediction data in background."""
    if bot_instance:
        data = await bot_instance.fetch_data()
        if data:
            bot_instance.process_data(data)
            logger.info(f"Auto-update: Period {bot_instance.current_period}")

async def post_init(application: Application):
    """Setup background job."""
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(auto_update, interval=UPDATE_INTERVAL_SECONDS, first=1)

def main():
    """Start the bot."""
    global bot_instance
    bot_instance = JALWABot(BOT_TOKEN)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("prediction", get_prediction))
    application.add_handler(CommandHandler("history", get_history))
    application.add_handler(CommandHandler("status", get_status))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start bot
    print("🤖 JALWA AI BOT STARTED...")
    print(f"📡 API URL: {API_URL}")
    print(f"⏱️ Update interval: {UPDATE_INTERVAL_SECONDS}s")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
