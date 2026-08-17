import os
import asyncio
import aiohttp
from aiohttp import web
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputStream, InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAGHpKJH9vKkaFast9VpKjUFJ6PWNpFLvKs"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"

async def fetch_song_stream(query):
    api_url = f"https://saavn.dev/api/search/songs?query={query}&page=1&limit=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("data", {}).get("results", [])
                if results:
                    song = results[0]
                    title = song.get("name", "Music")
                    download_urls = song.get("downloadUrl", [])
                    if download_urls:
                        stream_url = download_urls[-1].get("url")
                        return stream_url, title
    raise Exception("Gaana nahi mila!")

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
    print(f"Web server started on port {port}")

    app = Client("music_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    user = Client("assistant_account", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)
    call = PyTgCalls(user)

    @app.on_message(filters.command(["start", "ping"]))
    async def start_cmd(client, message):
        await message.reply_text("✅ Bot bilkul active chhe! Gaano vagadva mate `/play [song name]` lakho.")

    @app.on_message(filters.command("play"))
    async def play_music(client, message):
        if len(message.command) < 2:
            await message.reply_text("❌ Kripya gaana nu naam lakho! Example: `/play Kesariya`")
            return
        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"🔎 `{query}` search thai rahyu chhe...")
        try:
            stream_url, title = await fetch_song_stream(query)
            await m.edit(f"▶️ **Voice Chat ma vaagi rahyu chhe:** `{title}`")
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
            await m.edit(f"❌ Error: {str(e)}")

    await app.start()
    await user.start()
    await call.start()
    print("\nBot aur Assistant ready!")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
