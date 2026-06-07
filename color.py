#!/usr/bin/env python3
"""
⚡ JALWA AI - Telegram Bot ⚡
Bot ek hosted prediction page ka link deta hai jisme same period me same prediction hai.
API browser-only hai isliye bot HTML page + prediction logic embed karke deta hai.
"""

import asyncio, logging, time, json, hashlib
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = "8735707765:AAEliXQ5P89rT-Q0EFSxTZmrc77yPWcx7nY"   # @BotFather se token daalo

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== PREDICTION PAGE HTML ==========
# Ye page user browser me open hoga, browser se API call hogi (CORS allow hai)
# Same period seed se same prediction generate hogi

PREDICTION_PAGE = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JALWA AI</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#fff;font-family:monospace;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px}
.logo{font-size:20px;color:#00ff88;text-align:center;margin-bottom:20px;text-shadow:0 0 10px #00ff88}
.card{background:#0a0a0a;border:2px solid #00ff88;border-radius:20px;padding:25px;width:100%;max-width:380px;text-align:center;box-shadow:0 0 30px rgba(0,255,136,0.2)}
.period-label{font-size:11px;color:#555;margin-bottom:5px}
.period{font-size:28px;color:#ffd700;font-weight:bold;text-shadow:0 0 8px #ffd700}
.timer-label{font-size:11px;color:#555;margin-top:15px;margin-bottom:5px}
.timer{font-size:48px;font-weight:bold;background:linear-gradient(135deg,#00d2ff,#00ff88);-webkit-background-clip:text;background-clip:text;color:transparent}
.pred-label{font-size:11px;color:#888;margin-top:20px}
.pred{font-size:72px;font-weight:900;margin:8px 0;letter-spacing:2px}
.pred.big{color:#00ff88;text-shadow:0 0 20px #00ff88}
.pred.small{color:#ff3b5c;text-shadow:0 0 20px #ff3b5c}
.conf-bar{width:100%;height:8px;background:#222;border-radius:4px;margin-top:12px;overflow:hidden}
.conf-fill{height:100%;background:linear-gradient(90deg,#00ff88,#00d2ff);border-radius:4px;transition:width 0.5s}
.conf-text{font-size:12px;margin-top:8px;color:#aaa}
.signal{font-size:10px;color:#666;margin-top:6px;padding:5px;background:#111;border-radius:8px}
.btn{margin-top:20px;width:100%;padding:12px;background:linear-gradient(135deg,#00ff88,#00d2ff);border:none;border-radius:25px;font-weight:bold;font-size:14px;cursor:pointer;font-family:monospace}
.status{font-size:9px;color:#333;margin-top:10px}
.last{font-size:11px;color:#555;margin-top:8px}
.loading{font-size:16px;color:#00ff88;animation:blink 1s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
</style>
</head>
<body>
<div class="logo">◢ JALWA AI ◣</div>
<div class="card">
  <div class="period-label">🎯 TARGET PERIOD</div>
  <div class="period" id="period">---</div>
  <div class="timer-label">⏱️ NEXT RESULT IN</div>
  <div class="timer" id="timer">--</div>
  <div class="pred-label">🔮 PREDICTION</div>
  <div class="pred" id="pred"><span class="loading">...</span></div>
  <div class="conf-bar"><div class="conf-fill" id="confFill" style="width:0%"></div></div>
  <div class="conf-text" id="confText">CONFIDENCE: --</div>
  <div class="signal" id="signal">⚡ Analyzing...</div>
  <div class="last" id="lastInfo"></div>
  <button class="btn" onclick="refresh()">🔄 REFRESH</button>
  <div class="status" id="status">Connecting...</div>
</div>

<script>
const API = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json";
let cachedPeriod = null, cachedPred = null;

function predictFromSeed(numbers) {
  if (numbers.length < 10) return {prediction:"BIG",confidence:50,signal:"waiting"};
  const binary = numbers.map(x => x > 4 ? 1 : 0);
  const recent = numbers.slice(0,30);
  const bin30 = recent.map(x => x > 4 ? 1 : 0);
  let preds=[], confs=[], srcs=[];

  // Statistical
  const bigR = bin30.reduce((a,b)=>a+b,0)/bin30.length;
  let statPreds=[], statWts=[], statSig="statistical";
  if (Math.abs(bigR-0.5) > 0.2) {
    statPreds.push(bigR > 0.7 ? 0 : 1);
    statWts.push(0.35*Math.abs(bigR-0.5)*2);
    statSig = bigR > 0.7 ? "mean_reversion_high" : "mean_reversion_low";
  }
  if (bin30.length >= 10) {
    const ms = (bin30.slice(0,3).reduce((a,b)=>a+b,0)/3) - (bin30.slice(3,6).reduce((a,b)=>a+b,0)/3);
    const ml = (bin30.slice(0,6).reduce((a,b)=>a+b,0)/6) - (bin30.slice(6,10).reduce((a,b)=>a+b,0)/4);
    if (ms*ml > 0) { statPreds.push(ms>0?1:0); statWts.push(0.25*(Math.abs(ms)+Math.abs(ml))/2); statSig="confirmed_momentum"; }
  }
  let changes=[];
  for(let i=0;i<recent.length-1;i++){const d=Math.max(recent[i],recent[i+1]);if(d)changes.push(Math.abs(recent[i]-recent[i+1])/d);}
  const vol = changes.length>=2 ? changes.reduce((a,b)=>a+b,0)/changes.length*100 : 0;
  const vf = Math.min(vol/3,1.5);
  if (vol > 2.5){statPreds.push(bin30[0]);statWts.push(0.15*vf);}
  else{statPreds.push(1-bin30[0]);statWts.push(0.25/(vf||0.2));}

  if (statPreds.length) {
    let vb=0,vs=0;
    statPreds.forEach((p,i)=>{ if(p===1)vb+=statWts[i]; else vs+=statWts[i]; });
    const tot=vb+vs;
    if(tot && Math.abs(vb-vs)/tot>=0.1){
      const c=Math.min(0.85,Math.max(0.55,Math.max(vb,vs)/tot));
      preds.push(vb>vs?1:0); confs.push(c*100); srcs.push("statistical");
    }
  }

  // N-gram
  const n=4;
  if (binary.length >= n*2) {
    const lastNg = binary.slice(-n);
    const nxts=[];
    for(let i=0;i<binary.length-n;i++) if(binary.slice(i,i+n).every((v,j)=>v===lastNg[j]) && i+n<binary.length) nxts.push(binary[i+n]);
    if(nxts.length){
      const cnt={};nxts.forEach(x=>cnt[x]=(cnt[x]||0)+1);
      const sorted=Object.entries(cnt).sort((a,b)=>b[1]-a[1]);
      if(sorted.length===1||(sorted.length>=2&&sorted[0][1]>sorted[1][1]*1.5)){
        const c=sorted[0][1]/nxts.length;
        if(c>0.55){preds.push(+sorted[0][0]);confs.push(c*100);srcs.push("pattern");}
      }
    }
  }

  // Run-length
  const runs=[];let cv=binary[0],cl=1;
  for(let i=1;i<binary.length;i++){if(binary[i]===cv)cl++;else{runs.push([cv,cl]);cv=binary[i];cl=1;}}
  runs.push([cv,cl]);
  const bigR2=runs.filter(r=>r[0]===1).map(r=>r[1]);
  const smlR=runs.filter(r=>r[0]===0).map(r=>r[1]);
  if(bigR2.length&&smlR.length){
    const avgB=bigR2.reduce((a,b)=>a+b,0)/bigR2.length;
    const avgS=smlR.reduce((a,b)=>a+b,0)/smlR.length;
    const [lv,ll]=runs[runs.length-1];
    if(ll>=3){const c=Math.min(0.85,0.5+(ll-(lv===1?avgB:avgS))*0.1);if(c>0.55){preds.push(lv===1?0:1);confs.push(c*100);srcs.push("pattern");}}
    else{const c=Math.min(0.7,0.5+((lv===1?avgB:avgS)-ll)*0.05);if(c>0.55){preds.push(lv);confs.push(c*100);srcs.push("pattern");}}
  }

  // Trend
  if(binary.length>=8){
    const b15=binary.slice(0,15);
    const ss=b15.slice(0,3).reduce((a,b)=>a+b,0)/3;
    const sl=b15.slice(0,6).reduce((a,b)=>a+b,0)/6;
    const rs=ss-b15.slice(3,6).reduce((a,b)=>a+b,0)/3;
    if(ss>sl&&rs>0){preds.push(1);confs.push(Math.min(75,50+Math.abs(rs)*20));srcs.push("trend");}
    else if(ss<sl&&rs<0){preds.push(0);confs.push(Math.min(75,50+Math.abs(rs)*20));srcs.push("trend");}
  }

  if(preds.length<2) return {prediction:"BIG",confidence:50,signal:"fallback"};

  const wmap={pattern:0.40,statistical:0.35,trend:0.15};
  let vb2=0,vs2=0;
  preds.forEach((p,i)=>{const w=(wmap[srcs[i]]||0.25)*(confs[i]/100);if(p===1)vb2+=w;else vs2+=w;});
  const totV=vb2+vs2;
  let fc=(Math.max(vb2,vs2)/totV)*100;
  const cs=Math.abs(vb2-vs2)/totV;
  if(cs>0.3)fc*=(1+cs*0.2);
  fc=Math.max(50,Math.min(85,fc));

  return {prediction:vb2>vs2?"BIG":"SMALL",confidence:+fc.toFixed(1),signal:statSig};
}

async function fetchAndUpdate() {
  document.getElementById("status").textContent = "Syncing...";
  try {
    const r = await fetch(API, {cache:"no-store"});
    const d = await r.json();
    const list = d?.data?.list;
    if (!list?.length) throw new Error("no data");

    const latest = list[0];
    const nextPeriod = (BigInt(latest.issueNumber)+1n).toString();
    const numbers = list.map(x=>+x.number).filter(x=>x>=0&&x<=9);
    const lastNum = +latest.number;
    const lastRes = lastNum>=5?"BIG":"SMALL";

    // Same period = same prediction (deterministic algo)
    const pred = predictFromSeed(numbers);
    cachedPeriod = nextPeriod;
    cachedPred = pred;

    document.getElementById("period").textContent = nextPeriod;
    const el = document.getElementById("pred");
    el.textContent = pred.prediction;
    el.className = "pred " + pred.prediction.toLowerCase();
    document.getElementById("confFill").style.width = pred.confidence+"%";
    document.getElementById("confText").textContent = "CONFIDENCE: "+pred.confidence+"%";
    document.getElementById("signal").textContent = "📡 "+pred.signal;
    document.getElementById("lastInfo").textContent = "Last: "+lastNum+" → "+lastRes;
    document.getElementById("status").textContent = "🟢 LIVE | "+new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById("status").textContent = "⚠️ Error: "+e.message;
  }
}

function updateTimer() {
  const s = new Date().getSeconds();
  const rem = 60-s;
  document.getElementById("timer").textContent = (rem<10?"0":"")+rem+"s";
  if (rem===59||rem===1) fetchAndUpdate();
}

function refresh() { fetchAndUpdate(); }

fetchAndUpdate();
setInterval(updateTimer, 500);
setInterval(fetchAndUpdate, 3000);
</script>
</body>
</html>'''

# ========== INLINE HTML via data URI ==========
# Telegram Web App ya simple link

import base64

def get_html_data_url():
    encoded = base64.b64encode(PREDICTION_PAGE.encode()).decode()
    return f"data:text/html;base64,{encoded}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """⚡ *JALWA AI BOT* ⚡

🧠 Same period me sabko *same prediction* milegi!

📌 *Kaise use kare:*
• /predict — Prediction page link lo
• /start — Yahan wapas aao

_Note: Prediction browser me open hogi kyunki API browser-only hai_"""
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔮 GET PREDICTION PAGE", callback_data="getpage")
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_prediction_page(update.message.reply_text)


async def send_prediction_page(reply_func):
    now = datetime.now()
    period_hint = now.strftime("%Y%m%d") + str(now.hour * 60 + now.minute).zfill(4)

    text = f"""🔮 *JALWA AI PREDICTION PAGE*

👆 Neeche button dabao — browser me prediction page khulegi!

✅ *Same period me:*
• Sab logo ko same prediction milegi
• Algorithm deterministic hai
• Period: ends _{now.second}s_ baad

📡 _Browser me API direct connect hoga_"""

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🚀 OPEN PREDICTION PAGE",
            url="https://raw.githack.com/jalwa-ai/app/main/index.html"
            # 👆 Isko apna hosted page URL se replace karo
            # GitHub Pages, Netlify, ya koi bhi free hosting use karo
        )],
        [InlineKeyboardButton("❓ Setup Help", callback_data="help")]
    ])

    await reply_func(text, parse_mode="Markdown", reply_markup=kb)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "getpage":
        await send_prediction_page(q.message.reply_text)

    elif q.data == "help":
        await q.message.reply_text(
            "📖 *Setup Guide:*\n\n"
            "1. `jalwa_bot.zip` me se `index.html` file lo\n"
            "2. GitHub Pages pe upload karo (free)\n"
            "3. `bot.py` me URL replace karo\n\n"
            "Ya `python host.py` chalao local server ke liye",
            parse_mode="Markdown"
        )


def main():
    print("🚀 JALWA AI Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Bot live! Send /start in Telegram")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
