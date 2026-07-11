import os
import logging
import psutil
import pyautogui
from PIL import Image
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
import subprocess
import time
import threading
import cv2
import numpy as np
from screeninfo import get_monitors

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.getenv("8887120621:AAFooZnbT2eypcxk-ksKr8c6TjF-JZiWNEs")
AUTHORIZED_USER_ID = 1908250518  # ЗАМЕНИ НА СВОЙ ID!

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

recording_active = False

# --- Ограничение доступа ---
async def restrict_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return False
    return True

# --- СКРИНШОТ ---
async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    try:
        screenshot = pyautogui.screenshot()
        screenshot.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
        bio = BytesIO()
        bio.name = f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        screenshot.save(bio, 'JPEG', quality=85)
        bio.seek(0)
        await update.message.reply_photo(
            photo=bio,
            caption=f"📸 Скриншот: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# --- ЗАПИСЬ ЭКРАНА ---
def record_screen(stop_event, output_path, fps=10, duration=30):
    monitor = get_monitors()[0]
    width, height = monitor.width, monitor.height
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    start_time = time.time()
    
    while not stop_event.is_set():
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        out.write(frame)
        if (time.time() - start_time) > duration:
            break
        time.sleep(1/fps)
    
    out.release()
    global recording_active
    recording_active = False

async def start_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    global recording_active
    
    if recording_active:
        await update.message.reply_text("⏳ Запись уже идет!")
        return
    
    duration = 30
    if context.args:
        try:
            duration = min(int(context.args[0]), 300)
        except ValueError:
            pass
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"screen_record_{timestamp}.mp4"
    
    recording_active = True
    stop_event = threading.Event()
    
    thread = threading.Thread(
        target=record_screen,
        args=(stop_event, video_path, 10, duration)
    )
    thread.daemon = True
    thread.start()
    
    context.user_data['stop_event'] = stop_event
    context.user_data['video_path'] = video_path
    
    await update.message.reply_text(
        f"🎥 **Запись экрана начата!**\n⏱️ {duration} сек.",
        parse_mode='Markdown'
    )

async def stop_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    global recording_active
    
    if not recording_active:
        await update.message.reply_text("❌ Нет активной записи.")
        return
    
    stop_event = context.user_data.get('stop_event')
    if stop_event:
        stop_event.set()
    
    video_path = context.user_data.get('video_path')
    await update.message.reply_text("⏳ Обработка видео...")
    time.sleep(2)
    
    try:
        with open(video_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=f"🎬 Запись завершена",
                supports_streaming=True
            )
        os.remove(video_path)
        recording_active = False
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# --- УПРАВЛЕНИЕ ПИТАНИЕМ ---
async def power_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    keyboard = [
        [InlineKeyboardButton("🔄 Перезагрузить", callback_data='restart')],
        [InlineKeyboardButton("⏻ Выключить", callback_data='shutdown')],
        [InlineKeyboardButton("💤 Сон", callback_data='sleep')],
        [InlineKeyboardButton("🔒 Блокировка", callback_data='lock')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚡ Управление питанием:", reply_markup=reply_markup)

# --- ГЛАВНОЕ МЕНЮ ---
async def control_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    keyboard = [
        [InlineKeyboardButton("📸 Скриншот", callback_data='screenshot')],
        [InlineKeyboardButton("🎥 Запись 30с", callback_data='record_30')],
        [InlineKeyboardButton("🎥 Запись 60с", callback_data='record_60')],
        [InlineKeyboardButton("🖱️ Клик ЛКМ", callback_data='click_left')],
        [InlineKeyboardButton("🖱️ Клик ПКМ", callback_data='click_right')],
        [InlineKeyboardButton("⌨️ Ввести текст", callback_data='type_text')],
        [InlineKeyboardButton("⚡ Питание", callback_data='power_menu')],
        [InlineKeyboardButton("📊 Система", callback_data='sysinfo')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎮 Панель управления:", reply_markup=reply_markup)

# --- ОБРАБОТЧИК КНОПОК ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != AUTHORIZED_USER_ID:
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    
    if data == 'screenshot':
        try:
            screenshot = pyautogui.screenshot()
            screenshot.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            bio = BytesIO()
            bio.name = 'screenshot.jpg'
            screenshot.save(bio, 'JPEG', quality=85)
            bio.seek(0)
            await query.edit_message_text("📸 Отправляю скриншот...")
            await context.bot.send_photo(chat_id=query.from_user.id, photo=bio)
        except Exception as e:
            await query.edit_message_text(f"❌ {e}")
    
    elif data == 'record_30':
        await query.edit_message_text("🎥 Запись 30 секунд...")
        context.args = [30]
        await start_recording(update, context)
    
    elif data == 'record_60':
        await query.edit_message_text("🎥 Запись 60 секунд...")
        context.args = [60]
        await start_recording(update, context)
    
    elif data == 'power_menu':
        keyboard = [
            [InlineKeyboardButton("🔄 Перезагрузить", callback_data='restart')],
            [InlineKeyboardButton("⏻ Выключить", callback_data='shutdown')],
            [InlineKeyboardButton("💤 Сон", callback_data='sleep')],
            [InlineKeyboardButton("🔒 Блокировка", callback_data='lock')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back')]
        ]
        await query.edit_message_text("⚡ Управление питанием:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == 'restart':
        await query.edit_message_text("🔄 Перезагрузка через 5 сек...")
        time.sleep(5)
        os.system("shutdown /r /t 0")
    
    elif data == 'shutdown':
        await query.edit_message_text("⏻ Выключение через 5 сек...")
        time.sleep(5)
        os.system("shutdown /s /t 0")
    
    elif data == 'sleep':
        await query.edit_message_text("💤 Сон...")
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    
    elif data == 'lock':
        os.system("rundll32.exe user32.dll,LockWorkStation")
        await query.edit_message_text("🔒 Заблокировано")
    
    elif data == 'click_left':
        pyautogui.click()
        await query.edit_message_text("✅ ЛКМ")
    
    elif data == 'click_right':
        pyautogui.rightClick()
        await query.edit_message_text("✅ ПКМ")
    
    elif data == 'type_text':
        context.user_data['waiting_for_text'] = True
        await query.edit_message_text("✏️ Введи текст:")
    
    elif data == 'sysinfo':
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        text = (
            f"📊 **Система**\n"
            f"CPU: {cpu}%\n"
            f"RAM: {ram.percent}% ({ram.used//(1024**3)}/{ram.total//(1024**3)} ГБ)\n"
            f"Disk: {disk.percent}%"
        )
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == 'back':
        await control_panel(update, context)

# --- ОБРАБОТЧИК ТЕКСТА ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    if context.user_data.get('waiting_for_text'):
        pyautogui.write(update.message.text)
        context.user_data['waiting_for_text'] = False
        await update.message.reply_text(f"✅ Напечатано: `{update.message.text}`", parse_mode='Markdown')

# --- СТАРТ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    await update.message.reply_text(
        "🤖 **Бот управления ПК**\n\n"
        "/control — 🎮 Открыть панель\n"
        "/screenshot — 📸 Скриншот\n"
        "/record [сек] — 🎥 Запись экрана\n"
        "/stop — ⏹️ Остановить запись\n"
        "/power — ⚡ Управление питанием",
        parse_mode='Markdown'
    )

# --- ЗАПУСК ---
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("control", control_panel))
    app.add_handler(CommandHandler("screenshot", screenshot))
    app.add_handler(CommandHandler("record", start_recording))
    app.add_handler(CommandHandler("stop", stop_recording))
    app.add_handler(CommandHandler("power", power_control))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # 🚀 ЗАПУСКАЕМ ПОЛЛИНГ (НЕ ВЕБХУК!)
    print("🚀 Бот запущен и готов к работе!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
