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
    dx = tx - mx
    dy = ty - my
    dz = tz - mz

    dist = math.sqrt(dx * dx + dz * dz) + dist_offset
    yaw = math.degrees(math.atan2(-dx, dz)) + yaw_offset
    
    if yaw > 180: yaw -= 360
    elif yaw < -180: yaw += 360
    yaw = round(yaw, 1)

    powder_count = 2 if dist <= 350 else math.ceil(dist / 150)
    
    # [우리가 직접 검증한 실전 캘리브레이션 데이터 반영]
    # 30m = +13.0, 50m = +8.0, 60m = +6.0, 80m = +1.5, 100m = -2.0
    # 마인크래프트 포물선 곡률과 0.5도 단위 제약을 만족하는 정밀 보간 공식 적용
    if dist <= 40:
        # 30m~50m 구간 보간
        base_pitch = 13.0 - ((dist - 30) / 20) * 5.0
    elif dist <= 70:
        # 50m~60m, 60m~80m 구간 부드러운 연결
        base_pitch = 8.0 - ((dist - 50) / 30) * 6.5
    elif dist <= 100:
        # 80m~100m 구간 보간
        base_pitch = 1.5 - ((dist - 80) / 20) * 3.5
    else:
        # 100m 초과 원거리 기본 선형 추정
        base_pitch = -2.0 - ((dist - 100) * 0.175)

    # 0.5도 단위로 반올림 (플러그인 필수 조건)
    base_pitch = round(base_pitch * 2) / 2

    # 고저차 반영 (Y축 오차 보정)
    elevation_correction = (dy / max(dist, 1)) * 5
    final_pitch = round((base_pitch + elevation_correction) * 2) / 2

    return {
        "dist": round(dist, 1), "yaw": yaw,
        "pitch": final_pitch, "powder": powder_count
    }

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 슬래시 명령어 {len(synced)}개 동기화 완료!")
    except Exception as e:
        print(f"❌ 동기화 실패: {e}")

@bot.tree.command(name="박격포", description="실전 데이터가 반영된 PlanetEarth 박격포 사격 제원을 계산합니다.")
@app_commands.describe(mx="내 X", mz="내 Z", tx="적 X", tz="적 Z", my="내 Y (기본 64)", ty="적 Y (기본 64)")
async def mortar_slash(interaction: discord.Interaction, mx: float, mz: float, tx: float, tz: float, my: float = 64.0, ty: float = 64.0):
    guild_id = interaction.guild.id if interaction.guild else 0
    server_zero = guild_zeroing_data.get(guild_id, {"dist_offset": 0.0, "yaw_offset": 0.0})
    
    res = calculate_mortar(mx, my, mz, tx, ty, tz, server_zero["dist_offset"], server_zero["yaw_offset"])

    embed = discord.Embed(title="🚀 PlanetEarth 실전 맞춤형 박격포 제원", color=discord.Color.blue())
    embed.add_field(name="📏 측정 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="💣 화약 개수", value=f"화약 **{res['powder']}개** / TNT **1개**", inline=True)
    
    sign_text = f"p: {res['powder']} c: TNT\n{res['yaw']}/{res['pitch']}"
    embed.add_field(name="📝 표지판 입력 값 (좌우/각도)", value=f"```\n{sign_text}\n```", inline=False)

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)