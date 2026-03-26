import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
import os

TOKEN = os.environ.get("DISCORD_TOKEN", "PASTE_YOUR_TOKEN_HERE")
DB_PATH = os.environ.get("DB_PATH", "league.db")

# ── Persistent DB connection ──────────────────────────────────────
_db = None

async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("PRAGMA journal_mode=WAL")
    return _db

# ── Pre-configured teams and roles ───────────────────────────────
GUILD_ID           = 1464096719867347096
FA_ROLE_ID         = 1464129524210995325
MANAGER_ROLE_ID    = 1484655385607540989
SUSPENSION_ROLE_ID = 1484723857339453471
SUSPENSION_CHANNEL = 1478093960621723730

TEAM_DATA = [
    ("Iowa Dream",              "IOWA", 1478105341899051028),
    ("St Louis Archers",        "STL",  1478111948313989160),
    ("Philadelphia Surge",      "PHI",  1483156350258254084),
    ("Seattle Sonics",          "SEA",  1481717125877071992),
    ("Los Angeles Reapers",     "LAR",  1482413661824745602),
    ("Chicago Ravens",          "CHI",  1483336220544077924),
    ("Arizona Firebirds",       "ARI",  1482435095938732042),
    ("Houston Bulls",           "HOU",  1482465219103166484),
    ("San Diego Tropics",       "SDT",  1483156220369047615),
    ("Dallas Panthers",         "DAL",  1483306097535225956),
    ("Miami Sharks",            "MIA",  1483695684199645256),
    ("San Francisco JailBirds", "SFJ",  1481718381760479446),
]

WESTERN = ["SEA","ARI","SFJ","SDT","DAL","LAR"]
EASTERN = ["IOWA","STL","PHI","MIA","CHI","HOU"]

DIVISION_EMOJIS = {
    "WESTERN": "🌅",
    "EASTERN": "🌆",
}

# Team emoji map
TEAM_EMOJIS = {
    "DAL":  "<:panthers:1483185226174697555>",
    "STL":  "<:StLouisArchers:1478098322244768066>",
    "SEA":  "<:SeattleSonics:1478098221560762468>",
    "LAR":  "<:reapers:1482244326699565058>",
    "SDT":  "<:SanDiegoTropics:1478097958921830522>",
    "PHI":  "<:Philadelphia:1478098432273944787>",
    "ARI":  "<:ArizonaFirebirds:1478097743128956998>",
    "IOWA": "<:IowaDream:1478098067818545244>",
    "HOU":  "<:HoustonBulls:1478100936692994089>",
    "MIA":  "<:MiamiSharks:1478099812875243686>",
    "SFJ":  "<:SanFranciscoJailBirds:1478099356048429099>",
    "CHI":  "<:ChicagoRavens:1478100433456336938>",
}

# Week 1 Schedule — Round 1 — Monday March 30th
WEEK1_SCHEDULE = [
    ("DAL",  "STL",  "LS1 — Monday March 30th 8PM EST"),
    ("SEA",  "LAR",  "LS2 — Monday March 30th 8PM EST"),
    ("SDT",  "PHI",  "LS3 — Monday March 30th 8PM EST"),
    ("ARI",  "IOWA", "LS4 — Monday March 30th 9PM EST"),
    ("HOU",  "MIA",  "LS5 — Monday March 30th 9PM EST"),
    ("SFJ",  "CHI",  "LS6 — Monday March 30th 9PM EST"),
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
            rblx_username TEXT,
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
        CREATE TABLE IF NOT EXISTS game_stats (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      INTEGER REFERENCES games(id),
            player_id    INTEGER REFERENCES players(id),
            batting_avg  REAL,
            home_runs    INTEGER,
            rbi          INTEGER,
            era          REAL,
            strikeouts   INTEGER,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE IF NOT EXISTS team_managers (
            team_id    INTEGER REFERENCES teams(id),
            discord_id INTEGER NOT NULL,
            PRIMARY KEY (team_id, discord_id)
        );
        CREATE TABLE IF NOT EXISTS lineups (
            team_id    INTEGER PRIMARY KEY REFERENCES teams(id),
            lineup     TEXT,
            bullpen    TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suspensions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL,
            reason     TEXT NOT NULL,
            games      INTEGER DEFAULT 0,
            issued_by  INTEGER NOT NULL,
            active     INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await db.commit()

    # Add division column if not exists
    try:
        await db.execute("ALTER TABLE teams ADD COLUMN division TEXT DEFAULT ''")
        await db.commit()
    except:
        pass

    # Remove Baltimore Ospreys if exists
    cur_bal = await db.execute("SELECT id FROM teams WHERE abbreviation='BAL'")
    bal = await cur_bal.fetchone()
    if bal:
        await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE team_id=?", (bal[0],))
        await db.execute("DELETE FROM team_roles WHERE team_id=?", (bal[0],))
        await db.execute("DELETE FROM teams WHERE id=?", (bal[0],))
        await db.commit()
        print("  🗑️ Removed Baltimore Ospreys")

    # Seed teams and link roles
    for name, abbr, role_id in TEAM_DATA:
        division = "WESTERN" if abbr in WESTERN else "EASTERN"
        cur = await db.execute("SELECT id FROM teams WHERE abbreviation=?", (abbr,))
        row = await cur.fetchone()
        if not row:
            cur2 = await db.execute(
                "INSERT INTO teams (name, abbreviation, owner_id, division) VALUES (?,?,?,?)",
                (name, abbr, 0, division)
            )
            team_id = cur2.lastrowid
            print(f"  ✅ Seeded team: {name} [{abbr}] — {division}")
        else:
            team_id = row[0]
            await db.execute("UPDATE teams SET division=? WHERE id=?", (division, team_id))
        await db.execute("""
            INSERT INTO team_roles (team_id, role_id) VALUES (?,?)
            ON CONFLICT(team_id) DO UPDATE SET role_id=excluded.role_id
        """, (team_id, role_id))
    await db.commit()

    # Seed Week 1 schedule if not already added
    cur_sched = await db.execute("SELECT COUNT(*) FROM games WHERE scheduled_at LIKE '%March 30th%'")
    already = (await cur_sched.fetchone())[0]
    if not already:
        for away_abbr, home_abbr, slot in WEEK1_SCHEDULE:
            cur_a = await db.execute("SELECT id FROM teams WHERE abbreviation=?", (away_abbr,))
            away_team = await cur_a.fetchone()
            cur_h = await db.execute("SELECT id FROM teams WHERE abbreviation=?", (home_abbr,))
            home_team = await cur_h.fetchone()
            if away_team and home_team:
                await db.execute(
                    "INSERT INTO games (home_team_id, away_team_id, status, scheduled_at) VALUES (?,?,?,?)",
                    (home_team[0], away_team[0], "scheduled", slot)
                )
                print(f"  📅 Scheduled: {away_abbr} @ {home_abbr} — {slot}")
        await db.commit()
        print("✅ Week 1 schedule seeded.")

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


def is_team_manager(interaction: discord.Interaction) -> bool:
    """Returns True if the user has the Manager role or is an admin."""
    manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
    if manager_role and manager_role in interaction.user.roles:
        return True
    return interaction.user.guild_permissions.administrator

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

@bot.tree.command(name="standings", description="View league standings by division")
async def standings(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT name, abbreviation, wins, losses, division FROM teams ORDER BY division, wins DESC, losses ASC")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Teams Yet"))

    def build_table(teams):
        if not teams:
            return "```No teams```"
        first_w, first_l = teams[0][2], teams[0][3]
        lines = [f"{'#':<3} {'TEAM':<24} {'W':>3} {'L':>3} {'PCT':>6} {'GB':>5}"]
        lines.append("─" * 43)
        for i, (name, abbr, w, l, div) in enumerate(teams, 1):
            total = w + l
            pct = (w / total) if total else 0.0
            if i == 1:
                gb_str = "  —"
            else:
                gb = ((first_w - first_l) - (w - l)) / 2
                gb_str = f"{gb:>4.1f}" if gb > 0 else "  —"
            emoji = TEAM_EMOJIS.get(abbr, "⚾")
            lines.append(f"{i:<3} {name:<24} {w:>3} {l:>3} {pct:>6.3f} {gb_str:>5}")
        return "```" + "\n".join(lines) + "```"

    western = [(n,a,w,l,d) for n,a,w,l,d in rows if d == "WESTERN"]
    eastern = [(n,a,w,l,d) for n,a,w,l,d in rows if d == "EASTERN"]

    e = discord.Embed(color=0xFFD700)
    e.set_author(name="🏆  CLS League — Standings")

    if western:
        w_lines = []
        first_w, first_l = western[0][2], western[0][3]
        for i, (name, abbr, w, l, d) in enumerate(western, 1):
            total = w + l
            pct = (w / total) if total else 0.0
            gb = "—" if i == 1 else f"{((first_w-first_l)-(w-l))/2:.1f}"
            emoji = TEAM_EMOJIS.get(abbr, "⚾")
            w_lines.append(f"`{i}.` {emoji} **{name}** — `{w}W {l}L` · `{pct:.3f}` · GB: `{gb}`")
        e.add_field(name="🌅  Western Conference", value="\n".join(w_lines), inline=False)

    if eastern:
        e_lines = []
        first_w, first_l = eastern[0][2], eastern[0][3]
        for i, (name, abbr, w, l, d) in enumerate(eastern, 1):
            total = w + l
            pct = (w / total) if total else 0.0
            gb = "—" if i == 1 else f"{((first_w-first_l)-(w-l))/2:.1f}"
            emoji = TEAM_EMOJIS.get(abbr, "⚾")
            e_lines.append(f"`{i}.` {emoji} **{name}** — `{w}W {l}L` · `{pct:.3f}` · GB: `{gb}`")
        e.add_field(name="🌆  Eastern Conference", value="\n".join(e_lines), inline=False)

    e.set_footer(text="⚾ HCBB 9v9 2.0 League  ·  Top 3 per division + 2 wild cards advance to playoffs")
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
@app_commands.describe(position="Your primary position", rblx_username="Your Roblox username")
@app_commands.choices(position=[app_commands.Choice(name=p, value=p) for p in POSITIONS])
async def register(interaction: discord.Interaction, position: str, rblx_username: str):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (interaction.user.id,))
    if await cur.fetchone():
        return await interaction.followup.send(embed=warn_embed("Already Registered", "You're already in the league."))
    await db.execute("INSERT INTO players (discord_id, username, rblx_username, position) VALUES (?,?,?,?)",
                     (interaction.user.id, interaction.user.display_name, rblx_username, position))
    await db.commit()
    e = discord.Embed(color=SUCCESS_COLOR)
    e.set_author(name="✅ Player Registered!", icon_url=interaction.user.display_avatar.url)
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    e.add_field(name="Discord", value=interaction.user.mention, inline=True)
    e.add_field(name="Roblox", value=f"`{rblx_username}`", inline=True)
    e.add_field(name="Position", value=f"{POSITION_EMOJIS.get(position,'⚾')} **{position}**", inline=True)
    e.add_field(name="Status", value="🆓 Free Agent", inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
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
    cur = await db.execute("SELECT discord_id, username, rblx_username, position FROM players WHERE free_agent=1 ORDER BY position")
    fas = await cur.fetchall()

    if not fas:
        return await interaction.followup.send("❌ No free agents — everyone is signed!")

    # Build plain text pages of 15
    pages = []
    chunk_size = 15
    for i in range(0, len(fas), chunk_size):
        chunk = fas[i:i + chunk_size]
        lines = [f"🆓 **Free Agents** — {len(fas)} available\n"]
        for did, u, rblx, pos in chunk:
            emoji = POSITION_EMOJIS.get(pos, "⚾")
            rblx_str = f" (`{rblx}`)" if rblx else ""
            lines.append(f"{emoji} **{u}**{rblx_str} — {pos}")
        page_num = len(pages) + 1
        total_pages = -(-len(fas) // chunk_size)
        if total_pages > 1:
            lines.append(f"\nPage {page_num}/{total_pages}")
        pages.append("\n".join(lines))

    view = FAPageView(interaction.user.id, pages)
    await interaction.followup.send(pages[0], view=view)

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

@bot.tree.command(name="report_game", description="Report a game result — owners and managers can use this")
@app_commands.describe(
    home_team="Home team",
    away_team="Away team",
    home_score="Home team score",
    away_score="Away team score"
)
async def report_game(interaction: discord.Interaction, home_team: discord.Role, away_team: discord.Role, home_score: int, away_score: int):
    await interaction.response.defer()
    ht = await get_team_by_role(home_team)
    at = await get_team_by_role(away_team)
    if not ht or not at:
        return await interaction.followup.send(embed=error_embed("Team Not Found", "One or both roles aren't linked to a team."))
    db = await get_db()

    # Check user is owner or manager of one of the two teams, or is admin
    is_admin = interaction.user.guild_permissions.administrator
    is_ht_owner = ht[3] == interaction.user.id
    is_at_owner = at[3] == interaction.user.id
    cur_mgr_ht = await db.execute("SELECT 1 FROM team_managers WHERE team_id=? AND discord_id=?", (ht[0], interaction.user.id))
    cur_mgr_at = await db.execute("SELECT 1 FROM team_managers WHERE team_id=? AND discord_id=?", (at[0], interaction.user.id))
    is_ht_mgr = await cur_mgr_ht.fetchone() is not None
    is_at_mgr = await cur_mgr_at.fetchone() is not None
    if not any([is_admin, is_ht_owner, is_at_owner, is_ht_mgr, is_at_mgr]):
        return await interaction.followup.send(embed=error_embed("Not Authorized", "You must be the owner or manager of one of these teams to report the result."), ephemeral=True)
    # Find the scheduled game between these two teams
    cur = await db.execute("""
        SELECT id FROM games
        WHERE ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
        AND status='scheduled'
        ORDER BY id ASC LIMIT 1
    """, (ht[0], at[0], at[0], ht[0]))
    game = await cur.fetchone()
    if game:
        game_id = game[0]
        await db.execute("UPDATE games SET home_score=?, away_score=?, status='final', played_at=CURRENT_TIMESTAMP WHERE id=?",
                         (home_score, away_score, game_id))
    else:
        # No scheduled game found, just insert a new final
        cur2 = await db.execute(
            "INSERT INTO games (home_team_id, away_team_id, home_score, away_score, status, played_at) VALUES (?,?,?,?,'final',CURRENT_TIMESTAMP)",
            (ht[0], at[0], home_score, away_score)
        )
        game_id = cur2.lastrowid

    if home_score > away_score:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (ht[0],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (at[0],))
        winner, loser = ht, at
        w_score, l_score = home_score, away_score
    else:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (at[0],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (ht[0],))
        winner, loser = at, ht
        w_score, l_score = away_score, home_score
    await db.commit()

    e = discord.Embed(color=0xFFD700)
    e.set_author(name=f"⚾  Final Score — Game #{game_id}")
    e.description = f"**{at[1]}** vs **{ht[1]}**"
    e.add_field(name="🏆 Winner", value=f"**{winner[1]}**", inline=True)
    e.add_field(name="📊 Score", value=f"**{w_score} — {l_score}**", inline=True)
    e.add_field(name="❌ Loser", value=f"**{loser[1]}**", inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="recent_games", description="View recent game results")
async def recent_games(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT g.id, ht.name, at.name, g.home_score, g.away_score, g.played_at
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.status = 'final' ORDER BY g.played_at DESC LIMIT 10
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Games Yet", "No results have been reported yet."))
    e = discord.Embed(title="📊  Recent Results", color=0xFFD700)
    for gid, hname, aname, hs, as_, dt in rows:
        date = dt[:10] if dt else "?"
        if hs > as_:
            result = f"🏆 **{hname}** {hs} — {as_} {aname}"
        else:
            result = f"🏆 **{aname}** {as_} — {hs} {hname}"
        e.add_field(
            name=f"Game #{gid}  ·  {date}",
            value=result,
            inline=False
        )
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="upcoming_games", description="View upcoming scheduled games")
async def upcoming_games(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT ht.name, ht.abbreviation, at.name, at.abbreviation, g.scheduled_at
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.status = 'scheduled' ORDER BY g.id ASC LIMIT 12
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Upcoming Games", "The schedule is empty."))

    from collections import defaultdict
    grouped = defaultdict(list)
    for hname, habbr, aname, aabbr, sched in rows:
        slot = sched or "TBD"
        away_emoji = TEAM_EMOJIS.get(aabbr, "⚾")
        home_emoji = TEAM_EMOJIS.get(habbr, "⚾")
        grouped[slot].append(f"{away_emoji} **{aname}**  `@`  {home_emoji} **{hname}**")

    e = discord.Embed(title="📅  Upcoming Games", color=BRAND_COLOR)
    for slot, games in grouped.items():
        e.add_field(
            name=f"🗓️  {slot}",
            value="\n".join(games),
            inline=False
        )
    e.set_footer(text=f"⚾ HCBB 9v9 2.0 League  ·  {len(rows)} game(s) scheduled")
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


@bot.tree.command(name="set_manager", description="[OWNER] Appoint a player as team manager")
@app_commands.describe(team="Your team", manager="The player to appoint as manager")
async def set_manager(interaction: discord.Interaction, team: discord.Role, manager: discord.Member):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    # Only team owner or admin can appoint
    if row[3] != interaction.user.id and not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "Only the team owner can appoint a manager."))
    # Give them the manager role
    manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
    if manager_role:
        try:
            await manager.add_roles(manager_role, reason=f"HCBB: Appointed manager of {row[1]}")
        except discord.Forbidden:
            return await interaction.followup.send(embed=error_embed("Permission Error", "Bot can't assign the manager role. Make sure bot role is above it."))
    # Store manager in DB
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS team_managers (
            team_id    INTEGER REFERENCES teams(id),
            discord_id INTEGER NOT NULL,
            PRIMARY KEY (team_id, discord_id)
        )
    """)
    await db.execute("INSERT OR IGNORE INTO team_managers (team_id, discord_id) VALUES (?,?)", (row[0], manager.id))
    await db.commit()

    e = discord.Embed(color=0xF1C40F)
    e.set_author(name="👔 Manager Appointed", icon_url=manager.display_avatar.url)
    e.set_thumbnail(url=manager.display_avatar.url)
    e.add_field(name="Manager", value=manager.mention, inline=True)
    e.add_field(name="Team", value=team.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="remove_manager", description="[OWNER] Remove a team manager")
@app_commands.describe(team="Your team", manager="The manager to remove")
async def remove_manager(interaction: discord.Interaction, team: discord.Role, manager: discord.Member):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    if row[3] != interaction.user.id and not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "Only the team owner can remove a manager."))
    db = await get_db()
    await db.execute("DELETE FROM team_managers WHERE team_id=? AND discord_id=?", (row[0], manager.id))
    await db.commit()
    # Check if they manage any other teams, if not remove the role
    cur = await db.execute("SELECT COUNT(*) FROM team_managers WHERE discord_id=?", (manager.id,))
    count = (await cur.fetchone())[0]
    if count == 0:
        manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
        if manager_role and manager_role in manager.roles:
            try:
                await manager.remove_roles(manager_role, reason="HCBB: Manager removed")
            except discord.Forbidden:
                pass

    e = discord.Embed(color=0xFF6B35)
    e.set_author(name="👔 Manager Removed", icon_url=manager.display_avatar.url)
    e.add_field(name="Manager", value=manager.mention, inline=True)
    e.add_field(name="Team", value=team.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="managers", description="View all team managers in the league")
async def managers(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS team_managers (
            team_id    INTEGER REFERENCES teams(id),
            discord_id INTEGER NOT NULL,
            PRIMARY KEY (team_id, discord_id)
        )
    """)
    cur = await db.execute("""
        SELECT t.name, tm.discord_id
        FROM team_managers tm
        JOIN teams t ON t.id = tm.team_id
        ORDER BY t.name
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Managers", "No managers have been appointed yet."))
    e = discord.Embed(title="👔  Team Managers", color=0xF1C40F)
    current_team = None
    lines = []
    team_lines = []
    for team_name, discord_id in rows:
        if team_name != current_team:
            if current_team and team_lines:
                lines.append(f"**{current_team}**\n" + "\n".join(team_lines))
            current_team = team_name
            team_lines = []
        team_lines.append(f"└ <@{discord_id}>")
    if current_team and team_lines:
        lines.append(f"**{current_team}**\n" + "\n".join(team_lines))
    e.description = "\n\n".join(lines)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)


@bot.tree.command(name="report_score", description="[MOD] Report a game result with MVP")
@app_commands.describe(
    home_team="Home team",
    away_team="Away team",
    home_score="Home team score",
    away_score="Away team score",
    mvp="MVP of the game (optional)"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def report_score(interaction: discord.Interaction, home_team: discord.Role, away_team: discord.Role, home_score: int, away_score: int, mvp: discord.Member = None):
    await interaction.response.defer()
    ht = await get_team_by_role(home_team)
    at = await get_team_by_role(away_team)
    if not ht or not at:
        return await interaction.followup.send(embed=error_embed("Team Not Found", "One or both roles aren't linked to a team."))
    db = await get_db()
    cur = await db.execute("""
        SELECT id FROM games
        WHERE ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
        AND status='scheduled'
        ORDER BY id ASC LIMIT 1
    """, (ht[0], at[0], at[0], ht[0]))
    game = await cur.fetchone()
    if game:
        game_id = game[0]
        await db.execute("UPDATE games SET home_score=?, away_score=?, status='final', played_at=CURRENT_TIMESTAMP WHERE id=?",
                         (home_score, away_score, game_id))
    else:
        cur2 = await db.execute(
            "INSERT INTO games (home_team_id, away_team_id, home_score, away_score, status, played_at) VALUES (?,?,?,?,'final',CURRENT_TIMESTAMP)",
            (ht[0], at[0], home_score, away_score)
        )
        game_id = cur2.lastrowid

    if home_score > away_score:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (ht[0],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (at[0],))
        winner, loser = ht, at
        w_score, l_score = home_score, away_score
    else:
        await db.execute("UPDATE teams SET wins=wins+1 WHERE id=?", (at[0],))
        await db.execute("UPDATE teams SET losses=losses+1 WHERE id=?", (ht[0],))
        winner, loser = at, ht
        w_score, l_score = away_score, home_score
    await db.commit()

    e = discord.Embed(color=0xFFD700)
    e.set_author(name="⚾  Final Score", icon_url=mvp.display_avatar.url if mvp else discord.Embed.Empty)
    e.description = f"**{at[1]}** vs **{ht[1]}**"
    e.add_field(name="🏆 Winner", value=f"**{winner[1]}**", inline=True)
    e.add_field(name="📊 Score", value=f"**{w_score} — {l_score}**", inline=True)
    e.add_field(name="❌ Loser", value=f"**{loser[1]}**", inline=True)
    if mvp:
        e.add_field(name="⭐ MVP", value=mvp.mention, inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="submit_stats", description="Submit your stats after a game")
@app_commands.describe(
    game_id="Game ID these stats are for",
    batting_avg="Your batting average e.g. 0.350",
    home_runs="Home runs hit",
    rbi="RBIs",
    era="ERA (pitchers only)",
    strikeouts="Strikeouts (pitchers only)"
)
async def submit_stats(interaction: discord.Interaction, game_id: int,
                       batting_avg: float = None, home_runs: int = None,
                       rbi: int = None, era: float = None, strikeouts: int = None):
    await interaction.response.defer(ephemeral=True)
    db = await get_db()
    cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (interaction.user.id,))
    p = await cur.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", "You need to `/register` first."))
    cur2 = await db.execute("SELECT id, status FROM games WHERE id=?", (game_id,))
    game = await cur2.fetchone()
    if not game:
        return await interaction.followup.send(embed=error_embed("Game Not Found", f"No game with ID #{game_id}."))

    # Update career stats
    updates, values = [], []
    if batting_avg  is not None: updates.append("batting_avg=?");  values.append(batting_avg)
    if home_runs    is not None: updates.append("home_runs=home_runs+?"); values.append(home_runs)
    if rbi          is not None: updates.append("rbi=rbi+?");       values.append(rbi)
    if era          is not None: updates.append("era=?");            values.append(era)
    if strikeouts   is not None: updates.append("strikeouts=strikeouts+?"); values.append(strikeouts)
    updates.append("games_played=games_played+1")
    values.append(interaction.user.id)
    await db.execute(f"UPDATE players SET {', '.join(updates)} WHERE discord_id=?", values)
    await db.commit()

    e = success_embed("Stats Submitted!", f"Your stats for Game **#{game_id}** have been recorded.")
    parts = []
    if batting_avg  is not None: parts.append(f"AVG: `{batting_avg:.3f}`")
    if home_runs    is not None: parts.append(f"HR: `{home_runs}`")
    if rbi          is not None: parts.append(f"RBI: `{rbi}`")
    if era          is not None: parts.append(f"ERA: `{era:.2f}`")
    if strikeouts   is not None: parts.append(f"K: `{strikeouts}`")
    if parts:
        e.add_field(name="Submitted", value=" · ".join(parts), inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="auto_schedule", description="[ADMIN] Generate and post ONE round of the schedule")
@app_commands.describe(
    round_num="Round number e.g. 1",
    date="Date e.g. Monday March 30th",
    time_slot_1="Game time e.g. 8PM EST"
)
@app_commands.checks.has_permissions(administrator=True)
async def auto_schedule(interaction: discord.Interaction, round_num: int, date: str, time_slot_1: str = "8PM EST"):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id, name, abbreviation FROM teams ORDER BY name")
    teams = await cur.fetchall()
    if len(teams) < 2:
        return await interaction.followup.send(embed=error_embed("Not Enough Teams", "Need at least 2 teams."))

    team_list = list(teams)
    if len(team_list) % 2 != 0:
        team_list.append((None, "BYE", "BYE"))

    # Rotate to get the right round
    n = len(team_list)
    fixed = team_list[0]
    rotating = team_list[1:]
    for _ in range(round_num - 1):
        rotating = [rotating[-1]] + rotating[:-1]
    rotated = [fixed] + rotating

    # Generate matchups for this round
    round_games = []
    for i in range(n // 2):
        home = rotated[i]
        away = rotated[n - 1 - i]
        if home[0] and away[0]:
            round_games.append((away, home))  # (away, home)

    # Insert all games into DB under one time slot
    for away, home in round_games:
        slot = f"Round {round_num} — {date} {time_slot_1}"
        await db.execute(
            "INSERT INTO games (home_team_id, away_team_id, status, scheduled_at) VALUES (?,?,?,?)",
            (home[0], away[0], "scheduled", slot)
        )
    await db.commit()

    # Build plain text message
    lines = [f"@here", f"**ROUND {round_num}**", f"**{date}**", "", f"**{time_slot_1}**"]
    for i, (away, home) in enumerate(round_games, 1):
        away_emoji = TEAM_EMOJIS.get(away[2], "⚾")
        home_emoji = TEAM_EMOJIS.get(home[2], "⚾")
        lines.append(f"{away_emoji} at {home_emoji} LS{i}")
    lines.append("")

    lines.append("**NOTES**")
    lines.append("# *PMs can reschedule if a mutual agreement is reached if not the original time will be played*")
    lines.append("# *one person from each game must screenshot all stats and the score of each game in my DMs*")

    await interaction.followup.send("\n".join(lines))


@bot.tree.command(name="suspend", description="[ADMIN] Suspend a player")
@app_commands.describe(
    player="Player to suspend",
    reason="Reason for suspension",
    games="Number of games suspended (0 = indefinite)"
)
@app_commands.checks.has_permissions(administrator=True)
async def suspend(interaction: discord.Interaction, player: discord.Member, reason: str, games: int = 0):
    await interaction.response.defer()
    db = await get_db()

    # Check if already suspended
    cur = await db.execute("SELECT id FROM suspensions WHERE discord_id=? AND active=1", (player.id,))
    if await cur.fetchone():
        return await interaction.followup.send(embed=error_embed("Already Suspended", f"{player.mention} is already suspended."))

    # Give suspension role
    susp_role = interaction.guild.get_role(SUSPENSION_ROLE_ID)
    if susp_role:
        try:
            await player.add_roles(susp_role, reason=f"HCBB Suspension: {reason}")
        except discord.Forbidden:
            pass

    # Log to DB
    await db.execute(
        "INSERT INTO suspensions (discord_id, reason, games, issued_by) VALUES (?,?,?,?)",
        (player.id, reason, games, interaction.user.id)
    )
    await db.commit()

    games_str = f"**{games} game(s)**" if games > 0 else "**Indefinite**"

    # Post to suspension channel
    susp_channel = interaction.guild.get_channel(SUSPENSION_CHANNEL)
    if susp_channel:
        announcement = discord.Embed(color=0xFF0000)
        announcement.set_author(name="🚨  League Suspension", icon_url=player.display_avatar.url)
        announcement.set_thumbnail(url=player.display_avatar.url)
        announcement.description = f"{player.mention} has been suspended from league play."
        announcement.add_field(name="👤 Player", value=f"{player.mention} `{player.display_name}`", inline=True)
        announcement.add_field(name="⏳ Length", value=games_str, inline=True)
        announcement.add_field(name="📋 Reason", value=f">>> {reason}", inline=False)
        announcement.add_field(name="🔨 Issued By", value=interaction.user.mention, inline=True)
        announcement.set_footer(text="⚾ HCBB 9v9 2.0 League")
        await susp_channel.send(embed=announcement)

    # Reply to command
    e = discord.Embed(color=0xFF0000)
    e.set_author(name="🚨  Player Suspended", icon_url=player.display_avatar.url)
    e.set_thumbnail(url=player.display_avatar.url)
    e.description = f"**{player.display_name}** has been suspended."
    e.add_field(name="👤 Player", value=player.mention, inline=True)
    e.add_field(name="⏳ Length", value=games_str, inline=True)
    e.add_field(name="📋 Reason", value=f">>> {reason}", inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="unsuspend", description="[ADMIN] Lift a player's suspension")
@app_commands.describe(player="Player to unsuspend")
@app_commands.checks.has_permissions(administrator=True)
async def unsuspend(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT id FROM suspensions WHERE discord_id=? AND active=1", (player.id,))
    if not await cur.fetchone():
        return await interaction.followup.send(embed=error_embed("Not Suspended", f"{player.mention} isn't currently suspended."))

    await db.execute("UPDATE suspensions SET active=0 WHERE discord_id=? AND active=1", (player.id,))
    await db.commit()

    # Remove suspension role
    susp_role = interaction.guild.get_role(SUSPENSION_ROLE_ID)
    if susp_role and susp_role in player.roles:
        try:
            await player.remove_roles(susp_role, reason="HCBB: Suspension lifted")
        except discord.Forbidden:
            pass

    # Announce in suspension channel
    susp_channel = interaction.guild.get_channel(SUSPENSION_CHANNEL)
    if susp_channel:
        announcement = discord.Embed(color=0x2ECC71)
        announcement.set_author(name="✅  Suspension Lifted", icon_url=player.display_avatar.url)
        announcement.description = f"{player.mention}'s suspension has been lifted. They are eligible to play."
        announcement.add_field(name="🔓 Reinstated By", value=interaction.user.mention, inline=True)
        announcement.set_footer(text="⚾ HCBB 9v9 2.0 League")
        await susp_channel.send(embed=announcement)

    e = discord.Embed(color=0x2ECC71)
    e.set_author(name="✅  Suspension Lifted", icon_url=player.display_avatar.url)
    e.description = f"**{player.display_name}**'s suspension has been lifted."
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="suspensions", description="View all active suspensions")
async def suspensions(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("""
        SELECT discord_id, reason, games, issued_by, created_at
        FROM suspensions WHERE active=1 ORDER BY created_at DESC
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=success_embed("No Active Suspensions", "All players are eligible to play."))
    e = discord.Embed(title="🚨  Active Suspensions", color=0xFF0000)
    lines = []
    for discord_id, reason, games, issued_by, ts in rows:
        length = f"{games} game(s)" if games > 0 else "Indefinite"
        date = ts[:10] if ts else "?"
        lines.append(f"<@{discord_id}> · **{length}** · `{date}`\n> {reason}")
    e.description = "\n\n".join(lines)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="force_sign", description="[ADMIN] Force sign a player to a team")
@app_commands.describe(player="Player to sign", team="Team to sign them to")
@app_commands.checks.has_permissions(administrator=True)
async def force_sign(interaction: discord.Interaction, player: discord.Member, team: discord.Role):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    db = await get_db()

    # Roster cap check
    cur_count = await db.execute("SELECT COUNT(*) FROM players WHERE team_id=?", (row[0],))
    count = (await cur_count.fetchone())[0]
    if count >= 20:
        return await interaction.followup.send(embed=error_embed("Roster Full", f"**{row[1]}** is at **20/20** players."))

    # Auto-register if not in DB
    cur2 = await db.execute("SELECT id, free_agent, team_id FROM players WHERE discord_id=?", (player.id,))
    p = await cur2.fetchone()
    if not p:
        await db.execute("INSERT INTO players (discord_id, username, position) VALUES (?,?,?)",
                         (player.id, player.display_name, "N/A"))
        await db.commit()
        cur2 = await db.execute("SELECT id, free_agent, team_id FROM players WHERE discord_id=?", (player.id,))
        p = await cur2.fetchone()

    # Release from current team if on one
    if p[2]:
        cur_old = await db.execute("SELECT id FROM team_roles WHERE team_id=?", (p[2],))
        old_role_row = await cur_old.fetchone()
        if old_role_row:
            old_role = interaction.guild.get_role(old_role_row[0])
            if old_role and old_role in player.roles:
                try:
                    await player.remove_roles(old_role, reason="HCBB: Force signed to new team")
                except discord.Forbidden:
                    pass

    await db.execute("UPDATE players SET team_id=?, free_agent=0 WHERE discord_id=?", (row[0], player.id))
    await db.execute("INSERT INTO transactions (player_id, to_team, type) VALUES (?,?,?)", (p[0], row[0], "SIGN"))
    await db.commit()

    await add_team_role(player, interaction.guild, row[0])
    fa_role = interaction.guild.get_role(FA_ROLE_ID)
    if fa_role and fa_role in player.roles:
        try:
            await player.remove_roles(fa_role, reason="HCBB: Force signed")
        except discord.Forbidden:
            pass

    e = discord.Embed(color=0xE74C3C)
    e.set_author(name="⚡  Force Signed", icon_url=player.display_avatar.url)
    e.set_thumbnail(url=player.display_avatar.url)
    e.description = f"**{player.display_name}** has been force signed to {team.mention}"
    e.add_field(name="👤 Player", value=player.mention, inline=True)
    e.add_field(name="🏟️ Team", value=team.mention, inline=True)
    e.add_field(name="📋 Roster", value=f"`{count+1}/20`", inline=True)
    e.add_field(name="🔨 Signed By", value=interaction.user.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

    tx = discord.Embed(color=0xE74C3C)
    tx.set_author(name="⚡  Transaction Wire — FORCE SIGNED", icon_url=player.display_avatar.url)
    tx.set_thumbnail(url=player.display_avatar.url)
    tx.description = f"**{player.display_name}** force signed to {team.mention}"
    tx.add_field(name="👤 Player", value=player.mention, inline=True)
    tx.add_field(name="🏟️ Team", value=team.mention, inline=True)
    tx.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await post_transaction(interaction.guild, config, tx)


@bot.tree.command(name="clear_schedule", description="[ADMIN] Remove all upcoming scheduled games")
@app_commands.describe(confirm="Type YES to confirm clearing all scheduled games")
@app_commands.checks.has_permissions(administrator=True)
async def clear_schedule(interaction: discord.Interaction, confirm: str):
    await interaction.response.defer()
    if confirm.upper() != "YES":
        return await interaction.followup.send(embed=warn_embed("Cancelled", "Type `YES` to confirm clearing the schedule."))
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM games WHERE status='scheduled'")
    count = (await cur.fetchone())[0]
    if count == 0:
        return await interaction.followup.send(embed=warn_embed("Nothing to Clear", "No scheduled games found."))
    await db.execute("DELETE FROM games WHERE status='scheduled'")
    await db.commit()
    e = discord.Embed(color=0xFF4444)
    e.set_author(name="🗑️  Schedule Cleared")
    e.description = f"**{count}** scheduled game(s) have been removed."
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="cancel_game", description="[ADMIN] Cancel a specific scheduled game between two teams")
@app_commands.describe(home_team="Home team", away_team="Away team")
@app_commands.checks.has_permissions(manage_guild=True)
async def cancel_game(interaction: discord.Interaction, home_team: discord.Role, away_team: discord.Role):
    await interaction.response.defer()
    ht = await get_team_by_role(home_team)
    at = await get_team_by_role(away_team)
    if not ht or not at:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    db = await get_db()
    cur = await db.execute("""
        SELECT id FROM games
        WHERE ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
        AND status='scheduled' ORDER BY id ASC LIMIT 1
    """, (ht[0], at[0], at[0], ht[0]))
    game = await cur.fetchone()
    if not game:
        return await interaction.followup.send(embed=error_embed("Game Not Found", f"No scheduled game found between **{ht[1]}** and **{at[1]}**."))
    await db.execute("DELETE FROM games WHERE id=?", (game[0],))
    await db.commit()
    e = discord.Embed(color=0xFF4444)
    e.set_author(name="🗑️  Game Cancelled")
    e.description = f"**{at[1]}** @ **{ht[1]}** has been removed from the schedule."
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)


@bot.tree.command(name="gametime", description="[ADMIN] Post upcoming games as a plain schedule announcement")
@app_commands.checks.has_permissions(manage_guild=True)
async def gametime(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()

    cur = await db.execute("""
        SELECT ht.name, at.name, g.scheduled_at
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.status = 'scheduled'
        ORDER BY g.id ASC
        LIMIT 20
    """)
    rows = await cur.fetchall()

    if not rows:
        return await interaction.followup.send(embed=error_embed("No Upcoming Games", "Schedule is empty."))

    from collections import defaultdict
    grouped = defaultdict(list)
    for hname, aname, sched in rows:
        slot = sched if sched else "TBD"
        grouped[slot].append((aname, hname))

    lines = ["||@everyone||", ""]
    slot_num = 1
    for slot, games in grouped.items():
        lines.append(f"**{slot}**")
        for i, (away, home) in enumerate(games, 1):
            lines.append(f"LS{slot_num} — **{away}** @ **{home}**")
            slot_num += 1
        lines.append("")

    lines.append("*📌 PMs can reschedule with mutual agreement — original time stands otherwise*")
    lines.append("*📸 One player per game must screenshot stats & score and DM the commissioner*")

    await interaction.followup.send("\n".join(lines))

@bot.tree.command(name="submit_player_stats", description="[MOD] Submit stats for multiple players at once after a game")
@app_commands.describe(
    game_info="Short description e.g. DAL vs STL Round 1"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def submit_player_stats(interaction: discord.Interaction, game_info: str):
    """Opens a modal to submit stats for up to 5 players at once."""
    modal = BulkStatsModal(game_info=game_info)
    await interaction.response.send_modal(modal)


class BulkStatsModal(discord.ui.Modal, title="Submit Player Stats"):
    def __init__(self, game_info: str):
        super().__init__()
        self.game_info = game_info

    players_input = discord.ui.TextInput(
        label="Player Stats (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder=(
            "@username AVG:0.350 HR:2 RBI:3 ERA:1.50 K:5\n"
            "@username AVG:0.280 HR:1 RBI:1\n"
            "@username ERA:2.00 K:8"
        ),
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        import re
        db = await get_db()
        lines = self.players_input.value.strip().split("\n")
        results = []
        errors = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Extract discord ID from mention
            id_match = re.search(r"<@!?([0-9]+)>", line)
            if not id_match:
                errors.append(f"❌ Couldn't find mention in: `{line[:30]}`")
                continue
            uid = int(id_match.group(1))
            cur = await db.execute("SELECT id FROM players WHERE discord_id=?", (uid,))
            p = await cur.fetchone()
            if not p:
                errors.append(f"❌ <@{uid}> isn't registered")
                continue

            updates, values = [], []
            avg = re.search(r"AVG:([\d.]+)", line, re.I)
            hr  = re.search(r"HR:(\d+)", line, re.I)
            rbi = re.search(r"RBI:(\d+)", line, re.I)
            era = re.search(r"ERA:([\d.]+)", line, re.I)
            k   = re.search(r"K:(\d+)", line, re.I)

            if avg: updates.append("batting_avg=?");          values.append(float(avg.group(1)))
            if hr:  updates.append("home_runs=home_runs+?");  values.append(int(hr.group(1)))
            if rbi: updates.append("rbi=rbi+?");              values.append(int(rbi.group(1)))
            if era: updates.append("era=?");                  values.append(float(era.group(1)))
            if k:   updates.append("strikeouts=strikeouts+?"); values.append(int(k.group(1)))
            updates.append("games_played=games_played+1")

            if len(updates) == 1:
                errors.append(f"❌ No stats found for <@{uid}>")
                continue

            values.append(uid)
            await db.execute(f"UPDATE players SET {', '.join(updates)} WHERE discord_id=?", values)
            stat_parts = []
            if avg: stat_parts.append(f"AVG `{avg.group(1)}`")
            if hr:  stat_parts.append(f"HR `{hr.group(1)}`")
            if rbi: stat_parts.append(f"RBI `{rbi.group(1)}`")
            if era: stat_parts.append(f"ERA `{era.group(1)}`")
            if k:   stat_parts.append(f"K `{k.group(1)}`")
            results.append(f"✅ <@{uid}> — {'  '.join(stat_parts)}")

        await db.commit()

        e = discord.Embed(title=f"📊  Stats Submitted — {self.game_info}", color=SUCCESS_COLOR)
        if results:
            e.add_field(name=f"Updated ({len(results)})", value="\n".join(results), inline=False)
        if errors:
            e.add_field(name=f"Errors ({len(errors)})", value="\n".join(errors), inline=False)
        e.set_footer(text="⚾ HCBB 9v9 2.0 League")
        await interaction.followup.send(embed=e, ephemeral=True)


# ── PLAYOFFS & WILDCARD ───────────────────────────────────────────
@bot.tree.command(name="playoff_bracket", description="[ADMIN] Generate playoff bracket from current standings")
@app_commands.checks.has_permissions(administrator=True)
async def playoff_bracket(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    cur = await db.execute("SELECT name, abbreviation, wins, losses, division FROM teams ORDER BY division, wins DESC, losses ASC")
    rows = await cur.fetchall()

    western = [(n,a,w,l) for n,a,w,l,d in rows if d == "WESTERN"]
    eastern = [(n,a,w,l) for n,a,w,l,d in rows if d == "EASTERN"]

    # Top 3 per division + 2 wild cards (best remaining records)
    w_seeds = western[:3]
    e_seeds = eastern[:3]
    w_remaining = western[3:]
    e_remaining = eastern[3:]
    all_remaining = sorted(w_remaining + e_remaining, key=lambda x: (-(x[2]/(x[2]+x[3]) if x[2]+x[3] else 0)))
    wildcards = all_remaining[:2]

    # Playoff seeding: W1, W2, W3, E1, E2, E3, WC1, WC2
    seeds = w_seeds + e_seeds + wildcards

    lines = ["**🏆  CLS LEAGUE PLAYOFFS**", ""]
    lines.append("**🌅 Western Conference**")
    for i, (name, abbr, w, l) in enumerate(w_seeds, 1):
        emoji = TEAM_EMOJIS.get(abbr, "⚾")
        lines.append(f"W{i}. {emoji} **{name}** `{w}W-{l}L`")

    lines.append("")
    lines.append("**🌆 Eastern Conference**")
    for i, (name, abbr, w, l) in enumerate(e_seeds, 1):
        emoji = TEAM_EMOJIS.get(abbr, "⚾")
        lines.append(f"E{i}. {emoji} **{name}** `{w}W-{l}L`")

    if wildcards:
        lines.append("")
        lines.append("**🃏 Wild Cards**")
        for i, (name, abbr, w, l) in enumerate(wildcards, 1):
            emoji = TEAM_EMOJIS.get(abbr, "⚾")
            lines.append(f"WC{i}. {emoji} **{name}** `{w}W-{l}L`")

    lines.append("")
    lines.append("**📋 First Round Matchups**")
    if len(seeds) >= 4:
        n1, a1, _, _ = seeds[0]
        n2, a2, _, _ = seeds[-1]
        n3, a3, _, _ = seeds[1]
        n4, a4, _, _ = seeds[-2]
        lines.append(f"{TEAM_EMOJIS.get(a1,'⚾')} **{n1}** vs {TEAM_EMOJIS.get(a2,'⚾')} **{n2}**")
        lines.append(f"{TEAM_EMOJIS.get(a3,'⚾')} **{n3}** vs {TEAM_EMOJIS.get(a4,'⚾')} **{n4}**")

    await interaction.followup.send("\n".join(lines))

# ── ALL STAR ──────────────────────────────────────────────────────
@bot.tree.command(name="allstar_add", description="[ADMIN] Add a player to the All-Star roster")
@app_commands.describe(player="Player to add", conference="WESTERN or EASTERN")
@app_commands.choices(conference=[
    app_commands.Choice(name="Western Conference", value="WESTERN"),
    app_commands.Choice(name="Eastern Conference", value="EASTERN"),
])
@app_commands.checks.has_permissions(administrator=True)
async def allstar_add(interaction: discord.Interaction, player: discord.Member, conference: str):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS allstar (
            discord_id INTEGER NOT NULL,
            conference TEXT NOT NULL,
            PRIMARY KEY (discord_id, conference)
        )
    """)
    await db.execute("INSERT OR IGNORE INTO allstar (discord_id, conference) VALUES (?,?)", (player.id, conference))
    await db.commit()
    conf_emoji = "🌅" if conference == "WESTERN" else "🌆"
    e = success_embed("All-Star Added!", f"{player.mention} added to the {conf_emoji} **{conference}** All-Star roster.")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="allstar_roster", description="View the All-Star rosters")
async def allstar_roster(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS allstar (
            discord_id INTEGER NOT NULL,
            conference TEXT NOT NULL,
            PRIMARY KEY (discord_id, conference)
        )
    """)
    cur = await db.execute("""
        SELECT a.discord_id, a.conference, p.position, p.rblx_username
        FROM allstar a
        LEFT JOIN players p ON p.discord_id = a.discord_id
        ORDER BY a.conference, p.position
    """)
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No All-Stars Yet", "Use `/allstar_add` to build the rosters."))

    western = [(did, pos, rblx) for did, conf, pos, rblx in rows if conf == "WESTERN"]
    eastern = [(did, pos, rblx) for did, conf, pos, rblx in rows if conf == "EASTERN"]

    e = discord.Embed(title="⭐  All-Star Game Rosters", color=0xFFD700)
    if western:
        lines = [f"{POSITION_EMOJIS.get(pos or '','⚾')} <@{did}>{f' (`{rblx}`)' if rblx else ''}" for did, pos, rblx in western]
        e.add_field(name=f"🌅 Western Conference ({len(western)})", value="\n".join(lines), inline=False)
    if eastern:
        lines = [f"{POSITION_EMOJIS.get(pos or '','⚾')} <@{did}>{f' (`{rblx}`)' if rblx else ''}" for did, pos, rblx in eastern]
        e.add_field(name=f"🌆 Eastern Conference ({len(eastern)})", value="\n".join(lines), inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League All-Star Game")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="allstar_clear", description="[ADMIN] Clear All-Star rosters")
@app_commands.checks.has_permissions(administrator=True)
async def allstar_clear(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("DELETE FROM allstar")
    await db.commit()
    await interaction.followup.send(embed=success_embed("All-Star Rosters Cleared"))

# ── HR DERBY ──────────────────────────────────────────────────────
@bot.tree.command(name="hrderbry_add", description="[ADMIN] Add a player to the HR Derby")
@app_commands.describe(player="Player to add to HR Derby")
@app_commands.checks.has_permissions(administrator=True)
async def hrderby_add(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS hrderby (discord_id INTEGER PRIMARY KEY, home_runs INTEGER DEFAULT 0)")
    await db.execute("INSERT OR IGNORE INTO hrderby (discord_id) VALUES (?)", (player.id,))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Added to HR Derby!", f"{player.mention} is in the HR Derby."))

@bot.tree.command(name="hrderby_score", description="[ADMIN] Update a player's HR Derby home run count")
@app_commands.describe(player="Player", home_runs="Number of home runs hit")
@app_commands.checks.has_permissions(administrator=True)
async def hrderby_score(interaction: discord.Interaction, player: discord.Member, home_runs: int):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("UPDATE hrderby SET home_runs=? WHERE discord_id=?", (home_runs, player.id))
    await db.commit()
    await interaction.followup.send(embed=success_embed("Score Updated", f"{player.mention}: **{home_runs} HR**"))

@bot.tree.command(name="hrderby_standings", description="View HR Derby leaderboard")
async def hrderby_standings(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS hrderby (discord_id INTEGER PRIMARY KEY, home_runs INTEGER DEFAULT 0)")
    cur = await db.execute("SELECT discord_id, home_runs FROM hrderby ORDER BY home_runs DESC")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Participants", "No one is in the HR Derby yet."))
    medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 20)]
    e = discord.Embed(title="💪  HR Derby Leaderboard", color=0xFF4500)
    lines = [f"{medals[i]} <@{did}> — **{hr} HR**" for i, (did, hr) in enumerate(rows)]
    e.description = "\n".join(lines)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League — HR Derby")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="hrderby_clear", description="[ADMIN] Clear the HR Derby")
@app_commands.checks.has_permissions(administrator=True)
async def hrderby_clear(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("DELETE FROM hrderby")
    await db.commit()
    await interaction.followup.send(embed=success_embed("HR Derby Cleared"))

# ── AWARDS ────────────────────────────────────────────────────────
AWARD_TYPES = [
    "MVP",
    "Cy Young Award",
    "Silver Slugger",
    "Batting Title",
    "Rookie of the Year",
    "Manager of the Year",
    "Clutch Hitter of the Year",
    "Broken Glove Award",
    "Whiff Award",
    "Champion",
]

@bot.tree.command(name="give_award", description="[ADMIN] Give a league award to a player")
@app_commands.describe(player="Player receiving the award", award="Award type")
@app_commands.choices(award=[app_commands.Choice(name=a, value=a) for a in AWARD_TYPES])
@app_commands.checks.has_permissions(administrator=True)
async def give_award(interaction: discord.Interaction, player: discord.Member, award: str):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS awards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL,
            award TEXT NOT NULL,
            season TEXT DEFAULT 'Season 1',
            given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("INSERT INTO awards (discord_id, award) VALUES (?,?)", (player.id, award))
    await db.commit()
    award_emojis = {
        "MVP": "🏆",
        "Cy Young Award": "⚾",
        "Silver Slugger": "🥈",
        "Batting Title": "🎯",
        "Rookie of the Year": "🌟",
        "Manager of the Year": "👔",
        "Clutch Hitter of the Year": "💥",
        "Broken Glove Award": "🧤",
        "Whiff Award": "💨",
        "Champion": "💍",
    }
    emoji = award_emojis.get(award, "🏅")
    e = discord.Embed(color=0xFFD700)
    e.set_author(name=f"{emoji}  Award Ceremony", icon_url=player.display_avatar.url)
    e.set_thumbnail(url=player.display_avatar.url)
    e.description = f"{player.mention} has been awarded the **{award}**!"
    e.add_field(name="Award", value=f"{emoji} **{award}**", inline=True)
    e.add_field(name="Recipient", value=player.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="awards", description="View all league awards")
async def awards(interaction: discord.Interaction):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS awards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL,
            award TEXT NOT NULL,
            season TEXT DEFAULT 'Season 1',
            given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur = await db.execute("SELECT discord_id, award, season FROM awards ORDER BY given_at DESC")
    rows = await cur.fetchall()
    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Awards Yet"))
    award_emojis = {
        "MVP": "🏆", "Cy Young Award": "⚾", "Silver Slugger": "🥈",
        "Batting Title": "🎯", "Rookie of the Year": "🌟", "Manager of the Year": "👔",
        "Clutch Hitter of the Year": "💥", "Broken Glove Award": "🧤",
        "Whiff Award": "💨", "Champion": "💍",
    }
    e = discord.Embed(title="🏅  League Awards", color=0xFFD700)
    lines = [f"{award_emojis.get(award,'🏅')} **{award}** — <@{did}> _{season}_" for did, award, season in rows]
    e.description = "\n".join(lines)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="player_awards", description="View awards for a specific player")
@app_commands.describe(player="Player to check")
async def player_awards(interaction: discord.Interaction, player: discord.Member = None):
    await interaction.response.defer()
    target = player or interaction.user
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS awards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL,
            award TEXT NOT NULL,
            season TEXT DEFAULT 'Season 1',
            given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur = await db.execute("SELECT award, season FROM awards WHERE discord_id=? ORDER BY given_at DESC", (target.id,))
    rows = await cur.fetchall()
    award_emojis = {"MVP":"🏆","Cy Young Award":"⚾","Silver Slugger":"🥈","Batting Title":"🎯","Rookie of the Year":"🌟","Manager of the Year":"👔","Clutch Hitter of the Year":"💥","Broken Glove Award":"🧤","Whiff Award":"💨","Champion":"💍"}
    e = discord.Embed(color=0xFFD700)
    e.set_author(name=f"{target.display_name}'s Awards", icon_url=target.display_avatar.url)
    e.set_thumbnail(url=target.display_avatar.url)
    if rows:
        lines = [f"{award_emojis.get(award,'🏅')} **{award}** — _{season}_" for award, season in rows]
        e.description = "\n".join(lines)
    else:
        e.description = "_No awards yet._"
    await interaction.followup.send(embed=e)


# ── REACTION ROLES PANEL ─────────────────────────────────────────
PING_ROLES = [
    ("📖", "Bible Ping",        1485344909253673030),
    ("📸", "Media Ping",        1485364229241569471),
    ("🤝", "Partnership Ping",  1485364338872029328),
    ("🏅", "Awards",            1485364545710198874),
    ("📊", "Final Scores Ping", 1485364629956853861),
    ("📰", "Server News Ping",  1485364702883352778),
    ("🎮", "Games News Ping",   1485364814774800584),
    ("⚾", "Game Day Ping",     1485364903333072966),
]

class PingRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for emoji, label, role_id in PING_ROLES:
            self.add_item(PingRoleButton(emoji=emoji, label=label, role_id=role_id))

class PingRoleButton(discord.ui.Button):
    def __init__(self, emoji: str, label: str, role_id: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji=emoji,
            custom_id=f"pingrole_{role_id}"
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message(
                embed=error_embed("Role Not Found", "This role doesn't exist anymore."),
                ephemeral=True
            )
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Ping role panel")
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"✅ Removed **{role.name}** from your roles.",
                    color=0xFF6B35
                ),
                ephemeral=True
            )
        else:
            await interaction.user.add_roles(role, reason="Ping role panel")
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"✅ Added **{role.name}** to your roles.",
                    color=0x2ECC71
                ),
                ephemeral=True
            )

@bot.tree.command(name="pingroles_panel", description="[ADMIN] Post the ping roles panel")
@app_commands.checks.has_permissions(administrator=True)
async def pingroles_panel(interaction: discord.Interaction):
    await interaction.response.defer()

    lines = ["**Get Your Role To Get Notified About**", ""]
    for emoji, label, role_id in PING_ROLES:
        lines.append(f"{emoji} - {label.upper()}")
    lines.append("")
    lines.append("*Click a button below to get the role!*")
    lines.append("*Click again to remove it*")

    await interaction.followup.send("\n".join(lines), view=PingRoleView())


@bot.tree.command(name="force_release", description="[ADMIN] Force release a player from their team")
@app_commands.describe(player="Player to release")
@app_commands.checks.has_permissions(administrator=True)
async def force_release(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()
    config = await get_config(interaction.guild.id)
    db = await get_db()
    cur = await db.execute("SELECT id, team_id FROM players WHERE discord_id=?", (player.id,))
    p = await cur.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{player.mention} isn't in the league."))
    if not p[1]:
        return await interaction.followup.send(embed=error_embed("Not On A Team", f"{player.mention} is already a free agent."))

    cur2 = await db.execute("SELECT name FROM teams WHERE id=?", (p[1],))
    team = await cur2.fetchone()
    team_name = team[0] if team else "Unknown"

    await db.execute("UPDATE players SET team_id=NULL, free_agent=1 WHERE discord_id=?", (player.id,))
    await db.execute("INSERT INTO transactions (player_id, from_team, type) VALUES (?,?,?)", (p[0], p[1], "RELEASE"))
    await db.commit()

    # Remove team role, add FA role
    await remove_team_role_fn(player, interaction.guild, p[1])
    fa_role = interaction.guild.get_role(FA_ROLE_ID)
    if fa_role and fa_role not in player.roles:
        try:
            await player.add_roles(fa_role, reason="HCBB: Force released")
        except discord.Forbidden:
            pass

    e = discord.Embed(color=0xFF4444)
    e.set_author(name="⚡  Force Released", icon_url=player.display_avatar.url)
    e.set_thumbnail(url=player.display_avatar.url)
    e.description = f"**{player.display_name}** has been force released from **{team_name}**."
    e.add_field(name="👤 Player", value=player.mention, inline=True)
    e.add_field(name="📤 From", value=f"**{team_name}**", inline=True)
    e.add_field(name="📌 Status", value="🆓 Free Agent", inline=True)
    e.add_field(name="🔨 Released By", value=interaction.user.mention, inline=True)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

    tx = discord.Embed(color=0xFF4444)
    tx.set_author(name="⚡  Transaction Wire — FORCE RELEASED", icon_url=player.display_avatar.url)
    tx.set_thumbnail(url=player.display_avatar.url)
    tx.description = f"**{player.display_name}** force released from **{team_name}**"
    tx.add_field(name="👤 Player", value=player.mention, inline=True)
    tx.add_field(name="📤 From", value=f"**{team_name}**", inline=True)
    tx.add_field(name="📌 Status", value="🆓 Free Agent", inline=True)
    tx.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await post_transaction(interaction.guild, config, tx)


@bot.tree.command(name="team_rename", description="[ADMIN] Rename a team")
@app_commands.describe(
    team="The team to rename",
    new_name="New full team name e.g. Brooklyn Bears",
    new_abbreviation="New abbreviation e.g. BRK (optional)"
)
@app_commands.checks.has_permissions(administrator=True)
async def team_rename(interaction: discord.Interaction, team: discord.Role, new_name: str, new_abbreviation: str = None):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))
    db = await get_db()
    old_name = row[1]
    old_abbr = row[2]

    if new_abbreviation:
        new_abbreviation = new_abbreviation.upper()
        # Check abbreviation not taken
        cur = await db.execute("SELECT id FROM teams WHERE abbreviation=? AND id!=?", (new_abbreviation, row[0]))
        if await cur.fetchone():
            return await interaction.followup.send(embed=error_embed("Abbreviation Taken", f"`{new_abbreviation}` is already used by another team."))
        await db.execute("UPDATE teams SET name=?, abbreviation=? WHERE id=?", (new_name, new_abbreviation, row[0]))
    else:
        await db.execute("UPDATE teams SET name=? WHERE id=?", (new_name, row[0]))
    await db.commit()

    # Update TEAM_EMOJIS key if abbreviation changed
    final_abbr = new_abbreviation if new_abbreviation else old_abbr

    e = success_embed("Team Renamed ✏️")
    e.add_field(name="Before", value=f"**{old_name}** `{old_abbr}`", inline=True)
    e.add_field(name="After", value=f"**{new_name}** `{final_abbr}`", inline=True)
    e.add_field(name="Role", value=team.mention, inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)


class FAPageView(discord.ui.View):
    def __init__(self, user_id: int, pages: list):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pages = pages
        self.index = 0
        self.prev_btn.disabled = True
        self.next_btn.disabled = len(pages) <= 1

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ These buttons aren't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1
        await interaction.response.edit_message(content=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1
        await interaction.response.edit_message(content=self.pages[self.index], view=self)


@bot.tree.command(name="awards_announce", description="[ADMIN] Post the season awards announcement")
@app_commands.describe(season="Season number e.g. 2")
@app_commands.checks.has_permissions(administrator=True)
async def awards_announce(interaction: discord.Interaction, season: int = 1):
    await interaction.response.defer()
    msg = f"""|| <@&1485364545710198874> ||

# Awards for this Season {season}

__**Awards**__
- Most Valuable Player (MVP)
- Cy Young Award
- Silver Slugger Awards
- Batting Title (Highest Batting Average)
- Rookie of the Year
- Manager of the Year

__**Miscellaneous**__
- Clutch Hitter of the Year (Given to the **Most Clutch Player** of the season | RISP + RBIs factored into decision making.)
- Broken Glove Award (Most errors/Worst lowlight of the season)
- Whiff Award (Most Batting Strikeouts)"""
    await interaction.followup.send(msg)


# ── LINEUP & BULLPEN ─────────────────────────────────────────────
@bot.tree.command(name="set_lineup", description="Set your team's batting lineup and bullpen")
@app_commands.describe(
    team="Your team",
    lineup="Batting order — one player per line or comma separated",
    bullpen="Pitchers — one per line or comma separated (optional)"
)
async def set_lineup(interaction: discord.Interaction, team: discord.Role, lineup: str, bullpen: str = None):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    is_owner = row[3] == interaction.user.id
    db = await get_db()
    cur_mgr = await db.execute("SELECT 1 FROM team_managers WHERE team_id=? AND discord_id=?", (row[0], interaction.user.id))
    is_mgr = await cur_mgr.fetchone() is not None
    if not is_owner and not is_mgr and not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "Only the team owner or manager can set the lineup."))
    await db.execute("""
        INSERT INTO lineups (team_id, lineup, bullpen) VALUES (?,?,?)
        ON CONFLICT(team_id) DO UPDATE SET lineup=excluded.lineup, bullpen=excluded.bullpen, updated_at=CURRENT_TIMESTAMP
    """, (row[0], lineup, bullpen))
    await db.commit()
    e = success_embed(f"Lineup Set — {row[1]}")
    e.add_field(name="⚾ Batting Order", value=lineup[:1024], inline=False)
    if bullpen:
        e.add_field(name="🌀 Bullpen", value=bullpen[:1024], inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="lineup", description="View a team's lineup and bullpen")
@app_commands.describe(team="The team to view")
async def view_lineup(interaction: discord.Interaction, team: discord.Role):
    await interaction.response.defer()
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found"))
    db = await get_db()
    cur = await db.execute("SELECT lineup, bullpen, updated_at FROM lineups WHERE team_id=?", (row[0],))
    lu = await cur.fetchone()
    if not lu or not lu[0]:
        return await interaction.followup.send(embed=warn_embed("No Lineup Set", f"**{row[1]}** hasn't set a lineup yet."))
    e = discord.Embed(title=f"📋  {row[1]} — Lineup", color=BRAND_COLOR)
    e.add_field(name="⚾ Batting Order", value=lu[0][:1024], inline=False)
    if lu[1]:
        e.add_field(name="🌀 Bullpen", value=lu[1][:1024], inline=False)
    if lu[2]:
        e.set_footer(text=f"⚾ HCBB 9v9 2.0 League  ·  Updated {lu[2][:10]}")
    await interaction.followup.send(embed=e)

# ── AUTO ALL-STAR ─────────────────────────────────────────────────
@bot.tree.command(name="allstar_auto", description="[ADMIN] Auto-select All-Stars based on top stats per conference")
@app_commands.describe(players_per_conf="How many players per conference (default 9)")
@app_commands.checks.has_permissions(administrator=True)
async def allstar_auto(interaction: discord.Interaction, players_per_conf: int = 9):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS allstar (
            discord_id INTEGER NOT NULL,
            conference TEXT NOT NULL,
            PRIMARY KEY (discord_id, conference)
        )
    """)

    results = {"WESTERN": [], "EASTERN": []}
    for conf, abbrs in [("WESTERN", WESTERN), ("EASTERN", EASTERN)]:
        placeholders = ",".join("?" * len(abbrs))
        cur = await db.execute(f"""
            SELECT p.discord_id, p.username, p.position,
                   (p.batting_avg * 100 + p.home_runs * 2 + p.rbi) as score
            FROM players p
            JOIN teams t ON t.id = p.team_id
            WHERE t.abbreviation IN ({placeholders})
            ORDER BY score DESC
            LIMIT ?
        """, (*abbrs, players_per_conf))
        rows = await cur.fetchall()
        for did, uname, pos, score in rows:
            await db.execute("INSERT OR IGNORE INTO allstar (discord_id, conference) VALUES (?,?)", (did, conf))
            results[conf].append((did, uname, pos))
    await db.commit()

    e = discord.Embed(title="⭐  All-Stars Auto-Selected", color=0xFFD700)
    for conf, players in results.items():
        emoji = "🌅" if conf == "WESTERN" else "🌆"
        if players:
            lines = [f"{POSITION_EMOJIS.get(pos,'⚾')} **{u}** <@{did}>" for did, u, pos in players]
            e.add_field(name=f"{emoji} {conf} ({len(players)})", value="\n".join(lines), inline=False)
        else:
            e.add_field(name=f"{emoji} {conf}", value="_No players with stats yet_", inline=False)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League  ·  Use /allstar_roster to view full rosters")
    await interaction.followup.send(embed=e)

# ── AUTO HR DERBY ─────────────────────────────────────────────────
@bot.tree.command(name="hrderby_auto", description="[ADMIN] Auto-select top HR hitters for the HR Derby")
@app_commands.describe(top_n="How many players to select (default 8)")
@app_commands.checks.has_permissions(administrator=True)
async def hrderby_auto(interaction: discord.Interaction, top_n: int = 8):
    await interaction.response.defer()
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS hrderby (discord_id INTEGER PRIMARY KEY, home_runs INTEGER DEFAULT 0)")

    cur = await db.execute("""
        SELECT p.discord_id, p.username, p.home_runs, t.name
        FROM players p
        LEFT JOIN teams t ON t.id = p.team_id
        WHERE p.home_runs > 0
        ORDER BY p.home_runs DESC
        LIMIT ?
    """, (top_n,))
    rows = await cur.fetchall()

    if not rows:
        return await interaction.followup.send(embed=warn_embed("No Stats", "No players have home run stats yet."))

    for did, uname, hr, tname in rows:
        await db.execute("INSERT OR REPLACE INTO hrderby (discord_id, home_runs) VALUES (?,?)", (did, hr))
    await db.commit()

    medals = ["🥇","🥈","🥉"] + [f"`{i}.`" for i in range(4, 20)]
    e = discord.Embed(title="💪  HR Derby — Auto Selected", color=0xFF4500)
    lines = []
    for i, (did, uname, hr, tname) in enumerate(rows):
        team_str = f"({tname})" if tname else "(FA)"
        lines.append(f"{medals[i]} **{uname}** {team_str} — `{hr} HR`")
    e.description = "\n".join(lines)
    e.set_footer(text="⚾ HCBB 9v9 2.0 League  ·  Use /hrderby_standings to view live leaderboard")
    await interaction.followup.send(embed=e)


# ── OFFER SYSTEM ─────────────────────────────────────────────────
class OfferView(discord.ui.View):
    def __init__(self, player_id: int, team_id: int, team_name: str, team_role_id: int, owner_id: int):
        super().__init__(timeout=86400)  # 24 hours
        self.player_id   = player_id
        self.team_id     = team_id
        self.team_name   = team_name
        self.team_role_id = team_role_id
        self.owner_id    = owner_id

    @discord.ui.button(label="✅  Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message("❌ This offer isn't for you.", ephemeral=True)

        db = await get_db()
        # Check roster cap
        cur = await db.execute("SELECT COUNT(*) FROM players WHERE team_id=?", (self.team_id,))
        count = (await cur.fetchone())[0]
        if count >= 20:
            await interaction.response.edit_message(
                content="❌ Offer expired — that team's roster is now full.",
                embed=None, view=None
            )
            return

        # Check still a free agent
        cur2 = await db.execute("SELECT id, free_agent FROM players WHERE discord_id=?", (self.player_id,))
        p = await cur2.fetchone()
        if not p or not p[1]:
            await interaction.response.edit_message(
                content="❌ Offer expired — you're already on a team.",
                embed=None, view=None
            )
            return

        await db.execute("UPDATE players SET team_id=?, free_agent=0 WHERE discord_id=?", (self.team_id, self.player_id))
        await db.execute("INSERT INTO transactions (player_id, to_team, type) VALUES (?,?,?)", (p[0], self.team_id, "SIGN"))
        await db.commit()

        # Roles
        guild = interaction.guild
        if guild:
            member = guild.get_member(self.player_id)
            if member:
                team_role = guild.get_role(self.team_role_id)
                fa_role   = guild.get_role(FA_ROLE_ID)
                try:
                    if team_role: await member.add_roles(team_role, reason="HCBB: Offer accepted")
                    if fa_role and fa_role in member.roles: await member.remove_roles(fa_role)
                except discord.Forbidden:
                    pass

        # Post to transactions channel
        config = await get_config(interaction.guild_id or 0)
        tx = discord.Embed(color=0x2ECC71)
        tx.set_author(name="✍️  Transaction Wire — SIGNED")
        tx.description = f"<@{self.player_id}> accepted an offer from **{self.team_name}**"
        tx.add_field(name="👤 Player", value=f"<@{self.player_id}>", inline=True)
        tx.add_field(name="🏟️ Team",  value=f"**{self.team_name}**", inline=True)
        tx.set_footer(text="⚾ HCBB 9v9 2.0 League")
        if interaction.guild:
            await post_transaction(interaction.guild, config, tx)

        e = discord.Embed(color=0x2ECC71)
        e.set_author(name="✅  Offer Accepted!")
        e.description = f"You have joined **{self.team_name}**. Welcome to the squad!"
        e.set_footer(text="⚾ HCBB 9v9 2.0 League")
        await interaction.response.edit_message(embed=e, view=None)

        # Notify owner
        owner = interaction.client.get_user(self.owner_id)
        if owner:
            try:
                notif = discord.Embed(color=0x2ECC71)
                notif.set_author(name="✅  Offer Accepted!")
                notif.description = f"<@{self.player_id}> accepted your offer to join **{self.team_name}**!"
                notif.set_footer(text="⚾ HCBB 9v9 2.0 League")
                await owner.send(embed=notif)
            except discord.Forbidden:
                pass

        self.stop()

    @discord.ui.button(label="❌  Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message("❌ This offer isn't for you.", ephemeral=True)

        e = discord.Embed(color=0xFF4444)
        e.set_author(name="❌  Offer Declined")
        e.description = f"You declined the offer from **{self.team_name}**."
        e.set_footer(text="⚾ HCBB 9v9 2.0 League")
        await interaction.response.edit_message(embed=e, view=None)

        # Notify owner
        owner = interaction.client.get_user(self.owner_id)
        if owner:
            try:
                notif = discord.Embed(color=0xFF4444)
                notif.set_author(name="❌  Offer Declined")
                notif.description = f"<@{self.player_id}> declined your offer to join **{self.team_name}**."
                notif.set_footer(text="⚾ HCBB 9v9 2.0 League")
                await owner.send(embed=notif)
            except discord.Forbidden:
                pass

        self.stop()

@bot.tree.command(name="offer", description="Send a signing offer to a free agent via DM")
@app_commands.describe(player="The player to offer", team="Your team")
async def offer(interaction: discord.Interaction, player: discord.Member, team: discord.Role):
    await interaction.response.defer(ephemeral=True)
    row = await get_team_by_role(team)
    if not row:
        return await interaction.followup.send(embed=error_embed("Team Not Found", f"{team.mention} isn't linked to a team."))

    # Check user is owner or manager
    db = await get_db()
    is_owner = row[3] == interaction.user.id
    cur_mgr = await db.execute("SELECT 1 FROM team_managers WHERE team_id=? AND discord_id=?", (row[0], interaction.user.id))
    is_mgr = await cur_mgr.fetchone() is not None
    if not is_owner and not is_mgr and not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(embed=error_embed("Not Authorized", "Only the team owner or manager can send offers."))

    # Check roster cap
    cur2 = await db.execute("SELECT COUNT(*) FROM players WHERE team_id=?", (row[0],))
    count = (await cur2.fetchone())[0]
    if count >= 20:
        return await interaction.followup.send(embed=error_embed("Roster Full", f"**{row[1]}** is at 20/20 players."))

    # Check player is registered and a free agent
    cur3 = await db.execute("SELECT id, free_agent FROM players WHERE discord_id=?", (player.id,))
    p = await cur3.fetchone()
    if not p:
        return await interaction.followup.send(embed=error_embed("Not Registered", f"{player.mention} hasn't registered yet."))
    if not p[1]:
        return await interaction.followup.send(embed=error_embed("Not a Free Agent", f"{player.mention} is already on a team."))

    # Get team role ID
    cur4 = await db.execute("SELECT role_id FROM team_roles WHERE team_id=?", (row[0],))
    role_row = await cur4.fetchone()
    team_role_id = role_row[0] if role_row else 0

    # Build the offer embed
    offer_embed = discord.Embed(color=0x1E90FF)
    offer_embed.set_author(name="📨  Offer Received", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    offer_embed.description = (
        f"You have been offered by **{row[1]}** to join their franchise, do you accept?"
    )
    offer_embed.add_field(name="🏟️ Team",  value=f"**{row[1]}**  {team.mention}", inline=False)
    offer_embed.add_field(name="👤 GM",    value=f"{interaction.user.mention}  `{interaction.user.display_name}`", inline=False)
    offer_embed.add_field(name="⏳ Expires", value="24 hours", inline=False)
    offer_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)
    offer_embed.set_footer(text="⚾ HCBB 9v9 2.0 League  ·  Accept or decline below")

    view = OfferView(
        player_id=player.id,
        team_id=row[0],
        team_name=row[1],
        team_role_id=team_role_id,
        owner_id=interaction.user.id
    )

    try:
        await player.send(embed=offer_embed, view=view)
        await interaction.followup.send(
            embed=success_embed("Offer Sent!", f"📨 Your offer has been sent to {player.mention}'s DMs."),
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send(
            embed=error_embed("Can't DM Player", f"{player.mention} has DMs disabled. They need to enable DMs from server members."),
            ephemeral=True
        )

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
        bot.add_view(PingRoleView())
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
