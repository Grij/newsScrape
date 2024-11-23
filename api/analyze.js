const { google } = require('googleapis');
const fetch = require('node-fetch');

function getAuthClient() {
  try {
    const credentials = JSON.parse(process.env.GOOGLE_APPLICATION_CREDENTIALS);
    return new google.auth.JWT(
      credentials.client_email,
      null,
      credentials.private_key,
      ['https://www.googleapis.com/auth/spreadsheets']
    );
  } catch (error) {
    console.error('Помилка при створенні auth клієнта:', error);
    throw error;
  }
}

async function analyzeArticles(req, res) {
  console.log('[' + new Date().toLocaleTimeString() + '] Початок аналізу статей...');
  const startTime = Date.now();

  try {
    const auth = getAuthClient();
    const sheets = google.sheets({ version: 'v4', auth });

    // Отримання даних з Google Sheets
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: 'A2:E', // Припускаємо, що дані починаються з другого рядка
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('Не знайдено даних у таблиці');
    }

    let analyzedCount = 0;

    // Аналіз кожної статті
    for (const row of rows) {
      const [date, title, link, status, relevance] = row;
      
      // Пропускаємо статті, які вже мають оцінку релевантності або статус "Rejected"
      if (relevance || status === 'Rejected') continue;

      // Аналіз статті за допомогою Perplexity API
      const perplexityResponse = await fetch('https://api.perplexity.ai/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.PERPLEXITY_API_KEY}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model: 'mistral-7b-instruct',
          messages: [
            { role: 'system', content: 'You are an AI assistant that analyzes article titles and provides a relevance score from 1 to 10.' },
            { role: 'user', content: `Analyze the following article title and provide a relevance score from 1 to 10, where 10 is highly relevant to technology and innovation: "${title}"` }
          ]
        })
      });

      if (!perplexityResponse.ok) {
        throw new Error(`Помилка API Perplexity: ${perplexityResponse.statusText}`);
      }

      const perplexityData = await perplexityResponse.json();
      const relevanceScore = parseInt(perplexityData.choices[0].message.content);

      // Оновлення Google Sheets з оцінкою релевантності
      await sheets.spreadsheets.values.update({
        spreadsheetId: process.env.SPREADSHEET_ID,
        range: `E${rows.indexOf(row) + 2}`, // +2 because rows are 0-indexed and we start from the second row
        valueInputOption: 'USER_ENTERED',
        resource: {
          values: [[relevanceScore]]
        }
      });

      analyzedCount++;
      console.log(`[${new Date().toLocaleTimeString()}] Проаналізовано статтю: ${title}, Оцінка: ${relevanceScore}`);
    }

    const endTime = Date.now();
    const executionTime = (endTime - startTime) / 1000;
    const message = `Аналіз завершено. Проаналізовано статей: ${analyzedCount}. Загальний час виконання: ${executionTime.toFixed(2)} секунд`;
    console.log(`[${new Date().toLocaleTimeString()}] ${message}`);

    res.status(200).json({ message, executionTime, analyzedCount });
  } catch (error) {
    console.error(`[${new Date().toLocaleTimeString()}] Помилка:`, error);
    res.status(500).json({ error: 'An error occurred while processing articles', details: error.message });
  }
}

module.exports = analyzeArticles;