import os
import random
import asyncio
import base64
import subprocess
import aiohttp
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import InputStream, InputAudioStream
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pytgcalls.types.stream import StreamAudioEnded
from Crypto.Cipher import DES
import imageio_ffmpeg

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_BIN)

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAHAvGt04-_K1di9r8S6GqvfjBMRW2ZRQ1w"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"
DES_KEY = b"38346591"

QUEUE = {}
ACTIVE_TRACK = {}
PLAYED_TIME = {}
ADMIN_CACHE = {}
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

def run_ffmpeg_convert(mp3_file, raw_file, start_sec=0):
    cmd = [FFMPEG_BIN, "-y"]
    if start_sec > 0:
        cmd.extend(["-ss", str(start_sec)])
    cmd.extend([
        "-threads", "1",
        "-i", mp3_file,
        "-f", "s16le", "-ac", "1", "-ar", "48000",
        "-acodec", "pcm_s16le", raw_file
    ])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

async def async_download_and_convert(query, start_sec=0):
    search_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query={query}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(search_url, timeout=10) as r:
            data = await r.json(content_type=None)
            songs = data.get("songs", {}).get("data", [])
            if not songs:
                raise Exception("Song not found!")
            
            song_id = songs[0].get("id")
            title = songs[0].get("title", "Song").replace("&quot;", '"').replace("&amp;", "&")
            singers = songs[0].get("more_info", {}).get("singers", "Artist")
            thumb = songs[0].get("image", "").replace("50x50", "500x500").replace("150x150", "500x500")

        detail_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}"
        async with session.get(detail_url, timeout=10) as r_detail:
            detail_data = await r_detail.json(content_type=None)
            song_data = detail_data.get(song_id)
            duration_sec = int(song_data.get("duration", 0))
            stream_url = decrypt_url(song_data.get("encrypted_media_url"))

        mp3_file = f"t_{song_id}.mp3"
        raw_file = f"t_{song_id}_{start_sec}.raw"

        if not os.path.exists(mp3_file):
            async with session.get(stream_url, timeout=25) as audio_r:
                content = await audio_r.read()
                with open(mp3_file, "wb") as f:
                    f.write(content)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_ffmpeg_convert, mp3_file, raw_file, start_sec)
    
    return raw_file, title, singers, duration_sec, format_sec(duration_sec), thumb, mp3_file

def get_controls():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ Pause", "pause_music"), InlineKeyboardButton("▶️ Resume", "resume_music"), InlineKeyboardButton("🔂 Loop", "loop_music")],
        [InlineKeyboardButton("🔀 Shuffle", "shuffle_music"), InlineKeyboardButton("⏭ Skip", "skip_music"), InlineKeyboardButton("⏹ Stop", "stop_music")],
        [InlineKeyboardButton("🗑 Delete This", "delete_msg")]
    ])

def get_queue_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete This", "delete_msg")]])

async def reload_admin_cache(client, chat_id):
    try:
        admins = []
        async for m in client.get_chat_members(chat_id, filter=pyrogram.enums.ChatMembersFilter.ADMINISTRATORS):
            admins.append(m.user.id)
        ADMIN_CACHE[chat_id] = admins
        return admins
    except Exception:
        return []

async def is_admin(client, chat_id, user_id):
    if not user_id:
        return False
    if chat_id in ADMIN_CACHE and user_id in ADMIN_CACHE[chat_id]:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            if chat_id not in ADMIN_CACHE:
                ADMIN_CACHE[chat_id] = []
            ADMIN_CACHE[chat_id].append(user_id)
            return True
    except Exception:
        pass
    return False

async def handle_ping(request):
    return web.Response(text="Bot is running smoothly!")

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

    async def ensure_assistant(chat_id):
        try:
            bot_me = await app.get_me()
            bot_member = await app.get_chat_member(chat_id, bot_me.id)
            if bot_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return False
            try:
                await user.get_chat_member(chat_id, (await user.get_me()).id)
            except Exception:
                await user.join_chat(await app.export_chat_invite_link(chat_id))
            return True
        except Exception:
            return False

    async def delayed_leave(chat_id):
        await asyncio.sleep(180)
        if chat_id not in ACTIVE_TRACK:
            try:
                await call.leave_group_call(chat_id)
            except Exception:
                pass
            try:
                await user.leave_chat(chat_id)
            except Exception:
                pass

    async def play_next(chat_id):
        if chat_id in TIMERS:
            TIMERS[chat_id].cancel()
        PLAYED_TIME[chat_id] = 0
        
        if LOOP_MODE.get(chat_id) and chat_id in ACTIVE_TRACK:
            next_song = ACTIVE_TRACK[chat_id]
        elif chat_id in QUEUE and QUEUE[chat_id]:
            next_song = QUEUE[chat_id].pop(0)
            ACTIVE_TRACK[chat_id] = next_song
        else:
            ACTIVE_TRACK.pop(chat_id, None)
            PLAYED_TIME.pop(chat_id, None)
            try:
                await call.leave_group_call(chat_id)
            except Exception:
                pass
            LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_leave(chat_id))
            return
            
        stream = InputStream(InputAudioStream(next_song["path"], HighQualityAudio()))
        try:
            await call.change_stream(chat_id, stream)
        except Exception:
            await call.join_group_call(chat_id, stream)
        
        cap = (
            f"🎵 **Now Playing in Voice Chat**\n\n"
            f"📌 **Title:** `{next_song['title']}`\n"
            f"🎤 **Artist:** `{next_song['artist']}`\n"
            f"👤 **Req by:** {next_song['requester']}\n"
            f"⏱ **Time:** `00:00 {get_progress_bar(0, next_song['duration_sec'])} {next_song['duration_str']}`\n"
            f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
        )
        if next_song.get("thumb"):
            msg = await app.send_photo(chat_id, photo=next_song["thumb"], caption=cap, reply_markup=get_controls())
        else:
            msg = await app.send_message(chat_id, cap, reply_markup=get_controls())
        TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, next_song))

    async def update_timeline(chat_id, msg_id, song):
        start_at = PLAYED_TIME.get(chat_id, 0)
        for i in range(start_at, song["duration_sec"], 10):
            await asyncio.sleep(10)
            PLAYED_TIME[chat_id] = i
            if chat_id not in ACTIVE_TRACK or ACTIVE_TRACK[chat_id] != song:
                return
            try:
                await app.edit_message_caption(
                    chat_id,
                    msg_id,
                    caption=(
                        f"🎵 **Now Playing in Voice Chat**\n\n"
                        f"📌 **Title:** `{song['title']}`\n"
                        f"🎤 **Artist:** `{song['artist']}`\n"
                        f"👤 **Req by:** {song['requester']}\n"
                        f"⏱ **Time:** `{format_sec(i)} {get_progress_bar(i, song['duration_sec'])} {song['duration_str']}`\n"
                        f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
                    ),
                    reply_markup=get_controls()
                )
            except Exception:
                pass

    @call.on_stream_end()
    async def stream_end(client, update: StreamAudioEnded):
        await play_next(update.chat_id)

    @app.on_message(filters.command("play"))
    async def play_cmd(client, message):
        chat_id = message.chat.id
        if not await ensure_assistant(chat_id):
            return await message.reply_text("⚠️ **I need Admin rights (with Manage Video Chats permission) to invite my Assistant and play music!**")
        if len(message.command) < 2:
            return await message.reply_text("❌ **Please provide a song title!**\nExample: `/play Kesariya`")
        if chat_id in LEAVE_TIMERS:
            LEAVE_TIMERS[chat_id].cancel()
        
        query = message.text.split(None, 1)[1]
        m = await message.reply_text(f"🔎 **Searching & Preparing:** `{query}`...")
        
        try:
            raw_path, title, art, dur, dur_str, thumb, mp3_file = await async_download_and_convert(query, 0)
            
            song = {
                "path": raw_path,
                "mp3_file": mp3_file,
                "query": query,
                "title": title,
                "artist": art,
                "duration_sec": dur,
                "duration_str": dur_str,
                "thumb": thumb,
                "requester": message.from_user.mention if message.from_user else "User"
            }
            
            if chat_id in ACTIVE_TRACK:
                if chat_id not in QUEUE:
                    QUEUE[chat_id] = []
                QUEUE[chat_id].append(song)
                await m.delete()
                await message.reply_text(
                    f" Queued at Position #{len(QUEUE[chat_id])}\n\n"
                    f"📌 **Title:** `{title}`\n"
                    f"👤 **Requested By:** {song['requester']}\n"
                    f"⏱ **Duration:** `{dur_str}`",
                    reply_markup=get_queue_markup()
                )
            else:
                ACTIVE_TRACK[chat_id] = song
                PLAYED_TIME[chat_id] = 0
                stream = InputStream(InputAudioStream(raw_path, HighQualityAudio()))
                try:
                    await call.join_group_call(chat_id, stream)
                except Exception:
                    await call.change_stream(chat_id, stream)
                await m.delete()
                cap = (
                    f"🎵 **Now Playing in Voice Chat**\n\n"
                    f"📌 **Title:** `{title}`\n"
                    f"🎤 **Artist:** `{art}`\n"
                    f"👤 **Requested By:** {song['requester']}\n"
                    f"⏱ **Time:** `00:00 {get_progress_bar(0, dur)} {dur_str}`\n"
                    f"🎧 **Audio Quality:** `HD Audio (Lossless)`"
                )
                if thumb:
                    msg = await message.reply_photo(thumb, caption=cap, reply_markup=get_controls())
                else:
                    msg = await message.reply_text(cap, reply_markup=get_controls())
                TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, song))
        except Exception as e:
            await m.edit(f"❌ **Error:** `{e}`")

    @app.on_message(filters.command(["reload", "refresh", "admincache"]))
    async def reload_cmd(client, message):
        chat_id = message.chat.id
        if not await is_admin(client, chat_id, message.from_user.id if message.from_user else 0):
            return await message.reply_text("❌ **Only Admins can use this command!**")
        
        m = await message.reply_text("🔄 **Refreshing Admin Cache & Syncing Voice Chat...**")
        admins = await reload_admin_cache(client, chat_id)
        
        if chat_id in ACTIVE_TRACK:
            curr = ACTIVE_TRACK[chat_id]
            current_sec = PLAYED_TIME.get(chat_id, 0)
            raw_path, _, _, _, _, _, _ = await async_download_and_convert(curr["query"], current_sec)
            curr["path"] = raw_path
            
            stream = InputStream(InputAudioStream(raw_path, HighQualityAudio()))
            try:
                await call.change_stream(chat_id, stream)
            except Exception:
                try:
                    await call.join_group_call(chat_id, stream)
                except Exception:
                    pass

        await m.edit(f"✅ **Admin Cache Refreshed!** (`{len(admins)}` Admins Cached)\n🎧 **Voice Chat Stream Synced.**")

    @app.on_message(filters.command("queue"))
    async def queue_cmd(client, message):
        chat_id = message.chat.id
        if chat_id not in QUEUE or not QUEUE[chat_id]:
            return await message.reply_text("📜 **Queue is empty.**", reply_markup=get_queue_markup())
        queue_text = "📜 **Upcoming Songs in Queue:**\n\n"
        for i, song in enumerate(QUEUE[chat_id], 1):
            queue_text += f"{i}. `{song['title']}` | {song['requester']} | `{song['duration_str']}`\n"
        await message.reply_text(queue_text, reply_markup=get_queue_markup())

    @app.on_message(filters.command(["skip", "pause", "resume", "stop", "shuffle", "loop"]))
    async def admin_cmds(client, m):
        if not await is_admin(client, m.chat.id, m.from_user.id if m.from_user else 0):
            return await m.reply_text("❌ **Only Admins can use this command!**")
        cmd = m.command[0]
        if cmd == "skip":
            await play_next(m.chat.id)
            await m.reply_text("⏭ **Skipped!**")
        elif cmd == "pause":
            await call.pause_stream(m.chat.id)
            await m.reply_text("⏸ **Paused!**")
        elif cmd == "resume":
            await call.resume_stream(m.chat.id)
            await m.reply_text("▶️ **Resumed!**")
        elif cmd == "stop":
            QUEUE.pop(m.chat.id, None)
            ACTIVE_TRACK.pop(m.chat.id, None)
            PLAYED_TIME.pop(m.chat.id, None)
            LOOP_MODE.pop(m.chat.id, None)
            if m.chat.id in TIMERS:
                TIMERS[m.chat.id].cancel()
            try:
                await call.leave_group_call(m.chat.id)
            except Exception:
                pass
            LEAVE_TIMERS[m.chat.id] = asyncio.create_task(delayed_leave(m.chat.id))
            await m.reply_text("⏹ **Stopped and queue cleared!**")
        elif cmd == "shuffle":
            if m.chat.id in QUEUE and len(QUEUE[m.chat.id]) > 1:
                random.shuffle(QUEUE[m.chat.id])
                await m.reply_text("🔀 **Shuffled!**")
            else:
                await m.reply_text("❌ **Not enough songs to shuffle.**")
        elif cmd == "loop":
            LOOP_MODE[m.chat.id] = not LOOP_MODE.get(m.chat.id, False)
            await m.reply_text(f"🔂 **Loop:** `{'Enabled' if LOOP_MODE[m.chat.id] else 'Disabled'}`")

    @app.on_callback_query()
    async def cb(c, q):
        if q.data == "delete_msg":
            try:
                await q.message.delete()
            except Exception:
                pass
            return
        if not await is_admin(c, q.message.chat.id, q.from_user.id if q.from_user else 0):
            return await q.answer("❌ Only Admins can control playback!", show_alert=True)
            
        chat_id = q.message.chat.id
        if q.data == "skip_music":
            await q.answer("⏭ Skipping...")
            await play_next(chat_id)
        elif q.data == "pause_music":
            try:
                await call.pause_stream(chat_id)
                await q.answer("⏸ Paused")
            except Exception:
                await q.answer("Already paused", show_alert=True)
        elif q.data == "resume_music":
            try:
                await call.resume_stream(chat_id)
                await q.answer("▶️ Resumed")
            except Exception:
                await q.answer("Already playing", show_alert=True)
        elif q.data == "loop_music":
            LOOP_MODE[chat_id] = not LOOP_MODE.get(chat_id, False)
            await q.answer(f"🔂 Loop {'Enabled' if LOOP_MODE[chat_id] else 'Disabled'}", show_alert=True)
        elif q.data == "shuffle_music":
            if chat_id in QUEUE and len(QUEUE[chat_id]) > 1:
                random.shuffle(QUEUE[chat_id])
                await q.answer("🔀 Shuffled", show_alert=True)
            else:
                await q.answer("Not enough tracks in queue", show_alert=True)
        elif q.data == "stop_music":
            QUEUE.pop(chat_id, None)
            ACTIVE_TRACK.pop(chat_id, None)
            PLAYED_TIME.pop(chat_id, None)
            LOOP_MODE.pop(chat_id, None)
            if chat_id in TIMERS:
                TIMERS[chat_id].cancel()
            try:
                await call.leave_group_call(chat_id)
            except Exception:
                pass
            LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_leave(chat_id))
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.answer("⏹ Stopped")

    await app.start()
    await user.start()
    await call.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
