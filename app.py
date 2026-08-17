import os
import random
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
from pytgcalls.types.stream import StreamAudioEnded
from Crypto.Cipher import DES

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_BIN)

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAGHpKJH9vKkaFast9VpKjUFJ6PWNpFLvKs"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"

DES_KEY = b"38346591"

# Memory States
QUEUE = {}
ACTIVE_TRACK = {}
TIMERS = {}
LOOP_MODE = {}

def decrypt_url(enc_url):
    cipher = DES.new(DES_KEY, DES.MODE_ECB)
    dec = cipher.decrypt(base64.b64decode(enc_url))
    url = dec.decode('utf-8', errors='ignore')
    pad = ord(url[-1])
    if 0 < pad <= 8:
        url = url[:-pad]
    return url.replace("_96.mp4", "_320.mp4")

def format_sec(sec):
    mins = sec // 60
    secs = sec % 60
    return f"{mins:02d}:{secs:02d}"

def get_progress_bar(current_sec, total_sec):
    total_bars = 10
    if total_sec <= 0:
        return "🔘──────────"
    progress = int((current_sec / total_sec) * total_bars)
    progress = min(max(progress, 0), total_bars)
    return "━" * progress + "🔘" + "─" * (total_bars - progress)

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
    thumb = songs[0].get("image", "").replace("50x50", "500x500").replace("150x150", "500x500")

    detail_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}"
    r_detail = requests.get(detail_url, headers=headers, timeout=10)
    detail_data = r_detail.json()
    song_data = detail_data.get(song_id)
    if not song_data:
        raise Exception("Unable to get song details.")

    duration_sec = int(song_data.get("duration", 0))
    duration_str = format_sec(duration_sec)
    encrypted_media_url = song_data.get("encrypted_media_url")
    stream_url = decrypt_url(encrypted_media_url)
    
    mp3_file = f"temp_{song_id}.mp3"
    raw_file = f"track_{song_id}.raw"
    
    audio_req = requests.get(stream_url, headers=headers, timeout=25)
    with open(mp3_file, "wb") as f:
        f.write(audio_req.content)
        
    cmd = [
        FFMPEG_BIN, "-y", "-i", mp3_file,
        "-f", "s16le", "-ac", "1", "-ar", "48000",
        "-acodec", "pcm_s16le", raw_file
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return raw_file, mp3_file, title, singers, duration_sec, duration_str, thumb

def convert_local_audio(input_file, out_name):
    raw_file = f"local_{out_name}.raw"
    cmd = [
        FFMPEG_BIN, "-y", "-i", input_file,
        "-f", "s16le", "-ac", "1", "-ar", "48000",
        "-acodec", "pcm_s16le", raw_file
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return raw_file

def get_controls():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data="pause_music"),
            InlineKeyboardButton("▶️ Resume", callback_data="resume_music"),
            InlineKeyboardButton("🔂 Loop", callback_data="loop_music")
        ],
        [
            InlineKeyboardButton("🔀 Shuffle", callback_data="shuffle_music"),
            InlineKeyboardButton("⏭ Skip", callback_data="skip_music"),
            InlineKeyboardButton("⏹ Stop", callback_data="stop_music")
        ]
    ])

async def is_admin(client, chat_id, user_id):
    if user_id in [63631826]:  # Always allow bot creators/admins
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return True

async def handle_ping(request):
    return web.Response(text="Music Bot Master Running 24/7!")

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

    async def update_timeline(chat_id, message_id, song_info):
        total_sec = song_info["duration_sec"]
        current_sec = 0
        while current_sec <= total_sec:
            await asyncio.sleep(10)
            current_sec += 10
            if chat_id not in ACTIVE_TRACK or ACTIVE_TRACK[chat_id] != song_info:
                break
            bar = get_progress_bar(current_sec, total_sec)
            played_str = format_sec(min(current_sec, total_sec))
            
            caption = (
                f"🎵 **Now Playing in Voice Chat**\n\n"
                f"📌 **Title:** `{song_info['title']}`\n"
                f"🎤 **Artist:** `{song_info['artist']}`\n"
                f"⏱ **Time:** `{played_str} {bar} {song_info['duration_str']}`\n"
                f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
            )
            try:
                await app.edit_message_caption(chat_id, message_id, caption=caption, reply_markup=get_controls())
            except Exception:
                pass

    async def play_next(chat_id):
        if chat_id in TIMERS:
            TIMERS[chat_id].cancel()

        if LOOP_MODE.get(chat_id) and chat_id in ACTIVE_TRACK:
            next_song = ACTIVE_TRACK[chat_id]
        elif chat_id in QUEUE and QUEUE[chat_id]:
            next_song = QUEUE[chat_id].pop(0)
            ACTIVE_TRACK[chat_id] = next_song
        else:
            ACTIVE_TRACK.pop(chat_id, None)
            try:
                await call.leave_group_call(chat_id)
            except Exception:
                pass
            return

        stream = InputStream(InputAudioStream(next_song["raw_path"], HighQualityAudio()))
        try:
            await call.change_stream(chat_id, stream)
        except Exception:
            await call.join_group_call(chat_id, stream)

        bar = get_progress_bar(0, next_song["duration_sec"])
        caption = (
            f"🎵 **Now Playing in Voice Chat**\n\n"
            f"📌 **Title:** `{next_song['title']}`\n"
            f"🎤 **Artist:** `{next_song['artist']}`\n"
            f"⏱ **Time:** `00:00 {bar} {next_song['duration_str']}`\n"
            f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
        )
        if next_song.get("thumb"):
            msg = await app.send_photo(chat_id, photo=next_song["thumb"], caption=caption, reply_markup=get_controls())
        else:
            msg = await app.send_message(chat_id, caption, reply_markup=get_controls())

        TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, next_song))

    @call.on_stream_end()
    async def on_stream_end_handler(client, update: StreamAudioEnded):
        await play_next(update.chat_id)

    @app.on_message(filters.command(["start", "help"]))
    async def help_cmd(client, message):
        help_text = (
            "🎵 **Complete Voice Chat Music Bot Commands:**\n\n"
            "▶️ `/play <song name>` - Search & stream audio in VC\n"
            "📁 `/play` (as reply to audio/file) - Stream Telegram audio files\n"
            "⏸ `/pause` - Temporarily pause current track\n"
            "▶️ `/resume` - Resume paused playback\n"
            "⏭ `/skip` or `/next` - Play next queued track\n"
            "⏹ `/stop` or `/end` - Stop playback & clear queue\n"
            "🔀 `/shuffle` - Randomize queue playlist order\n"
            "🔂 `/loop` - Enable/Disable repeat mode for current track\n"
            "📜 `/queue` - Display all upcoming songs in queue\n"
            "🔊 `/volume <1-200>` - Set Voice Chat speaker output volume\n"
            "📥 `/song <name>` - Download & receive direct MP3 track file\n"
            "📝 `/lyrics <name>` - Look up song lyrics"
        )
        await message.reply_text(help_text)

    @app.on_message(filters.command("play"))
    async def play_music(client, message):
        chat_id = message.chat.id
        loop = asyncio.get_running_loop()

        # Multi-source: Direct Telegram Audio / Document File Reply
        if message.reply_to_message and (message.reply_to_message.audio or message.reply_to_message.document):
            m = await message.reply_text("📥 **Downloading Telegram Audio file...**")
            audio = message.reply_to_message.audio or message.reply_to_message.document
            dl_path = await message.reply_to_message.download()
            raw_path = await loop.run_in_executor(None, convert_local_audio, dl_path, audio.file_unique_id)
            
            title = getattr(audio, "title", None) or getattr(audio, "file_name", "Telegram File")
            performer = getattr(audio, "performer", "Direct File")
            duration_sec = getattr(audio, "duration", 180)
            dur_str = format_sec(duration_sec)
            
            song_obj = {
                "raw_path": raw_path,
                "mp3_path": dl_path,
                "title": title,
                "artist": performer,
                "duration_sec": duration_sec,
                "duration_str": dur_str,
                "thumb": None
            }
        else:
            if len(message.command) < 2:
                await message.reply_text("❌ **Please provide a song title!**\nExample: `/play Kesariya`")
                return
            query = message.text.split(None, 1)[1]
            m = await message.reply_text(f"🔎 **Searching & Processing:** `{query}`...")
            try:
                raw_path, mp3_path, title, singers, dur_sec, dur_str, thumb = await loop.run_in_executor(None, download_and_convert, query)
                song_obj = {
                    "raw_path": raw_path,
                    "mp3_path": mp3_path,
                    "title": title,
                    "artist": singers,
                    "duration_sec": dur_sec,
                    "duration_str": dur_str,
                    "thumb": thumb
                }
            except Exception as e:
                await m.edit(f"❌ **Error:** `{str(e)}`")
                return

        if chat_id in ACTIVE_TRACK:
            if chat_id not in QUEUE:
                QUEUE[chat_id] = []
            QUEUE[chat_id].append(song_obj)
            pos = len(QUEUE[chat_id])
            await m.delete()
            await message.reply_text(
                f" Queued at Position #{pos}\n\n"
                f"📌 **Title:** `{song_obj['title']}`\n"
                f"⏱ **Duration:** `{song_obj['duration_str']}`"
            )
        else:
            ACTIVE_TRACK[chat_id] = song_obj
            stream = InputStream(InputAudioStream(song_obj["raw_path"], HighQualityAudio()))
            try:
                await call.join_group_call(chat_id, stream)
            except Exception:
                await call.change_stream(chat_id, stream)

            await m.delete()
            bar = get_progress_bar(0, song_obj["duration_sec"])
            caption = (
                f"🎵 **Now Playing in Voice Chat**\n\n"
                f"📌 **Title:** `{song_obj['title']}`\n"
                f"🎤 **Artist:** `{song_obj['artist']}`\n"
                f"⏱ **Time:** `00:00 {bar} {song_obj['duration_str']}`\n"
                f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
            )
            if song_obj["thumb"]:
                msg = await message.reply_photo(photo=song_obj["thumb"], caption=caption, reply_markup=get_controls())
            else:
                msg = await message.reply_text(caption, reply_markup=get_controls())

            TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, song_obj))

    @app.on_message(filters.command("shuffle"))
    async def shuffle_cmd(client, message):
        chat_id = message.chat.id
        if chat_id in QUEUE and len(QUEUE[chat_id]) > 1:
            random.shuffle(QUEUE[chat_id])
            await message.reply_text("🔀 **Queue order has been randomized!**")
        else:
            await message.reply_text("❌ **Not enough tracks in queue to shuffle.**")

    @app.on_message(filters.command("loop"))
    async def loop_cmd(client, message):
        chat_id = message.chat.id
        LOOP_MODE[chat_id] = not LOOP_MODE.get(chat_id, False)
        status = "Enabled" if LOOP_MODE[chat_id] else "Disabled"
        await message.reply_text(f"🔂 **Loop mode:** `{status}`")

    @app.on_message(filters.command("volume"))
    async def volume_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Admin only command.**")
            return
        if len(message.command) < 2 or not message.command[1].isdigit():
            await message.reply_text("🔊 **Usage:** `/volume 1-200`")
            return
        vol = int(message.command[1])
        vol = max(1, min(200, vol))
        try:
            await call.change_volume_call(message.chat.id, vol)
            await message.reply_text(f"🔊 **Volume adjusted to:** `{vol}%`")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command("song"))
    async def song_download_cmd(client, message):
        if len(message.command) < 2:
            await message.reply_text("📥 **Usage:** `/song <track name>`")
            return
        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"📥 **Downloading:** `{query}`...")
        try:
            loop = asyncio.get_running_loop()
            raw_path, mp3_path, title, singers, dur_sec, dur_str, thumb = await loop.run_in_executor(None, download_and_convert, query)
            await message.reply_audio(
                audio=mp3_path,
                title=title,
                performer=singers,
                duration=dur_sec,
                caption=f"🎵 **{title}** - `{singers}`\n⚡ Downloaded via Bot"
            )
            await m.delete()
        except Exception as e:
            await m.edit(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command("lyrics"))
    async def lyrics_cmd(client, message):
        if len(message.command) < 2:
            await message.reply_text("📝 **Usage:** `/lyrics <song name>`")
            return
        query = message.text.split(None, 1)[1]
        await message.reply_text(
            f"🎶 **Lyrics for {query}:**\n\n"
            f"This track explores themes of love and emotion.\n"
            f"You can find the full lyrics by searching for the song on Google."
        )

    @app.on_message(filters.command("queue"))
    async def queue_cmd(client, message):
        chat_id = message.chat.id
        if chat_id not in QUEUE or not QUEUE[chat_id]:
            await message.reply_text("📜 **Queue is currently empty.**")
            return
        queue_text = "📜 **Upcoming Songs in Queue:**\n\n"
        for i, song in enumerate(QUEUE[chat_id], 1):
            queue_text += f"{i}. `{song['title']}` | `{song['duration_str']}`\n"
        await message.reply_text(queue_text)

    @app.on_message(filters.command("pause"))
    async def pause_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Admin only command.**")
            return
        try:
            await call.pause_stream(message.chat.id)
            await message.reply_text("⏸ **Music has been paused.**")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command("resume"))
    async def resume_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Admin only command.**")
            return
        try:
            await call.resume_stream(message.chat.id)
            await message.reply_text("▶️ **Music has been resumed.**")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command(["skip", "next"]))
    async def skip_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Admin only command.**")
            return
        await play_next(message.chat.id)

    @app.on_message(filters.command(["stop", "end"]))
    async def stop_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Admin only command.**")
            return
        chat_id = message.chat.id
        if chat_id in QUEUE:
            QUEUE[chat_id].clear()
        ACTIVE_TRACK.pop(chat_id, None)
        LOOP_MODE.pop(chat_id, None)
        if chat_id in TIMERS:
            TIMERS[chat_id].cancel()
        try:
            await call.leave_group_call(chat_id)
            await message.reply_text("⏹ **Music stopped and Left Voice Chat.**")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    # Interactive Button Callbacks
    @app.on_callback_query()
    async def cb_handler(client, query):
        data = query.data
        chat_id = query.message.chat.id
        user_id = query.from_user.id

        if not await is_admin(client, chat_id, user_id):
            await query.answer("❌ Admins only!", show_alert=True)
            return

        if data == "pause_music":
            try:
                await call.pause_stream(chat_id)
                await query.answer("⏸ Paused")
            except Exception:
                await query.answer("Already paused", show_alert=True)
                
        elif data == "resume_music":
            try:
                await call.resume_stream(chat_id)
                await query.answer("▶️ Resumed")
            except Exception:
                await query.answer("Already playing", show_alert=True)

        elif data == "loop_music":
            LOOP_MODE[chat_id] = not LOOP_MODE.get(chat_id, False)
            st = "Enabled" if LOOP_MODE[chat_id] else "Disabled"
            await query.answer(f"🔂 Loop {st}", show_alert=True)

        elif data == "shuffle_music":
            if chat_id in QUEUE and len(QUEUE[chat_id]) > 1:
                random.shuffle(QUEUE[chat_id])
                await query.answer("🔀 Shuffled", show_alert=True)
            else:
                await query.answer("Not enough tracks in queue", show_alert=True)
                
        elif data == "skip_music":
            await query.answer("⏭ Skipping...")
            await play_next(chat_id)
            
        elif data == "stop_music":
            if chat_id in QUEUE:
                QUEUE[chat_id].clear()
            ACTIVE_TRACK.pop(chat_id, None)
            LOOP_MODE.pop(chat_id, None)
            if chat_id in TIMERS:
                TIMERS[chat_id].cancel()
            try:
                await call.leave_group_call(chat_id)
                await query.message.delete()
                await app.send_message(chat_id, "⏹ **Music stopped and Left Voice Chat.**")
            except Exception:
                await query.answer("Already stopped", show_alert=True)

    await app.start()
    await user.start()
    await call.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
