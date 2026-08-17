import os
import asyncio
import json
import base64
import requests
from aiohttp import web
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputStream, InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio
from Crypto.Cipher import DES

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

def fetch_saavn_direct(query):
    search_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query={query}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(search_url, headers=headers, timeout=10)
    data = r.json()
    songs = data.get("songs", {}).get("data", [])
    if not songs:
        raise Exception("Song not found! Please check spelling.")
    
    song_id = songs[0].get("id")
    title = songs[0].get("title", "Song").replace("&quot;", '"').replace("&amp;", "&")

    detail_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}"
    r_detail = requests.get(detail_url, headers=headers, timeout=10)
    detail_data = r_detail.json()
    
    song_data = detail_data.get(song_id)
    if not song_data:
        raise Exception("Unable to retrieve audio stream.")

    encrypted_media_url = song_data.get("encrypted_media_url")
    stream_url = decrypt_url(encrypted_media_url)
    return stream_url, title

async def handle_ping(request):
    return web.Response(text="Bot is running 24/7!")

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
        await message.reply_text("✅ **Bot is active and running!**\nUse `/play [song name]` to play music in the Voice Chat.")

    @app.on_message(filters.command("play"))
    async def play_music(client, message):
        if len(message.command) < 2:
            await message.reply_text("❌ **Please provide a song title!**\nExample: `/play Kesariya`")
            return
        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"🔎 **Searching for:** `{query}`...")
        try:
            loop = asyncio.get_running_loop()
            stream_url, title = await loop.run_in_executor(None, fetch_saavn_direct, query)
            await m.edit(f"▶️ **Now Playing in Voice Chat:** `{title}`")
            await call.join_group_call(
                message.chat.id,
                InputStream(
                    InputAudioStream(
                        stream_url,
                        HighQualityAudio(),
                    )
                )
            )
        except Exception as e:
            await m.edit(f"❌ **Error:** `{str(e)}`")

    await app.start()
    await user.start()
    await call.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
