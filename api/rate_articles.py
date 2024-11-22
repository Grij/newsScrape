import os
import json
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
PERPLEXITY_API_KEY = os.environ.get('PERPLEXITY_API_KEY')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

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

def get_unprocessed_articles(sheet):
    try:
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Articles!A2:D').execute()
        articles = result.get('values', [])
        unprocessed = [article for article in articles if article[1] == "Неопубліковано"]
        logging.info(f"Retrieved {len(unprocessed)} unprocessed articles")
        return unprocessed
    except HttpError as error:
        logging.error(f"An error occurred while fetching articles: {error}")
        raise

def analyze_with_perplexity(title, content):
    prompt = f"Проаналізуйте цю новину та визначте, чи вона стосується України. Заголовок: '{title}'. Зміст: '{content[:500]}...'. Дайте відповідь 'Так' або 'Ні', а потім оцініть актуальність новини для України за шкалою від 1 до 10."
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mixtral-8x7b-instruct",
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        analysis = result['choices'][0]['message']['content']
        
        is_relevant = "Так" in analysis.split()[0]
        relevance_score = int(analysis.split()[-1]) if is_relevant else 0
        
        return is_relevant, relevance_score
    except Exception as e:
        logging.error(f"Error analyzing with Perplexity: {e}")
        return False, 0

def update_article_status(sheet, row, status, facebook=False):
    try:
        range_name = f'Articles!B{row}:E{row}'
        values = [[status, None, None, "Facebook" if facebook else None]]
        body = {'values': values}
        sheet.values().update(spreadsheetId=SPREADSHEET_ID, range=range_name, valueInputOption='USER_ENTERED', body=body).execute()
        logging.info(f"Updated status for article in row {row} to {status}")
    except HttpError as error:
        logging.error(f"An error occurred while updating article status: {error}")
        raise

def process_articles():
    sheet = setup_sheets()
    articles = get_unprocessed_articles(sheet)
    
    for index, article in enumerate(articles, start=2):  # start=2 because we skip the header row
        title, _, _, content = article
        is_relevant, relevance_score = analyze_with_perplexity(title, content)
        
        if not is_relevant:
            update_article_status(sheet, index, "Забраковано")
        elif relevance_score >= 8:  # Припустимо, що 8 і вище - це "супер актуально"
            update_article_status(sheet, index, "Опубліковано", facebook=True)
        else:
            update_article_status(sheet, index, "Опубліковано")

if __name__ == "__main__":
    process_articles()
