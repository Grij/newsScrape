import os
import json
import logging
from datetime import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from http.server import BaseHTTPRequestHandler

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL = "https://babel.ua/news"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
BATCH_SIZE = 10

def перевірити_змінні_середовища():
    creds = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    logging.info(f"GOOGLE_APPLICATION_CREDENTIALS: {'Встановлено' if creds else 'Не встановлено'}")
    if creds:
        logging.info(f"Довжина GOOGLE_APPLICATION_CREDENTIALS: {len(creds)}")
    
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    logging.info(f"SPREADSHEET_ID: {spreadsheet_id if spreadsheet_id else 'Не встановлено'}")

async def отримати_вміст_сторінки(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                return await response.text()
        except Exception as e:
            logging.error(f"Помилка отримання сторінки: {e}")
            return None

def розібрати_статті(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    articles = soup.select("div.c-entry-content-box")
    parsed_articles = []
    for article in articles:
        link = article.select_one("h3.c-entry-title a")
        if link:
            url = link['href']
            title = link.text.strip()
            parsed_articles.append({'url': url, 'title': title})
    logging.info(f"Розібрано {len(parsed_articles)} статей")
    return parsed_articles

async def отримати_чистий_текст(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                article_div = soup.find('div', class_='c-post-text js-article-content')
                if article_div:
                    return article_div.get_text(separator=' ', strip=True).replace('\xa0', ' ')
                return "Вміст статті не знайдено."
        except Exception as e:
            return f"Помилка обробки сторінки: {e}"

def налаштувати_sheets():
    try:
        creds_json = os.environ['GOOGLE_APPLICATION_CREDENTIALS']
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        logging.info("Успішно налаштовано сервіс Google Sheets")
        return service.spreadsheets()
    except Exception as e:
        logging.error(f"Помилка налаштування Google Sheets: {e}")
        raise

def отримати_або_створити_лист(sheet, spreadsheet_id, sheet_name):
    try:
        sheet_metadata = sheet.get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        for s in sheets:
            if s['properties']['title'] == sheet_name:
                logging.info(f"Лист '{sheet_name}' вже існує")
                return
        
        logging.info(f"Лист '{sheet_name}' не знайдено. Створюємо його.")
        body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }]
        }
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    except HttpError as error:
        logging.error(f"Виникла помилка: {error}")
        raise

def налаштувати_випадаючий_список(sheet, spreadsheet_id):
    try:
        sheet_id = 0  # ID листа "Articles"
        body = {
            "requests": [
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 1,
                            "endColumnIndex": 2
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "Неопубліковано"},
                                    {"userEnteredValue": "Опубліковано"},
                                    {"userEnteredValue": "Забраковано"},
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                }
            ]
        }
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        logging.info("Випадаючий список для колонки статусу успішно налаштовано")
    except HttpError as error:
        logging.error(f"Виникла помилка при налаштуванні випадаючого списку: {error}")
        raise

def отримати_оброблені_статті(sheet, spreadsheet_id):
    try:
        отримати_або_створити_лист(sheet, spreadsheet_id, 'ProcessedArticles')
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:C').execute()
        processed = set(row[2] for row in result.get('values', [])[1:])  # Пропустити заголовок
        logging.info(f"Отримано {len(processed)} оброблених статей")
        return processed
    except HttpError as error:
        logging.error(f"Виникла помилка при отриманні оброблених статей: {error}")
        raise

async def зберегти_статті_в_лист(sheet, spreadsheet_id, articles, is_initial=False):
    try:
        отримати_або_створити_лист(sheet, spreadsheet_id, 'Articles')
        отримати_або_створити_лист(sheet, spreadsheet_id, 'ProcessedArticles')
        
        values = [["Заголовок", "Статус", "Посилання", "Текст", "Релевантність"]] if is_initial else []
        for article in articles:
            text = await отримати_чистий_текст(article['url'])
            values.append([article['title'], "Неопубліковано", article['url'], text, ""])
        
        body = {'values': values}
        range_name = 'Articles!A1' if is_initial else 'Articles!A1:E1'
        if is_initial:
            sheet.values().clear(spreadsheetId=spreadsheet_id, range='Articles!A:E').execute()
            sheet.values().clear(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:C').execute()
        
        logging.info(f"Спроба вставки {len(values)} рядків даних")
        logging.debug(f"Перший рядок даних: {values[0] if values else 'Немає даних'}")
        
        result = sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        # Оновити лист ProcessedArticles
        processed_values = [[article['title'], "Неопубліковано", article['url']] for article in articles]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range='ProcessedArticles!A1',
            valueInputOption='USER_ENTERED',
            body={'values': processed_values}
        ).execute()
        
        logging.info(f"Додано {len(articles)} статей до листа")
        return result.get('updates').get('updatedCells')
    except HttpError as error:
        logging.error(f"Виникла помилка при збереженні статей: {error}")
        raise

async def скрапінг(is_initial_scrape=False):
    start_time = datetime.now()
    logging.info(f"{'Початковий' if is_initial_scrape else 'Регулярний'} скрапінг розпочато.")
    
    перевірити_змінні_середовища()
    
    try:
        sheet = налаштувати_sheets()
        spreadsheet_id = os.environ.get('SPREADSHEET_ID')
        if not spreadsheet_id:
            raise ValueError("Змінна середовища SPREADSHEET_ID не встановлена")
        
        html_content = await отримати_вміст_сторінки(URL)
        if not html_content:
            return json.dumps({"error": "Не вдалося отримати вміст сторінки"})

        articles = розібрати_статті(html_content)

        if is_initial_scrape:
            updated_cells = await зберегти_статті_в_лист(sheet, spreadsheet_id, articles, is_initial=True)
            налаштувати_випадаючий_список(sheet, spreadsheet_id)
            result = f"Початковий скрапінг завершено. Додано {len(articles)} статей. Оновлено {updated_cells} клітинок."
        else:
            processed_articles = отримати_оброблені_статті(sheet, spreadsheet_id)
            new_articles = [article for article in articles if article['url'] not in processed_articles]
            total_updated_cells = 0
            for i in range(0, len(new_articles), BATCH_SIZE):
                batch = new_articles[i:i+BATCH_SIZE]
                updated_cells = await зберегти_статті_в_лист(sheet, spreadsheet_id, batch)
                total_updated_cells += updated_cells
                logging.info(f"Оброблено партію {i//BATCH_SIZE + 1} з {len(new_articles)//BATCH_SIZE + 1}")
            result = f"Додано {len(new_articles)} нових статей партіями. Оновлено {total_updated_cells} клітинок."
        
        logging.info(result)
        return json.dumps({"message": result})
        
    except Exception as e:
        logging.error(f"Виникла помилка: {str(e)}")
        return json.dumps({"error": str(e)})

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/scrape'):
            try:
                is_initial_scrape = 'type=first' in self.path
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(скрапінг(is_initial_scrape))
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(result.encode())
            except Exception as e:
                error_message = json.dumps({
                    "error": str(e),
                    "details": {key: 'Встановлено' if value else 'Не встановлено' for key, value in os.environ.items() if key.startswith('GOOGLE_') or key == 'SPREADSHEET_ID'}
                })
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(error_message.encode())
        else:
            self.send_error(404)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(скрапінг(True))