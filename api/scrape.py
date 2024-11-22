import sys
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

def log_info(message):
    print(f"INFO: {message}", file=sys.stdout)

def log_error(error_message):
    print(f"ERROR: {error_message}", file=sys.stderr)

def get_google_sheets_service():
    try:
        log_info("Initializing Google Sheets service")
        creds_dict = json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        log_error(f"Error initializing Google Sheets service: {str(e)}")
        raise

def fetch_page_content(url):
    try:
        log_info(f"Fetching content from {url}")
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        log_error(f"Error fetching page: {str(e)}")
        return None

def parse_articles(html_content):
    try:
        log_info("Parsing articles")
        soup = BeautifulSoup(html_content, 'html.parser')
        articles = soup.select("div.c-entry-content-box")
        parsed_articles = []
        for article in articles:
            link = article.select_one("h3.c-entry-title a")
            if link:
                url = link['href']
                title = link.text.strip()
                parsed_articles.append({'url': url, 'title': title})
        log_info(f"Parsed {len(parsed_articles)} articles")
        return parsed_articles
    except Exception as e:
        log_error(f"Error parsing articles: {str(e)}")
        raise

def get_clean_text(url):
    try:
        log_info(f"Getting clean text from {url}")
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        article_div = soup.find('div', class_='c-post-text js-article-content')
        if article_div:
            text = article_div.get_text(separator=' ', strip=True).replace('\xa0', ' ')
            return text
        else:
            log_error("Article content not found")
            return "Article content not found."
    except requests.exceptions.RequestException as e:
        log_error(f"Error downloading page: {str(e)}")
        return f"Error downloading page: {str(e)}"
    except Exception as e:
        log_error(f"Error processing page: {str(e)}")
        return f"Error processing page: {str(e)}"

def create_new_sheet(service, spreadsheet_id):
    try:
        log_info("Creating new sheet")
        today = datetime.now().strftime("%d%m%Y")
        sheet_name = f"{today}_babel"
        
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
        log_info(f"Created new sheet: {sheet_name}")
        return sheet_name
    except Exception as e:
        log_error(f"Error creating new sheet: {str(e)}")
        return None

def append_to_sheet(service, spreadsheet_id, sheet_name, values):
    try:
        log_info(f"Appending {len(values)} rows to sheet {sheet_name}")
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:D",
            body={"values": values},
            valueInputOption="USER_ENTERED"
        ).execute()
        log_info("Append operation completed")
    except Exception as e:
        log_error(f"Error appending to sheet: {str(e)}")
        raise

def get_processed_articles(service, spreadsheet_id):
    try:
        log_info("Getting processed articles")
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="ProcessedArticles!A:A"
        ).execute()
        processed = set(row[0] for row in result.get('values', [])[1:])
        log_info(f"Retrieved {len(processed)} processed articles")
        return processed
    except Exception as e:
        log_error(f"Error getting processed articles: {str(e)}")
        return set()

def fetch_and_save_news(service, spreadsheet_id):
    try:
        log_info("Starting fetch_and_save_news")
        html_content = fetch_page_content(URL)
        if not html_content:
            log_error("Failed to fetch page content")
            return

        articles = parse_articles(html_content)
        processed_articles = get_processed_articles(service, spreadsheet_id)

        new_articles = [article for article in articles if article['url'] not in processed_articles]
        log_info(f"Found {len(new_articles)} new articles")

        if new_articles:
            sheet_name = create_new_sheet(service, spreadsheet_id)
            if not sheet_name:
                log_error("Failed to create new sheet")
                return

            values = [["Заголовок", "Статус", "Посилання", "Текст"]]
            for article in new_articles:
                log_info(f"Processing article: {article['url']}")
                text = get_clean_text(article['url'])
                values.append([article['title'], "Неопубліковано", article['url'], text])

            append_to_sheet(service, spreadsheet_id, sheet_name, values)
            append_to_sheet(service, spreadsheet_id, "ProcessedArticles", [[article['url']] for article in new_articles])

            log_info(f"Added {len(new_articles)} new articles")
        else:
            log_info("No new articles found.")
    except Exception as e:
        log_error(f"Error in fetch_and_save_news: {str(e)}")
        raise

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            log_info("Starting serverless function execution")
            service = get_google_sheets_service()
            fetch_and_save_news(service, SPREADSHEET_ID)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write('Scraping completed'.encode())
            log_info("Serverless function execution completed successfully")
        except Exception as e:
            log_error(f"An error occurred in handler: {str(e)}")
            self.send_error(500, f"Internal Server Error: {str(e)}")
        return

if __name__ == "__main__":
    log_info(f"Script started")
    try:
        service = get_google_sheets_service()
        fetch_and_save_news(service, SPREADSHEET_ID)
        log_info("Script completed successfully")
    except Exception as e:
        log_error(f"Script failed: {str(e)}")
