import os
import asyncio
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped
import yt_dlp

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAGHpKJH9vKkaFast9VpKjUFJ6PWNpFLvKs"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"

app = Client("music_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("assistant_account", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)
call = PyTgCalls(user)

ydl_ops = {
    'format': 'bestaudio/best',
    'default_search': 'ytsearch1',
    'outtmpl': '%(id)s.%(ext)s',
    'quiet': True,
    'nocheckcertificate': True
}

@app.on_message(filters.command("play") & filters.group)
async def play_music(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Kripya gane ka naam likhein! Example: `/play Kesariya`")
        return

    chat_id = message.chat.id
    query = message.text.split(None, 1)[1]
    m = await message.reply_text("🔎 Gana dhund raha hoon...")

    try:
        with yt_dlp.YoutubeDL(ydl_ops) as ydl:
            info_dict = ydl.extract_info(query, download=True)
            video_data = info_dict['entries'][0] if 'entries' in info_dict else info_dict
            file_path = ydl.prepare_filename(video_data)
            title = video_data.get('title', 'Music')

        await m.edit(f"▶️ **Voice Chat me baj raha hai:** `{title}`")
        await call.play(chat_id, AudioPiped(file_path))

    except Exception as e:
        await m.edit(f"❌ Error: {str(e)}")

async def start_services():
    await app.start()
    await user.start()
    await call.start()
    print("Bot aur Assistant VC ke liye ready hain!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_services())
