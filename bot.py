import discord
from discord.ext import commands
from discord import app_commands
import math
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 렌더 포트 유지용 웹 서버 (타임아웃 방지)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

guild_zeroing_data = {}

def calculate_mortar(mx: float, my: float, mz: float, tx: float, ty: float, tz: float, dist_offset: float = 0.0, yaw_offset: float = 0.0):
    dx = tx - mx  # X축 (전진 거리)
    dz = tz - mz  # Z축 (좌우 편차)
    dy = ty - my

    # 평면 거리 계산
    dist = math.sqrt(dx * dx + dz * dz) + dist_offset

    # [좌우각(Yaw) 계산] X축 전진, Z축 좌우 편차 기준
    if dx == 0:
        raw_yaw = 45.0 if dz > 0 else -45.0
    else:
        raw_yaw = math.degrees(math.atan2(dz, dx)) + yaw_offset

    # 플러그인 제한 범위 (-45.0 ~ +45.0) 적용 및 0.5도 단위 반올림
    yaw = max(-45.0, min(45.0, raw_yaw))
    yaw = round(round(yaw * 2) / 2, 1)

    powder_count = 2 if dist <= 350 else math.ceil(dist / 150)
    
    # [실전 캘리브레이션 데이터 룩업 테이블 반영]
    # 30m = +13.0, 50m = +8.0, 60m = +6.0, 80m = +1.5, 100m = -2.0
    if dist <= 40:
        base_pitch = 13.0 - ((dist - 30) / 20) * 5.0
    elif dist <= 70:
        base_pitch = 8.0 - ((dist - 50) / 30) * 6.5
    elif dist <= 100:
        base_pitch = 1.5 - ((dist - 80) / 20) * 3.5
    else:
        # 100m 초과 원거리 구간
        base_pitch = -2.0 - ((dist - 100) * 0.18)

    # 상하각(Pitch) 무조건 0.5도 단위 반올림
    base_pitch = round(base_pitch * 2) / 2

    # 고저차(Y축) 보정 (0.5도 단위 적용)
    elevation_correction = (dy / max(dist, 1)) * 5
    final_pitch = round((base_pitch + elevation_correction) * 2) / 2

    return {
        "dist": round(dist, 1), 
        "yaw": yaw,
        "pitch": final_pitch, 
        "powder": powder_count
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
@app_commands.describe(mx="내 X", mz="내 Z", tx="적 X", tz="적 Z", my="내 Y (기본 64)", ty="적 Y (기본 64)")
async def mortar_slash(interaction: discord.Interaction, mx: float, mz: float, tx: float, tz: float, my: float = 64.0, ty: float = 64.0):
    guild_id = interaction.guild.id if interaction.guild else 0
    server_zero = guild_zeroing_data.get(guild_id, {"dist_offset": 0.0, "yaw_offset": 0.0})
    
    res = calculate_mortar(mx, my, mz, tx, ty, tz, server_zero["dist_offset"], server_zero["yaw_offset"])

    embed = discord.Embed(title="🚀 PlanetEarth 박격포 사격 제원", color=discord.Color.blue())
    embed.add_field(name="📏 측정 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="💣 장약 제원", value=f"화약 **{res['powder']}개** / TNT **1개**", inline=True)
    
    sign_text = f"p: {res['powder']} c: TNT\n{res['yaw']}/{res['pitch']}"
    embed.add_field(name="📝 표지판 입력 값", value=f"```\n{sign_text}\n```", inline=False)

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)