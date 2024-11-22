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

def check_env_vars():
    creds = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    logging.info(f"GOOGLE_APPLICATION_CREDENTIALS: {'Set' if creds else 'Not set'}")
    if creds:
        logging.info(f"Length of GOOGLE_APPLICATION_CREDENTIALS: {len(creds)}")
    
    spreadsheet_id = os.getenv('SPREADSHEET_ID')
    logging.info(f"SPREADSHEET_ID: {'Set' if spreadsheet_id else 'Not set'}")

def get_articles():
    url = "https://babel.ua/texts"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all('article', class_='article-card')
        
        parsed_articles = []
        for article in articles:
            title = article.find('h3', class_='article-card__title').text.strip()
            link = "https://babel.ua" + article.find('a', class_='article-card__link')['href']
            parsed_articles.append((title, link))
        
        logging.info(f"Found {len(parsed_articles)} articles")
        return parsed_articles
    except requests.RequestException as e:
        logging.error(f"Error fetching articles: {str(e)}")
        return []

def setup_sheets():
    try:
        creds_json = os.environ['GOOGLE_APPLICATION_CREDENTIALS']
    except KeyError:
        logging.error("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set")
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set")
    
    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in GOOGLE_APPLICATION_CREDENTIALS: {str(e)}")
        raise ValueError(f"Invalid JSON in GOOGLE_APPLICATION_CREDENTIALS: {str(e)}")
    
    try:
        service = build('sheets', 'v4', credentials=creds)
        logging.info("Successfully set up Google Sheets service")
        return service.spreadsheets()
    except HttpError as error:
        logging.error(f"An error occurred while setting up Google Sheets: {error}")
        raise Exception(f"An error occurred while setting up Google Sheets: {error}")

def get_processed_articles(sheet):
    spreadsheet_id = os.getenv('SPREADSHEET_ID')
    if not spreadsheet_id:
        logging.error("SPREADSHEET_ID environment variable is not set")
        raise ValueError("SPREADSHEET_ID environment variable is not set")
    
    try:
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:B').execute()
        processed = set(tuple(row) for row in result.get('values', []))
        logging.info(f"Retrieved {len(processed)} processed articles")
        return processed
    except HttpError as error:
        logging.error(f"An error occurred while fetching processed articles: {error}")
        raise Exception(f"An error occurred while fetching processed articles: {error}")

def add_new_articles(sheet, new_articles):
    spreadsheet_id = os.getenv('SPREADSHEET_ID')
    if not spreadsheet_id:
        logging.error("SPREADSHEET_ID environment variable is not set")
        raise ValueError("SPREADSHEET_ID environment variable is not set")
    
    try:
        body = {
            'values': [[title, link, str(datetime.now())] for title, link in new_articles]
        }
        result = sheet.values().append(
            spreadsheetId=spreadsheet_id, range='Articles!A:C',
            valueInputOption='USER_ENTERED', body=body).execute()
        logging.info(f"{result.get('updates').get('updatedCells')} cells appended.")
        
        # Додавання нових статей до списку оброблених
        body = {
            'values': [[title, link] for title, link in new_articles]
        }
        sheet.values().append(
            spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:B',
            valueInputOption='USER_ENTERED', body=body).execute()
        logging.info(f"Added {len(new_articles)} new articles to ProcessedArticles")
        
    except HttpError as error:
        logging.error(f"An error occurred while adding new articles: {error}")
        raise Exception(f"An error occurred while adding new articles: {error}")

def scrape():
    start_time = datetime.now()
    logging.info("Script started.")
    
    check_env_vars()
    
    try:
        sheet = setup_sheets()
        processed_articles = get_processed_articles(sheet)
        current_articles = get_articles()
        
        new_articles = [article for article in current_articles if article not in processed_articles]
        
        if new_articles:
            add_new_articles(sheet, new_articles)
            logging.info(f"Added {len(new_articles)} new articles.")
        else:
            logging.info("No new articles found.")
        
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        return f"Error: {str(e)}"
    
    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()
    logging.info(f"Script finished. Execution time: {execution_time:.2f} seconds.")
    return f"Script completed successfully. Execution time: {execution_time:.2f} seconds."

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/scrape':
            try:
                result = scrape()
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(result.encode())
            except Exception as e:
                error_message = f"An error occurred: {str(e)}\n"
                error_message += f"Environment variables:\n"
                for key, value in os.environ.items():
                    if key.startswith('GOOGLE_') or key == 'SPREADSHEET_ID':
                        error_message += f"{key}: {'Set' if value else 'Not set'}\n"
                self.send_error(500, error_message)
        else:
            self.send_error(404)

if __name__ == "__main__":
    scrape()
