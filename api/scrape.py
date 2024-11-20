 from http.server import BaseHTTPRequestHandlerfrom http.server import BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
import os

# Константи
URL = "https://babel.ua/news"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

def get_google_sheets_service():
    creds_dict = json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

# Інші функції (fetch_page_content, parse_articles, get_clean_text, create_new_sheet, append_to_sheet, get_processed_articles) залишаються такими ж, як у попередньому прикладі

def fetch_and_save_news(service, spreadsheet_id):
    # Логіка fetch_and_save_news залишається такою ж, як у попередньому прикладі

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        service = get_google_sheets_service()
        fetch_and_save_news(service, SPREADSHEET_ID)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write('Scraping completed'.encode())
        return
