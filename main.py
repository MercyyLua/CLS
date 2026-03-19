import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
import os

TOKEN = os.environ.get("DISCORD_TOKEN", "PASTE_YOUR_TOKEN_HERE")
DB_PATH = "league.db"

# ── Persistent DB connection ──────────────────────────────────────
_db = None

async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("PRAGMA journal_mode=WAL")
    return _db

# ── Pre-configured teams and roles ───────────────────────────────
GUILD_ID      = 1464096719867347096
FA_ROLE_ID    = 1464129524210995325

TEAM_DATA = [
    ("Iowa Dream",           "IOWA", 1478105341899051028),
    ("St Louis Archers",     "STL",  1478111948313989160),
    ("Philadelphia Surge",   "PHI",  1483156350258254084),
    ("Seattle Sonics",       "SEA",  1481717125877071992),
    ("Baltimore Ospreys",    "BAL",  1481718253536546888),
    ("Los Angeles Reapers",  "LAR",  1482413661824745602),
    ("Chicago Ravens",       "CHI",  1483336220544077924),
    ("Arizona Firebirds",    "ARI",  1482435095938732042),
    ("Houston Bulls",        "HOU",  1482465219103166484),
    ("San Diego Tropics",    "SDT",  1483156220369047615),
    ("Dallas Panthers",      "DAL",  1483306097535225956),
]

async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT UNIQUE NOT NULL,
            abbreviation TEXT UNIQUE NOT NULL,
            owner_id     INTEGER NOT NULL,
            logo_url     TEXT,
            wins         INTEGER DEFAULT 0,
            losses       INTEGER DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS players (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id   INTEGER UNIQUE NOT NULL,
            username     TEXT NOT NULL,
            position     TEXT NOT NULL,
            team_id      INTEGER REFERENCES teams(id),
            batting_avg  REAL DEFAULT 0.0,
            home_runs    INTEGER DEFAULT 0,
            rbi          INTEGER DEFAULT 0,
            era          REAL DEFAULT 0.0,
            strikeouts   INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            free_agent   INTEGER DEFAULT 1,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS games (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            home_team_id INTEGER REFERENCES teams(id),
            away_team_id INTEGER REFERENCES teams(id),
            home_score   INTEGER,
            away_score   INTEGER,
            innings      INTEGER DEFAULT 9,
            status       TEXT DEFAULT 'scheduled',
            scheduled_at TIMESTAMP,
            played_at    TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id  INTEGER REFERENCES players(id),
            from_team  INTEGER REFERENCES teams(id),
            to_team    INTEGER REFERENCES teams(id),
            type       TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS config (
            guild_id             INTEGER PRIMARY KEY,
            transactions_channel INTEGER
        );
        CREATE TABLE IF NOT EXISTS team_roles (
            team_id INTEGER PRIMARY KEY REFERENCES teams(id),
            role_id INTEGER NOT NULL
        );
    """)
    await db.commit()

    # Seed teams and link roles
    for name, abbr, role_id in TEAM_DATA:
        cur = await db.execute("SELECT id FROM teams WHERE abbreviation=?", (abbr,))
        row = await cur.fetchone()
        if not row:
            cur2 = await db.execute(
                "INSERT INTO teams (name, abbreviation, owner_id) VALUES (?,?,?)",
                (name, abbr, 0)
            )
            team_id = cur2.lastrowid
            print(f"  ✅ Seeded team: {name} [{abbr}]")
        else:
            team_id = row[0]
        await db.execute("""
            INSERT INTO team_roles (team_id, role_id) VALUES (?,?)
            ON CONFLICT(team_id) DO UPDATE SET role_id=excluded.role_id
        """, (team_id, role_id))
    await db.commit()
    print("✅ Database initialized. All teams and roles ready.")

# ── Helpers ───────────────────────────────────────────────────────
BRAND_COLOR   = 0x1E90FF
SUCCESS_COLOR = 0x2ECC71
ERROR_COLOR   = 0xFF4444
WARN_COLOR    = 0xF1C40F

POSITIONS = ["C","1B","2B","3B","SS","LF","CF","RF","DH","SP","RP","CL"]
POSITION_EMOJIS = {
    "C":"🧤","1B":"1️⃣","2B":"2️⃣","3B":"3️⃣","SS":"🌟",
    "LF":"🌿","CF":"🌿","RF":"🌿","DH":"🔨",
    "SP":"⚾","RP":"⚾","CL":"🔒"
}

def base_embed(title="", description="", color=BRAND_COLOR):
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    return e

def success_embed(title, description=""):
    return base_embed(f"✅ {title}", description, SUCCESS_COLOR)

def error_embed(title, description=""):
    return base_embed(f"❌ {title}", description, ERROR_COLOR)

def warn_embed(title, description=""):
    return base_embed(f"⚠️ {title}", description, WARN_COLOR)

async def get_config(guild_id):
    db = await get_db()
    cur = await db.execute("SELECT transactions_channel FROM config WHERE guild_id=?", (guild_id,))
    row = await cur.fetchone()
    return {"transactions_channel": row[0]} if row else {}

async def get_team_role(team_id):
    db = await get_db()
    cur = await db.execute("SELECT role_id FROM team_roles WHERE team_id=?", (team_id,))
    row = await cur.fetchone()
    return row[0] if row else None

async def post_transaction(guild, config, embed):
    ch_id = config.get("transactions_channel")
    if not ch_id:
        return
    channel = guild.get_channel(ch_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

async def add_team_role(member, guild, team_id):
    role_id = await get_team_role(team_id)
    if role_id:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role, reason="HCBB: Signed")
            except discord.Forbidden:
                pass

async def remove_team_role_fn(member, guild, team_id):
    role_id = await get_team_role(team_id)
    if role_id:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.remove_roles(role, reason="HCBB: Released/Traded")
            except discord.Forbidden:
                pass

async def swap_team_roles(member, guild, from_team_id, to_team_id):
    await remove_team_role_fn(member, guild, from_team_id)
    await add_team_role(member, guild, to_team_id)

# ── Bot ───────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── TEAM COMMANDS ─────────────────────────────────────────────────
@bot.tree.command(name="team_create", description="Create a new league team")
@app_commands.describe(name="Full team name", abbreviation="3-4 letter abbreviation", logo_url="Optional logo URL")
@app_commands.checks.has_permissions(manage_guild=True)
async def team_create(interaction: discord.Interaction, name: str, abbreviation: str, logo_url: str = None):
    await interaction.response.defer()
    abbreviation = abbreviation.upper()
    db = await get_db()
    cur = await db.execute("SELECT id FROM teams WHERE name=? OR abbreviation=?", (name, abbreviation))
    if await cur.fetchone():
        return await interaction.followup.send(embed=error_embed("Team Exists", "Name or abbreviation already taken."))
    await db.execute("INSERT INTO teams (name, abbreviation, owner_id, logo_url) VALUES (?,?,?,?)",
                     (name, abbreviation, interaction.user.id, logo_url))
    await db.commit()
    e = success_embed("Team Created!", f"**{name}** `[{abbreviation}]` added to the league.")
    if logo_url:
        e.set_thumbnail(url=logo_url)
    e.add_field(name="Owner", value=interaction.user.mention)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="team_info", description="View a team's info and roster")
@app_commands.describe(name="Team name or abbreviation")
async def team_info(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT * FROM teams WHERE name=? OR abbreviation=?", (name, name.upper()))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Not Found", f"No team named `{name}`."))
    cur2 = await db.execute("SELECT username, position FROM players WHERE team_id=?", (team[0],))
    roster = await cur2.fetchall()
    owner = interaction.guild.get_member(team[3])
    e = base_embed(f"⚾ {team[1]}  `{team[2]}`")
    if team[4]:
        e.set_thumbnail(url=team[4])
    e.add_field(name="Owner/GM", value=owner.mention if owner else f"<@{team[3]}>")
    e.add_field(name="Record", value=f"**{team[5]}W - {team[6]}L**")
    e.add_field(name="Roster Size", value=str(len(roster)))
    if roster:
        lines = [f"{POSITION_EMOJIS.get(pos,'⚾')} **{u}** — {pos}" for u, pos in roster]
        e.add_field(name="Roster", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Roster", value="_No players yet._", inline=False)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="standings", description="View league standings")
async def standings(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT name, abbreviation, wins, losses FROM teams ORDER BY wins DESC, losses ASC")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Teams Yet"))
    e = base_embed("🏆 League Standings")
    medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 20)]
    lines = []
    for i, (name, abbr, w, l) in enumerate(rows, 1):
        pct = (w / (w+l)) if (w+l) else 0.0
        lines.append(f"{medals[i-1]} **{name}** `{abbr}` — {w}W {l}L  *(PCT: {pct:.3f})*")
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="team_delete", description="[ADMIN] Delete a team")
@app_commands.describe(abbreviation="Team abbreviation")
@app_commands.checks.has_permissions(administrator=True)
async def team_delete(interaction: discord.Interaction, abbreviation: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (abbreviation.upper(),))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Not Found"))
    await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE team_id=?", (team[0],))
    await db.execute("DELETE FROM teams WHERE id=?", (team[0],))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Team Deleted", f"**{team[1]}** removed. Players are now free agents."))


# ── FRANCHISE OWNERS ──────────────────────────────────────────────
@bot.tree.command(name="set_owner", description="[ADMIN] Set the franchise owner of a team")
@app_commands.describe(team_abbr="Team abbreviation", owner="The franchise owner to assign")
@app_commands.checks.has_permissions(administrator=True)
async def set_owner(interaction: discord.Interaction, team_abbr: str, owner: discord.Member):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (team_abbr.upper(),))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"No team with abbreviation `{team_abbr.upper()}`."))
    await db.execute("UPDATE teams SET owner_id=? WHERE id=?", (owner.id, team[0]))
    await db.commit()
    e = success_embed("Franchise Owner Set 👑",
        f"**{owner.display_name}** is now the franchise owner of **{team[1]}** `[{team_abbr.upper()}]`.")
    e.set_thumbnail(url=owner.display_avatar.url)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="owners", description="View all franchise owners across the league")
async def owners(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute(
        "SELECT name, abbreviation, owner_id FROM teams ORDER BY name"
    )
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Teams", "No teams registered yet."))

    e = base_embed("👑 Franchise Owners", f"**{len(rows)} teams in the league**")
    lines = []
    for name, abbr, owner_id in rows:
        member = interaction.guild.get_member(owner_id)
        if member:
            owner_str = f"{member.mention} `{member.display_name}`"
        elif owner_id and owner_id != 0:
            owner_str = f"<@{owner_id}>"
        else:
            owner_str = "_No owner set_"
        lines.append(f"**{name}** `[{abbr}]` — {owner_str}")
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

# ── PLAYER COMMANDS ───────────────────────────────────────────────
@bot.tree.command(name="register", description="Register yourself as an HCBB league player")
@app_commands.describe(position="Your primary position")
@app_commands.choices(position=[app_commands.Choice(name=p, value=p) for p in POSITIONS])
async def register(interaction: discord.Interaction, position: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (interaction.user.id,))
    if await cur.fetchone():
        return await interaction.followup.send(embed=warn_embed("Already Registered", "You're already in the league."))
    await db.execute("INSERT INTO players (discord_id, username, position) VALUES (?,?,?)",
                     (interaction.user.id, interaction.user.display_name, position))
    await db.commit()
    e = success_embed("Registered!", f"Welcome **{interaction.user.display_name}**!\n{POSITION_EMOJIS.get(position,'⚾')} Position: **{position}**\nStatus: **Free Agent**")
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="sign", description="[GM] Sign a free agent to your team")
@app_commands.describe(player="Player to sign", team_abbr="Your team abbreviation")
async def sign(interaction: discord.Interaction, player: discord.Member, team_abbr: str):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=? AND owner_id=?",
                           (team_abbr.upper(), interaction.user.id))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "You don't own that team."))
    cur2 = await db.execute("SELECT id, username, free_agent, team_id FROM players WHERE discord_id=?", (player.id,))
    p = await cur2.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{player.mention} hasn't used `/register` yet."))
    if not p[2]:
        cur3 = await db.execute("SELECT name FROM teams WHERE id=?", (p[3],))
        ct = await cur3.fetchone()
        return await interaction.followup.send(embed=error_embed("Not a Free Agent", f"{player.mention} is already on **{ct[0] if ct else 'a team'}**."))
    await db.execute("UPDATE players SET team_id=?, free_agent=0 WHERE discord_id=?", (team[0], player.id))
    await db.execute("INSERT INTO transactions (player_id, to_team, type) VALUES (?,?,?)", (p[0], team[0], "SIGN"))
    await db.commit()
    await add_team_role(player, interaction.guild, team[0])
    e = success_embed("Player Signed! ✍️", f"{player.mention} signed to **{team[1]}** `[{team_abbr.upper()}]`!")
    e.set_thumbnail(url=player.display_avatar.url)
    await interaction.followup.send(embed=e)
    tx = base_embed("✍️ Transaction Wire", color=0x2ECC71)
    tx.add_field(name="Type", value="**SIGNED**")
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`")
    tx.add_field(name="Team", value=f"**{team[1]}** `[{team_abbr.upper()}]`")
    tx.set_thumbnail(url=player.display_avatar.url)
    await post_transaction(interaction.guild, config, tx)

@bot.tree.command(name="release", description="[GM] Release a player from your team")
@app_commands.describe(player="Player to release", team_abbr="Your team abbreviation")
async def release(interaction: discord.Interaction, player: discord.Member, team_abbr: str):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=? AND owner_id=?",
                           (team_abbr.upper(), interaction.user.id))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Not Authorized"))
    cur2 = await db.execute("SELECT id FROM players WHERE discord_id=? AND team_id=?", (player.id, team[0]))
    p = await cur2.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not On Team", f"{player.mention} isn't on **{team[1]}**."))
    await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE discord_id=?", (player.id,))
    await db.execute("INSERT INTO transactions (player_id, from_team, type) VALUES (?,?,?)", (p[0], team[0], "RELEASE"))
    await db.commit()
    await remove_team_role_fn(player, interaction.guild, team[0])
    await interaction.followup.send(embed=success_embed("Released 🚪", f"{player.mention} released from **{team[1]}** — now a Free Agent."))
    tx = base_embed("🚪 Transaction Wire", color=0xFF6B35)
    tx.add_field(name="Type", value="**RELEASED**")
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`")
    tx.add_field(name="From", value=f"**{team[1]}** `[{team_abbr.upper()}]`")
    tx.add_field(name="Status", value="🆓 Free Agent")
    tx.set_thumbnail(url=player.display_avatar.url)
    await post_transaction(interaction.guild, config, tx)

@bot.tree.command(name="trade", description="[ADMIN] Trade a player between teams")
@app_commands.describe(player="Player to trade", from_team="From team abbreviation", to_team="To team abbreviation")
@app_commands.checks.has_permissions(administrator=True)
async def trade(interaction: discord.Interaction, player: discord.Member, from_team: str, to_team: str):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    db = await get_db()
    cur1 = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (from_team.upper(),))
    ft = await cur1.fetchone()
    cur2 = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (to_team.upper(),))
    tt = await cur2.fetchone()
    if not ft or not tt:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    cur3 = await db.execute("SELECT id FROM players WHERE discord_id=? AND team_id=?", (player.id, ft[0]))
    p = await cur3.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Player Not Found", f"{player.mention} isn't on **{ft[1]}**."))
    await db.execute("UPDATE players SET team_id=? WHERE discord_id=?", (tt[0], player.id))
    await db.execute("INSERT INTO transactions (player_id, from_team, to_team, type) VALUES (?,?,?,?)",
                     (p[0], ft[0], tt[0], "TRADE"))
    await db.commit()
    await swap_team_roles(player, interaction.guild, ft[0], tt[0])
    await interaction.followup.send(embed=success_embed("Trade Complete 🔄", f"{player.mention} traded\n**{ft[1]}** → **{tt[1]}**"))
    tx = base_embed("🔄 Transaction Wire", color=0x9B59B6)
    tx.add_field(name="Type", value="**TRADED**")
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`")
    tx.add_field(name="From", value=f"**{ft[1]}** `[{from_team.upper()}]`", inline=False)
    tx.add_field(name="To", value=f"**{tt[1]}** `[{to_team.upper()}]`")
    tx.set_thumbnail(url=player.display_avatar.url)
    await post_transaction(interaction.guild, config, tx)

@bot.tree.command(name="profile", description="View a player's profile and stats")
@app_commands.describe(player="Leave blank for your own profile")
async def profile(interaction: discord.Interaction, player: discord.Member = None):
    await interaction.response.defer()
    target = player or interaction.user
    db = await get_db()
    cur = await db.execute("SELECT * FROM players WHERE discord_id=?", (target.id,))
    p = await cur.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{target.mention} hasn't registered."))
    team_name = "Free Agent 🆓"
    if p[4]:
        cur2 = await db.execute("SELECT name, abbreviation FROM teams WHERE id=?", (p[4],))
        t = await cur2.fetchone()
        team_name = f"{t[0]} `[{t[1]}]`" if t else "Free Agent 🆓"
    e = base_embed(f"{POSITION_EMOJIS.get(p[3],'⚾')} {target.display_name}'s Profile")
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="Position", value=p[3])
    e.add_field(name="Team", value=team_name)
    e.add_field(name="Games Played", value=str(p[10]))
    e.add_field(name="── Batting ──", value="\u200b", inline=False)
    e.add_field(name="AVG", value=f"{p[5]:.3f}")
    e.add_field(name="HR", value=str(p[6]))
    e.add_field(name="RBI", value=str(p[7]))
    e.add_field(name="── Pitching ──", value="\u200b", inline=False)
    e.add_field(name="ERA", value=f"{p[8]:.2f}")
    e.add_field(name="K", value=str(p[9]))
    await interaction.followup.send(embed=e)

@bot.tree.command(name="free_agents", description="List all free agents")
async def free_agents(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT discord_id, username, position FROM players WHERE free_agent=1 ORDER BY position")
    fas = await cur.fetchall()
    fa_role = interaction.guild.get_role(FA_ROLE_ID)
    fa_role_str = f"{fa_role.mention} — " if fa_role else ""
    if not fas:
        return await interaction.followup.send(embed=warn_embed("No Free Agents", f"{fa_role_str}Everyone is signed!"))
    e = base_embed("🆓 Free Agent Board", f"{fa_role_str}**{len(fas)} available players**")
    lines = [f"{POSITION_EMOJIS.get(pos,'⚾')} **{u}** — {pos}  (<@{did}>)" for did, u, pos in fas]
    e.description += "\n\n" + "\n".join(lines)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="transactions", description="View recent transactions")
async def transactions(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT t.type, p.username, ft.name, tt.name, t.created_at
        FROM transactions t
        JOIN players p ON p.id = t.player_id
        LEFT JOIN teams ft ON ft.id = t.from_team
        LEFT JOIN teams tt ON tt.id = t.to_team
        ORDER BY t.created_at DESC LIMIT 15
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Transactions Yet"))
    icons = {"SIGN":"✍️","RELEASE":"🚪","TRADE":"🔄"}
    lines = []
    for tx_type, username, from_t, to_t, ts in rows:
        date = ts[:10] if ts else "?"
        if tx_type == "SIGN":
            lines.append(f"{icons[tx_type]} `{date}` **{username}** signed to **{to_t}**")
        elif tx_type == "RELEASE":
            lines.append(f"{icons[tx_type]} `{date}` **{username}** released by **{from_t}**")
        elif tx_type == "TRADE":
            lines.append(f"{icons[tx_type]} `{date}` **{username}** traded **{from_t}** → **{to_t}**")
    e = base_embed("📋 Recent Transactions")
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

# ── GAME COMMANDS ─────────────────────────────────────────────────
@bot.tree.command(name="schedule_game", description="[MOD] Schedule a game")
@app_commands.describe(home="Home team abbreviation", away="Away team abbreviation", date="Date/time e.g. June 15 8PM")
@app_commands.checks.has_permissions(manage_guild=True)
async def schedule_game(interaction: discord.Interaction, home: str, away: str, date: str = None):
    await interaction.response.defer()
    db = await get_db()
    cur1 = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (home.upper(),))
    ht = await cur1.fetchone()
    cur2 = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (away.upper(),))
    at = await cur2.fetchone()
    if not ht or not at:
        return await interaction.followup.send(embed=error_embed("Team Not Found", "Check abbreviations."))
    if ht[0] == at[0]:
        return await interaction.followup.send(embed=error_embed("Same Team"))
    cur3 = await db.execute("INSERT INTO games (home_team_id, away_team_id, status, scheduled_at) VALUES (?,?,?,?)",
                            (ht[0], at[0], "scheduled", date))
    await db.commit()
    gid = cur3.lastrowid
    e = success_embed(f"Game #{gid} Scheduled ⚾", f"**{at[1]}** @ **{ht[1]}**")
    if date:
        e.add_field(name="📅 Date/Time", value=date)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="report_game", description="[MOD] Report a game result")
@app_commands.describe(game_id="Game ID", home_score="Home score", away_score="Away score")
@app_commands.checks.has_permissions(manage_guild=True)
async def report_game(interaction: discord.Interaction, game_id: int, home_score: int, away_score: int):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, home_team_id, away_team_id, status FROM games WHERE id=?", (game_id,))
    game = await cur.fetchone()
    if not game:
        return await interaction.followup.send(embed=error_embed("Game Not Found"))
    if game[3] == "final":
        return await interaction.followup.send(embed=warn_embed("Already Reported"))
    await db.execute("UPDATE games SET home_score=?, away_score=?, status='final', played_at=CURRENT_TIMESTAMP WHERE id=?",
                     (home_score, away_score, game_id))
    if home_score > away_score:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (game[1],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (game[2],))
    else:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (game[2],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (game[1],))
    await db.commit()
    cur2 = await db.execute("SELECT name, abbreviation FROM teams WHERE id=?", (game[1],))
    ht = await cur2.fetchone()
    cur3 = await db.execute("SELECT name, abbreviation FROM teams WHERE id=?", (game[2],))
    at = await cur3.fetchone()
    winner = ht if home_score > away_score else at
    loser  = at if home_score > away_score else ht
    e = base_embed(f"⚾ Final — Game #{game_id}", color=0xFFD700)
    e.add_field(name="🏆 Winner", value=f"**{winner[0]}** `{winner[1]}`")
    e.add_field(name="Score", value=f"**{max(home_score,away_score)} - {min(home_score,away_score)}**")
    e.add_field(name="❌ Loser", value=f"{loser[0]} `{loser[1]}`")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="recent_games", description="View recent game results")
async def recent_games(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT g.id, ht.name, ht.abbreviation, at.name, at.abbreviation,
               g.home_score, g.away_score, g.played_at
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.status = 'final' ORDER BY g.played_at DESC LIMIT 10
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Games Yet"))
    e = base_embed("📊 Recent Results")
    lines = []
    for gid, hname, habbr, aname, aabbr, hs, as_, dt in rows:
        date = dt[:10] if dt else "?"
        winner = f"**{hname}**" if hs > as_ else f"**{aname}**"
        lines.append(f"`#{gid}` `{date}` — {aabbr} **{as_}** @ {habbr} **{hs}**  ✅ {winner}")
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="upcoming_games", description="View upcoming scheduled games")
async def upcoming_games(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT g.id, ht.name, ht.abbreviation, at.name, at.abbreviation, g.scheduled_at
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.status = 'scheduled' ORDER BY g.scheduled_at ASC LIMIT 10
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Upcoming Games"))
    e = base_embed("📅 Upcoming Games")
    lines = [f"`#{gid}` **{aname}** `{aabbr}` @ **{hname}** `{habbr}` — 📅 {sched or 'TBD'}"
             for gid, hname, habbr, aname, aabbr, sched in rows]
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="update_stats", description="[MOD] Update a player's stats")
@app_commands.describe(player="Player to update", batting_avg="Batting AVG", home_runs="Home runs",
                       rbi="RBIs", era="ERA", strikeouts="Strikeouts", games_played="Games played")
@app_commands.checks.has_permissions(manage_guild=True)
async def update_stats(interaction: discord.Interaction, player: discord.Member,
                       batting_avg: float = None, home_runs: int = None, rbi: int = None,
                       era: float = None, strikeouts: int = None, games_played: int = None):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (player.id,))
    if not await cur.fetchone():
        return await interaction.followup.send(embed=error_embed("Not Registered"))
    updates, values = [], []
    if batting_avg  is not None: updates.append("batting_avg=?");  values.append(batting_avg)
    if home_runs    is not None: updates.append("home_runs=?");     values.append(home_runs)
    if rbi          is not None: updates.append("rbi=?");           values.append(rbi)
    if era          is not None: updates.append("era=?");           values.append(era)
    if strikeouts   is not None: updates.append("strikeouts=?");    values.append(strikeouts)
    if games_played is not None: updates.append("games_played=?");  values.append(games_played)
    if not updates:
        return await interaction.followup.send(embed=warn_embed("Nothing to Update"))
    values.append(player.id)
    await db.execute(f"UPDATE players SET {', '.join(updates)} WHERE discord_id=?", values)
    await db.commit()
    await interaction.followup.send(embed=success_embed("Stats Updated", f"**{player.display_name}**'s stats updated."))

# ── LEADERBOARD & ADMIN ───────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="View player stat leaderboard")
@app_commands.describe(category="Stat category")
@app_commands.choices(category=[
    app_commands.Choice(name="Home Runs",    value="home_runs"),
    app_commands.Choice(name="Batting Avg",  value="batting_avg"),
    app_commands.Choice(name="RBI",          value="rbi"),
    app_commands.Choice(name="ERA",          value="era"),
    app_commands.Choice(name="Strikeouts",   value="strikeouts"),
    app_commands.Choice(name="Games Played", value="games_played"),
])
async def leaderboard(interaction: discord.Interaction, category: str):
    await interaction.response.defer()
    order = "ASC" if category == "era" else "DESC"
    label_map = {
        "home_runs":    ("🏠 Home Run Leaders",       "HR"),
        "batting_avg":  ("🥇 Batting Average Leaders", "AVG"),
        "rbi":          ("💥 RBI Leaders",             "RBI"),
        "era":          ("⚾ ERA Leaders",              "ERA"),
        "strikeouts":   ("🌀 Strikeout Leaders",       "K"),
        "games_played": ("🎮 Games Played Leaders",    "G"),
    }
    title, stat_label = label_map[category]
    db = await get_db()
    cur = await db.execute(f"""
        SELECT p.username, p.{category}, t.abbreviation
        FROM players p LEFT JOIN teams t ON t.id = p.team_id
        ORDER BY p.{category} {order} LIMIT 10
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Stats Yet"))
    medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 11)]
    e = base_embed(title)
    lines = []
    for i, (username, val, abbr) in enumerate(rows):
        team_str = f"`[{abbr}]`" if abbr else "*(FA)*"
        fmt = f"{val:.3f}" if category == "batting_avg" else (f"{val:.2f}" if category == "era" else str(val))
        lines.append(f"{medals[i]} **{username}** {team_str} — {stat_label}: **{fmt}**")
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="reset_season", description="[ADMIN] Reset all records and stats")
@app_commands.checks.has_permissions(administrator=True)
async def reset_season(interaction: discord.Interaction):
    view = ConfirmView()
    await interaction.response.send_message(
        embed=warn_embed("Confirm Season Reset", "Wipes **all wins/losses and player stats**. Cannot be undone."),
        view=view, ephemeral=True
    )
    await view.wait()
    if view.confirmed:
        db = await get_db()
        await db.execute("UPDATE teams SET wins=0, losses=0")
        await db.execute("UPDATE players SET batting_avg=0, home_runs=0, rbi=0, era=0, strikeouts=0, games_played=0")
        await db.execute("UPDATE games SET status='archived' WHERE status='final'")
        await db.commit()
        await interaction.followup.send(embed=success_embed("Season Reset!", "All records wiped. New season! ⚾"))
    else:
        await interaction.followup.send(embed=base_embed("Reset Cancelled."), ephemeral=True)

@bot.tree.command(name="leaguehelp", description="Show all league bot commands")
async def leaguehelp(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    e = base_embed("⚾ HCBB 9v9 2.0 — Command Guide")
    e.add_field(name="👤 Players", inline=False, value="`/register` `/profile` `/free_agents` `/transactions`")
    e.add_field(name="🏟️ Teams",  inline=False, value="`/team_info` `/standings`")
    e.add_field(name="📋 Games",   inline=False, value="`/upcoming_games` `/recent_games` `/leaderboard`")
    e.add_field(name="⚙️ GM/Mod", inline=False, value="`/sign` `/release` `/team_create` `/schedule_game` `/report_game` `/update_stats`")
    e.add_field(name="🔒 Admin",   inline=False, value="`/trade` `/team_delete` `/reset_season` `/set_transactions_channel` `/set_team_role` `/remove_team_role` `/league_config`")
    await interaction.followup.send(embed=e)

# ── CONFIG COMMANDS ───────────────────────────────────────────────
@bot.tree.command(name="set_transactions_channel", description="[ADMIN] Set the transactions announcement channel")
@app_commands.describe(channel="Channel to post announcements in")
@app_commands.checks.has_permissions(administrator=True)
async def set_transactions_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        INSERT INTO config (guild_id, transactions_channel) VALUES (?,?)
        ON CONFLICT(guild_id) DO UPDATE SET transactions_channel=excluded.transactions_channel
    """, (interaction.guild.id, channel.id))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Channel Set ✅", f"Transactions will post in {channel.mention}."))

@bot.tree.command(name="set_team_role", description="[ADMIN] Link a Discord role to a team")
@app_commands.describe(team_abbr="Team abbreviation", role="Role to assign to players on this team")
@app_commands.checks.has_permissions(administrator=True)
async def set_team_role(interaction: discord.Interaction, team_abbr: str, role: discord.Role):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (team_abbr.upper(),))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    await db.execute("""
        INSERT INTO team_roles (team_id, role_id) VALUES (?,?)
        ON CONFLICT(team_id) DO UPDATE SET role_id=excluded.role_id
    """, (team[0], role.id))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Team Role Linked 🎽",
        f"{role.mention} linked to **{team[1]}** `[{team_abbr.upper()}]`."))

@bot.tree.command(name="remove_team_role", description="[ADMIN] Unlink a role from a team")
@app_commands.describe(team_abbr="Team abbreviation")
@app_commands.checks.has_permissions(administrator=True)
async def remove_team_role(interaction: discord.Interaction, team_abbr: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name FROM teams WHERE abbreviation=?", (team_abbr.upper(),))
    team = await cur.fetchone()
    if not team:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    await db.execute("DELETE FROM team_roles WHERE team_id=?", (team[0],))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Role Removed", f"Role unlinked from **{team[1]}**."))

@bot.tree.command(name="league_config", description="[ADMIN] View current bot config")
@app_commands.checks.has_permissions(administrator=True)
async def league_config(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    db = await get_db()
    cur = await db.execute("SELECT transactions_channel FROM config WHERE guild_id=?", (interaction.guild.id,))
    cfg = await cur.fetchone()
    cur2 = await db.execute("""
        SELECT t.name, t.abbreviation, tr.role_id FROM team_roles tr
        JOIN teams t ON t.id = tr.team_id ORDER BY t.name
    """)
    team_roles = await cur2.fetchall()
    e = base_embed("⚙️ League Config")
    e.add_field(name="📢 Transactions Channel",
                value=f"<#{cfg[0]}>" if cfg and cfg[0] else "❌ Not set", inline=False)
    if team_roles:
        lines = [f"**{n}** `[{a}]` → <@&{rid}>" for n, a, rid in team_roles]
        e.add_field(name="🎽 Team Roles", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="🎽 Team Roles", value="None set yet.", inline=False)
    await interaction.followup.send(embed=e)

# ── CONFIRM VIEW ──────────────────────────────────────────────────
class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.confirmed = False

    @discord.ui.button(label="Yes, Reset", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.defer()

# ── START ─────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await init_db()
    # Sync globally — shows up in all servers, no guild copy needed
    synced = await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Synced {len(synced)} commands globally.")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="⚾ HCBB 9v9 2.0 League"
    ))

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
