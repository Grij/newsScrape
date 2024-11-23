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
      range: 'Articles!A2:E',
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('Не знайдено даних у таблиці');
    }

    let analyzedCount = 0;

    // Аналіз кожної статті
    for (const [index, row] of rows.entries()) {
      const [title, status, link, text, relevance] = row;
      
      // Пропускаємо статті, які вже мають оцінку релевантності або статус "Забраковано"
      if (relevance || status === 'Забраковано') continue;

      console.log(`Аналізуємо статтю: ${title}`);

      // Аналіз статті за допомогою Perplexity API
      const perplexityRequestBody = {
        model: 'llama-2-70b-chat',  // Оновлено на офіційно підтримувану модель
        messages: [
          { role: 'system', content: 'You are an AI assistant that analyzes article titles and provides a relevance score from 1 to 10. Also, determine if the article is related to Ukraine.' },
          { role: 'user', content: `Analyze the following article title and provide a relevance score from 1 to 10, where 10 is highly relevant to technology and innovation. Also, indicate if it's related to Ukraine: "${title}"` }
        ]
      };

      console.log('Запит до Perplexity API:', JSON.stringify(perplexityRequestBody, null, 2));

      try {
        const perplexityResponse = await fetch('https://api.perplexity.ai/chat/completions', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${process.env.PERPLEXITY_API_KEY}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(perplexityRequestBody)
        });

        if (!perplexityResponse.ok) {
          const errorBody = await perplexityResponse.text();
          throw new Error(`Помилка API Perplexity: ${perplexityResponse.status} ${perplexityResponse.statusText}\nТіло відповіді: ${errorBody}`);
        }

        const perplexityData = await perplexityResponse.json();
        console.log('Відповідь від Perplexity API:', JSON.stringify(perplexityData, null, 2));

        const aiResponse = perplexityData.choices[0].message.content;
        const relevanceScore = parseInt(aiResponse.match(/\d+/)[0]);
        const isRelatedToUkraine = aiResponse.toLowerCase().includes('related to ukraine');

        // Оновлення Google Sheets з оцінкою релевантності та статусом
        let newStatus = status;
        if (!isRelatedToUkraine) {
          newStatus = 'Забраковано';
        } else if (relevanceScore >= 8) {
          newStatus = 'Facebook';
        }

        await sheets.spreadsheets.values.update({
          spreadsheetId: process.env.SPREADSHEET_ID,
          range: `B${index + 2}:E${index + 2}`,
          valueInputOption: 'USER_ENTERED',
          resource: {
            values: [[newStatus, link, text, relevanceScore]]
          }
        });

        analyzedCount++;
        console.log(`[${new Date().toLocaleTimeString()}] Проаналізовано статтю: ${title}, Оцінка: ${relevanceScore}, Статус: ${newStatus}`);
      } catch (error) {
        console.error(`Помилка при аналізі статті "${title}":`, error);
        // Продовжуємо аналіз наступних статей
      }

      // Додаємо затримку між запитами, щоб уникнути обмежень API
      await new Promise(resolve => setTimeout(resolve, 1000));
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

module.exports = (req, res) => {
  if (req.method === 'GET') {
    analyzeArticles(req, res);
  } else {
    res.status(405).json({ error: 'Method Not Allowed' });
  }
};