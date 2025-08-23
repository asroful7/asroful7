import os
import logging
import random
import string
import datetime
import asyncio
import re
from typing import Dict, List, Optional, Tuple
from pytz import timezone

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardRemove,
    ChatAction,
    InputMediaPhoto,
    InputMediaVideo
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    filters, 
    CallbackQueryHandler,
    ConversationHandler
)
from telegram.error import BadRequest

# Konfigurasi
TOKEN = os.environ.get('TOKEN', '8431743515:AAFHijTcNB2FWqJEbUacWZYfr8WGSTDMFG8')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6791146624'))
MEDIA_CHANNEL_ID = int(os.environ.get('MEDIA_CHANNEL_ID', '-1002871126458'))
FORWARD_CHANNEL_ID = int(os.environ.get('FORWARD_CHANNEL_ID', '-1002859119357'))
MENFESS_CHANNEL_ID = int(os.environ.get('MENFESS_CHANNEL_ID', '-1002903162401'))
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'carijodohyee_bot')

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Timezone
TZ = timezone('Asia/Jakarta')

# States untuk ConversationHandler
REGISTER_NAME, REGISTER_AGE = range(2)
EDIT_PROFILE, EDIT_BIO, EDIT_ADDRESS = range(2, 5)
MENFESS_TEXT, MENFESS_MEDIA, MENFESS_CONFIRM = range(5, 8)
VIP_PURCHASE, VIP_CONFIRM = range(8, 10)
TRANSFER_TYPE, TRANSFER_AMOUNT, TRANSFER_TARGET, TRANSFER_CONFIRM = range(10, 14)
GIFT_SELECT, GIFT_TARGET, GIFT_CONFIRM = range(14, 17)
TOPUP_VOUCHER = range(17, 18)
INBOX_VIEW, INBOX_DELETE = range(18, 20)

# Database sederhana (dalam produksi sebaiknya gunakan database eksternal)
users = {}
messages = {}
links = {}
vouchers = {}
inboxes = {}
gifts_sent = {}

# Daftar hadiah dan harganya
GIFTS = {
    "permen": {"price": 2000, "emoji": "🍬"},
    "kopi": {"price": 5000, "emoji": "☕"},
    "bunga": {"price": 10000, "emoji": "💐"},
    "boneka": {"price": 25000, "emoji": "🧸"},
    "motor": {"price": 50000, "emoji": "🏍️"},
    "mobil": {"price": 100000, "emoji": "🚗"},
    "kapal": {"price": 150000, "emoji": "🚢"},
    "pesawat": {"price": 250000, "emoji": "✈️"}
}

# Helper functions
def generate_unique_id() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def get_user(user_id: int) -> Dict:
    return users.get(user_id)

def save_user(user_data: Dict):
    users[user_data['id']] = user_data

def get_jakarta_time():
    return datetime.datetime.now(TZ)

def format_vip_time(until_date):
    if not until_date:
        return "Tidak aktif"
    now = get_jakarta_time()
    if until_date < now:
        return "Kadaluarsa"
    return f"Sampai {until_date.strftime('%d-%m-%Y %H:%M')}"

def format_time_delta(delta):
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    if days > 0:
        return f"{days} hari {hours} jam"
    elif hours > 0:
        return f"{hours} jam {minutes} menit"
    else:
        return f"{minutes} menit"

async def delete_previous_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if 'last_messages' in context.user_data:
        for msg_id in context.user_data['last_messages']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except BadRequest:
                pass
        context.user_data['last_messages'] = []

async def send_and_track_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, 
                                reply_markup=None, parse_mode=None) -> int:
    message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )
    if 'last_messages' not in context.user_data:
        context.user_data['last_messages'] = []
    context.user_data['last_messages'].append(message.message_id)
    return message.message_id

async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Jika user belum terdaftar
    if user_id not in users:
        await update.message.reply_text(
            "Selamat datang! Silakan register terlebih dahulu dengan /start"
        )
        return
    
    user = users[user_id]
    
    # Update statistik pengguna
    user['message_count'] += 1
    user['exp'] += 1
    user['charisma'] += 1
    user['points'] += 1
    user['last_message'] = get_jakarta_time()
    
    # Level up logic
    if user['exp'] >= user['level'] * 100:
        user['level'] += 1
        user['exp'] = 0
        await update.message.reply_text(f"🎉 Level up! Sekarang level {user['level']}")
    
    save_user(user)
    
    # Jika pesan dimulai dengan /, biarkan command handler yang menangani
    if update.message.text and update.message.text.startswith('/'):
        return
    
    # Jika ini adalah balasan ke pesan menfess
    if update.message.reply_to_message and update.message.reply_to_message.text and "💌 Menfess" in update.message.reply_to_message.text:
        await handle_menfess_reply(update, context)
        return
    
    # Jika user memiliki link aktif dan pesan bukan command, simpan sebagai pesan masuk
    if user_id in links and links[user_id]['active'] and not update.message.text.startswith('/'):
        # Simpan pesan ke inbox pemilik link
        link_owner_id = None
        for uid, link_data in links.items():
            if link_data['link'].endswith(user['unique_id']):
                link_owner_id = uid
                break
        
        if link_owner_id and link_owner_id in users:
            if link_owner_id not in inboxes:
                inboxes[link_owner_id] = []
            
            message_data = {
                'from_user': user_id,
                'message_id': update.message.message_id,
                'chat_id': update.effective_chat.id,
                'text': update.message.text if update.message.text else "",
                'media_type': None,
                'media_id': None,
                'timestamp': get_jakarta_time(),
                'read': False
            }
            
            if update.message.photo:
                message_data['media_type'] = 'photo'
                message_data['media_id'] = update.message.photo[-1].file_id
                # Forward foto ke channel media
                forwarded = await context.bot.forward_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
                message_data['channel_message_id'] = forwarded.message_id
            elif update.message.video:
                message_data['media_type'] = 'video'
                message_data['media_id'] = update.message.video.file_id
                # Forward video ke channel media
                forwarded = await context.bot.forward_message(
                    chat_id=MEDIA_CHANNEL_ID,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
                message_data['channel_message_id'] = forwarded.message_id
            
            inboxes[link_owner_id].append(message_data)
            
            # Kirim notifikasi ke pemilik link
            try:
                owner = users[link_owner_id]
                sender_name = user['name']
                if user['vip']:
                    sender_name = f"⭐ {sender_name}"
                
                notification = f"📥 Anda mendapat pesan baru dari {sender_name} (#{user['unique_id']})"
                
                if update.message.text:
                    preview = update.message.text[:50] + "..." if len(update.message.text) > 50 else update.message.text
                    notification += f"\n\n{preview}"
                
                keyboard = [[InlineKeyboardButton("📨 Buka Inbox", callback_data="inbox_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=link_owner_id,
                    text=notification,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error sending notification: {e}")

async def handle_menfess_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ekstrak ID unik dari pesan menfess
    message_text = update.message.reply_to_message.text
    match = re.search(r'#(\w+)', message_text)
    
    if match:
        unique_id = match.group(1)
        # Cari user dengan ID unik tersebut
        target_user = None
        for user_id, user_data in users.items():
            if user_data['unique_id'] == unique_id:
                target_user = user_data
                break
        
        if target_user:
            reply_text = update.message.text
            sender = get_user(update.effective_user.id)
            
            # Kirim balasan ke target user
            try:
                message = f"💌 Anda mendapat balasan menfess dari {sender['name']}:\n\n{reply_text}"
                await context.bot.send_message(
                    chat_id=target_user['id'],
                    text=message
                )
                await update.message.reply_text("✅ Balasan telah dikirim!")
            except Exception as e:
                logger.error(f"Error sending menfess reply: {e}")
                await update.message.reply_text("❌ Gagal mengirim balasan. User mungkin telah memblokir bot.")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in users:
        # Buat user baru
        users[user_id] = {
            'id': user_id,
            'name': update.effective_user.first_name or "Anonymous",
            'username': update.effective_user.username,
            'age': None,
            'level': 1,
            'exp': 0,
            'charisma': 0,
            'points': 0,
            'diamonds': 0,
            'vip': False,
            'vip_until': None,
            'badge': "Newbie",
            'address': "",
            'bio': "",
            'profile_photo': None,
            'registered_at': get_jakarta_time(),
            'last_message': get_jakarta_time(),
            'unique_id': generate_unique_id(),
            'message_count': 0
        }
        
        await update.message.reply_text(
            "Selamat datang! Silakan register terlebih dahulu.\nMasukkan nama Anda:"
        )
        return REGISTER_NAME
    else:
        await show_main_menu(update, context)
        return ConversationHandler.END

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['register_name'] = update.message.text
    await update.message.reply_text("Masukkan umur Anda:")
    return REGISTER_AGE

async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 5 or age > 100:
            await update.message.reply_text("Umur tidak valid. Masukkan umur antara 5-100:")
            return REGISTER_AGE
        
        user = get_user(update.effective_user.id)
        user['name'] = context.user_data['register_name']
        user['age'] = age
        save_user(user)
        
        await update.message.reply_text(
            f"Registrasi berhasil!\nNama: {user['name']}\nUmur: {user['age']}"
        )
        await show_main_menu(update, context)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Umur harus berupa angka. Silakan masukkan lagi:")
        return REGISTER_AGE

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    
    await delete_previous_messages(context, update.effective_chat.id)
    
    keyboard = [
        [InlineKeyboardButton("🔗 Link Saya", callback_data="link_menu")],
        [InlineKeyboardButton("📥 Inbox", callback_data="inbox_menu")],
        [InlineKeyboardButton("⭐ VIP", callback_data="vip_menu")],
        [InlineKeyboardButton("👤 Profil", callback_data="profile_menu")],
        [InlineKeyboardButton("🎁 Gift", callback_data="gift_menu")],
        [InlineKeyboardButton("💎 Topup", callback_data="topup_menu")],
        [InlineKeyboardButton("💌 Menfess", callback_data="menfess_menu")]
    ]
    
    if user['id'] == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Menu", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🛡️ *Menu Utama Pesan Rahasia*\n\nPilih menu di bawah untuk melanjutkan:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

# Link menu handlers
async def link_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    user_id = user['id']
    
    if user_id not in links:
        links[user_id] = {
            'link': f"https://t.me/{BOT_USERNAME}?start={user['unique_id']}",
            'created_at': get_jakarta_time(),
            'active': True
        }
    
    keyboard = [
        [InlineKeyboardButton("📋 Lihat Link", callback_data="view_link")],
        [InlineKeyboardButton("🔗 Buat Link Baru", callback_data="create_link")],
        [InlineKeyboardButton("🗑️ Hapus Link", callback_data="delete_link")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🔗 *Menu Link Pribadi*\n\nGunakan link ini untuk menerima pesan rahasia dari orang lain."
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def view_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    user_id = user['id']
    
    if user_id in links and links[user_id]['active']:
        link_info = links[user_id]
        text = f"🔗 *Link Pribadi Anda:*\n\n{link_info['link']}\n\nDibuat: {link_info['created_at'].strftime('%d-%m-%Y %H:%M')}"
    else:
        text = "❌ Anda belum memiliki link aktif. Buat link baru terlebih dahulu."
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="link_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def create_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    user_id = user['id']
    
    # Generate new unique ID
    user['unique_id'] = generate_unique_id()
    save_user(user)
    
    links[user_id] = {
        'link': f"https://t.me/{BOT_USERNAME}?start={user['unique_id']}",
        'created_at': get_jakarta_time(),
        'active': True
    }
    
    text = f"✅ Link baru berhasil dibuat!\n\n🔗 {links[user_id]['link']}"
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="link_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def delete_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id in links:
        links[user_id]['active'] = False
        text = "✅ Link berhasil dihapus (dinonaktifkan)."
    else:
        text = "❌ Anda tidak memiliki link aktif."
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="link_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

# Inbox menu handlers
async def inbox_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    unread_count = 0
    total_count = 0
    
    if user_id in inboxes:
        for msg in inboxes[user_id]:
            total_count += 1
            if not msg['read']:
                unread_count += 1
    
    keyboard = [
        [InlineKeyboardButton(f"📥 Pesan ({total_count})", callback_data="view_inbox")],
        [InlineKeyboardButton("🗑️ Hapus Inbox", callback_data="delete_inbox")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"📥 *Menu Inbox*\n\nAnda memiliki {unread_count} pesan belum dibaca dari total {total_count} pesan."
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def view_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in inboxes or not inboxes[user_id]:
        text = "📭 Inbox Anda kosong."
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="inbox_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
        return
    
    # Tampilkan pesan pertama yang belum dibaca atau pesan terakhir
    unread_messages = [msg for msg in inboxes[user_id] if not msg['read']]
    
    if unread_messages:
        message = unread_messages[0]
    else:
        message = inboxes[user_id][-1]
    
    # Tandai sebagai sudah dibaca
    message['read'] = True
    message['read_at'] = get_jakarta_time()
    
    # Dapatkan info pengirim
    sender = get_user(message['from_user'])
    if sender:
        sender_name = sender['name']
        if sender['vip']:
            sender_name = f"⭐ {sender_name}"
        sender_info = f"{sender_name} (#{sender['unique_id']})"
    else:
        sender_info = "Anonymous"
    
    # Format waktu
    time_diff = get_jakarta_time() - message['timestamp']
    time_ago = format_time_delta(time_diff)
    
    # Tampilkan pesan
    if message['media_type'] == 'photo':
        text = f"📸 *Foto dari {sender_info}* ({time_ago} yang lalu)"
        await context.bot.send_photo(
            chat_id=user_id,
            photo=message['media_id'],
            caption=text,
            parse_mode="Markdown"
        )
    elif message['media_type'] == 'video':
        text = f"🎥 *Video dari {sender_info}* ({time_ago} yang lalu)"
        await context.bot.send_video(
            chat_id=user_id,
            video=message['media_id'],
            caption=text,
            parse_mode="Markdown"
        )
    else:
        text = f"✉️ *Pesan dari {sender_info}* ({time_ago} yang lalu)\n\n{message['text']}"
        await send_and_track_message(context, user_id, text, parse_mode="Markdown")
    
    # Tampilkan navigasi inbox
    current_index = inboxes[user_id].index(message)
    total_messages = len(inboxes[user_id])
    
    keyboard = []
    if total_messages > 1:
        if current_index > 0:
            keyboard.append([InlineKeyboardButton("⬅️ Pesan Sebelumnya", callback_data=f"inbox_prev_{current_index}")])
        if current_index < total_messages - 1:
            keyboard.append([InlineKeyboardButton("➡️ Pesan Berikutnya", callback_data=f"inbox_next_{current_index}")])
    
    keyboard.append([InlineKeyboardButton("🗑️ Hapus Pesan Ini", callback_data=f"inbox_delete_{current_index}")])
    keyboard.append([InlineKeyboardButton("🔙 Kembali ke Inbox", callback_data="inbox_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_and_track_message(context, user_id, "Navigasi inbox:", reply_markup)

async def delete_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🗑️ Hapus Semua", callback_data="inbox_delete_all")],
        [InlineKeyboardButton("✅ Hapus yang Sudah Dibaca", callback_data="inbox_delete_read")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="inbox_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🗑️ *Hapus Inbox*\n\nPilih opsi penghapusan:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def inbox_delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id in inboxes:
        del inboxes[user_id]
        text = "✅ Semua pesan dalam inbox telah dihapus."
    else:
        text = "❌ Inbox sudah kosong."
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="inbox_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def inbox_delete_read(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id in inboxes:
        # Hapus pesan yang sudah dibaca
        inboxes[user_id] = [msg for msg in inboxes[user_id] if not msg['read']]
        text = "✅ Semua pesan yang sudah dibaca telah dihapus."
    else:
        text = "❌ Inbox sudah kosong."
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="inbox_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

# VIP menu handlers
async def vip_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    keyboard = [
        [InlineKeyboardButton("7 Hari - 70 💎", callback_data="vip_7")],
        [InlineKeyboardButton("30 Hari - 250 💎", callback_data="vip_30")],
        [InlineKeyboardButton("1 Tahun - 2000 💎", callback_data="vip_365")],
        [InlineKeyboardButton("Lifetime - 5000 💎", callback_data="vip_lifetime")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    vip_status = "Aktif" if user['vip'] and user['vip_until'] and user['vip_until'] > get_jakarta_time() else "Tidak Aktif"
    vip_until = format_vip_time(user['vip_until'])
    
    text = f"⭐ *Menu VIP*\n\nStatus: {vip_status}\n{vip_until}\n\nManfaat VIP:\n- Lihat profil lengkap\n- Badge khusus\n- Fitur Menfess lengkap\n- Prioritas pesan\n\nPilih paket VIP:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def vip_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    data = query.data
    
    # Tentukan paket VIP
    if data == "vip_7":
        duration = datetime.timedelta(days=7)
        cost = 70
        package_name = "7 Hari"
    elif data == "vip_30":
        duration = datetime.timedelta(days=30)
        cost = 250
        package_name = "30 Hari"
    elif data == "vip_365":
        duration = datetime.timedelta(days=365)
        cost = 2000
        package_name = "1 Tahun"
    else:  # vip_lifetime
        duration = None  # Lifetime
        cost = 5000
        package_name = "Lifetime"
    
    # Simpan data di context
    context.user_data['vip_package'] = {
        'duration': duration,
        'cost': cost,
        'name': package_name
    }
    
    # Cek apakah diamond cukup
    if user['diamonds'] < cost:
        text = f"❌ Diamond tidak cukup. Anda membutuhkan {cost} 💎 untuk paket {package_name}, tetapi hanya memiliki {user['diamonds']} 💎."
        keyboard = [[InlineKeyboardButton("💎 Topup Diamond", callback_data="topup_menu")],
                   [InlineKeyboardButton("🔙 Kembali", callback_data="vip_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
        return
    
    # Tampilkan konfirmasi
    text = f"✅ Konfirmasi Pembelian VIP {package_name}\n\nHarga: {cost} 💎\nDiamond Anda: {user['diamonds']} 💎"
    keyboard = [
        [InlineKeyboardButton("✅ Konfirmasi", callback_data="vip_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="vip_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def vip_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    package = context.user_data['vip_package']
    
    # Kurangi diamond
    user['diamonds'] -= package['cost']
    
    # Set VIP
    user['vip'] = True
    if package['duration']:
        user['vip_until'] = get_jakarta_time() + package['duration']
    else:
        user['vip_until'] = None  # Lifetime
    
    save_user(user)
    
    text = f"🎉 Selamat! Anda sekarang adalah member VIP {package['name']}!"
    keyboard = [[InlineKeyboardButton("🔙 Kembali ke Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

# Profile menu handlers
async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    keyboard = [
        [InlineKeyboardButton("👀 Lihat Profil", callback_data="view_profile")],
        [InlineKeyboardButton("✏️ Edit Profil", callback_data="edit_profile")],
        [InlineKeyboardButton("💎 Tukar Poin", callback_data="exchange_points")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "👤 *Menu Profil*\n\nKelola profil dan data Anda di sini."
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    # Format teks profil
    profile_text = f"""
👤 *Profil Pengguna*

🆔 ID Unik: {user['unique_id']}
📛 Nama: {user['name']}
🎂 Umur: {user['age']}
📍 Alamat: {user['address'] or 'Tidak diisi'}
📝 Bio: {user['bio'] or 'Tidak diisi'}

⭐ Level: {user['level']}
✨ EXP: {user['exp']}
💫 Karisma: {user['charisma']}
🏆 Badge: {user['badge']}

📊 Statistik:
• Poin: {user['points']}
• Diamond: {user['diamonds']}
• Pesan: {user['message_count']}

💎 Status VIP: {'Aktif' if user['vip'] else 'Tidak Aktif'}
{format_vip_time(user['vip_until'])}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="profile_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Kirim foto profil jika ada
    if user['profile_photo']:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=user['profile_photo'],
                caption=profile_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Error sending profile photo: {e}")
    
    await send_and_track_message(context, update.effective_chat.id, profile_text, reply_markup, parse_mode="Markdown")

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Bio", callback_data="edit_bio")],
        [InlineKeyboardButton("📍 Edit Alamat", callback_data="edit_address")],
        [InlineKeyboardButton("📸 Edit Foto Profil", callback_data="edit_photo")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="profile_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "✏️ *Edit Profil*\n\nPilih bagian yang ingin diedit:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await send_and_track_message(context, update.effective_chat.id, "✍️ Masukkan bio baru Anda:")
    return EDIT_BIO

async def edit_bio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    user['bio'] = update.message.text
    save_user(user)
    
    await update.message.reply_text("✅ Bio berhasil diperbarui!")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def edit_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await send_and_track_message(context, update.effective_chat.id, "📍 Masukkan alamat baru Anda:")
    return EDIT_ADDRESS

async def edit_address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    user['address'] = update.message.text
    save_user(user)
    
    await update.message.reply_text("✅ Alamat berhasil diperbarui!")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await send_and_track_message(context, update.effective_chat.id, "📸 Silakan kirim foto profil baru Anda:")
    # State akan ditangani oleh handler foto

async def handle_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        user = get_user(update.effective_user.id)
        user['profile_photo'] = update.message.photo[-1].file_id
        save_user(user)
        
        await update.message.reply_text("✅ Foto profil berhasil diperbarui!")
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Silakan kirim foto yang valid.")

async def exchange_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    # 500 poin = 1 diamond
    exchange_rate = 500
    max_diamonds = user['points'] // exchange_rate
    
    if max_diamonds < 1:
        text = f"❌ Anda tidak memiliki cukup poin. Diperuhkan {exchange_rate} poin untuk 1 💎, tetapi Anda hanya memiliki {user['points']} poin."
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="profile_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
        return
    
    text = f"💱 *Tukar Poin ke Diamond*\n\nRate: 500 poin = 1 💎\nPoin Anda: {user['points']}\nDiamond yang bisa didapat: {max_diamonds} 💎\n\nMasukkan jumlah diamond yang ingin ditukar:"
    await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
    
    context.user_data['exchange_rate'] = exchange_rate
    context.user_data['max_diamonds'] = max_diamonds
    return VIP_PURCHASE  # Reusing state

async def exchange_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        diamonds = int(update.message.text)
        user = get_user(update.effective_user.id)
        exchange_rate = context.user_data['exchange_rate']
        max_diamonds = context.user_data['max_diamonds']
        
        if diamonds < 1 or diamonds > max_diamonds:
            await update.message.reply_text(f"❌ Jumlah tidak valid. Masukkan antara 1-{max_diamonds}:")
            return VIP_PURCHASE
        
        # Lakukan penukaran
        points_needed = diamonds * exchange_rate
        user['points'] -= points_needed
        user['diamonds'] += diamonds
        save_user(user)
        
        await update.message.reply_text(f"✅ Berhasil menukar {points_needed} poin menjadi {diamonds} 💎!")
        await show_main_menu(update, context)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka yang valid:")
        return VIP_PURCHASE

# Transfer handlers
async def transfer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    keyboard = [
        [InlineKeyboardButton("💎 Transfer Diamond", callback_data="transfer_diamond")],
        [InlineKeyboardButton("🪙 Transfer Poin", callback_data="transfer_points")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="profile_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"💸 *Transfer*\n\nPilih jenis transfer:\n\nDiamond: {user['diamonds']} 💎\nPoin: {user['points']} 🪙"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def transfer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = get_user(update.effective_user.id)
    
    if data == "transfer_diamond":
        context.user_data['transfer_type'] = 'diamond'
        context.user_data['balance'] = user['diamonds']
        currency = "💎"
    else:
        context.user_data['transfer_type'] = 'points'
        context.user_data['balance'] = user['points']
        currency = "🪙"
    
    text = f"💸 Transfer {context.user_data['transfer_type']}\n\nSaldo Anda: {context.user_data['balance']} {currency}\n\nMasukkan jumlah yang ingin ditransfer:"
    await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
    
    return TRANSFER_AMOUNT

async def transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text)
        transfer_type = context.user_data['transfer_type']
        balance = context.user_data['balance']
        
        if amount < 1 or amount > balance:
            await update.message.reply_text(f"❌ Jumlah tidak valid. Masukkan antara 1-{balance}:")
            return TRANSFER_AMOUNT
        
        context.user_data['transfer_amount'] = amount
        await update.message.reply_text("👤 Masukkan ID unik penerima:")
        return TRANSFER_TARGET
        
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka yang valid:")
        return TRANSFER_AMOUNT

async def transfer_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_unique_id = update.message.text.upper()
    sender = get_user(update.effective_user.id)
    
    # Cari user dengan ID unik tersebut
    target_user = None
    for user_id, user_data in users.items():
        if user_data['unique_id'] == target_unique_id:
            target_user = user_data
            break
    
    if not target_user:
        await update.message.reply_text("❌ ID unik tidak ditemukan. Masukkan ID unik yang valid:")
        return TRANSFER_TARGET
    
    if target_user['id'] == sender['id']:
        await update.message.reply_text("❌ Tidak dapat transfer ke diri sendiri. Masukkan ID unik penerima:")
        return TRANSFER_TARGET
    
    context.user_data['target_user'] = target_user
    transfer_type = context.user_data['transfer_type']
    amount = context.user_data['transfer_amount']
    currency = "💎" if transfer_type == 'diamond' else "🪙"
    
    text = f"✅ Konfirmasi Transfer\n\nKirim {amount} {currency} ke {target_user['name']} (#{target_user['unique_id']})?"
    keyboard = [
        [InlineKeyboardButton("✅ Ya", callback_data="transfer_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="profile_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
    return TRANSFER_CONFIRM

async def transfer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    sender = get_user(update.effective_user.id)
    target_user = context.user_data['target_user']
    transfer_type = context.user_data['transfer_type']
    amount = context.user_data['transfer_amount']
    currency = "💎" if transfer_type == 'diamond' else "🪙"
    
    # Lakukan transfer
    if transfer_type == 'diamond':
        if sender['diamonds'] < amount:
            text = "❌ Saldo diamond tidak cukup."
            await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
            await show_main_menu(update, context)
            return ConversationHandler.END
        
        sender['diamonds'] -= amount
        target_user['diamonds'] += amount
    else:
        if sender['points'] < amount:
            text = "❌ Saldo poin tidak cukup."
            await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
            await show_main_menu(update, context)
            return ConversationHandler.END
        
        sender['points'] -= amount
        target_user['points'] += amount
    
    save_user(sender)
    save_user(target_user)
    
    # Kirim notifikasi ke penerima
    try:
        notification = f"🎉 Anda menerima transfer {amount} {currency} dari {sender['name']} (#{sender['unique_id']})!"
        await context.bot.send_message(chat_id=target_user['id'], text=notification)
    except Exception as e:
        logger.error(f"Error sending transfer notification: {e}")
    
    text = f"✅ Berhasil transfer {amount} {currency} ke {target_user['name']}!"
    await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
    await show_main_menu(update, context)
    return ConversationHandler.END

# Gift menu handlers
async def gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    keyboard = []
    row = []
    for i, (gift_id, gift_data) in enumerate(GIFTS.items()):
        emoji = gift_data['emoji']
        price = gift_data['price']
        row.append(InlineKeyboardButton(f"{emoji} {price}", callback_data=f"gift_{gift_id}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🎁 *Toko Hadiah*\n\nPilih hadiah yang ingin dikirim:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def gift_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    gift_id = query.data.split('_')[1]
    gift_data = GIFTS[gift_id]
    user = get_user(update.effective_user.id)
    
    # Cek apakah diamond cukup
    if user['diamonds'] < gift_data['price']:
        text = f"❌ Diamond tidak cukup. Anda membutuhkan {gift_data['price']} 💎 untuk {gift_data['emoji']} {gift_id}, tetapi hanya memiliki {user['diamonds']} 💎."
        keyboard = [[InlineKeyboardButton("💎 Topup Diamond", callback_data="topup_menu")],
                   [InlineKeyboardButton("🔙 Kembali", callback_data="gift_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
        return
    
    context.user_data['gift_id'] = gift_id
    context.user_data['gift_data'] = gift_data
    
    await send_and_track_message(context, update.effective_chat.id, "👤 Masukkan ID unik penerima hadiah:")
    return GIFT_TARGET

async def gift_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_unique_id = update.message.text.upper()
    sender = get_user(update.effective_user.id)
    gift_id = context.user_data['gift_id']
    gift_data = context.user_data['gift_data']
    
    # Cari user dengan ID unik tersebut
    target_user = None
    for user_id, user_data in users.items():
        if user_data['unique_id'] == target_unique_id:
            target_user = user_data
            break
    
    if not target_user:
        await update.message.reply_text("❌ ID unik tidak ditemukan. Masukkan ID unik yang valid:")
        return GIFT_TARGET
    
    if target_user['id'] == sender['id']:
        await update.message.reply_text("❌ Tidak dapat mengirim hadiah ke diri sendiri. Masukkan ID unik penerima:")
        return GIFT_TARGET
    
    context.user_data['target_user'] = target_user
    
    text = f"✅ Konfirmasi Kirim Hadiah\n\nKirim {gift_data['emoji']} {gift_id} (senilai {gift_data['price']} 💎) ke {target_user['name']} (#{target_user['unique_id']})?"
    keyboard = [
        [InlineKeyboardButton("✅ Ya", callback_data="gift_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="gift_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")
    return GIFT_CONFIRM

async def gift_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    sender = get_user(update.effective_user.id)
    target_user = context.user_data['target_user']
    gift_id = context.user_data['gift_id']
    gift_data = context.user_data['gift_data']
    
    # Kurangi diamond pengirim
    if sender['diamonds'] < gift_data['price']:
        text = "❌ Saldo diamond tidak cukup."
        await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    sender['diamonds'] -= gift_data['price']
    save_user(sender)
    
    # Catat hadiah yang dikirim
    if sender['id'] not in gifts_sent:
        gifts_sent[sender['id']] = []
    
    gifts_sent[sender['id']].append({
        'to': target_user['id'],
        'gift': gift_id,
        'price': gift_data['price'],
        'timestamp': get_jakarta_time()
    })
    
    # Kirim notifikasi ke penerima
    try:
        notification = f"🎁 Anda menerima {gift_data['emoji']} {gift_id} dari {sender['name']} (#{sender['unique_id']})!"
        await context.bot.send_message(chat_id=target_user['id'], text=notification)
    except Exception as e:
        logger.error(f"Error sending gift notification: {e}")
    
    text = f"✅ Berhasil mengirim {gift_data['emoji']} {gift_id} ke {target_user['name']}!"
    await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
    await show_main_menu(update, context)
    return ConversationHandler.END

# Topup menu handlers
async def topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = "💎 *Topup Diamond*\n\nUntuk topup diamond, silakan beli voucher dari admin dan masukkan kode voucher di sini.\n\nMasukkan kode voucher:"
    await send_and_track_message(context, update.effective_chat.id, text, parse_mode="Markdown")
    return TOPUP_VOUCHER

async def topup_voucher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voucher_code = update.message.text.upper()
    user = get_user(update.effective_user.id)
    
    if voucher_code in vouchers and vouchers[voucher_code]['active']:
        voucher = vouchers[voucher_code]
        diamond_amount = voucher['diamonds']
        
        # Tambahkan diamond ke user
        user['diamonds'] += diamond_amount
        save_user(user)
        
        # Nonaktifkan voucher
        vouchers[voucher_code]['active'] = False
        vouchers[voucher_code]['used_by'] = user['id']
        vouchers[voucher_code]['used_at'] = get_jakarta_time()
        
        await update.message.reply_text(f"✅ Topup berhasil! Anda mendapatkan {diamond_amount} 💎")
        await show_main_menu(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Kode voucher tidak valid atau sudah digunakan. Masukkan kode voucher yang valid:")
        return TOPUP_VOUCHER

# Menfess handlers
async def menfess_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    
    if user['vip']:
        keyboard = [
            [InlineKeyboardButton("📝 Text Only", callback_data="menfess_text")],
            [InlineKeyboardButton("🖼️ Dengan Media", callback_data="menfess_media")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
        ]
        text = "💌 *Menu Menfess*\n\nPilih jenis menfess yang ingin dikirim. VIP dapat mengirim media."
    else:
        keyboard = [
            [InlineKeyboardButton("📝 Text Only", callback_data="menfess_text")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
        ]
        text = "💌 *Menu Menfess*\n\nKirim pesan anonim ke channel menfess. Upgrade VIP untuk kirim media."
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def menfess_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await send_and_track_message(context, update.effective_chat.id, "✍️ Silakan ketik pesan menfess Anda:")
    return MENFESS_TEXT

async def menfess_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    menfess_text = update.message.text
    
    # Kirim ke channel menfess
    try:
        if user['vip']:
            caption = f"💌 #{user['unique_id']} ⭐\n\n{menfess_text}\n\n*Balas pesan ini untuk membalas menfess*"
        else:
            caption = f"💌 #{user['unique_id']}\n\n{menfess_text}\n\n*Balas pesan ini untuk membalas menfess*"
        
        message = await context.bot.send_message(
            chat_id=MENFESS_CHANNEL_ID,
            text=caption,
            parse_mode="Markdown"
        )
        
        # Simpan info menfess untuk balasan
        if 'menfess_messages' not in context.bot_data:
            context.bot_data['menfess_messages'] = {}
        
        context.bot_data['menfess_messages'][message.message_id] = {
            'from_user': user['id'],
            'unique_id': user['unique_id'],
            'timestamp': get_jakarta_time()
        }
        
        await update.message.reply_text("✅ Pesan menfess telah dikirim!")
    except Exception as e:
        logger.error(f"Error sending menfess: {e}")
        await update.message.reply_text("❌ Gagal mengirim menfess. Silakan coba lagi nanti.")
    
    await show_main_menu(update, context)
    return ConversationHandler.END

async def menfess_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await send_and_track_message(context, update.effective_chat.id, "🖼️ Silakan kirim foto atau video untuk menfess Anda:")
    return MENFESS_MEDIA

async def menfess_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    
    if update.message.photo:
        media_type = 'photo'
        media_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = 'video'
        media_id = update.message.video.file_id
    else:
        await update.message.reply_text("❌ Silakan kirim foto atau video yang valid.")
        return MENFESS_MEDIA
    
    context.user_data['menfess_media'] = {
        'type': media_type,
        'id': media_id
    }
    
    await send_and_track_message(context, update.effective_chat.id, "✍️ Silakan ketik caption untuk menfess Anda:")
    return MENFESS_TEXT

async def menfess_media_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    caption = update.message.text
    media_data = context.user_data['menfess_media']
    
    # Kirim ke channel menfess
    try:
        if user['vip']:
            caption_text = f"💌 #{user['unique_id']} ⭐\n\n{caption}\n\n*Balas pesan ini untuk membalas menfess*"
        else:
            caption_text = f"💌 #{user['unique_id']}\n\n{caption}\n\n*Balas pesan ini untuk membalas menfess*"
        
        if media_data['type'] == 'photo':
            message = await context.bot.send_photo(
                chat_id=MENFESS_CHANNEL_ID,
                photo=media_data['id'],
                caption=caption_text,
                parse_mode="Markdown"
            )
        else:  # video
            message = await context.bot.send_video(
                chat_id=MENFESS_CHANNEL_ID,
                video=media_data['id'],
                caption=caption_text,
                parse_mode="Markdown"
            )
        
        # Simpan info menfess untuk balasan
        if 'menfess_messages' not in context.bot_data:
            context.bot_data['menfess_messages'] = {}
        
        context.bot_data['menfess_messages'][message.message_id] = {
            'from_user': user['id'],
            'unique_id': user['unique_id'],
            'timestamp': get_jakarta_time()
        }
        
        await update.message.reply_text("✅ Pesan menfess telah dikirim!")
    except Exception as e:
        logger.error(f"Error sending menfess: {e}")
        await update.message.reply_text("❌ Gagal mengirim menfess. Silakan coba lagi nanti.")
    
    await show_main_menu(update, context)
    return ConversationHandler.END

# Admin menu handlers
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if user['id'] != ADMIN_ID:
        await query.edit_message_text("❌ Akses ditolak.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistik Bot", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Kelola Pengguna", callback_data="admin_users")],
        [InlineKeyboardButton("🎫 Kelola Voucher", callback_data="admin_vouchers")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "👑 *Menu Admin*\n\nPilih opsi admin yang tersedia:"
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if user['id'] != ADMIN_ID:
        await query.edit_message_text("❌ Akses ditolak.")
        return
    
    total_users = len(users)
    active_today = len([u for u in users.values() if (get_jakarta_time() - u['last_message']).days < 1])
    total_messages = sum(u['message_count'] for u in users.values())
    total_vip = len([u for u in users.values() if u['vip'] and u['vip_until'] and u['vip_until'] > get_jakarta_time()])
    
    # Hitung total diamond dan poin
    total_diamonds = sum(u['diamonds'] for u in users.values())
    total_points = sum(u['points'] for u in users.values())
    
    stats_text = f"""
📊 *Statistik Bot*

👥 Total Pengguna: {total_users}
🚶 Pengguna Aktif (24j): {active_today}
💬 Total Pesan: {total_messages}
⭐ VIP Aktif: {total_vip}

💎 Total Diamond: {total_diamonds}
🪙 Total Poin: {total_points}

⏰ Server Time: {get_jakarta_time().strftime('%d-%m-%Y %H:%M:%S')}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, stats_text, reply_markup, parse_mode="Markdown")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if user['id'] != ADMIN_ID:
        await query.edit_message_text("❌ Akses ditolak.")
        return
    
    # Tampilkan daftar 10 user terbaru
    recent_users = sorted(users.values(), key=lambda x: x['registered_at'], reverse=True)[:10]
    
    users_text = "👥 *10 User Terbaru*\n\n"
    for i, u in enumerate(recent_users, 1):
        users_text += f"{i}. {u['name']} (#{u['unique_id']}) - {u['registered_at'].strftime('%d/%m/%Y')}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, users_text, reply_markup, parse_mode="Markdown")

async def admin_vouchers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if user['id'] != ADMIN_ID:
        await query.edit_message_text("❌ Akses ditolak.")
        return
    
    # Generate voucher code
    voucher_code = generate_unique_id()
    vouchers[voucher_code] = {
        'diamonds': 100,  # Default value
        'active': True,
        'created_at': get_jakarta_time(),
        'created_by': ADMIN_ID,
        'used_by': None,
        'used_at': None
    }
    
    text = f"🎫 *Voucher Baru*\n\nKode: `{voucher_code}`\nNilai: 100 💎\n\nBagikan kode ini ke user untuk topup."
    keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, update.effective_chat.id, text, reply_markup, parse_mode="Markdown")

# Callback query handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "main_menu":
        await show_main_menu(update, context)
    elif data == "link_menu":
        await link_menu(update, context)
    elif data == "view_link":
        await view_link(update, context)
    elif data == "create_link":
        await create_link(update, context)
    elif data == "delete_link":
        await delete_link(update, context)
    elif data == "inbox_menu":
        await inbox_menu(update, context)
    elif data == "view_inbox":
        await view_inbox(update, context)
    elif data == "delete_inbox":
        await delete_inbox(update, context)
    elif data == "inbox_delete_all":
        await inbox_delete_all(update, context)
    elif data == "inbox_delete_read":
        await inbox_delete_read(update, context)
    elif data == "vip_menu":
        await vip_menu(update, context)
    elif data in ["vip_7", "vip_30", "vip_365", "vip_lifetime"]:
        await vip_purchase(update, context)
    elif data == "vip_confirm":
        await vip_confirm(update, context)
    elif data == "profile_menu":
        await profile_menu(update, context)
    elif data == "view_profile":
        await view_profile(update, context)
    elif data == "edit_profile":
        await edit_profile(update, context)
    elif data == "edit_bio":
        await edit_bio(update, context)
    elif data == "edit_address":
        await edit_address(update, context)
    elif data == "edit_photo":
        await edit_photo(update, context)
    elif data == "exchange_points":
        await exchange_points(update, context)
    elif data == "transfer_menu":
        await transfer_menu(update, context)
    elif data in ["transfer_diamond", "transfer_points"]:
        await transfer_type(update, context)
    elif data == "transfer_confirm":
        await transfer_confirm(update, context)
    elif data == "gift_menu":
        await gift_menu(update, context)
    elif data.startswith("gift_"):
        await gift_select(update, context)
    elif data == "gift_confirm":
        await gift_confirm(update, context)
    elif data == "topup_menu":
        await topup_menu(update, context)
    elif data == "menfess_menu":
        await menfess_menu(update, context)
    elif data == "menfess_text":
        await menfess_text(update, context)
    elif data == "menfess_media":
        await menfess_media(update, context)
    elif data == "admin_menu":
        await admin_menu(update, context)
    elif data == "admin_stats":
        await admin_stats(update, context)
    elif data == "admin_users":
        await admin_users(update, context)
    elif data == "admin_vouchers":
        await admin_vouchers(update, context)
    elif data.startswith("inbox_prev_") or data.startswith("inbox_next_"):
        # Handle inbox navigation
        await handle_inbox_navigation(update, context)
    elif data.startswith("inbox_delete_"):
        # Handle inbox deletion
        await handle_inbox_deletion(update, context)
    else:
        await query.answer("Fitur dalam pengembangan")

async def handle_inbox_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("inbox_prev_"):
        current_index = int(data.split("_")[2])
        new_index = current_index - 1
    else:  # inbox_next_
        current_index = int(data.split("_")[2])
        new_index = current_index + 1
    
    if user_id not in inboxes or new_index < 0 or new_index >= len(inboxes[user_id]):
        await query.answer("Tidak ada pesan lagi")
        return
    
    message = inboxes[user_id][new_index]
    
    # Tandai sebagai sudah dibaca
    message['read'] = True
    message['read_at'] = get_jakarta_time()
    
    # Dapatkan info pengirim
    sender = get_user(message['from_user'])
    if sender:
        sender_name = sender['name']
        if sender['vip']:
            sender_name = f"⭐ {sender_name}"
        sender_info = f"{sender_name} (#{sender['unique_id']})"
    else:
        sender_info = "Anonymous"
    
    # Format waktu
    time_diff = get_jakarta_time() - message['timestamp']
    time_ago = format_time_delta(time_diff)
    
    # Hapus pesan sebelumnya
    await delete_previous_messages(context, user_id)
    
    # Tampilkan pesan
    if message['media_type'] == 'photo':
        text = f"📸 *Foto dari {sender_info}* ({time_ago} yang lalu)"
        await context.bot.send_photo(
            chat_id=user_id,
            photo=message['media_id'],
            caption=text,
            parse_mode="Markdown"
        )
    elif message['media_type'] == 'video':
        text = f"🎥 *Video dari {sender_info}* ({time_ago} yang lalu)"
        await context.bot.send_video(
            chat_id=user_id,
            video=message['media_id'],
            caption=text,
            parse_mode="Markdown"
        )
    else:
        text = f"✉️ *Pesan dari {sender_info}* ({time_ago} yang lalu)\n\n{message['text']}"
        await send_and_track_message(context, user_id, text, parse_mode="Markdown")
    
    # Tampilkan navigasi inbox
    total_messages = len(inboxes[user_id])
    
    keyboard = []
    if total_messages > 1:
        if new_index > 0:
            keyboard.append([InlineKeyboardButton("⬅️ Pesan Sebelumnya", callback_data=f"inbox_prev_{new_index}")])
        if new_index < total_messages - 1:
            keyboard.append([InlineKeyboardButton("➡️ Pesan Berikutnya", callback_data=f"inbox_next_{new_index}")])
    
    keyboard.append([InlineKeyboardButton("🗑️ Hapus Pesan Ini", callback_data=f"inbox_delete_{new_index}")])
    keyboard.append([InlineKeyboardButton("🔙 Kembali ke Inbox", callback_data="inbox_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_and_track_message(context, user_id, "Navigasi inbox:", reply_markup)

async def handle_inbox_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    index = int(data.split("_")[2])
    
    if user_id in inboxes and 0 <= index < len(inboxes[user_id]):
        # Hapus pesan dari inbox
        del inboxes[user_id][index]
        text = "✅ Pesan telah dihapus dari inbox."
    else:
        text = "❌ Pesan tidak ditemukan."
    
    keyboard = [[InlineKeyboardButton("🔙 Kembali ke Inbox", callback_data="inbox_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_and_track_message(context, user_id, text, reply_markup, parse_mode="Markdown")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling update:", exc_info=context.error)

# Main function
def main():
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)],
            EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bio_handler)],
            EDIT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_address_handler)],
            MENFESS_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, menfess_text_handler)],
            MENFESS_MEDIA: [
                MessageHandler(filters.PHOTO, menfess_media_handler),
                MessageHandler(filters.VIDEO, menfess_media_handler)
            ],
            VIP_PURCHASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, exchange_points_handler)],
            TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount)],
            TRANSFER_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_target)],
            GIFT_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_target)],
            TOPUP_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_voucher)],
        },
        fallbacks=[CommandHandler('cancel', show_main_menu)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_profile_photo))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming_message))
    application.add_error_handler(error_handler)
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
