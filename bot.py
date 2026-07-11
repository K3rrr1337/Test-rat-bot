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
from screeninfo import get_monitors  # Для определения разрешения экрана

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv("8887120621:AAFooZnbT2eypcxk-ksKr8c6TjF-JZiWNEs")

# ТВОЙ Telegram ID (узнай у @userinfobot)
AUTHORIZED_USER_ID = 1908250518  # ЗАМЕНИ!

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальная переменная для остановки записи видео
recording_active = False
video_output = None

# --- Ограничение доступа ---
async def restrict_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return False
    return True

# ============================================
# 1. СКРИНШОТ (улучшенный)
# ============================================
async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    
    try:
        # Делаем скриншот всего экрана
        screenshot = pyautogui.screenshot()
        
        # Сжимаем для экономии трафика
        max_size = (1920, 1080)
        screenshot.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        bio = BytesIO()
        bio.name = f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        screenshot.save(bio, 'JPEG', quality=85, optimize=True)
        bio.seek(0)
        
        await update.message.reply_photo(
            photo=bio,
            caption=f"📸 Скриншот: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ============================================
# 2. ЗАПИСЬ ЭКРАНА (ВИДЕО)
# ============================================
def record_screen(stop_event, output_path, fps=10, duration=None):
    """Функция записи экрана в отдельном потоке"""
    global recording_active
    
    # Получаем размер экрана
    monitor = get_monitors()[0]
    width, height = monitor.width, monitor.height
    
    # Настройка кодека
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    start_time = time.time()
    
    while not stop_event.is_set():
        # Делаем скриншот и конвертируем в OpenCV формат
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        out.write(frame)
        
        # Если задана длительность, останавливаемся
        if duration and (time.time() - start_time) > duration:
            break
        
        time.sleep(1/fps)
    
    out.release()
    recording_active = False

async def start_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать запись экрана (по умолчанию 30 секунд)"""
    if not await restrict_access(update, context): return
    
    global recording_active
    
    if recording_active:
        await update.message.reply_text("⏳ Запись уже идет! Используй /stop_recording чтобы остановить.")
        return
    
    # Парсим аргументы: /record 60 (запись на 60 секунд)
    duration = 30  # по умолчанию
    if context.args:
        try:
            duration = int(context.args[0])
            if duration > 300:  # максимум 5 минут
                duration = 300
                await update.message.reply_text("⏱️ Максимальная длительность 5 минут. Установлено 300 сек.")
        except ValueError:
            pass
    
    # Путь для сохранения видео
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"screen_record_{timestamp}.mp4"
    
    recording_active = True
    stop_event = threading.Event()
    
    # Запускаем запись в отдельном потоке
    thread = threading.Thread(
        target=record_screen,
        args=(stop_event, video_path, 10, duration)  # 10 FPS
    )
    thread.daemon = True
    thread.start()
    
    # Сохраняем событие остановки в контексте
    context.user_data['stop_event'] = stop_event
    context.user_data['video_path'] = video_path
    
    await update.message.reply_text(
        f"🎥 **Начата запись экрана!**\n"
        f"⏱️ Длительность: {duration} сек.\n"
        f"🔄 Используй /stop_recording для досрочной остановки.",
        parse_mode='Markdown'
    )

async def stop_recording(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановить запись и отправить видео"""
    if not await restrict_access(update, context): return
    
    global recording_active
    
    if not recording_active:
        await update.message.reply_text("❌ Нет активной записи.")
        return
    
    # Останавливаем запись
    stop_event = context.user_data.get('stop_event')
    if stop_event:
        stop_event.set()
    
    video_path = context.user_data.get('video_path')
    
    await update.message.reply_text("⏳ Обработка видео...")
    
    # Ждем, пока файл сохранится
    time.sleep(2)
    
    # Отправляем видео
    try:
        with open(video_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=f"🎬 Запись экрана завершена: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
                supports_streaming=True
            )
        
        # Удаляем файл после отправки
        os.remove(video_path)
        recording_active = False
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при отправке видео: {e}")
        recording_active = False

# ============================================
# 3. УПРАВЛЕНИЕ ПИТАНИЕМ ПК
# ============================================
async def power_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель управления питанием"""
    if not await restrict_access(update, context): return
    
    keyboard = [
        [InlineKeyboardButton("🔄 Перезагрузить", callback_data='restart')],
        [InlineKeyboardButton("⏻ Выключить", callback_data='shutdown')],
        [InlineKeyboardButton("💤 Сон", callback_data='sleep')],
        [InlineKeyboardButton("🔒 Заблокировать", callback_data='lock')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_control')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚡ **Управление питанием ПК**\n\n"
        "⚠️ **ВНИМАНИЕ!** После выключения/перезагрузки бот перестанет отвечать до включения ПК.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ============================================
# 4. ОСНОВНАЯ ПАНЕЛЬ УПРАВЛЕНИЯ (расширенная)
# ============================================
async def control_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    
    keyboard = [
        [InlineKeyboardButton("📸 Скриншот", callback_data='screenshot')],
        [InlineKeyboardButton("🎥 Запись экрана (30с)", callback_data='record_30')],
        [InlineKeyboardButton("🎥 Запись экрана (60с)", callback_data='record_60')],
        [InlineKeyboardButton("🖱️ Клик ЛКМ", callback_data='click_left')],
        [InlineKeyboardButton("🖱️ Клик ПКМ", callback_data='click_right')],
        [InlineKeyboardButton("⌨️ Написать текст", callback_data='type_text')],
        [InlineKeyboardButton("⚡ Управление питанием", callback_data='power_menu')],
        [InlineKeyboardButton("📋 Список процессов", callback_data='processes')],
        [InlineKeyboardButton("📊 Системная информация", callback_data='sysinfo')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎮 **Панель управления ПК**\nВыбери действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ============================================
# 5. ОБРАБОТЧИК КНОПОК (универсальный)
# ============================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id != AUTHORIZED_USER_ID:
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    
    # --- Скриншот ---
    if data == 'screenshot':
        try:
            screenshot = pyautogui.screenshot()
            screenshot.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            bio = BytesIO()
            bio.name = 'screenshot.jpg'
            screenshot.save(bio, 'JPEG', quality=85)
            bio.seek(0)
            await query.edit_message_text("📸 Скриншот создан, отправляю...")
            await context.bot.send_photo(chat_id=user_id, photo=bio)
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")
    
    # --- Запись экрана ---
    elif data == 'record_30':
        await query.edit_message_text("🎥 Начинаю запись на 30 секунд...")
        # Запускаем запись (используем существующую функцию)
        context.args = [30]
        await start_recording(update, context)
        # Не редактируем сообщение, т.к. start_recording отправит новое
    
    elif data == 'record_60':
        await query.edit_message_text("🎥 Начинаю запись на 60 секунд...")
        context.args = [60]
        await start_recording(update, context)
    
    # --- Управление питанием ---
    elif data == 'power_menu':
        keyboard = [
            [InlineKeyboardButton("🔄 Перезагрузить", callback_data='restart')],
            [InlineKeyboardButton("⏻ Выключить", callback_data='shutdown')],
            [InlineKeyboardButton("💤 Сон", callback_data='sleep')],
            [InlineKeyboardButton("🔒 Заблокировать", callback_data='lock')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_control')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "⚡ **Управление питанием**\n\n⚠️ Выключение/перезагрузка остановят бота!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == 'restart':
        await query.edit_message_text("🔄 Перезагрузка ПК через 5 секунд...")
        time.sleep(5)
        os.system("shutdown /r /t 0")
    
    elif data == 'shutdown':
        await query.edit_message_text("⏻ Выключение ПК через 5 секунд...")
        time.sleep(5)
        os.system("shutdown /s /t 0")
    
    elif data == 'sleep':
        await query.edit_message_text("💤 Перевожу ПК в спящий режим...")
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    
    elif data == 'lock':
        os.system("rundll32.exe user32.dll,LockWorkStation")
        await query.edit_message_text("🔒 ПК заблокирован.")
    
    # --- Кнопки управления мышью ---
    elif data == 'click_left':
        pyautogui.click()
        await query.edit_message_text("✅ Выполнен клик ЛКМ")
    
    elif data == 'click_right':
        pyautogui.rightClick()
        await query.edit_message_text("✅ Выполнен клик ПКМ")
    
    # --- Команда для ввода текста ---
    elif data == 'type_text':
        context.user_data['waiting_for_text'] = True
        await query.edit_message_text("✏️ Введи текст для печати на ПК:")
    
    # --- Информация о системе ---
    elif data == 'sysinfo':
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        text = (
            f"📊 **Системная информация**\n\n"
            f"🧠 **CPU:** {cpu}%\n"
            f"💾 **ОЗУ:** {ram.used // (1024**3)} ГБ / {ram.total // (1024**3)} ГБ ({ram.percent}%)\n"
            f"💽 **Диск:** {disk.used // (1024**3)} ГБ / {disk.total // (1024**3)} ГБ ({disk.percent}%)\n"
        )
        await query.edit_message_text(text, parse_mode='Markdown')
    
    # --- Список процессов ---
    elif data == 'processes':
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                procs.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs = sorted(procs, key=lambda p: p['cpu_percent'] or 0, reverse=True)[:10]
        text = "📋 **ТОП-10 процессов:**\n\n"
        for p in procs:
            text += f"• {p['name']} (PID: {p['pid']}) — {p['cpu_percent']}%\n"
        await query.edit_message_text(text, parse_mode='Markdown')
    
    # --- Назад в главное меню ---
    elif data == 'back_to_control':
        await control_panel(update, context)

# ============================================
# 6. ОБРАБОТЧИК ТЕКСТА
# ============================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    
    if context.user_data.get('waiting_for_text'):
        text_to_type = update.message.text
        pyautogui.write(text_to_type)
        context.user_data['waiting_for_text'] = False
        await update.message.reply_text(f"✅ Текст напечатан на ПК:\n`{text_to_type}`", parse_mode='Markdown')

# ============================================
# 7. ЗАГРУЗКА ФАЙЛА
# ============================================
async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    
    try:
        file_path = ' '.join(context.args)
        if not file_path:
            await update.message.reply_text("❌ Укажи путь. Пример: `/download C:/file.txt`", parse_mode='Markdown')
            return
        
        if not os.path.exists(file_path):
            await update.message.reply_text("❌ Файл не найден.")
            return
        
        with open(file_path, 'rb') as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ============================================
# 8. СТАРТ
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    await update.message.reply_text(
        "🤖 **Бот для удаленного управления ПК**\n\n"
        "📌 **Команды:**\n"
        "/start — Показать это сообщение\n"
        "/control — 🎮 Открыть панель управления\n"
        "/screenshot — 📸 Быстрый скриншот\n"
        "/record [сек] — 🎥 Запись экрана (по умолч. 30с)\n"
        "/stop_recording — ⏹️ Остановить запись\n"
        "/sysinfo — 📊 Информация о системе\n"
        "/processes — 📋 Список процессов\n"
        "/power — ⚡ Управление питанием\n"
        "/download /путь — ⬇️ Скачать файл",
        parse_mode='Markdown'
    )

# ============================================
# 9. ЗАПУСК
# ============================================
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("control", control_panel))
    app.add_handler(CommandHandler("screenshot", screenshot))
    app.add_handler(CommandHandler("record", start_recording))
    app.add_handler(CommandHandler("stop_recording", stop_recording))
    app.add_handler(CommandHandler("sysinfo", lambda u, c: sysinfo_command(u, c) if u.effective_user.id == AUTHORIZED_USER_ID else None))
    app.add_handler(CommandHandler("processes", processes_command))
    app.add_handler(CommandHandler("power", power_control))
    app.add_handler(CommandHandler("download", download_file))
    
    # Обработчики кнопок и текста
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запуск на Railway
    port = int(os.environ.get("PORT", 8443))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=f"https://{os.environ.get('RAILWAY_STATIC_URL')}/webhook"
    )

# Отдельные функции для команд (чтобы избежать конфликтов)
async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    text = f"📊 **Система**\nCPU: {cpu}%\nRAM: {ram.percent}%\nDisk: {disk.percent}%"
    await update.message.reply_text(text, parse_mode='Markdown')

async def processes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_access(update, context): return
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            procs.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs = sorted(procs, key=lambda p: p['cpu_percent'] or 0, reverse=True)[:10]
    text = "📋 **ТОП-10 процессов:**\n\n"
    for p in procs:
        text += f"• {p['name']} (PID: {p['pid']}) — {p['cpu_percent']}%\n"
    await update.message.reply_text(text, parse_mode='Markdown')

if __name__ == "__main__":
    main()
