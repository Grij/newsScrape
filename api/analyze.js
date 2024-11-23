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

    console.log('Отримання даних з Google Sheets...');
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: 'Articles!A2:E',
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('Не знайдено даних у таблиці');
    }

    console.log(`Знайдено ${rows.length} рядків для аналізу`);

    let analyzedCount = 0;

    for (const [index, row] of rows.entries()) {
      if (!Array.isArray(row) || row.length < 5) {
        console.warn(`Пропущено некоректний рядок з індексом ${index}`);
        continue;
      }

      const [title, status, link, text, relevance] = row;
      
      if (relevance || status === 'Забраковано') {
        console.log(`Пропущено статтю "${title}" (вже оброблена або забракована)`);
        continue;
      }

      console.log(`Аналізуємо статтю: "${title}"`);

      const perplexityRequestBody = {
        model: "llama-3.1-sonar-small-128k-online",
        messages: [
          { role: "system", content: "You are an AI assistant that analyzes article titles and provides a relevance score from 1 to 10. Also, determine if the article is related to Ukraine." },
          { role: "user", content: `Analyze the following article title and provide a relevance score from 1 to 10, where 10 is highly relevant to technology and innovation. Also, indicate if it's related to Ukraine: "${title}"` }
        ],
        temperature: 0.2,
        top_p: 0.9,
        max_tokens: 150
      };

      try {
        console.log('Відправка запиту до Perplexity API...');
        const perplexityResponse = await fetch('https://api.perplexity.ai/chat/completions', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${process.env.PERPLEXITY_API_KEY}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(perplexityRequestBody)
        });

        if (!perplexityResponse.ok) {
          const errorText = await perplexityResponse.text();
          console.error("Perplexity API error:", perplexityResponse.status, perplexityResponse.statusText, errorText);
          throw new Error(`Помилка API Perplexity: ${perplexityResponse.status} ${perplexityResponse.statusText}\nТіло відповіді: ${errorText}`);
        }

        const responseData = await perplexityResponse.json();
        console.log('Відповідь від Perplexity API:', JSON.stringify(responseData, null, 2));

        const aiResponse = responseData.choices[0].message.content;
        const relevanceScore = parseInt(aiResponse.match(/\d+/)[0]) || 0;
        const isRelatedToUkraine = aiResponse.toLowerCase().includes('related to ukraine');

        let newStatus = status;
        if (!isRelatedToUkraine) {
          newStatus = 'Забраковано';
        } else if (relevanceScore >= 8) {
          newStatus = 'Facebook';
        }

        console.log(`Оновлення Google Sheets для статті "${title}"...`);
        await sheets.spreadsheets.values.update({
          spreadsheetId: process.env.SPREADSHEET_ID,
          range: `B${index + 2}:E${index + 2}`,
          valueInputOption: 'USER_ENTERED',
          resource: {
            values: [[newStatus, link, text, relevanceScore]]
          }
        });

        analyzedCount++;
        console.log(`[${new Date().toLocaleTimeString()}] Проаналізовано статтю: "${title}", Оцінка: ${relevanceScore}, Статус: ${newStatus}`);
      } catch (error) {
        console.error(`Помилка при аналізі статті "${title}":`, error);
      }

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