import logging
from datetime import datetime
from dadata import Dadata 
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = '8494242621:AAEUCTXyf0iibHFBCttejFh7w0zxvJvHt5U'
DADATA_API_KEY = '8661126d2bafb75aa000de2908425ba8e55d470e'


def safe_subdict(data: dict, key: str) -> dict:
    """Безопасный доступ к вложенному dict: возвращает {} если None"""
    return data.get(key) or {}


def format_date(value):
    """Форматирует timestamp или строку в дату, или N/A"""
    if not value:
        return 'N/A'
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000).strftime('%Y-%m-%d')
        return str(value)
    except:
        return 'N/A'


def check_inn(inn: str) -> dict:
    """Запрос к DaData API через библиотеку для проверки ИНН"""
    dadata = Dadata(DADATA_API_KEY)  # Создаём клиент
    try:
        results = dadata.find_by_id(name="party", query=inn)
        dadata.close()
        if results:
            return results[0]['data']  # Возвращаем data первого совпадения
        else:
            return {'error': 'Компания не найдена по ИНН'}
    except Exception as e:
        dadata.close()
        logger.error(f'Ошибка DaData API: {e}')
        return {'error': f'Ошибка запроса к API: {str(e)[:100]} (проверьте ключ)'}


def assess_risks(company_data: dict) -> tuple[str, str]:
    """Оценка рисков на основе данных компании"""
    if 'error' in company_data:
        return 'Неизвестно', company_data['error']

    state_dict = safe_subdict(company_data, 'state')
    status = state_dict.get('status', 'UNKNOWN')
    invalid = company_data.get('invalid', False)

    # Founders: list или None → []
    founders = company_data.get('founders') or []
    has_invalid_founder = any((f or {}).get('invalidity', False) for f in founders)

    # Management: dict или None → {}
    management = safe_subdict(company_data, 'management')
    has_invalid_manager = management.get('invalidity', False)

    if status != 'ACTIVE':
        risk_level = 'Высокий'
        reason = f'Статус: {status} (не активна)'
    elif invalid or has_invalid_founder or has_invalid_manager:
        risk_level = 'Средний'
        reason = 'Есть недостоверные данные (учредители, руководство или адрес)'
    else:
        risk_level = 'Низкий'
        reason = 'Нет признаков рисков'

    return risk_level, reason


def format_company_info(company_data: dict) -> str:
    """Форматирование отчёта о компании"""
    if 'error' in company_data:
        return f"❌ Ошибка: {company_data['error']}"

    info = []
    info.append("🏢 **Реквизиты компании:**")

    # Name: dict или None → safe
    name_dict = safe_subdict(company_data, 'name')
    info.append(f"📛 Название: {name_dict.get('full_with_opf', 'N/A')}")

    info.append(f"🆔 ИНН: {company_data.get('inn', 'N/A')}")

    # OGRN date: safe format
    ogrn_date = format_date(company_data.get('ogrn_date'))
    info.append(f"🆔 ОГРН: {company_data.get('ogrn', 'N/A')} ({ogrn_date})")

    # Address: dict или None → safe
    address_dict = safe_subdict(company_data, 'address')
    info.append(f"📍 Адрес: {address_dict.get('value', 'N/A')}")

    # State: dict или None → safe
    state_dict = safe_subdict(company_data, 'state')
    reg_date = format_date(state_dict.get('registration_date'))
    info.append(f"📊 Статус: {state_dict.get('status', 'N/A')} (с {reg_date})")

    # Management: dict или None → safe
    management = safe_subdict(company_data, 'management')
    if management.get('name') or management.get('ceo'):  # Проверяем наличие данных
        start_date = format_date(management.get('start_date'))
        post = management.get('post', 'N/A')
        name_ceo = management.get('name') or management.get('ceo', 'N/A')
        info.append(f"👤 Руководитель: {name_ceo} ({post}, с {start_date})")

    # Founders: list или None → [] , первые 2
    founders = company_data.get('founders') or []
    if founders:
        info.append("👥 **Учредители:**")
        for f in founders[:2]:
            f_safe = f or {}
            f_name = f_safe.get('name', 'N/A')
            share_dict = safe_subdict(f_safe, 'share')
            share = share_dict.get('value', 0)
            info.append(f"   - {f_name} (доля: {share}%)")
        if len(founders) > 2:
            info.append(f"   ... и ещё {len(founders) - 2}")

    # Риски
    risk_level, reason = assess_risks(company_data)
    info.append(f"\n⚠️ **Уровень риска: {risk_level}**")
    info.append(f"   Причина: {reason}")

    return '\n'.join(info)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    keyboard = [['/check']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        'Привет! Я бот для проверки контрагента по ИНН.\n'
        'Нажми /check, чтобы начать проверку.',
        reply_markup=reply_markup
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /check"""
    await update.message.reply_text('Введите ИНН компании (10 или 12 цифр):')


async def handle_inn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщения с ИНН"""
    inn = update.message.text.strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        await update.message.reply_text('❌ Неверный формат ИНН. Введите 10 или 12 цифр.')
        return

    await update.message.reply_text('🔄 Проверяю... Это может занять несколько секунд.')

    try:
        company_data = check_inn(inn)
        report = format_company_info(company_data)
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        logger.error(f'Ошибка в handle_inn: {type(e).__name__}: {e}')
        await update.message.reply_text('❌ Произошла ошибка при обработке. Попробуйте позже или проверьте ИНН.')


def main():
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('check', check_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inn))

    # Глобальный error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.warning(f'Update {update} caused error {context.error}')
        # Опционально: отправить админу уведомление

    application.add_error_handler(error_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()