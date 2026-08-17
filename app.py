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
from pyrogram.enums import ChatMemberStatus
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
LEAVE_TIMERS = {}
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
    
    if os.path.exists(mp3_file):
        os.remove(mp3_file)
        
    return raw_file, title, singers, duration_sec, duration_str, thumb

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
    if user_id in [63631826]:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return True
    except Exception:
        pass
    return False

async def handle_ping(request):
    return web.Response(text="Bot is running!")

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

    async def ensure_assistant_in_group(chat_id):
        try:
            assistant_user = await user.get_me()
            try:
                await app.get_chat_member(chat_id, assistant_user.id)
            except Exception:
                invite_link = await app.export_chat_invite_link(chat_id)
                await user.join_chat(invite_link)
        except Exception as e:
            print(f"Auto-join error: {e}")

    async def delayed_assistant_leave(chat_id, delay=180):
        try:
            # Wait for 3 minutes (180s) before leaving
            await asyncio.sleep(delay)
            if chat_id not in ACTIVE_TRACK:
                try:
                    await call.leave_group_call(chat_id)
                except Exception:
                    pass
                try:
                    await user.leave_chat(chat_id)
                except Exception:
                    pass
                await app.send_message(chat_id, "👋 **Assistant left due to 3 minutes of inactivity.**")
        except asyncio.CancelledError:
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
            # Start 3-minute countdown before leaving group
            if chat_id in LEAVE_TIMERS:
                LEAVE_TIMERS[chat_id].cancel()
            LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_assistant_leave(chat_id, 180))
            return

        stream = InputStream(InputAudioStream(next_song["path"], HighQualityAudio()))
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

        TIMERS[chat_id] = asyncio.create_task(track_timer_and_auto_next(chat_id, msg.id, next_song))

    async def track_timer_and_auto_next(chat_id, message_id, song_info):
        total_sec = song_info["duration_sec"]
        current_sec = 0
        while current_sec < total_sec:
            await asyncio.sleep(10)
            current_sec += 10
            if chat_id not in ACTIVE_TRACK or ACTIVE_TRACK[chat_id] != song_info:
                return
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
        await asyncio.sleep(2)
        await play_next(chat_id)

    @app.on_message(filters.command("play"))
    async def play_music(client, message):
        chat_id = message.chat.id
        if len(message.command) < 2:
            await message.reply_text("❌ **Please provide a song title!**\nExample: `/play Kesariya`")
            return
        
        # If assistant was about to leave, cancel countdown
        if chat_id in LEAVE_TIMERS:
            LEAVE_TIMERS[chat_id].cancel()
            LEAVE_TIMERS.pop(chat_id, None)

        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"🔎 **Searching & Preparing:** `{query}`...")
        
        await ensure_assistant_in_group(chat_id)

        try:
            loop = asyncio.get_running_loop()
            raw_path, title, singers, dur_sec, dur_str, thumb = await loop.run_in_executor(None, download_and_convert, query)
            
            song_obj = {
                "path": raw_path,
                "title": title,
                "artist": singers,
                "duration_sec": dur_sec,
                "duration_str": dur_str,
                "thumb": thumb
            }
            
            if chat_id in ACTIVE_TRACK:
                if chat_id not in QUEUE:
                    QUEUE[chat_id] = []
                QUEUE[chat_id].append(song_obj)
                pos = len(QUEUE[chat_id])
                await m.delete()
                await message.reply_text(
                    f" Queued at Position #{pos}\n\n"
                    f"📌 **Title:** `{title}`\n"
                    f"⏱ **Duration:** `{dur_str}`"
                )
            else:
                ACTIVE_TRACK[chat_id] = song_obj
                stream = InputStream(InputAudioStream(raw_path, HighQualityAudio()))
                try:
                    await call.join_group_call(chat_id, stream)
                except Exception:
                    await call.change_stream(chat_id, stream)
                
                await m.delete()
                bar = get_progress_bar(0, dur_sec)
                caption = (
                    f"🎵 **Now Playing in Voice Chat**\n\n"
                    f"📌 **Title:** `{title}`\n"
                    f"🎤 **Artist:** `{singers}`\n"
                    f"⏱ **Time:** `00:00 {bar} {dur_str}`\n"
                    f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
                )
                if thumb:
                    msg = await message.reply_photo(photo=thumb, caption=caption, reply_markup=get_controls())
                else:
                    msg = await message.reply_text(caption, reply_markup=get_controls())
                    
                TIMERS[chat_id] = asyncio.create_task(track_timer_and_auto_next(chat_id, msg.id, song_obj))
                    
        except Exception as e:
            await m.edit(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command(["stop", "end"]))
    async def stop_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Only Admins can use this command!**")
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
        except Exception:
            pass
            
        if chat_id in LEAVE_TIMERS:
            LEAVE_TIMERS[chat_id].cancel()
        LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_assistant_leave(chat_id, 180))
        await message.reply_text("⏹ **Music stopped. Assistant will leave in 3 minutes if no new songs are played.**")

    @app.on_message(filters.command(["skip", "next"]))
    async def skip_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Only Admins can use this command!**")
            return
        await play_next(message.chat.id)

    @app.on_message(filters.command("pause"))
    async def pause_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Only Admins can use this command!**")
            return
        try:
            await call.pause_stream(message.chat.id)
            await message.reply_text("⏸ **Music paused.**")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command("resume"))
    async def resume_cmd(client, message):
        if not await is_admin(client, message.chat.id, message.from_user.id):
            await message.reply_text("❌ **Only Admins can use this command!**")
            return
        try:
            await call.resume_stream(message.chat.id)
            await message.reply_text("▶️ **Music resumed.**")
        except Exception as e:
            await message.reply_text(f"❌ **Error:** `{str(e)}`")

    @app.on_message(filters.command("queue"))
    async def queue_cmd(client, message):
        chat_id = message.chat.id
        if chat_id not in QUEUE or not QUEUE[chat_id]:
            await message.reply_text("📜 **Queue is empty.**")
            return
        queue_text = "📜 **Upcoming Songs:**\n\n"
        for i, song in enumerate(QUEUE[chat_id], 1):
            queue_text += f"{i}. `{song['title']}` | `{song['duration_str']}`\n"
        await message.reply_text(queue_text)

    @app.on_message(filters.command(["start", "help"]))
    async def help_cmd(client, message):
        await message.reply_text("🎵 **Bot Commands:**\n`/play [song]` | `/skip` | `/pause` | `/resume` | `/stop` | `/queue` | `/shuffle` | `/loop`")

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
                await query.answer("Not enough tracks", show_alert=True)
                
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
            except Exception:
                pass
            if chat_id in LEAVE_TIMERS:
                LEAVE_TIMERS[chat_id].cancel()
            LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_assistant_leave(chat_id, 180))
            try:
                await query.message.delete()
            except Exception:
                pass
            await app.send_message(chat_id, "⏹ **Music stopped. Assistant will leave in 3 minutes if inactive.**")

    await app.start()
    await user.start()
    await call.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
