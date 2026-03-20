import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
import os

TOKEN = os.environ.get("DISCORD_TOKEN", "PASTE_YOUR_TOKEN_HERE")
DB_PATH = "/app/data/league.db"

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


async def get_team_by_role(role: discord.Role):
    db = await get_db()
    cur = await db.execute("""
        SELECT t.id, t.name, t.abbreviation, t.owner_id
        FROM team_roles tr
        JOIN teams t ON t.id = tr.team_id
        WHERE tr.role_id=?
    """, (role.id,))
    return await cur.fetchone()

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
@app_commands.describe(team="The team")
async def team_info(interaction: discord.Interaction, team: discord.Role):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Not Found", f"{team.mention} isn't linked to a team."))
    db = await get_db()
    cur2 = await db.execute("SELECT username, position FROM players WHERE team_id=? ORDER BY position", (row[0],))
    roster = await cur2.fetchall()
    cur3 = await db.execute("SELECT * FROM teams WHERE id=?", (row[0],))
    full = await cur3.fetchone()
    owner = interaction.guild.get_member(row[3])
    e = discord.Embed(title=f"⚾  {row[1]}", color=team.color if team.color.value else BRAND_COLOR)
    e.add_field(name="👑 Owner", value=owner.mention if owner else f"<@{row[3]}>", inline=True)
    e.add_field(name="📊 Record", value=f"**{full[5]}W — {full[6]}L**", inline=True)
    e.add_field(name="👥 Roster", value=f"**{len(roster)}/20**", inline=True)
    if roster:
        lines = [f"{POSITION_EMOJIS.get(pos,'⚾')} **{u}** — `{pos}`" for u, pos in roster]
        e.add_field(name="Players", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Players", value="_No players signed yet._", inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="standings", description="View league standings")
async def standings(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT name, abbreviation, wins, losses FROM teams ORDER BY wins DESC, losses ASC")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Teams Yet"))
    medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 20)]
    lines = []
    for i, (name, abbr, w, l) in enumerate(rows, 1):
        total = w + l
        pct = (w / total) if total else 0.0
        gb = ((rows[0][2] - rows[0][3]) - (w - l)) / 2 if i > 1 else "-"
        gb_str = f"GB: {gb:.1f}" if isinstance(gb, float) else "GB: —"
        lines.append(f"{medals[i-1]} **{name}** — `{w}W {l}L` · PCT: `{pct:.3f}` · {gb_str}")
    e = discord.Embed(title="🏆  League Standings", description="\n".join(lines), color=0xFFD700)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="team_delete", description="[ADMIN] Delete a team")
@app_commands.describe(team="The team role e.g. @Dallas Panthers")
@app_commands.checks.has_permissions(administrator=True)
async def team_delete(interaction: discord.Interaction, team: discord.Role):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Not Found", f"{team.mention} isn't linked to a team."))
    db = await get_db()
    await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE team_id=?", (row[0],))
    await db.execute("DELETE FROM teams WHERE id=?", (row[0],))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Team Deleted", f"**{row[1]}** removed. Players are now free agents."))


# ── FRANCHISE OWNERS ──────────────────────────────────────────────
@bot.tree.command(name="set_owner", description="[ADMIN] Set the franchise owner of a team")
@app_commands.describe(team="The team role (e.g. @Dallas Panthers)", owner="The franchise owner to assign")
@app_commands.checks.has_permissions(administrator=True)
async def set_owner(interaction: discord.Interaction, team: discord.Role, owner: discord.Member):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name, abbreviation FROM team_roles tr JOIN teams t ON t.id = tr.team_id WHERE tr.role_id=?", (team.id,))
    row = await cur.fetchone()
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to any team. Use `/set_team_role` first."))
    await db.execute("UPDATE teams SET owner_id=? WHERE id=?", (owner.id, row[0]))
    await db.commit()
    e = success_embed("Franchise Owner Set 👑",
        f"**{owner.display_name}** is now the franchise owner of **{row[1]}** `[{row[2]}]`.")
    e.set_thumbnail(url=owner.display_avatar.url)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="owners", description="View all franchise owners across the league")
async def owners(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT name, abbreviation, owner_id FROM teams ORDER BY name")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Teams", "No teams registered yet."))
    e = discord.Embed(title="👑  Franchise Owners", color=0xFFD700)
    for name, abbr, owner_id in rows:
        member = interaction.guild.get_member(owner_id)
        if member:
            val = f"{member.mention}"
        elif owner_id and owner_id != 0:
            val = f"<@{owner_id}>"
        else:
            val = "_Not set_"
        e.add_field(name=f"{name}", value=val, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
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

@bot.tree.command(name="sign", description="Sign a free agent to your team")
@app_commands.describe(player="Player to sign", team="Your team")
async def sign(interaction: discord.Interaction, player: discord.Member, team: discord.Role):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    if row[3] != interaction.user.id:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "You must be the franchise owner to sign players."))
    db = await get_db()
    # Check roster size
    cur_count = await db.execute("SELECT COUNT(*) FROM players WHERE team_id=?", (row[0],))
    count = (await cur_count.fetchone())[0]
    if count >= 20:
        return await interaction.followup.send(embed=error_embed("Roster Full", f"**{row[1]}** already has **{count}/20** players. Release someone first."))
    cur2 = await db.execute("SELECT id, username, free_agent, team_id, position FROM players WHERE discord_id=?", (player.id,))
    p = await cur2.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{player.mention} hasn't registered yet. They need to use `/register` first."))
    if not p[2]:
        cur3 = await db.execute("SELECT name FROM teams WHERE id=?", (p[3],))
        ct = await cur3.fetchone()
        return await interaction.followup.send(embed=error_embed("Not a Free Agent", f"{player.mention} is already on **{ct[0] if ct else 'a team'}**. They must be released first."))
    await db.execute("UPDATE players SET team_id=?, free_agent=0 WHERE discord_id=?", (row[0], player.id))
    await db.execute("INSERT INTO transactions (player_id, to_team, type) VALUES (?,?,?)", (p[0], row[0], "SIGN"))
    await db.commit()
    await add_team_role(player, interaction.guild, row[0])
    e = discord.Embed(color=0x2ECC71)
    e.set_author(name="Player Signed", icon_url="https://cdn.discordapp.com/emojis/1234567890.png")
    e.set_thumbnail(url=player.display_avatar.url)
    e.add_field(name="Player", value=f"{player.mention}", inline=True)
    e.add_field(name="Position", value=p[4], inline=True)
    e.add_field(name="Team", value=team.mention, inline=True)
    e.add_field(name="Roster", value=f"{count+1}/20", inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction")
    await interaction.followup.send(embed=e)
    tx = discord.Embed(color=0x2ECC71)
    tx.set_author(name="✍️  SIGNED")
    tx.set_thumbnail(url=player.display_avatar.url)
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`", inline=False)
    tx.add_field(name="Team", value=team.mention, inline=True)
    tx.add_field(name="Position", value=p[4], inline=True)
    tx.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction Wire")
    await post_transaction(interaction.guild, config, tx)

@bot.tree.command(name="release", description="Release a player from your team")
@app_commands.describe(player="Player to release", team="Your team")
async def release(interaction: discord.Interaction, player: discord.Member, team: discord.Role):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    if row[3] != interaction.user.id:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "You must be the franchise owner to release players."))
    db = await get_db()
    cur2 = await db.execute("SELECT id, position FROM players WHERE discord_id=? AND team_id=?", (player.id, row[0]))
    p = await cur2.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not On Team", f"{player.mention} is not on **{row[1]}**."))
    await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE discord_id=?", (player.id,))
    await db.execute("INSERT INTO transactions (player_id, from_team, type) VALUES (?,?,?)", (p[0], row[0], "RELEASE"))
    await db.commit()
    await remove_team_role_fn(player, interaction.guild, row[0])
    e = discord.Embed(color=0xFF6B35)
    e.set_thumbnail(url=player.display_avatar.url)
    e.set_author(name="Player Released")
    e.add_field(name="Player", value=player.mention, inline=True)
    e.add_field(name="Position", value=p[1], inline=True)
    e.add_field(name="Former Team", value=team.mention, inline=True)
    e.add_field(name="Status", value="🆓 Free Agent", inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction")
    await interaction.followup.send(embed=e)
    tx = discord.Embed(color=0xFF6B35)
    tx.set_author(name="🚪  RELEASED")
    tx.set_thumbnail(url=player.display_avatar.url)
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`", inline=False)
    tx.add_field(name="Former Team", value=team.mention, inline=True)
    tx.add_field(name="Status", value="🆓 Free Agent", inline=True)
    tx.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction Wire")
    await post_transaction(interaction.guild, config, tx)

@bot.tree.command(name="trade", description="Trade a player between teams")
@app_commands.describe(player="Player to trade", from_team="Team trading the player", to_team="Team receiving the player")
@app_commands.checks.has_permissions(administrator=True)
async def trade(interaction: discord.Interaction, player: discord.Member, from_team: discord.Role, to_team: discord.Role):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    ft = await get_team_by_role(from_team)
    tt = await get_team_by_role(to_team)
    if not ft or not tt:
        return await interaction.followup.send(embed=error_embed("Team Not Found", "One or both roles aren't linked to a team."))
    db = await get_db()
    # Check receiving team roster size
    cur_count = await db.execute("SELECT COUNT(*) FROM players WHERE team_id=?", (tt[0],))
    count = (await cur_count.fetchone())[0]
    if count >= 20:
        return await interaction.followup.send(embed=error_embed("Roster Full", f"**{tt[1]}** already has **{count}/20** players."))
    cur3 = await db.execute("SELECT id, position FROM players WHERE discord_id=? AND team_id=?", (player.id, ft[0]))
    p = await cur3.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Player Not Found", f"{player.mention} isn't on **{ft[1]}**."))
    await db.execute("UPDATE players SET team_id=? WHERE discord_id=?", (tt[0], player.id))
    await db.execute("INSERT INTO transactions (player_id, from_team, to_team, type) VALUES (?,?,?,?)",
                     (p[0], ft[0], tt[0], "TRADE"))
    await db.commit()
    await swap_team_roles(player, interaction.guild, ft[0], tt[0])
    e = discord.Embed(color=0x9B59B6)
    e.set_author(name="Trade Completed")
    e.set_thumbnail(url=player.display_avatar.url)
    e.add_field(name="Player", value=player.mention, inline=True)
    e.add_field(name="Position", value=p[1], inline=True)
    e.add_field(name="​", value="​", inline=True)
    e.add_field(name="From", value=from_team.mention, inline=True)
    e.add_field(name="To", value=to_team.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction")
    await interaction.followup.send(embed=e)
    tx = discord.Embed(color=0x9B59B6)
    tx.set_author(name="🔄  TRADED")
    tx.set_thumbnail(url=player.display_avatar.url)
    tx.add_field(name="Player", value=f"{player.mention} `{player.display_name}`", inline=False)
    tx.add_field(name="From", value=from_team.mention, inline=True)
    tx.add_field(name="→ To", value=to_team.mention, inline=True)
    tx.set_footer(text="⚾ HCBB 9v9 2.0 League • Transaction Wire")
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
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{target.mention} hasn't registered yet."))
    team_name = "🆓 Free Agent"
    team_color = BRAND_COLOR
    if p[4]:
        cur2 = await db.execute("SELECT name, abbreviation FROM teams WHERE id=?", (p[4],))
        t = await cur2.fetchone()
        team_name = f"{t[0]}" if t else "🆓 Free Agent"
    emoji = POSITION_EMOJIS.get(p[3], "⚾")
    e = discord.Embed(color=team_color)
    e.set_author(name=f"{target.display_name}", icon_url=target.display_avatar.url)
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="Position", value=f"{emoji} {p[3]}", inline=True)
    e.add_field(name="Team", value=team_name, inline=True)
    e.add_field(name="Games", value=str(p[10]), inline=True)
    e.add_field(name="⸻ Batting", value="\u200b", inline=False)
    e.add_field(name="AVG", value=f"`{p[5]:.3f}`", inline=True)
    e.add_field(name="HR", value=f"`{p[6]}`", inline=True)
    e.add_field(name="RBI", value=f"`{p[7]}`", inline=True)
    e.add_field(name="⸻ Pitching", value="\u200b", inline=False)
    e.add_field(name="ERA", value=f"`{p[8]:.2f}`", inline=True)
    e.add_field(name="K", value=f"`{p[9]}`", inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
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
@app_commands.describe(home="Home team role", away="Away team role", date="Date/time e.g. June 15 8PM")
@app_commands.checks.has_permissions(manage_guild=True)
async def schedule_game(interaction: discord.Interaction, home: discord.Role, away: discord.Role, date: str = None):
    await interaction.response.defer()
    ht = await get_team_by_role(home)
    at = await get_team_by_role(away)
    if not ht or not at:
        return await interaction.followup.send(embed=error_embed("Team Not Found", "One or both roles aren't linked to a team."))
    if ht[0] == at[0]:
        return await interaction.followup.send(embed=error_embed("Same Team"))
    db = await get_db()
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
@app_commands.describe(team_abbr="Team abbreviation (e.g. DAL)", role="Role to assign to players on this team")
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
        f"{role.mention} linked to **{team[1]}**."))

@bot.tree.command(name="remove_team_role", description="[ADMIN] Unlink a role from a team")
@app_commands.describe(role="The team role to unlink")
@app_commands.checks.has_permissions(administrator=True)
async def remove_team_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer()
    row = await get_team_by_role(role)
    if not row:
        return await interaction.followup.send(embed=error_embed("Not Found", f"{role.mention} isn't linked to any team."))
    db = await get_db()
    await db.execute("DELETE FROM team_roles WHERE team_id=?", (row[0],))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Role Removed", f"Role unlinked from **{row[1]}**."))

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


@bot.tree.command(name="abbreviations", description="View all team abbreviations")
async def abbreviations(interaction: discord.Interaction):
    await interaction.response.defer()
    e = base_embed("📋 Team Abbreviations")
    lines = [
        "`IOWA` — Iowa Dream",
        "`STL`  — St Louis Archers",
        "`PHI`  — Philadelphia Surge",
        "`SEA`  — Seattle Sonics",
        "`BAL`  — Baltimore Ospreys",
        "`LAR`  — Los Angeles Reapers",
        "`CHI`  — Chicago Ravens",
        "`ARI`  — Arizona Firebirds",
        "`HOU`  — Houston Bulls",
        "`SDT`  — San Diego Tropics",
        "`DAL`  — Dallas Panthers",
    ]
    e.description = "\n".join(lines)
    await interaction.followup.send(embed=e)



@bot.tree.command(name="register_player", description="[ADMIN] Register a player on their behalf")
@app_commands.describe(player="The player to register", position="Their primary position")
@app_commands.choices(position=[app_commands.Choice(name=p, value=p) for p in POSITIONS])
@app_commands.checks.has_permissions(manage_guild=True)
async def register_player(interaction: discord.Interaction, player: discord.Member, position: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (player.id,))
    if await cur.fetchone():
        return await interaction.followup.send(embed=warn_embed("Already Registered", f"{player.mention} is already in the league."))
    await db.execute("INSERT INTO players (discord_id, username, position) VALUES (?,?,?)",
                     (player.id, player.display_name, position))
    await db.commit()
    e = success_embed("Player Registered!", f"{player.mention} registered as **{position}** — now a Free Agent.")
    e.set_thumbnail(url=player.display_avatar.url)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="register_all", description="[ADMIN] Register all members of the server as free agents")
@app_commands.describe(position="Position to assign to everyone")
@app_commands.choices(position=[app_commands.Choice(name=p, value=p) for p in POSITIONS])
@app_commands.checks.has_permissions(manage_guild=True)
async def register_all(interaction: discord.Interaction, position: str):
    await interaction.response.send_message(
        embed=base_embed("⏳ Registering...", "Processing all server members, please wait..."),
    )
    db = await get_db()

    # Get existing player IDs
    cur = await db.execute("SELECT discord_id FROM players")
    existing = set(row[0] for row in await cur.fetchall())

    to_insert = []
    skipped = 0
    # Use guild members cached by discord.py — no API call needed
    for member in interaction.guild.members:
        if member.bot:
            continue
        if member.id in existing:
            skipped += 1
            continue
        to_insert.append((member.id, member.display_name, position))

    if to_insert:
        await db.executemany(
            "INSERT OR IGNORE INTO players (discord_id, username, position) VALUES (?,?,?)",
            to_insert
        )
        await db.commit()

    e = success_embed("Bulk Registration Complete")
    e.add_field(name="Position", value=position, inline=False)
    e.add_field(name="Registered", value=str(len(to_insert)), inline=True)
    e.add_field(name="Already Registered", value=str(skipped), inline=True)
    e.add_field(name="Total Members", value=str(len(to_insert) + skipped), inline=True)
    await interaction.edit_original_response(embed=e)

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
