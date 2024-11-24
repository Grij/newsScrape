const { google } = require('googleapis');
const fetch = require('node-fetch');

const MAX_EXECUTION_TIME_MS = 50000; // 50 seconds
const PERPLEXITY_API_URL = 'https://api.perplexity.ai/chat/completions';
const ARTICLES_RANGE = 'Articles!A2:F';

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
    console.error('Error creating auth client:', error);
    throw new Error('Authentication failed');
  }
}

async function analyzeArticle(sheets, row, index, perplexityApiKey) {
  const [title, status, link, text, relevance, score] = row;

  if (status !== 'Неопубліковано') {
    console.log(`Skipped article "${title}" (status is not "Неопубліковано")`);
    return;
  }

  console.log(`Analyzing article: "${title}"`);

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
    console.log('Sending request to Perplexity API...');
    const perplexityResponse = await fetch(PERPLEXITY_API_URL, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${perplexityApiKey}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(perplexityRequestBody),
      timeout: 10000 // 10-second timeout for Perplexity API
    });

    if (!perplexityResponse.ok) {
      const errorText = await perplexityResponse.text();
      throw new Error(`Perplexity API error: ${perplexityResponse.status} ${perplexityResponse.statusText}\nResponse body: ${errorText}`);
    }

    const responseData = await perplexityResponse.json();
    console.log('Response from Perplexity API:', JSON.stringify(responseData, null, 2));

    const aiResponse = responseData.choices[0].message.content;
    const relevanceScoreMatch = aiResponse.match(/\d+/);
    const relevanceScore = relevanceScoreMatch ? parseInt(relevanceScoreMatch[0]) : 0;
    const isRelatedToUkraine = aiResponse.toLowerCase().includes('related to ukraine');

    let newStatus = 'Неопубліковано';
    if (!isRelatedToUkraine || relevanceScore < 3) {
      newStatus = 'Забраковано';
    } else if (relevanceScore >= 8) {
      newStatus = 'Facebook';
    }

    console.log(`Updating Google Sheets for article "${title}"...`);
    await sheets.spreadsheets.values.update({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: `B${index + 2}:F${index + 2}`,
      valueInputOption: 'USER_ENTERED',
      resource: {
        values: [[newStatus, link || '', text || '', relevance || '', relevanceScore]]
      }
    });

    console.log(`[${new Date().toLocaleTimeString()}] Analyzed article: "${title}", Score: ${relevanceScore}, Status: ${newStatus}`);
  } catch (error) {
    console.error(`Error analyzing article "${title}":`, error);
    try {
      await sheets.spreadsheets.values.update({
        spreadsheetId: process.env.SPREADSHEET_ID,
        range: `B${index + 2}:F${index + 2}`,
        valueInputOption: 'USER_ENTERED',
        resource: {
          values: [['Помилка аналізу', link || '', text || '', relevance || '', `Error: ${error.message}`]]
        }
      });
    } catch (updateError) {
      console.error("Failed to update error status:", updateError);
    }
  }
}

async function analyzeArticles(req, res) {
  console.log('[' + new Date().toLocaleTimeString() + '] Starting article analysis...');
  const startTime = Date.now();
  const perplexityApiKey = process.env.PERPLEXITY_API_KEY;

  try {
    const auth = getAuthClient();
    const sheets = google.sheets({ version: 'v4', auth });

    console.log('Fetching data from Google Sheets...');
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: process.env.SPREADSHEET_ID,
      range: ARTICLES_RANGE,
    });

    const rows = response.data.values;
    if (!rows || rows.length === 0) {
      throw new Error('No data found in spreadsheet');
    }

    console.log(`Found ${rows.length} rows to analyze`);

    const analyzedArticles = [];

    for (const [index, row] of rows.entries()) {
      await analyzeArticle(sheets, row, index, perplexityApiKey);
      analyzedArticles.push(row[0]); // Add the title of the analyzed article

      if (Date.now() - startTime > MAX_EXECUTION_TIME_MS) {
        console.log('Max execution time reached. Stopping analysis.');
        break;
      }

      // Add a small delay between requests to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, 1000));
    }

    const endTime = Date.now();
    const executionTime = (endTime - startTime) / 1000;
    const message = `Analysis complete. Analyzed articles: ${analyzedArticles.length}. Total execution time: ${executionTime.toFixed(2)} seconds`;
    console.log(`[${new Date().toLocaleTimeString()}] ${message}`);

    res.status(200).json({ message, executionTime, analyzedCount: analyzedArticles.length });
  } catch (error) {
    console.error(`[${new Date().toLocaleTimeString()}] Error:`, error);
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