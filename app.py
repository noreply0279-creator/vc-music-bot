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

# Configuration
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_BIN)

API_ID = 24944630
API_HASH = "49d2337722244115abf15a4bc9d86eb3"
BOT_TOKEN = "8663631826:AAHAvGt04-_K1di9r8S6GqvfjBMRW2ZRQ1w"
STRING_SESSION = "BQF8n_YAHma28wBi1V61Ox_f22FGlFmHR5H065LbA-fGnABXwEzB2I6Ci3Ldhx8NDy9oZ5u6csQjwJ5JGNjv2m-ksVf5zBai4YN8Fa6UEWY83UE3yMbvZgsjtn6Xf89RNIsu2x7TeAEXBaKiF7du1l2nk0N8cm2jLP7bALQ0eVAdJ00GXnqIlGAhioBVcCwfZiXg5snIflglNa8ObUJJJhEubN-dDxfnMYOe8wQmngIMERiqOPS0ZKWamMkwLXWb7ljiY9-KTFN6R1az2ok6Vt0Fb9v_mMge4o0YWejF4D8En9TahcCJt_xt2rzNaF8xARSifoNY4cScOBt5bkyCArweSe_1FAAAAAHyu8ZdAA"
DES_KEY = b"38346591"

# Memory
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
    if total_sec <= 0: return "🔘──────────"
    progress = int((current_sec / total_sec) * total_bars)
    progress = min(max(progress, 0), total_bars)
    return "━" * progress + "🔘" + "─" * (total_bars - progress)

def download_and_convert(query):
    search_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&_format=json&_marker=0&cc=in&includeMetaTags=1&query={query}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(search_url, headers=headers, timeout=10)
    data = r.json()
    songs = data.get("songs", {}).get("data", [])
    if not songs: raise Exception("Song not found!")
    
    song_id = songs[0].get("id")
    title = songs[0].get("title", "Song").replace("&quot;", '"').replace("&amp;", "&")
    singers = songs[0].get("more_info", {}).get("singers", "Artist")
    thumb = songs[0].get("image", "").replace("50x50", "500x500").replace("150x150", "500x500")

    detail_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_id}"
    r_detail = requests.get(detail_url, headers=headers, timeout=10)
    song_data = r_detail.json().get(song_id)
    duration_sec = int(song_data.get("duration", 0))
    stream_url = decrypt_url(song_data.get("encrypted_media_url"))
    
    mp3_file, raw_file = f"t_{song_id}.mp3", f"t_{song_id}.raw"
    with open(mp3_file, "wb") as f: f.write(requests.get(stream_url, headers=headers, timeout=25).content)
    subprocess.run([FFMPEG_BIN, "-y", "-i", mp3_file, "-f", "s16le", "-ac", "1", "-ar", "48000", "-acodec", "pcm_s16le", raw_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(mp3_file): os.remove(mp3_file)
    return raw_file, title, singers, duration_sec, format_sec(duration_sec), thumb

# Utils
def get_controls(): return InlineKeyboardMarkup([[InlineKeyboardButton("⏸ Pause", "pause_music"), InlineKeyboardButton("▶️ Resume", "resume_music"), InlineKeyboardButton("🔂 Loop", "loop_music")], [InlineKeyboardButton("🔀 Shuffle", "shuffle_music"), InlineKeyboardButton("⏭ Skip", "skip_music"), InlineKeyboardButton("⏹ Stop", "stop_music")], [InlineKeyboardButton("🗑 Delete This", "delete_msg")]])
def get_queue_markup(): return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Delete This", "delete_msg")]])
async def is_admin(client, chat_id, user_id):
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except: return False

# Core Logic
async def main():
    app = Client("music_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    user = Client("assistant_account", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION)
    call = PyTgCalls(user)

    async def ensure_assistant(chat_id):
        try:
            bot_me = await app.get_me()
            if (await app.get_chat_member(chat_id, bot_me.id)).status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return False
            try: await user.get_chat_member(chat_id, (await user.get_me()).id)
            except: await user.join_chat(await app.export_chat_invite_link(chat_id))
            return True
        except: return False

    async def delayed_leave(chat_id):
        await asyncio.sleep(180)
        if chat_id not in ACTIVE_TRACK:
            try: await call.leave_group_call(chat_id)
            except: pass
            try: await user.leave_chat(chat_id)
            except: pass

    async def play_next(chat_id):
        if chat_id in TIMERS: TIMERS[chat_id].cancel()
        if LOOP_MODE.get(chat_id) and chat_id in ACTIVE_TRACK: next_song = ACTIVE_TRACK[chat_id]
        elif chat_id in QUEUE and QUEUE[chat_id]:
            next_song = QUEUE[chat_id].pop(0)
            ACTIVE_TRACK[chat_id] = next_song
        else:
            ACTIVE_TRACK.pop(chat_id, None)
            try: await call.leave_group_call(chat_id)
            except: pass
            LEAVE_TIMERS[chat_id] = asyncio.create_task(delayed_leave(chat_id))
            return
        stream = InputStream(InputAudioStream(next_song["path"], HighQualityAudio()))
        try: await call.change_stream(chat_id, stream)
        except: await call.join_group_call(chat_id, stream)
        
        cap = f"🎵 **Now Playing:** `{next_song['title']}`\n🎤 **Artist:** `{next_song['artist']}`\n👤 **Req by:** {next_song['requester']}"
        if next_song.get("thumb"): msg = await app.send_photo(chat_id, photo=next_song["thumb"], caption=cap, reply_markup=get_controls())
        else: msg = await app.send_message(chat_id, cap, reply_markup=get_controls())
        TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, next_song))

    async def update_timeline(chat_id, msg_id, song):
        for i in range(10, song["duration_sec"], 10):
            await asyncio.sleep(10)
            if chat_id not in ACTIVE_TRACK or ACTIVE_TRACK[chat_id] != song: return
            try: await app.edit_message_caption(chat_id, msg_id, caption=f"🎵 **Playing:** `{song['title']}`\n🎤 **Artist:** `{song['artist']}`\n👤 **Req by:** {song['requester']}\n⏱ {get_progress_bar(i, song['duration_sec'])}", reply_markup=get_controls())
            except: pass

    @call.on_stream_end()
    async def stream_end(client, update: StreamAudioEnded): await play_next(update.chat_id)

    @app.on_message(filters.command("play"))
    async def play_cmd(client, message):
        chat_id = message.chat.id
        if not await ensure_assistant(chat_id): return await message.reply_text("⚠️ **Bot needs Admin rights to join VC!**")
        if len(message.command) < 2: return await message.reply_text("❌ Give song name!")
        if chat_id in LEAVE_TIMERS: LEAVE_TIMERS[chat_id].cancel()
        
        m = await message.reply_text("🔎 **Searching...**")
        try:
            path, title, art, dur, dur_str, thumb = await asyncio.get_event_loop().run_in_executor(None, download_and_convert, message.text.split(None, 1)[1])
            song = {"path": path, "title": title, "artist": art, "duration_sec": dur, "duration_str": dur_str, "thumb": thumb, "requester": message.from_user.mention}
            
            if chat_id in ACTIVE_TRACK:
                if chat_id not in QUEUE: QUEUE[chat_id] = []
                QUEUE[chat_id].append(song)
                await m.edit(f"✅ **Queued:** `{title}`")
            else:
                ACTIVE_TRACK[chat_id] = song
                try: await call.join_group_call(chat_id, InputStream(InputAudioStream(path, HighQualityAudio())))
                except: await call.change_stream(chat_id, InputStream(InputAudioStream(path, HighQualityAudio())))
                await m.delete()
                cap = f"🎵 **Now Playing:** `{title}`\n🎤 **Artist:** `{art}`\n👤 **Req by:** {song['requester']}"
                if thumb: msg = await message.reply_photo(thumb, caption=cap, reply_markup=get_controls())
                else: msg = await message.reply_text(cap, reply_markup=get_controls())
                TIMERS[chat_id] = asyncio.create_task(update_timeline(chat_id, msg.id, song))
        except Exception as e: await m.edit(f"❌ **Error:** `{e}`")

    @app.on_message(filters.command(["reload", "refresh"]))
    async def reload_cmd(client, message):
        chat_id = message.chat.id
        if not await is_admin(client, chat_id, message.from_user.id if message.from_user else 0): return
        QUEUE[chat_id] = []
        ACTIVE_TRACK.pop(chat_id, None)
        try: await call.leave_group_call(chat_id)
        except: pass
        await message.reply_text("🔄 **Voice Chat reloaded! Play song again.**")

    # (Admin Controls & Callbacks - Shortened for space)
    @app.on_message(filters.command(["skip", "pause", "resume", "stop", "shuffle", "loop"]))
    async def admin_cmds(client, m):
        if not await is_admin(client, m.chat.id, m.from_user.id if m.from_user else 0): return await m.reply_text("❌ **Admin only!**")
        cmd = m.command[0]
        if cmd == "skip": await play_next(m.chat.id)
        elif cmd == "pause": await call.pause_stream(m.chat.id)
        elif cmd == "resume": await call.resume_stream(m.chat.id)
        elif cmd == "stop": 
            ACTIVE_TRACK.pop(m.chat.id, None)
            try: await call.leave_group_call(m.chat.id)
            except: pass
        elif cmd == "shuffle": random.shuffle(QUEUE.get(m.chat.id, []))
        await m.reply_text(f"✅ **Done:** `{cmd}`")

    @app.on_callback_query()
    async def cb(c, q):
        if q.data == "delete_msg": await q.message.delete()
        elif await is_admin(c, q.message.chat.id, q.from_user.id if q.from_user else 0):
            if q.data == "skip_music": await play_next(q.message.chat.id)
            elif q.data == "pause_music": await call.pause_stream(q.message.chat.id)
            elif q.data == "resume_music": await call.resume_stream(q.message.chat.id)
            elif q.data == "stop_music": 
                ACTIVE_TRACK.pop(q.message.chat.id, None)
                await call.leave_group_call(q.message.chat.id)
            q.answer("Done!")
        else: q.answer("❌ Admin only!")

    await app.start()
    await user.start()
    await call.start()
    await asyncio.Event().wait()

if __name__ == "__main__": asyncio.run(main())
