import discord
from discord.ext import commands
from discord import app_commands
import math
import os
import threading
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

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 서버별 영점 및 거리별 커스텀 보정값 저장소
guild_zeroing_data = {}

def calculate_mortar(mx: float, my: float, mz: float, tx: float, ty: float, tz: float, guild_id: int = 0):
    dx = tx - mx  # X축 (전진 거리)
    dz = tz - mz  # Z축 (좌우 편차)
    dy = ty - my

    # 평면 거리 계산
    dist = math.sqrt(dx * dx + dz * dz)

    # [좌우각(Yaw) 계산] X축 전진, Z축 좌우 편차 기준
    if dx == 0:
        raw_yaw = 45.0 if dz > 0 else -45.0
    else:
        raw_yaw = math.degrees(math.atan2(dz, dx))

    # 플러그인 제한 범위 (-45.0 ~ +45.0) 적용 및 0.5도 단위 반올림
    yaw = max(-45.0, min(45.0, raw_yaw))
    yaw = round(round(yaw * 2) / 2, 1)

    powder_count = 2 if dist <= 350 else math.ceil(dist / 150)
    
    # 서버별 커스텀 영점(학습된 값)이 있는지 확인 (±2m 이내 구간 적용)
    server_data = guild_zeroing_data.get(guild_id, {})
    custom_pitches = server_data.get("custom_pitches", {})
    
    applied_custom = False
    base_pitch = 0.0
    
    for d, p in custom_pitches.items():
        if abs(dist - d) <= 2.0:
            base_pitch = p
            applied_custom = True
            break
            
    # 커스텀 값이 없다면 기존 기본 룩업 테이블 공식 적용
    if not applied_custom:
        if dist <= 40:
            base_pitch = 13.0 - ((dist - 30) / 20) * 5.0
        elif dist <= 70:
            base_pitch = 8.0 - ((dist - 50) / 30) * 6.5
        elif dist <= 100:
            base_pitch = 1.5 - ((dist - 80) / 20) * 3.5
        else:
            # 100m 초과 원거리 구간 (120m = -7.5° 매칭 기울기 0.263)
            base_pitch = -2.0 - ((dist - 100) * 0.263)

        # 상하각(Pitch) 무조건 0.5도 단위 반올림
        base_pitch = round(base_pitch * 2) / 2

    # 고저차(Y축) 보정 (0.5도 단위 적용)
    elevation_correction = (dy / max(dist, 1)) * 5
    final_pitch = round((base_pitch + elevation_correction) * 2) / 2

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
@app_commands.describe(mx="내 X", mz="내 Z", tx="적 X", tz="적 Z", my="내 Y (기본 64)", ty="적 Y (기본 64)")
async def mortar_slash(interaction: discord.Interaction, mx: float, mz: float, tx: float, tz: float, my: float = 64.0, ty: float = 64.0):
    guild_id = interaction.guild.id if interaction.guild else 0
    res = calculate_mortar(mx, my, mz, tx, ty, tz, guild_id)

    embed = discord.Embed(title="🚀 PlanetEarth 박격포 사격 제원", color=discord.Color.blue())
    embed.add_field(name="📏 측정 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="💣 장약 제원", value=f"화약 **{res['powder']}개** / TNT **1개**", inline=True)
    
    if res['is_custom']:
        embed.set_footer(text="⭐ 이 서버에 학습된 커스텀 영점 데이터가 적용되었습니다.")

    sign_text = f"p: {res['powder']} c: TNT\n{res['yaw']}/{res['pitch']}"
    embed.add_field(name="📝 표지판 입력 값", value=f"```\n{sign_text}\n```", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="영점설정", description="특정 거리의 상하각 오차를 직접 수정하여 서버에 영점을 학습시킵니다.")
@app_commands.describe(distance="보정할 대략적 거리 (예: 120)", target_pitch="실제 명중하는 올바른 상하각 (예: -8.0)")
async def set_zeroing(interaction: discord.Interaction, distance: float, target_pitch: float):
    guild_id = interaction.guild.id if interaction.guild else 0
    
    if guild_id not in guild_zeroing_data:
        guild_zeroing_data[guild_id] = {"custom_pitches": {}}
    if "custom_pitches" not in guild_zeroing_data[guild_id]:
        guild_zeroing_data[guild_id]["custom_pitches"] = {}
        
    rounded_dist = round(distance)
    guild_zeroing_data[guild_id]["custom_pitches"][rounded_dist] = target_pitch
    
    await interaction.response.send_message(f"✅ **{rounded_dist}m** 부근의 상하각 영점이 **`{target_pitch}°`**(으)로 서버에 학습(저장)되었습니다! 이제부터 해당 거리에서 이 값이 우선 적용됩니다.")

bot.run(TOKEN)