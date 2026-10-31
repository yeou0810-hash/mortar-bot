import discord
from discord.ext import commands
from discord import app_commands
import math
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. 렌더(Render) 포트 감지용 간단한 웹 서버 (Timed Out 방지용)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass # 로그가 너무 많이 쌓이는 것을 방지

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# 백그라운드에서 웹 서버 실행
threading.Thread(target=run_web_server, daemon=True).start()


# 2. 디스코드 봇 설정
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

guild_zeroing_data = {}

def calculate_mortar(mx: float, my: float, mz: float, tx: float, ty: float, tz: float, dist_offset: float = 0.0, yaw_offset: float = 0.0):
    dx = tx - mx
    dy = ty - my
    dz = tz - mz

    dist = math.sqrt(dx * dx + dz * dz) + dist_offset
    yaw = math.degrees(math.atan2(-dx, dz)) + yaw_offset
    
    if yaw > 180: yaw -= 360
    elif yaw < -180: yaw += 360
    yaw = round(yaw, 1)

    if -22.5 <= yaw < 22.5: dir_str = "남(S)"
    elif 22.5 <= yaw < 67.5: dir_str = "남서(SW)"
    elif 67.5 <= yaw < 112.5: dir_str = "서(W)"
    elif 112.5 <= yaw < 157.5: dir_str = "북서(NW)"
    elif -67.5 <= yaw < -22.5: dir_str = "남동(SE)"
    elif -112.5 <= yaw < -67.5: dir_str = "동(E)"
    elif -157.5 <= yaw < -112.5: dir_str = "북동(NE)"
    else: dir_str = "북(N)"

    powder_count = 2 if dist <= 350 else math.ceil(dist / 150)
    tnt_count = 1

    if dist < 100: base_angle = 75
    elif dist < 200: base_angle = 60
    elif dist > 400: base_angle = 35
    else: base_angle = 45

    elevation_correction = round((dy / max(dist, 1)) * 15)
    final_pitch = min(85, max(10, base_angle + elevation_correction))

    return {
        "dist": round(dist, 1), "yaw": yaw, "dir_str": dir_str,
        "pitch": final_pitch, "powder": powder_count, "tnt": tnt_count
    }

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 슬래시 명령어 {len(synced)}개 동기화 완료!")
    except Exception as e:
        print(f"❌ 동기화 실패: {e}")

@bot.tree.command(name="박격포", description="플래닛어스 박격포 사격 제원을 계산합니다.")
@app_commands.describe(mx="내 X", mz="내 Z", tx="적 X", tz="적 Z", my="내 Y (기본 64)", ty="적 Y (기본 64)")
async def mortar_slash(interaction: discord.Interaction, mx: float, mz: float, tx: float, tz: float, my: float = 64.0, ty: float = 64.0):
    guild_id = interaction.guild.id if interaction.guild else 0
    server_zero = guild_zeroing_data.get(guild_id, {"dist_offset": 0.0, "yaw_offset": 0.0})
    
    res = calculate_mortar(mx, my, mz, tx, ty, tz, server_zero["dist_offset"], server_zero["yaw_offset"])

    embed = discord.Embed(title="🚀 PlanetEarth 박격포 사격 제원", color=discord.Color.blue())
    embed.add_field(name="📏 보정된 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="🧭 보정된 방위각 (Yaw)", value=f"`{res['yaw']}°` ({res['dir_str']})", inline=True)
    embed.add_field(name="📐 표지판 각도 (Pitch)", value=f"`{res['pitch']}°`", inline=True)
    embed.add_field(name="💣 장전 추천", value=f"화약 **{res['powder']}개** / TNT **{res['tnt']}개**", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="영점", description="이 서버 전체에 적용될 탄착군 오차를 입력해 고정합니다.")
@app_commands.describe(dist_offset="거리 오차", yaw_offset="방향 오차")
async def set_zero(interaction: discord.Interaction, dist_offset: float = 0.0, yaw_offset: float = 0.0):
    if not interaction.guild:
        await interaction.response.send_message("❌ 서버 내에서만 사용 가능합니다.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    guild_zeroing_data[guild_id] = {"dist_offset": dist_offset, "yaw_offset": yaw_offset}
    
    await interaction.response.send_message(f"🎯 영점 설정 완료! 거리 보정: `{dist_offset}m` / 방향 보정: `{yaw_offset}°`", ephemeral=True)

bot.run(TOKEN)