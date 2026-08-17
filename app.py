import os
import asyncio
import base64
import subprocess
import requests
import imageio_ffmpeg
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputStream, InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio
from Crypto.Cipher import DES

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_BIN)

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAGHpKJH9vKkaFast9VpKjUFJ6PWNpFLvKs"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"

DES_KEY = b"38346591"

def decrypt_url(enc_url):
    cipher = DES.new(DES_KEY, DES.MODE_ECB)
    dec = cipher.decrypt(base64.b64decode(enc_url))
    url = dec.decode('utf-8', errors='ignore')
    pad = ord(url[-1])
    if 0 < pad <= 8:
        url = url[:-pad]
    return url.replace("_96.mp4", "_320.mp4")

def download_and_convert(query):
    search_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query={query}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(search_url, headers=headers, timeout=10)
    data = r.json()
    songs = data.get("songs", {}).get("data", [])
    if not songs:
        raise Exception("Song not found! Check spelling.")
    
    song_id = songs[0].get("id")
    title = songs[0].get("title", "Song").replace("&quot;", '"').replace("&amp;", "&")
    singers = songs[0].get("more_info", {}).get("singers", "Artist")

    detail_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}"
    r_detail = requests.get(detail_url, headers=headers, timeout=10)
    detail_data = r_detail.json()
    
    song_data = detail_data.get(song_id)
    if not song_data:
        raise Exception("Unable to get song details.")

    duration_sec = int(song_data.get("duration", 0))
    mins = duration_sec // 60
    secs = duration_sec % 60
    duration_str = f"{mins:02d}:{secs:02d}"

    encrypted_media_url = song_data.get("encrypted_media_url")
    stream_url = decrypt_url(encrypted_media_url)
    
    mp3_file = f"temp_{song_id}.mp3"
    raw_file = f"track_{song_id}.raw"
    
    audio_req = requests.get(stream_url, headers=headers, timeout=25)
    with open(mp3_file, "wb") as f:
        f.write(audio_req.content)
        
    # Convert MP3 to standard 48kHz Stereo PCM (fixes static noise)
    cmd = [
        FFMPEG_BIN, "-y", "-i", mp3_file,
        "-f", "s16le", "-ac", "2", "-ar", "48000",
        raw_file
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(mp3_file):
        os.remove(mp3_file)
        
    return raw_file, title, singers, duration_str

async def handle_ping(request):
    return web.Response(text="Bot is live 24/7!")

async def main():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    app = Client("music_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    user = Client("assistant_account", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)
    call = PyTgCalls(user)

    @app.on_message(filters.command(["start", "ping"]))
    async def start_cmd(client, message):
        await message.reply_text("✅ **Bot is active and running!**\nUse `/play [song name]` to stream in Voice Chat.")

    @app.on_message(filters.command("play"))
    async def play_music(client, message):
        if len(message.command) < 2:
            await message.reply_text("❌ **Please provide a song title!**\nExample: `/play Kesariya`")
            return
        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"🔎 **Searching & Preparing:** `{query}`...")
        try:
            loop = asyncio.get_running_loop()
            raw_path, title, singers, duration = await loop.run_in_executor(None, download_and_convert, query)
            
            try:
                await call.join_group_call(
                    message.chat.id,
                    InputStream(
                        InputAudioStream(
                            raw_path,
                            HighQualityAudio(),
                        )
                    )
                )
            except Exception:
                await call.change_stream(
                    message.chat.id,
                    InputStream(
                        InputAudioStream(
                            raw_path,
                            HighQualityAudio(),
                        )
                    )
                )
            
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⏹ Stop", callback_data="stop_music"),
                    InlineKeyboardButton("⏭ Skip", callback_data="stop_music")
                ]
            ])
            
            caption = (
                f"🎵 **Now Playing in Voice Chat**\n\n"
                f"📌 **Title:** `{title}`\n"
                f"🎤 **Artist:** `{singers}`\n"
                f"⏱ **Duration:** `{duration}`\n"
                f"🎧 **Audio Quality:** `High (48kHz Stereo)`"
            )
            await m.edit(caption, reply_markup=buttons)
            
        except Exception as e:
            await m.edit(f"❌ **Error:** `{str(e)}`")

    @app.on_callback_query(filters.regex("stop_music"))
    async def stop_cb(client, callback_query):
        try:
            await call.leave_group_call(callback_query.message.chat.id)
            await callback_query.message.edit("⏹ **Music stopped and Left Voice Chat.**")
        except Exception:
            await callback_query.answer("Stream already stopped.", show_alert=True)

    await app.start()
    await user.start()
    await call.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
