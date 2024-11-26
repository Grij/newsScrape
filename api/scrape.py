import os
import json
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from http.server import BaseHTTPRequestHandler

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL = "https://babel.ua/news"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def check_env_vars():
    creds = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    logging.info(f"GOOGLE_APPLICATION_CREDENTIALS: {'Set' if creds else 'Not set'}")
    if creds:
        logging.info(f"Length of GOOGLE_APPLICATION_CREDENTIALS: {len(creds)}")
    
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    logging.info(f"SPREADSHEET_ID: {spreadsheet_id if spreadsheet_id else 'Not set'}")

def fetch_page_content(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching page: {e}")
        return None

def parse_articles(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    articles = soup.select("div.c-entry-content-box")
    parsed_articles = []
    for article in articles:
        link = article.select_one("h3.c-entry-title a")
        if link:
            url = link['href']
            title = link.text.strip()
            parsed_articles.append({'url': url, 'title': title})
    logging.info(f"Parsed {len(parsed_articles)} articles")
    return parsed_articles

def get_clean_text(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        article_div = soup.find('div', class_='c-post-text js-article-content')
        if article_div:
            text = article_div.get_text(separator=' ', strip=True).replace('\xa0', ' ')
            return text
        else:
            return "Article content not found."
    except requests.exceptions.RequestException as e:
        return f"Error downloading page: {e}"
    except Exception as e:
        return f"Error processing page: {e}"

def setup_sheets():
    try:
        creds_json = os.environ['GOOGLE_APPLICATION_CREDENTIALS']
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        logging.info("Successfully set up Google Sheets service")
        return service.spreadsheets()
    except Exception as e:
        logging.error(f"Error setting up Google Sheets: {e}")
        raise

def get_or_create_sheet(sheet, spreadsheet_id, sheet_name):
    try:
        sheet_metadata = sheet.get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        for s in sheets:
            if s['properties']['title'] == sheet_name:
                logging.info(f"Sheet '{sheet_name}' already exists")
                return
        
        logging.info(f"Sheet '{sheet_name}' not found. Creating it.")
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
        logging.error(f"An error occurred: {error}")
        raise

def setup_dropdown(sheet, spreadsheet_id):
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
        logging.info("Dropdown for status column set up successfully")
    except HttpError as error:
        logging.error(f"An error occurred while setting up dropdown: {error}")
        raise

def get_processed_articles(sheet, spreadsheet_id):
    try:
        get_or_create_sheet(sheet, spreadsheet_id, 'ProcessedArticles')
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:C').execute()
        processed = set(row[2] for row in result.get('values', [])[1:])  # Skip header
        logging.info(f"Retrieved {len(processed)} processed articles")
        return processed
    except HttpError as error:
        logging.error(f"An error occurred while fetching processed articles: {error}")
        raise

def save_articles_to_sheet(sheet, spreadsheet_id, articles, is_initial=False):
    try:
        get_or_create_sheet(sheet, spreadsheet_id, 'Articles')
        get_or_create_sheet(sheet, spreadsheet_id, 'ProcessedArticles')
        
        values = [["Заголовок", "Статус", "Посилання", "Текст", "Релевантність"]] if is_initial else []
        for article in articles:
            text = get_clean_text(article['url'])
            values.append([article['title'], "Неопубліковано", article['url'], text, ""])
        
        body = {'values': values}
        range_name = 'Articles!A1' if is_initial else 'Articles!A1:E1'
        if is_initial:
            sheet.values().clear(spreadsheetId=spreadsheet_id, range='Articles!A:E').execute()
            sheet.values().clear(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:C').execute()
        
        result = sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        # Update ProcessedArticles sheet
        processed_values = [[article['title'], "Неопубліковано", article['url']] for article in articles]
        sheet.values().append(
            spreadsheetId=spreadsheet_id,
            range='ProcessedArticles!A1',
            valueInputOption='USER_ENTERED',
            body={'values': processed_values}
        ).execute()
        
        logging.info(f"Added {len(articles)} articles to the sheet")
        return result.get('updates').get('updatedCells')
    except HttpError as error:
        logging.error(f"An error occurred while saving articles: {error}")
        raise

def scrape(is_initial_scrape=False):
    start_time = datetime.now()
    logging.info(f"{'Initial' if is_initial_scrape else 'Regular'} scraping started.")
    
    check_env_vars()
    
    try:
        sheet = setup_sheets()
        spreadsheet_id = os.environ.get('SPREADSHEET_ID')
        if not spreadsheet_id:
            raise ValueError("SPREADSHEET_ID environment variable is not set")
        
        html_content = fetch_page_content(URL)
        if not html_content:
            return json.dumps({"error": "Failed to fetch page content"})

        articles = parse_articles(html_content)

        if is_initial_scrape:
            updated_cells = save_articles_to_sheet(sheet, spreadsheet_id, articles, is_initial=True)
            setup_dropdown(sheet, spreadsheet_id)
            result = f"Initial scraping completed. Added {len(articles)} articles. Updated {updated_cells} cells."
        else:
            processed_articles = get_processed_articles(sheet, spreadsheet_id)
            new_articles = [article for article in articles if article['url'] not in processed_articles]
            if new_articles:
                updated_cells = save_articles_to_sheet(sheet, spreadsheet_id, new_articles)
                result = f"Added {len(new_articles)} new articles. Updated {updated_cells} cells."
            else:
                result = "No new articles found."
        
        logging.info(result)
        return json.dumps({"message": result})
        
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        return json.dumps({"error": str(e)})

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/scrape'):
            try:
                is_initial_scrape = 'type=first' in self.path
                result = scrape(is_initial_scrape)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(result.encode())
            except Exception as e:
                error_message = json.dumps({
                    "error": str(e),
                    "details": {key: 'Set' if value else 'Not set' for key, value in os.environ.items() if key.startswith('GOOGLE_') or key == 'SPREADSHEET_ID'}
                })
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(error_message.encode())
        else:
            self.send_error(404)

if __name__ == "__main__":
    print(scrape(True))