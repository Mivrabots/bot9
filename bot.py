import discord
from discord.ext import commands
from discord.ui import Select, View
import sqlite3
from keep_alive import keep_alive
keep_alive()
import random
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Intents and bot setup
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)

TOKEN = os.environ['token']

# Database setup
db = sqlite3.connect("stocks_bot.db")
cursor = db.cursor()

# Database initialization
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 1000,
    bank INTEGER DEFAULT 0,
    compound_last_calculated TEXT,
    last_work_time TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS stocks (
    stock_name TEXT PRIMARY KEY,
    price INTEGER
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS stock_history (
    stock_name TEXT,
    date TEXT,
    price INTEGER,
    PRIMARY KEY (stock_name, date)
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS stock_ownership (
    user_id INTEGER,
    stock_name TEXT,
    quantity INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, stock_name)
)
""")
db.commit()

# --- Helper Functions ---
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        db.commit()
        return get_user(user_id)
    return user

def check_cooldown(last_time, cooldown_minutes):
    if not last_time:
        return True
    last_time = datetime.fromisoformat(last_time)
    return (datetime.now() - last_time) > timedelta(minutes=cooldown_minutes)

def update_stock_prices():
    cursor.execute("SELECT * FROM stocks")
    stocks = cursor.fetchall()

    for stock in stocks:
        new_price = max(1, stock[1] + random.randint(-10, 10))  # Prevent negative prices
        cursor.execute("UPDATE stocks SET price = ? WHERE stock_name = ?", (new_price, stock[0]))
        cursor.execute("INSERT OR REPLACE INTO stock_history (stock_name, date, price) VALUES (?, ?, ?)", 
                       (stock[0], datetime.now().strftime('%Y-%m-%d'), new_price))

    db.commit()

def generate_stock_trend_graph(stock_name):
    cursor.execute("SELECT date, price FROM stock_history WHERE stock_name = ? ORDER BY date ASC", (stock_name,))
    history = cursor.fetchall()

    if not history:
        return None

    dates = [entry[0] for entry in history]
    prices = [entry[1] for entry in history]

    plt.figure(figsize=(10, 6))
    plt.plot(dates, prices, marker="o", linestyle="-", color="g")
    plt.title(f"Stock Trend: {stock_name}", fontsize=16)
    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Price ($)", fontsize=12)
    plt.grid()
    plt.xticks(rotation=45)
    plt.tight_layout()
    file_name = f"{stock_name}_history.png"
    plt.savefig(file_name)
    plt.close()
    return file_name

def generate_leaderboard_graph():
    cursor.execute("SELECT user_id, balance, bank FROM users ORDER BY balance + bank DESC LIMIT 10")
    top_users = cursor.fetchall()

    if not top_users:
        return None

    usernames = []
    wealths = []
    for user_id, balance, bank in top_users:
        user = bot.get_user(user_id)
        usernames.append(user.name if user else f"User {user_id}")
        wealths.append(balance + bank)

    plt.figure(figsize=(12, 7))
    plt.bar(usernames, wealths, color="skyblue")
    plt.title("Top 10 Wealthiest Users", fontsize=16)
    plt.xlabel("User", fontsize=12)
    plt.ylabel("Total Wealth ($)", fontsize=12)
    plt.xticks(rotation=45)
    plt.tight_layout()
    file_name = "leaderboard.png"
    plt.savefig(file_name)
    plt.close()
    return file_name

# --- Commands ---
@bot.tree.command(name="balance", description="Check your balance.")
async def balance(ctx):
    user = get_user(ctx.author.id)
    await ctx.respond(f"💰 Wallet: **${user[1]}**\n🏦 Bank: **${user[2]}**.")

@bot.tree.command(name="deposit", description="Deposit money into your bank.")
async def deposit(ctx, amount: int):
    user = get_user(ctx.author.id)
    if amount > user[1]:
        await ctx.respond("❌ You don't have enough money in your wallet.")
        return

    new_wallet = user[1] - amount
    new_bank = user[2] + amount
    cursor.execute("UPDATE users SET balance = ?, bank = ? WHERE user_id = ?", (new_wallet, new_bank, ctx.author.id))
    db.commit()

    await ctx.respond(f"✅ Deposited **${amount}** into your bank.\n🏦 New bank balance: **${new_bank}**.")

@bot.tree.command(name="withdraw", description="Withdraw money from your bank.")
async def withdraw(ctx, amount: int):
    user = get_user(ctx.author.id)
    if amount > user[2]:
        await ctx.respond("❌ You don't have enough money in your bank.")
        return

    new_wallet = user[1] + amount
    new_bank = user[2] - amount
    cursor.execute("UPDATE users SET balance = ?, bank = ? WHERE user_id = ?", (new_wallet, new_bank, ctx.author.id))
    db.commit()

    await ctx.respond(f"✅ Withdrew **${amount}** from your bank.\n💰 New wallet balance: **${new_wallet}**.")

@bot.tree.command(name="compound_interest", description="Apply compound interest to your bank balance.")
async def compound_interest(ctx):
    user = get_user(ctx.author.id)
    last_calculated = user[3]  # Assuming column 3 stores the last calculated time
    bank_balance = user[2]

    if not last_calculated:
        last_calculated = datetime.now() - timedelta(days=1)

    last_calculated = datetime.fromisoformat(last_calculated)
    days_since = (datetime.now() - last_calculated).days

    if days_since < 1:
        await ctx.respond("⏳ Compound interest can only be applied once per day.")
        return

    # Calculate compound interest
    rate = 0.05  # 5% annual, compounded daily
    new_balance = int(bank_balance * (1 + rate / 365) ** days_since)
    cursor.execute("UPDATE users SET bank = ?, compound_last_calculated = ? WHERE user_id = ?", 
                   (new_balance, datetime.now().isoformat(), ctx.author.id))
    db.commit()

    await ctx.respond(f"🏦 Compound interest applied!\nNew bank balance: **${new_balance}**.")

@bot.tree.command(name="market", description="View stock prices.")
async def market(ctx):
    cursor.execute("SELECT * FROM stocks")
    stocks = cursor.fetchall()
    if not stocks:
        await ctx.respond("📉 No stocks available in the market.")
        return

    embed = discord.Embed(title="Stock Market", color=discord.Color.blue())
    for stock in stocks:
        embed.add_field(name=stock[0], value=f"Price: **${stock[1]}**", inline=False)
    await ctx.respond(embed=embed)

@bot.tree.command(name="stock_trend", description="View the multi-day price trend of a stock.")
async def stock_trend(ctx, stock_name: str):
    file_path = generate_stock_trend_graph(stock_name)
    if not file_path:
        await ctx.respond("❌ No historical data found for this stock.")
        return

    await ctx.respond(file=discord.File(file_path))
    os.remove(file_path)

@bot.tree.command(name="leaderboard", description="View the leaderboard of the wealthiest users.")
async def leaderboard(ctx):
    file_path = generate_leaderboard_graph()
    if not file_path:
        await ctx.respond("❌ No data available for the leaderboard.")
        return

    await ctx.respond(file=discord.File(file_path))
    os.remove(file_path)

@bot.tree.command(name="update_market", description="Update stock prices (Admin only).")
@commands.has_permissions(administrator=True)
async def update_market(ctx):
    update_stock_prices()
    await ctx.respond("📈 Stock market updated successfully.")

# --- Events ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

# Scheduler for automated stock updates
scheduler = AsyncIOScheduler()
scheduler.add_job(update_stock_prices, "interval", hours=24)
scheduler.start()

# Run the bot
bot.run(TOKEN)
