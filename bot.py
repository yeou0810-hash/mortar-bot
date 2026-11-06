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

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 서버별 영점 및 거리별 커스텀 보정값 저장소
guild_zeroing_data = {}

# 📌 10m ~ 160m 확정 정밀 사격 룩업 테이블 (화약 개수, 상하각 Pitch)
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
    dx = tx - mx  # X축 전진 거리
    dz = tz - mz  # Z축 좌우 편차
    dy = ty - my

    # 평면 거리 계산
    dist = math.sqrt(dx * dx + dz * dz)

    # [좌우각(Yaw) 계산] 플러그인 제한 범위 (-45.0 ~ +45.0) 적용 및 0.5도 단위 반올림
    if dx == 0:
        raw_yaw = 45.0 if dz > 0 else -45.0
    else:
        raw_yaw = math.degrees(math.atan2(dz, dx))

    yaw = max(-45.0, min(45.0, raw_yaw))
    yaw = round(round(yaw * 2) / 2, 1)

    # 서버별 커스텀 영점(학습된 값)이 있는지 확인 (±2m 이내 구간 적용)
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

    # 커스텀 값이 없다면 가장 가까운 10m 단위 룩업 테이블 적용
    if not applied_custom:
        rounded_table_dist = int(round(dist / 10.0) * 10)
        if rounded_table_dist < 10:
            rounded_table_dist = 10
        elif rounded_table_dist > 160:
            rounded_table_dist = 160
        
        powder_count, base_pitch = BALLISTIC_TABLE[rounded_table_dist]

    # 고저차(Y축) 보정 적용 (0.5도 단위 반올림)
    elevation_correction = (dy / max(dist, 1)) * 5
    final_pitch = round((base_pitch + elevation_correction) * 2) / 2

    # 시스템 한계치 강제 보호 (-20° ~ +20°)
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
@app_commands.describe(
    mx="내 X 좌표", 
    mz="내 Z 좌표", 
    my="내 Y 좌표 (선택사항, 입력 안 하면 64)", 
    tx="적 X 좌표", 
    tz="적 Z 좌표", 
    ty="적 Y 좌표 (선택사항, 입력 안 하면 64)"
)
async def mortar_slash(
    interaction: discord.Interaction, 
    mx: float, 
    mz: float, 
    tx: float, 
    tz: float, 
    my: Optional[float] = None, 
    ty: Optional[float] = None
):
    # Y 좌표를 입력하지 않았다면 기본값 64.0으로 자동 지정
    real_my = my if my is not None else 64.0
    real_ty = ty if ty is not None else 64.0

    guild_id = interaction.guild.id if interaction.guild else 0
    res = calculate_mortar(mx, real_my, mz, tx, real_ty, tz, guild_id)

    embed = discord.Embed(title="🚀 PlanetEarth 박격포 사격 제원", color=discord.Color.blue())
    embed.add_field(name="📏 측정 거리", value=f"`{res['dist']}m`", inline=True)
    embed.add_field(name="💣 장약 제원", value=f"화약 **{res['powder']}개** / TNT **1개**", inline=True)
    
    if res['is_custom']:
        embed.set_footer(text="⭐ 이 서버에 학습된 커스텀 영점 데이터가 적용되었습니다.")

    sign_text = f"p: {res['powder']} c: TNT\n{res['yaw']}/{res['pitch']}"
    embed.add_field(name="📝 표지판 입력 값", value=f"```\n{sign_text}\n```", inline=False)

    await interaction.response.send_message(embed