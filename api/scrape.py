import os
import json
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_articles():
    url = "https://babel.ua/texts"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    articles = soup.find_all('article', class_='article-card')
    
    parsed_articles = []
    for article in articles:
        title = article.find('h3', class_='article-card__title').text.strip()
        link = "https://babel.ua" + article.find('a', class_='article-card__link')['href']
        parsed_articles.append((title, link))
    
    return parsed_articles

def setup_sheets():
    creds_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not creds_json:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set")
    
    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON in GOOGLE_APPLICATION_CREDENTIALS")
    
    try:
        service = build('sheets', 'v4', credentials=creds)
        return service.spreadsheets()
    except HttpError as error:
        raise Exception(f"An error occurred while setting up Google Sheets: {error}")

def get_processed_articles(sheet):
    spreadsheet_id = os.getenv('SPREADSHEET_ID')
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID environment variable is not set")
    
    try:
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range='ProcessedArticles!A:B').execute()
        return set(tuple(row) for row in result.get('values', []))
    except HttpError as error:
        raise Exception(f"An error occurred while fetching processed articles: {error}")

def add_new_articles(sheet, new_articles):
    spreadsheet_id = os.getenv('SPREADSHEET_ID')
    if not spreadsheet_id:
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
        
    except HttpError as error:
        raise Exception(f"An error occurred while adding new articles: {error}")

def main():
    start_time = datetime.now()
    logging.info("Script started.")
    
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
    
    end_time = datetime.now()
    execution_time = (end_time - start_time).total_seconds()
    logging.info(f"Script finished. Execution time: {execution_time:.2f} seconds.")

if __name__ == "__main__":
    main()
