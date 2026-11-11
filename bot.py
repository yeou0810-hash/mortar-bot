import discord
from discord.ext import commands
from discord import app_commands
import math
import os
import threading
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

# 렌더 포트 유지용 웹 서버 (타임아웃 방지 + HEAD 요청 완벽 대응)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
        
    def do_HEAD(self):  # UptimeRobot 상태 체크 대응
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")

# 🔴 [중요] 본인의 디스코드 사용자 숫자 ID를 여기에 입력하세요!
OWNER_ID = 123456789012345678  # 본인의 디스코드 숫자 ID로 변경하세요

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 서버별 데이터 저장소 (영점 데이터 및 서버 차단/잠금 상태 관리)
guild_zeroing_data = {}
locked_guilds = set()  # 원격으로 잠긴 서버 ID 목록

# 📌 10m ~ 160m 확정 정밀 사격 룩업 테이블
BALLISTIC_TABLE = {
    10:  (1,  16.0),
    20:  (1,  14.0),
    30:  (1,  11.0),
    40:  (1,   8.5),
    50:  (1,   6.0),
    60:  (1,   2.5),
    70:  (2,   4.0),
    80:  (2,   2.5),
    90:  (2,  -0.5),
    100: (2,  -2.0),
    110: (2,  -5.5),
    120: (2,  -7.5),
    130: (2, -12.5),
    140: (2, -15.0),
    150: (2, -18.0),
    160: (2, -20.0),
}

def calculate_mortar(mx: float, my: float, mz: float, tx: float, ty: float, tz: float, guild_id: int = 0):
    dx = tx - mx
    dz = tz - mz
    dy = ty - my
    dist = math.sqrt(dx * dx + dz * dz)

    if dx == 0:
        raw_yaw = 45.0 if dz > 0 else -45.0
    else:
        raw_yaw = math.degrees(math.atan2(dz, dx))

    yaw = max(-45.0, min(45.0, raw_yaw))
    yaw = round(round(yaw * 2) / 2, 1)

    server_data = guild_zeroing_data.get(guild_id, {})
    custom_pitches = server_data.get("custom_pitches", {})
    
    applied_custom = False
    base_pitch = 0.0
    powder_count = 1
    
    for d, p in custom_pitches.items():
        if abs(dist - d) <= 2.0:
            base_pitch = p
            applied_custom = True
            break

    if not applied_custom:
        rounded_table_dist = int(round(dist / 10.0) * 10)
        if rounded_table_dist < 10:
            rounded_table_dist = 10
        elif rounded_table_dist > 160:
            rounded_table_dist = 160
        powder_count, base_pitch = BALLISTIC_TABLE[rounded_table_dist]

    elevation_correction = (dy / max(dist, 1)) * 5
    final_pitch = round((base_pitch + elevation_correction) * 2) / 2
    final_pitch = max(-20.0, min(20.0, final_pitch))

    return {
        "dist": round(dist, 1), 
        "yaw": yaw,
        "pitch": final_pitch, 
        "powder": powder_count,
        "is_custom": applied_custom
    }

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 슬래시 명령어 {len(synced)}개 동기화 완료!")
    except Exception as e:
        print(f"❌ 동기화 실패: {e}")

@bot.tree.command(name="박격포", description="PlanetEarth 맞춤형 박격포 사격 제원을 계산합니다.")
@app_commands.describe(mx="내 X 좌표", mz="내 Z 좌표", my="내 Y 좌표 (선택)", tx="적 X 좌표", tz="적 Z 좌표", ty="적 Y 좌표 (선택)")
async def mortar_slash(
    interaction: discord.Interaction, 
    mx: float, mz: float, tx: float, tz: float, 
    my: Optional[float] = None, ty: Optional[float] = None
):
    guild_id = interaction.guild.id if interaction.guild else 0

    # 🔒 원격으로 잠금 처리된 서버라면 사용 차단
    if guild_id in locked_guilds:
        await interaction.response.send_message("❌ 이 서버는 관리자에 의해 봇 기능이 잠금 처리되었습니다.", ephemeral=True)
        return

    real_my = my if my is not None else 64.0
    real_ty = ty if ty is not None else 64.0

    res = calculate_mortar(mx, real_my, mz, tx, real_ty, tz, guild_id)

    embed = discord.Embed(title="🚀 PlanetEarth 박격포 사격 제원", color=discord.Color.blue())
    embed.add_field(name="📏 측정 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="💣 장약 제원", value=f"화약 **{res['powder']}개** / TNT **1개**", inline=True)
    
    if res['is_custom']:
        embed.set_footer(text="⭐ 이 서버에 학습된 커스텀 영점 데이터가 적용되었습니다.")

    sign_text = f"p: {res['powder']} c: TNT\n{res['yaw']}/{res['pitch']}"
    embed.add_field(name="📝 표지판 입력 값", value=f"```\n{sign_text}\n```", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="영점설정", description="특정 거리의 상하각 오차를 직접 수정하여 서버에 영점을 학습시킵니다.")
@app_commands.describe(distance="보정할 대략적 거리", target_pitch="실제 명중하는 올바른 상하각")
async def set_zeroing(interaction: discord.Interaction, distance: float, target_pitch: float):
    guild_id = interaction.guild.id if interaction.guild else 0
    if guild_id in locked_guilds:
        await interaction.response.send_message("❌ 이 서버는 잠금 처리되어 있습니다.", ephemeral=True)
        return

    if guild_id not in guild_zeroing_data:
        guild_zeroing_data[guild_id] = {"custom_pitches": {}}
    if "custom_pitches" not in guild_zeroing_data[guild_id]:
        guild_zeroing_data[guild_id]["custom_pitches"] = {}
        
    rounded_dist = round(distance)
    guild_zeroing_data[guild_id]["custom_pitches"][rounded_dist] = target_pitch
    
    await interaction.response.send_message(f"✅ **{rounded_dist}m** 부근의 영점이 **`{target_pitch}°`**(으)로 저장되었습니다!")


# ==========================================
# 🛠️ [오직 개발자(본인)만 쓰는 원격 관리 명령어들]
# ==========================================

@bot.tree.command(name="서버목록", description="[개발자전용] 봇이 참여 중인 모든 서버의 이름과 ID를 확인합니다.")
async def admin_server_list(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        return

    guilds = bot.guilds
    if not guilds:
        await interaction.response.send_message("현재 들어가 있는 서버가 없습니다.", ephemeral=True)
        return

    text = ""
    for g in guilds:
        status = "🔴 [잠김]" if g.id in locked_guilds else "🟢 [정상]"
        text += f"- **{g.name}**\n  ID: `{g.id}` | 멤버수: {g.member_count}명 {status}\n\n"

    embed = discord.Embed(title=f"📋 봇 참여 서버 목록 (총 {len(guilds)}개)", description=text, color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="서버추방", description="[개발자전용] 지정한 서버 ID의 서버에서 봇을 원격으로 강퇴(퇴장)시킵니다.")
@app_commands.describe(guild_id="추방할 서버의 ID 숫자")
async def admin_leave_guild(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        return

    try:
        g_id = int(guild_id)
        target_guild = bot.get_guild(g_id)
        if target_guild is None:
            await interaction.response.send_message(f"❌ 해당 ID(`{g_id}`)의 서버를 찾을 수 없습니다. (봇이 없거나 ID가 틀림)", ephemeral=True)
            return

        guild_name = target_guild.name
        await target_guild.leave()
        await interaction.response.send_message(f"✅ 성공적으로 **'{guild_name}'** (`{g_id}`) 서버에서 탈퇴(추방)했습니다.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 추방 중 에러 발생: {e}", ephemeral=True)

@bot.tree.command(name="서버잠금", description="[개발자전용] 특정 서버에서 봇 기능을 원격으로 잠급니다.")
@app_commands.describe(guild_id="잠금할 서버의 ID 숫자")
async def admin_lock_guild(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        return

    try:
        g_id = int(guild_id)
        locked_guilds.add(g_id)
        await interaction.response.send_message(f"🔒 서버 ID `{g_id}`의 봇 기능이 원격으로 **잠금**되었습니다.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 에러 발생: {e}", ephemeral=True)

@bot.tree.command(name="서버해제", description="[개발자전용] 잠금된 서버의 봇 기능을 다시 풀어줍니다.")
@app_commands.describe(guild_id="해제할 서버의 ID 숫자")
async def admin_unlock_guild(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        return

    try:
        g_id = int(guild_id)
        if g_id in locked_guilds:
            locked_guilds.remove(g_id)
        await interaction.response.send_message(f"🔓 서버 ID `{g_id}`의 봇 기능 잠금이 **해제**되었습니다.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 에러 발생: {e}", ephemeral=True)

bot.run(TOKEN)