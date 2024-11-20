import requests
from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
import os
from http.server import BaseHTTPRequestHandler

# Константи
URL = "https://babel.ua/news"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

def get_google_sheets_service():
    creds_dict = json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

def fetch_page_content(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
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

def create_new_sheet(service, spreadsheet_id):
    today = datetime.now().strftime("%d%m%Y")
    sheet_name = f"{today}_babel"
    
    try:
        request = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name
                    }
                }
            }]
        })
        request.execute()
        return sheet_name
    except Exception as e:
        print(f"Error creating new sheet: {e}")
        return None

def append_to_sheet(service, spreadsheet_id, sheet_name, values):
    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:D",
            body={"values": values},
            valueInputOption="USER_ENTERED"
        ).execute()
    except Exception as e:
        print(f"Error appending to sheet: {e}")

def get_processed_articles(service, spreadsheet_id):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="ProcessedArticles!A:A"
        ).execute()
        return set(row[0] for row in result.get('values', [])[1:])
    except Exception as e:
        print(f"Error getting processed articles: {e}")
        return set()

def fetch_and_save_news(service, spreadsheet_id):
    html_content = fetch_page_content(URL)
    if not html_content:
        return

    articles = parse_articles(html_content)
    processed_articles = get_processed_articles(service, spreadsheet_id)

    new_articles = [article for article in articles if article['url'] not in processed_articles]

    if new_articles:
        sheet_name = create_new_sheet(service, spreadsheet_id)
        if not sheet_name:
            return

        values = [["Заголовок", "Статус", "Посилання", "Текст"]]
        for article in new_articles:
            text = get_clean_text(article['url'])
            values.append([article['title'], "Неопубліковано", article['url'], text])

        append_to_sheet(service, spreadsheet_id, sheet_name, values)

        # Додавання нових URL до списку оброблених статей
        append_to_sheet(service, spreadsheet_id, "ProcessedArticles", [[article['url']] for article in new_articles])

        print(f"Added {len(new_articles)} new articles")
    else:
        print("No new articles found.")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        service = get_google_sheets_service()
        fetch_and_save_news(service, SPREADSHEET_ID)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write('Scraping completed'.encode())
        return
