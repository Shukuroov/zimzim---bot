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

# Yangi token va kalitlar
TELEGRAM_TOKEN = "9213330164:AAHFl-pDEwacoUv6-q0PuePV27EQNfNstoY"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHANNEL_USERNAME = "@Qora_fonlar_nomer1"
VOICE_MODEL = "uz-UZ-MadinaNeural"

user_histories = {}
verified_users = set()
MODELS_LIST = []
dp = Dispatcher()


def get_models_list():
  global MODELS_LIST
  if MODELS_LIST:
    return MODELS_LIST

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
  # Google TTS zaxira tizimi (qo'shimcha kutubxona talab qilmaydi)
  short_text = text[:200]
  q = urllib.parse.quote(short_text)
  url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=uz&client=tw-ob"
  req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
  with urllib.request.urlopen(req, timeout=10) as resp:
    return resp.read()


async def send_voice_reply(message: Message, bot: Bot, answer: str):
  speech_text = clean_text_for_speech(answer)
  await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")

  # 1-usul: edge-tts o'rnatilgan bo'lsa, MadinaNeural ovozida o'qiydi
  try:
    import edge_tts

    communicate = edge_tts.Communicate(speech_text, VOICE_MODEL)
    audio_bytes = b""
    async for chunk in communicate.stream():
      if chunk["type"] == "audio":
        audio_bytes += chunk["data"]
    if audio_bytes:
      voice_file = BufferedInputFile(audio_bytes, filename="voice.
