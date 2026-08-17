import os
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputStream, InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio
import yt_dlp

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAGHpKJH9vKkaFast9VpKjUFJ6PWNpFLvKs"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"

app = Client("music_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("assistant_account", api_id=API_ID, api_hash=API_HASH, sessionstring=STRING_SESSION if hasattr(Client, "sessionstring") else None, session_string=STRING_SESSION)
call = PyTgCalls(user)

ydl_ops = {
    'format': 'bestaudio/best',
    'default_search': 'ytsearch1',
    'outtmpl': '%(id)s.%(ext)s',
    'quiet': True,
    'nocheckcertificate': True
}

def download_audio(query):
    with yt_dlp.YoutubeDL(ydl_ops) as ydl:
        info = ydl.extract_info(query, download=True)
        data = info['entries'][0] if 'entries' in info else info
        return ydl.prepare_filename(data), data.get('title', 'Music')

@app.on_message(filters.command("play") & filters.group)
async def play_music(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Gaane ka naam likhein! Example: `/play Kesariya`")
        return
    query = message.text.split(None, 1)[1]
    m = await message.reply_text("🔎 Gaana search ho raha hai...")
    try:
        loop = asyncio.get_running_loop()
        file_path, title = await loop.run_in_executor(None, download_audio, query)
        await m.edit(f"▶️ **Voice Chat me baj raha hai:** `{title}`")
        await call.join_group_call(
            message.chat.id,
            InputStream(
                InputAudioStream(
                    file_path,
                    HighQualityAudio(),
                )
            )
        )
    except Exception as e:
        await m.edit(f"❌ Error: {str(e)}")

async def handle_ping(request):
    return web.Response(text="Bot is running 24/7!")

async def start_services():
    await app.start()
    await user.start()
    await call.start()
    print("\nBot aur Assistant VC ke liye ready hain!")
    
    server = web.Application()
    server.router.add_get("/", handle_ping)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_services())
