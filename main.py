import asyncio
import base64
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from aiohttp import web

# Token va kalitlar Render Environment'dan maxfiy o'qiladi
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHANNEL_USERNAME = "@Qora_fonlar_nomer1"
VOICE_MODEL = "uz-UZ-MadinaNeural"
USERS_FILE = "users.txt"

user_histories = {}
verified_users = set()
MODELS_LIST = []
dp = Dispatcher()


def add_user(user_id: int):
  try:
    users = set()
    if os.path.exists(USERS_FILE):
      with open(USERS_FILE, "r") as f:
        for line in f:
          line = line.strip()
          if line.isdigit():
            users.add(int(line))
    if user_id not in users:
      with open(USERS_FILE, "a") as f:
        f.write(f"{user_id}\n")
  except Exception:
    pass


def get_all_users() -> list:
  users = []
  try:
    if os.path.exists(USERS_FILE):
      with open(USERS_FILE, "r") as f:
        for line in f:
          line = line.strip()
          if line.isdigit():
            users.append(int(line))
  except Exception:
    pass
  return users


def get_models_list():
  global MODELS_LIST
  if MODELS_LIST:
    return MODELS_LIST

  if not GEMINI_API_KEY:
    return [
        "models/gemini-2.0-flash-lite",
        "models/gemini-2.0-flash",
        "models/gemini-flash-latest",
        "models/gemini-pro-latest",
    ]

  url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY.strip()}"
  try:
    with urllib.request.urlopen(url, timeout=5) as response:
      data = json.loads(response.read().decode("utf-8"))
      all_models = [
          m["name"]
          for m in data.get("models", [])
          if "generateContent" in m.get("supportedGenerationMethods", [])
          and "2.5-flash" not in m["name"]
      ]
      lite_models = [m for m in all_models if "lite" in m]
      flash_models = [
          m for m in all_models if "flash" in m and "lite" not in m
      ]
      other_models = [m for m in all_models if "flash" not in m]
      MODELS_LIST = lite_models + flash_models + other_models
      if MODELS_LIST:
        return MODELS_LIST
  except Exception:
    pass

  MODELS_LIST = [
      "models/gemini-2.0-flash-lite",
      "models/gemini-2.0-flash",
      "models/gemini-flash-latest",
      "models/gemini-pro-latest",
  ]
  return MODELS_LIST


def ask_gemini(user_id, parts):
  global MODELS_LIST
  if not GEMINI_API_KEY:
    return "Xatolik: GEMINI_API_KEY sozlanmagan."

  if user_id not in user_histories:
    user_histories[user_id] = []

  if len(user_histories[user_id]) > 6:
    user_histories[user_id] = user_histories[user_id][-6:]

  user_histories[user_id].append({"role": "user", "parts": parts})
  data = {
      "system_instruction": {
          "parts": [{
              "text": (
                  "Sen Aqliy yordamchi ai botisan. Sen matnli va ovozli"
                  " xabarlarni tushunasan hamda ovozli javob bera olasan."
                  " O'zbek tilida juda qisqa, lo'nda, tushunarli va samimiy"
                  " javob ber. Hech qachon 'ovozli xabar yubora olmayman' dema!"
              )
          }]
      },
      "contents": user_histories[user_id],
      "generationConfig": {"maxOutputTokens": 400, "temperature": 0.7},
  }
  headers = {"Content-Type": "application/json"}
  req_data = json.dumps(data).encode("utf-8")

  models = get_models_list()
  last_err = ""

  for i, model_name in enumerate(models):
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY.strip()}"
    try:
      req = urllib.request.Request(
          gemini_url, data=req_data, headers=headers, method="POST"
      )
      with urllib.request.urlopen(req, timeout=10) as response:
        res_json = json.loads(response.read().decode("utf-8"))
        answer = (
            res_json.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "Javob topilmadi.")
        )
        user_histories[user_id].append(
            {"role": "model", "parts": [{"text": answer}]}
        )
        if i != 0:
          MODELS_LIST.insert(0, MODELS_LIST.pop(i))
        return answer
    except urllib.error.HTTPError as e:
      last_err = f"Kod {e.code}"
      continue
    except Exception as e:
      last_err = str(e)
      continue

  user_histories[user_id].pop()
  return f"Server band ({last_err}). Qayta yozib ko'ring."


def clean_text_for_speech(text: str) -> str:
  cleaned = re.sub(r"[*#_`~>]", "", text)
  return cleaned.strip()


def generate_tts_bytes(text: str) -> bytes:
  short_text = text[:200]
  q = urllib.parse.quote(short_text)
  url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=uz&client=tw-ob"
  req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
  with urllib.request.urlopen(req, timeout=10) as resp:
    return resp.read()


async def send_voice_reply(message: Message, bot: Bot, answer: str):
  speech_text = clean_text_for_speech(answer)
  try:
    await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
  except Exception:
    pass

  try:
    import edge_tts

    communicate = edge_tts.Communicate(speech_text, VOICE_MODEL)
    audio_bytes = b""
    async for chunk in communicate.stream():
      if chunk["type"] == "audio":
        audio_bytes += chunk["data"]
    if audio_bytes:
      voice_file = BufferedInputFile(audio_bytes, filename="voice.mp3")
      await message.reply_voice(voice=voice_file, caption=answer[:1000])
      return
  except Exception:
    pass

  try:
    audio_bytes = await asyncio.to_thread(generate_tts_bytes, speech_text)
    voice_file = BufferedInputFile(audio_bytes, filename="voice.mp3")
    await message.reply_voice(voice=voice_file, caption=answer[:1000])
  except Exception:
    await message.reply(answer)


async def check_channel_member(bot: Bot, user_id: int) -> bool:
  if user_id in verified_users:
    return True
  try:
    member = await bot.get_chat_member(
        chat_id=CHANNEL_USERNAME, user_id=user_id
    )
    if member.status in ["creator", "administrator", "member"]:
      verified_users.add(user_id)
      return True
    return False
  except Exception:
    return True


@dp.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
  if message.chat.type == "private":
    add_user(message.from_user.id)
    user_histories.pop(message.from_user.id, None)

    # Obuna tekshiruvi FAQAT shaxsiy chatda ishlaydi
    if not await check_channel_member(bot, message.from_user.id):
      link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
      await message.answer(
          f"Assalomu alaykum, {message.from_user.first_name}! 👋\n\nBotdan"
          f" foydalanish uchun kanalimizga obuna bo'ling:\n{CHANNEL_USERNAME}",
          reply_markup={
              "inline_keyboard": [[{"text": "📢 Kanalga o'tish", "url": link}]]
          },
      )
      return

  await message.answer(
      f"Assalomu alaykum, {message.from_user.first_name}! ⚡️\n\n"
      "Men tezkor Aqliy yordamchi ai botiman. Menga savol, ovozli xabar, rasm"
      " yoki PDF yuboring!"
  )


@dp.message(Command("sendall"))
async def cmd_sendall(message: Message, bot: Bot):
  if message.chat.type != "private":
    return

  text_to_send = message.text.replace("/sendall", "").strip()
  if not text_to_send:
    await message.answer(
        "Iltimos, xabar matnini ham yozing.\nMisol: `/sendall Salom hammaga!`"
    )
    return

  users = get_all_users()
  sent_count = 0
  fail_count = 0

  status_msg = await message.answer(
      f"Xabar tarqatilmoqda... Jami foydalanuvchilar: {len(users)}"
  )

  for uid in users:
    try:
      await bot.send_message(chat_id=uid, text=text_to_send)
      sent_count += 1
      await asyncio.sleep(0.05)
    except Exception:
      fail_count += 1

  await status_msg.edit_text(
      f"✅ Xabar muvaffaqiyatli tarqatildi!\n\n"
      f"• Yuborildi: {sent_count}\n"
      f"• Xatolik (bloklaganlar): {fail_count}"
  )


@dp.message(F.voice)
async def handle_voice(message: Message, bot: Bot):
  # Guruhda obuna tekshirilmaydi
  if message.chat.type == "private":
    add_user(message.from_user.id)
    if not await check_channel_member(bot, message.from_user.id):
      link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
      await message.answer(
          f"Botdan foydalanish uchun kanalga obuna bo'ling: {CHANNEL_USERNAME}",
          reply_markup={
              "inline_keyboard": [[{"text": "📢 Kanalga o'tish", "url": link}]]
          },
      )
      return

  try:
    try:
      await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
    except Exception:
      pass

    file = await bot.get_file(message.voice.file_id)
    file_bytes = await bot.download_file(file.file_path)
    b64_data = base64.b64encode(file_bytes.read()).decode("utf-8")

    parts = [
        {"inline_data": {"mime_type": "audio/ogg", "data": b64_data}},
        {
            "text": (
                "Ushbu ovozli xabarni diqqat bilan eshitib, unga o'zbek tilida"
                " qisqa, aniq va samimiy javob ber."
            )
        },
    ]

    # Guruhda har bir foydalanuvchi o'z tarixi bilan gaplashishi uchun message.from_user.id ishlatiladi
    answer = await asyncio.to_thread(ask_gemini, message.from_user.id, parts)
    await send_voice_reply(message, bot, answer)
  except Exception:
    await message.answer(
        "Ovozli xabarni tushunishda xatolik yuz berdi. Qayta yuborib ko'ring."
    )


@dp.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
  if message.chat.type == "private":
    add_user(message.from_user.id)
    if not await check_channel_member(bot, message.from_user.id):
      return

  photo = message.photo[-2] if len(message.photo) > 1 else message.photo[-1]
  try:
    file = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file.file_path)
    b64_data = base64.b64encode(file_bytes.read()).decode("utf-8")
    caption = (
        message.caption
        or "Bu rasmda nima bor? O'zbek tilida qisqa va aniq tushuntir."
    )
    parts = [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64_data}},
        {"text": caption},
    ]
    answer = await asyncio.to_thread(ask_gemini, message.from_user.id, parts)
    await message.answer(answer)
  except Exception:
    await message.answer("Rasmni o'qishda xatolik yuz berdi.")


@dp.message(F.document)
async def handle_document(message: Message, bot: Bot):
  if message.chat.type == "private":
    add_user(message.from_user.id)
    if not await check_channel_member(bot, message.from_user.id):
      return

  if not message.document.file_name.endswith((".pdf", ".txt")):
    await message.answer("Faqat PDF va matnli hujjatlarni o'qiyman.")
    return
  try:
    file = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file.file_path)
    b64_data = base64.b64encode(file_bytes.read()).decode("utf-8")
    parts = [
        {"inline_data": {"mime_type": "application/pdf", "data": b64_data}},
        {"text": "Hujjat mazmunini o'zbek tilida qisqacha tushuntirib ber."},
    ]
    answer = await asyncio.to_thread(ask_gemini, message.from_user.id, parts)
    await message.answer(answer)
  except Exception:
    await message.answer("Hujjatni o'qishda xatolik yuz berdi.")


@dp.message(F.text)
async def handle_text(message: Message, bot: Bot):
  if message.chat.type == "private":
    add_user(message.from_user.id)
    if not await check_channel_member(bot, message.from_user.id):
      link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
      await message.answer(
          f"Botdan foydalanish uchun kanalga obuna bo'ling: {CHANNEL_USERNAME}",
          reply_markup={
              "inline_keyboard": [[{"text": "📢 Kanalga o'tish", "url": link}]]
          },
      )
      return

  text = message.text
  if message.chat.type in ["group", "supergroup"]:
    bot_info = await bot.get_me()
    bot_username = f"@{bot_info.username}"
    is_reply = (
        message.reply_to_message
        and message.reply_to_message.from_user.id == bot_info.id
    )
    if not (is_reply or bot_username in text):
      return
    text = text.replace(bot_username, "").strip()

  lower_text = text.lower()
  wants_voice = any(
      w in lower_text for w in ["ovozli", "golos", "ovozda", "gapirib"]
  )

  answer = await asyncio.to_thread(
      ask_gemini, message.from_user.id, [{"text": text}]
  )

  if wants_voice:
    await send_voice_reply(message, bot, answer)
  else:
    await message.answer(answer)


async def health_check(request):
  return web.Response(text="Bot 24/7 ishlamoqda!")


async def start_web_server():
  app = web.Application()
  app.router.add_get("/", health_check)
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.environ.get("PORT", 8080))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


async def main():
  if not TELEGRAM_TOKEN:
    print("Xatolik: TELEGRAM_TOKEN topilmadi!")
    return

  await start_web_server()
  print("🌐 Veb-server porti ochildi...")

  bot = Bot(token=TELEGRAM_TOKEN.strip())
  await bot.delete_webhook(drop_pending_updates=True)
  await asyncio.to_thread(get_models_list)
  print(
      "🌐 24/7 Server bot guruhlar uchun obunasiz rejimda ishga tushdi..."
  )
  await dp.start_polling(bot)


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO, stream=sys.stdout)
  asyncio.run(main())
